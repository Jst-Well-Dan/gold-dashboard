#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
牛熊周期图生成器（±阈值折返法）

把任意价格 / 指数序列切成一段段「上涨周期」「下跌周期」，每段都从 0% 重新起算：
上涨段画绿色、向上累积到本轮峰值；下跌段画红色、跌破 0 到本轮谷底。
峰谷处标注：日期 · 持续月数 · 本段累计涨跌幅 · 年化。

只要换数据源就能复用（黄金、标普、纳指、比特币、个股…… 脚本自己算回报率，
不需要你事先准备收益率序列，喂「价格/指数点位」即可）。

用法
----
    # 内置数据集（读取本仓库 data/ 下的 CSV，只读不改）
    python tools/bullbear_cycle.py --preset gold --start 1971-01 --scale log
    python tools/bullbear_cycle.py --preset spy  --start 1993-01
    python tools/bullbear_cycle.py --preset btc  --start 2014-01 --scale log

    # 自己的 CSV：自动找日期列和数值列，找不到就显式指定
    python tools/bullbear_cycle.py --csv my_prices.csv --date-col 日期 --value-col 收盘价 \
        --title "沪深300 牛熊周期" --threshold 20 --out out/hs300.png

    # 交互版（单文件 HTML，内嵌 ECharts，双击即看、悬停有详情卡）
    python tools/bullbear_cycle.py --preset gold --format html --out out/gold.html
    python tools/bullbear_cycle.py --preset spy --format both --out out/spy.png   # png + html

字段口径
--------
* --threshold  20 表示「自高点回撤 ≥20% 记为熊，自低点反弹 ≥20% 记为牛」（参考图同款）
* --scale pct  纵轴=简单累计涨跌幅，标注与纵轴完全一致（股票指数常用）
  --scale log  纵轴=对数累计涨跌幅 ln(末/初)，把 1971-80 黄金 +2200% 这类超长牛市压进画面
                （标注里仍写简单累计涨幅与年化，纵轴刻度是对数值，脚注会说明）
* --freq M     先按月取月末值再切周期；日频数据用默认 M 可避免 20% 阈值被日内噪声反复触发

输出
----
--format png（默认）出静态图，html 出单文件交互页（内嵌 ECharts，Shift+滚轮缩放），
both 两样都出。同时终端打印周期明细表（--table 可另存 CSV）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# --------------------------------------------------------------------- 常量
ROOT = Path(__file__).resolve().parents[1]          # 仓库根目录
DATA = ROOT / "data"

CJK_FONTS = ["Microsoft YaHei", "SimHei", "PingFang SC",
             "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Zen Hei", "DejaVu Sans"]

C = dict(
    bull="#3f8c53",
    bull_fill="#5fa874",
    bear="#b32a22",
    bear_fill="#c4554a",
    ink="#1c1a16",
    muted="#8b8375",
    line="#e8e2d4",
    zero="#a59b87",
    paper="#ffffff",
)

PRESETS = {
    # 名字 -> (文件, 值列, 默认起始, 图题)
    "gold": ("long_gold_monthly.csv", "value", "1971-01", "黄金（伦敦金）牛熊周期"),
    "gc":   ("yahoo/GC_F.csv", "close", "2000-09", "COMEX 黄金牛熊周期"),
    "spy":  ("yahoo/SPY.csv", "close", "1993-02", "标普 500（SPY）牛熊周期"),
    "qqq":  ("yahoo/QQQ.csv", "close", "1999-04", "纳指 100（QQQ）牛熊周期"),
    "btc":  ("yahoo/BTC-USD.csv", "close", "2014-10", "比特币牛熊周期"),
    "tlt":  ("yahoo/TLT.csv", "close", "2002-08", "长债 TLT 牛熊周期"),
}
DATE_NAMES = {"date", "datetime", "time", "day", "timestamp", "日期", "时间", "trade_date"}
VALUE_PREF = ["close", "value", "adjclose", "price", "收盘", "收盘价", "点位"]


# ------------------------------------------------------------------ 数据读取
def load_csv(path: Path, date_col: str | None, value_col: str | None) -> pd.Series:
    """读任意 CSV → 按日期索引的数值序列。"""
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]

    if date_col is None:
        for c in df.columns:
            if c.lower() in DATE_NAMES:
                date_col = c
                break
    if date_col is None:                        # 退化：取第一列能解析成日期的
        for c in df.columns:
            if pd.to_datetime(df[c], errors="coerce", format="mixed").notna().mean() > 0.9:
                date_col = c
                break
    if date_col is None:
        raise SystemExit(f"[x] 找不到日期列，请用 --date-col 指定。列名：{list(df.columns)}")

    if value_col is None:
        lower = {c.lower(): c for c in df.columns}
        for want in VALUE_PREF:
            if want in lower:
                value_col = lower[want]
                break
    if value_col is None:                       # 退化：日期列之后第一个能转数字的列
        for c in df.columns:
            if c == date_col:
                continue
            if pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.9:
                value_col = c
                break
    if value_col is None:
        raise SystemExit(f"[x] 找不到数值列，请用 --value-col 指定。列名：{list(df.columns)}")

    idx = pd.to_datetime(df[date_col], errors="coerce", format="mixed")
    vals = pd.to_numeric(df[value_col], errors="coerce")
    s = pd.Series(vals.to_numpy(), index=idx).dropna()
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if len(s) < 3:
        raise SystemExit(f"[x] {path} 里有效数据不足（{len(s)} 行）")
    return s.astype(float)


def resample_monthly(s: pd.Series) -> pd.Series:
    try:
        return s.resample("ME").last().dropna()
    except ValueError:                          # 老版本 pandas
        return s.resample("M").last().dropna()


# ---------------------------------------------------------------- 周期识别
def detect_legs(v: np.ndarray, th: float) -> list[dict]:
    """±阈值折返法。返回若干 {kind, start, end}，索引为 v 的下标。

    从第一个点开始视为上涨段；段内持续跟踪极值，一旦反向折返超过阈值，
    就在极值处切开：极值点是上一段的终点，也是下一段的起点（所以每段都从 0% 起算）。
    """
    n = len(v)
    legs: list[dict] = []
    kind, start, ext = "bull", 0, 0
    for i in range(1, n):
        if kind == "bull":
            if v[i] > v[ext]:
                ext = i
            elif v[i] <= v[ext] * (1.0 - th):
                legs.append(dict(kind="bull", start=start, end=ext))
                kind, start, ext = "bear", ext, i
        else:
            if v[i] < v[ext]:
                ext = i
            elif v[i] >= v[ext] * (1.0 + th):
                legs.append(dict(kind="bear", start=start, end=ext))
                kind, start, ext = "bull", ext, i
    if n - 1 > start:
        legs.append(dict(kind=kind, start=start, end=n - 1, ongoing=True))
    return [lg for lg in legs if lg["end"] > lg["start"]]


def months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.to_period("M") - a.to_period("M")).n


def summarise(s: pd.Series, legs: list[dict]) -> pd.DataFrame:
    rows = []
    for lg in legs:
        p0, p1 = s.iloc[lg["start"]], s.iloc[lg["end"]]
        cum = p1 / p0 - 1.0
        m = months_between(s.index[lg["start"]], s.index[lg["end"]])
        years = m / 12 if m > 0 else max((s.index[lg["end"]] - s.index[lg["start"]]).days / 365.25, 1 / 365.25)
        ann = (1.0 + cum) ** (1.0 / years) - 1.0 if 1.0 + cum > 0 else -1.0
        rows.append(dict(
            类型="上涨周期" if lg["kind"] == "bull" else "下跌周期",
            起点=s.index[lg["start"]].strftime("%Y.%m"),
            终点=s.index[lg["end"]].strftime("%Y.%m"),
            月数=m,
            累计涨跌幅=round(cum * 100, 1),
            年化=round(ann * 100, 1),
            状态="进行中" if lg.get("ongoing") else "",
        ))
    return pd.DataFrame(rows)


# -------------------------------------------------------------------- 绘图
def nice_step(span: float, target: int = 6) -> float:
    raw = max(span / target, 1e-9)
    mag = 10 ** np.floor(np.log10(raw))
    for k in (1, 2, 2.5, 5, 10):
        if raw <= k * mag:
            return k * mag
    return 10 * mag


def pct_fmt(v: float, _=None) -> str:
    return f"{v:+,.0f}%" if abs(v) >= 0.5 else "0%"


def label_candidates(above: bool, frac: float) -> list[tuple[float, float, str, str]]:
    """给标注挑落点：先紧贴极值，再逐步外推；靠边的段改成左/右对齐，避免出框。"""
    if frac < 0.05:
        ha_list = ["left"]
    elif frac > 0.94:
        ha_list = ["right"]
    else:
        ha_list = ["center", "right", "left"]
    out = []
    for k, gap in enumerate((9, 30, 54, 78, 102)):
        for ha in ha_list:
            dx = 0.0 if ha == "center" else (-5.0 if ha == "right" else 5.0)
            for side in (0, -1, 1) if k else (0,):
                out.append((dx + side * 26.0, gap if above else -gap, ha, "bottom" if above else "top"))
    return out


def draw(fig: plt.Figure, ax: plt.Axes, s: pd.Series, legs: list[dict],
         scale: str, label_fontsize: float, label_min: float,
         bull_color: str, bear_color: str) -> None:
    dates = s.index.to_pydatetime()
    v = s.to_numpy(dtype=float)
    to_y = (lambda c: np.log1p(c) * 100.0) if scale == "log" else (lambda c: c * 100.0)

    y_lo, y_hi = 0.0, 0.0
    curve_chunks = []
    for lg in legs:
        sl = slice(lg["start"], lg["end"] + 1)
        ratio = v[sl] / v[lg["start"]]
        y = to_y(ratio - 1.0)
        bull = lg["kind"] == "bull"
        color = bull_color if bull else bear_color
        fill = C["bull_fill"] if bull else C["bear_fill"]
        ax.fill_between(dates[sl], 0, y, color=fill, alpha=0.15 if bull else 0.16,
                        linewidth=0, zorder=2)
        ax.plot(dates[sl], y, color=color, lw=1.15, zorder=3,
                solid_capstyle="round", solid_joinstyle="round")
        curve_chunks.append(np.column_stack([mdates.date2num(list(dates[sl])), y]))
        y_lo, y_hi = min(y_lo, float(y.min())), max(y_hi, float(y.max()))
        lg["y_end"] = float(y[-1])

    # ---- 轴：零轴中线 / 网格 / 刻度
    ax.axhline(0, color=C["zero"], lw=0.9, zorder=4)
    ax.grid(axis="y", color=C["line"], lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(C["line"])
        ax.spines[sp].set_linewidth(0.9)

    pad = (y_hi - y_lo) * 0.14 or 10
    ax.set_ylim(y_lo - (pad if y_lo < 0 else 0), y_hi + pad * 1.35)
    step = nice_step(ax.get_ylim()[1] - ax.get_ylim()[0], 7)
    ax.yaxis.set_major_locator(plt.MultipleLocator(step))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(pct_fmt))
    ax.tick_params(axis="y", labelsize=10, colors=C["muted"], length=0, pad=6)
    ax.tick_params(axis="x", labelsize=10, colors=C["muted"], length=0, pad=8)

    span_years = (dates[-1] - dates[0]).days / 365.25
    yr_step = 10 if span_years > 70 else 5 if span_years > 30 else 2 if span_years > 12 else 1
    ax.xaxis.set_major_locator(mdates.YearLocator(yr_step))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    pad_x = max((dates[-1] - dates[0]).days * 0.012, 30)
    ax.set_xlim(dates[0] - pd.Timedelta(days=pad_x), dates[-1] + pd.Timedelta(days=pad_x))

    # ---- 图例
    ax.legend(handles=[
        Line2D([], [], color=bull_color, lw=2.2, label="上涨周期"),
        Line2D([], [], color=bear_color, lw=2.2, label="下跌周期"),
    ], loc="upper left", bbox_to_anchor=(0.0, 1.0), frameon=False, fontsize=11,
        handlelength=1.4, labelcolor=C["ink"], borderaxespad=0.2)

    # ---- 峰谷标注（避让：不出框、不压标签、不压曲线）
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax_bb = ax.get_window_extent(renderer)
    curve = ax.transData.transform(np.vstack(curve_chunks))
    taken = []
    x0, x1 = mdates.date2num(dates[0]), mdates.date2num(dates[-1])
    for lg in legs:
        cum = v[lg["end"]] / v[lg["start"]] - 1.0
        m = months_between(s.index[lg["start"]], s.index[lg["end"]])
        years = m / 12 if m > 0 else max((s.index[lg["end"]] - s.index[lg["start"]]).days / 365.25, 1e-3)
        ann = (1.0 + cum) ** (1.0 / years) - 1.0 if 1.0 + cum > 0 else -1.0
        if abs(cum) * 100 < label_min:
            continue
        edge = s.index[lg["end"]]
        tag = "（进行中）" if lg.get("ongoing") else ""
        text = (f"{edge.strftime('%Y.%m')}{tag}\n"
                f"{m}m · {cum * 100:+,.0f}%\n"
                f"{ann * 100:+,.0f}%/yr")
        color = bull_color if lg["kind"] == "bull" else bear_color
        frac = (mdates.date2num(edge) - x0) / max(x1 - x0, 1e-9)
        best = None
        for dx, dy, ha, va in label_candidates(lg["kind"] == "bull", frac):
            t = ax.annotate(text, (edge, lg["y_end"]), textcoords="offset points",
                            xytext=(dx, dy), ha=ha, va=va, fontsize=label_fontsize,
                            color=color, linespacing=1.45, zorder=7,
                            annotation_clip=False)
            bb = t.get_window_extent(renderer)
            inside = (ax_bb.x0 <= bb.x0 and bb.x1 <= ax_bb.x1 - 2
                      and ax_bb.y0 <= bb.y0 and bb.y1 <= ax_bb.y1)
            hit_curve = np.any((curve[:, 0] >= bb.x0 + 2) & (curve[:, 0] <= bb.x1 - 2)
                               & (curve[:, 1] >= bb.y0 + 2) & (curve[:, 1] <= bb.y1 - 2))
            if inside and not hit_curve and not any(
                    bb.expanded(1.06, 1.18).overlaps(p) for p in taken):
                taken.append(bb)
                best = t
                break
            t.remove()

    return


# ------------------------------------------------------------------- HTML
HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__TITLE__</title>
<style>
  :root {
    --paper:#f7f5f0; --card:#ffffff; --ink:#1f1a12; --ink2:#4b4437;
    --muted:#8a8375; --line:#e6ddc9; --up:#2c7a54; --down:#b8402f; --gold:#a8892a;
    --sans: Inter, -apple-system, "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  }
  * { box-sizing: border-box; }
  html, body { margin:0; background:var(--paper); color:var(--ink); font:400 15px/1.65 var(--sans); }
  .wrap { max-width: 1440px; margin: 0 auto; padding: 28px 26px 18px; }
  header h1 { margin:0 0 6px; font-size: 26px; font-weight: 700; letter-spacing:-.2px; }
  header p { margin:0; color:var(--muted); font-size:13px; }
  .card { margin-top:18px; background:var(--card); border:1px solid var(--line); border-radius:14px;
          box-shadow:0 1px 2px rgba(31,26,18,.04), 0 10px 28px -22px rgba(31,26,18,.45);
          padding:14px 16px 8px; }
  .plot { position: relative; }
  #chart { width:100%; height: min(74vh, 660px); }
  #labels { position:absolute; inset:0; pointer-events:none; }
  #labels .lbl { position:absolute; white-space:nowrap; text-align:center;
                 font:500 11.5px/1.45 var(--sans); letter-spacing:-.1px; }
  #labels .lbl.bull { color:var(--up); }
  #labels .lbl.bear { color:var(--down); }
  #labels .lbl .d { opacity:.92; }
  footer { margin-top:10px; display:flex; gap:18px; flex-wrap:wrap;
           color:var(--muted); font-size:12px; }
  footer .spacer { flex:1; }
  code { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size:12px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>__TITLE__</h1>
    <p>__SUBTITLE__</p>
  </header>
  <div class="card">
    <div class="plot">
      <div id="chart"></div>
      <div id="labels"></div>
    </div>
  </div>
  <footer>
    <span>__FOOTNOTE__</span>
    <span class="spacer"></span>
    <span>数据：<code>__SOURCE__</code></span>
  </footer>
</div>
__ECHARTS_SCRIPT__
<script>window.__CYCLE__ = __PAYLOAD__;</script>
<script>
(function () {
  const B = window.__CYCLE__;
  if (!B || !window.echarts) return;

  const K = { up: '#2c7a54', down: '#b8402f', ink: '#1f1a12', ink2: '#4b4437',
              muted: '#8a8375', line: '#e6ddc9', zero: '#a59b87', gold: '#a8892a' };
  const FONT = 'Inter, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
  const NL = String.fromCharCode(10);
  const sgn = (v, d) => (v > 0 ? '+' : '') + v.toFixed(d === undefined ? 0 : d);
  const num = (v) => v.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  const dstr = (ms) => {
    const d = new Date(ms);
    return d.getUTCFullYear() + '.' + String(d.getUTCMonth() + 1).padStart(2, '0');
  };

  /* ------------------------------------------------ 图形 */
  const series = B.legs.map((lg) => {
    const bull = lg.kind === 'bull';
    const color = bull ? K.up : K.down;
    return {
      name: bull ? '上涨周期' : '下跌周期',
      type: 'line',
      data: lg.points,
      showSymbol: false, symbol: 'circle', symbolSize: 5,
      lineStyle: { width: 1.4, color: color },
      itemStyle: { color: color },
      areaStyle: { color: color, opacity: 0.09 },
      emphasis: { disabled: true },
      animation: false,
      z: 3,
    };
  });
  series[0].markLine = {
    symbol: 'none', silent: true, animation: false, label: { show: false },
    lineStyle: { color: K.zero, width: 1 },
    data: [{ yAxis: 0 }],
  };

  const chart = echarts.init(document.getElementById('chart'), null, { renderer: 'canvas' });
  chart.setOption({
    animation: false,
    textStyle: { fontFamily: FONT },
    color: [K.up, K.down],
    grid: { left: 12, right: 22, top: 36, bottom: 8, containLabel: true },
    legend: {
      top: 0, left: 0, icon: 'roundRect', itemWidth: 16, itemHeight: 4, itemGap: 16,
      data: ['上涨周期', '下跌周期'],
      textStyle: { color: K.ink2, fontSize: 12, fontFamily: FONT },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,.98)', borderColor: K.line, borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: K.ink, fontSize: 12.5, fontFamily: FONT },
      axisPointer: { type: 'line', lineStyle: { color: K.gold, width: 1, type: 'dashed' } },
      formatter: (ps) => {
        const p = ps.find((x) => x.value != null);
        if (!p) return '';
        const lg = B.legs[p.seriesIndex];
        const ms = p.value[0], pct = p.value[1], price = p.value[2];
        const c = lg.kind === 'bull' ? K.up : K.down;
        return [
          '<div style="font-weight:700;margin-bottom:5px">' + dstr(ms) + '</div>',
          '点位 <b>' + num(price) + '</b> ' + B.unit,
          '本段至此 <b style="color:' + c + '">' + sgn(pct, 1) + '%</b>',
          '状态 <b style="color:' + c + '">' + (lg.kind === 'bull' ? '上涨周期' : '下跌周期') +
            '</b>' + (lg.ongoing ? '<span style="color:' + K.muted + '"> · 未确认</span>' : ''),
          '<div style="height:7px"></div>',
          '<span style="color:' + K.muted + '">本轮</span> ' + lg.start + ' → ' + lg.end +
            ' · ' + lg.months + ' 个月',
          '<span style="color:' + K.muted + '">本轮累计</span> <b style="color:' + c + '">' +
            sgn(lg.cum, 1) + '%</b>',
          '<span style="color:' + K.muted + '">年化</span> <b>' + sgn(lg.ann, 1) + '%</b>',
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'time',
      max: B.xmax,
      axisLine: { lineStyle: { color: K.line } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: {
        color: K.muted, fontSize: 11, hideOverlap: true, fontFamily: FONT,
        formatter: (v) => String(new Date(v).getUTCFullYear()),
      },
    },
    yAxis: {
      type: B.scale === 'log' ? 'log' : 'value',
      logBase: 10,
      scale: B.scale !== 'log',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: K.line, type: 'solid', width: 0.9 } },
      axisLabel: {
        color: K.muted, fontSize: 11, fontFamily: FONT,
        formatter: (v) => (Math.abs(v) < 0.5 ? '0%' : sgn(v) + '%'),
      },
    },
    dataZoom: [{ type: 'inside', zoomOnMouseWheel: 'shift', moveOnMouseWheel: false }],
    series: series,
  });

  /* ------------------------------------------------ 段末标注（DOM 层，自行避让）
     ECharts 的 endLabel / label 没有避让能力（hideOverlap 会直接丢掉标签），
     所以把标注放到覆盖层：先渲染、量出真实尺寸、再按候选位置逐个避让。 */
  const boxEl = document.getElementById('chart');
  const layer = document.getElementById('labels');
  let labelTimer = null;

  function placeLabels() {
    const W = boxEl.clientWidth, H = boxEl.clientHeight;
    const grid = chart.getModel().getComponent('grid').coordinateSystem.getRect();
    const BOUND = { l: 2, t: 2, r: W - 2, b: Math.min(H - 2, grid.y + grid.height + 24) };
    layer.textContent = '';
    const items = [];

    B.legs.forEach((lg) => {
      if (Math.abs(lg.cum) < B.label_min) return;
      const last = lg.points[lg.points.length - 1];
      const p = chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [last[0], last[1]]);
      if (!p) return;
      const d = document.createElement('div');
      d.className = 'lbl ' + lg.kind;
      d.innerHTML = '<div>' + lg.end + (lg.ongoing ? '（进行中）' : '') + '</div>' +
                    '<div class="d">' + lg.months + 'm · ' + sgn(lg.cum) + '%</div>' +
                    '<div class="d">' + sgn(lg.ann) + '%/yr</div>';
      d.style.visibility = 'hidden';
      d.style.left = '-9999px';
      layer.appendChild(d);
      items.push({ el: d, p: p, bull: lg.kind === 'bull' });
    });

    // 曲线点的像素位置：标注不能压在曲线上
    const curve = [];
    B.legs.forEach((lg) => {
      lg.points.forEach((pt) => {
        const q = chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [pt[0], pt[1]]);
        if (q) curve.push(q);
      });
    });

    const taken = [];
    items.forEach((it) => {
      const w = it.el.offsetWidth, h = it.el.offsetHeight;
      const dy0 = it.bull ? -(8 + h) : 8;
      const cands = [];
      [0, 20, 40, 60, 90, 120, 155].forEach((extra) => {
        [0, 0.6, -0.6, 1.15, -1.15, 1.7, -1.7].forEach((k) => {
          cands.push([k * w * 0.5, dy0 + (it.bull ? -extra : extra)]);
        });
      });
      // 给每个候选打分：压到别的标注 → 按面积罚；压到曲线 → 按点数罚；越远越贵。
      // 取分数最低的；有 0 分（完全干净）就立刻用它。
      let best = null;
      for (let i = 0; i < cands.length; i++) {
        const x = it.p[0] + cands[i][0] - w / 2;
        const y = it.p[1] + cands[i][1];
        const r = { l: x, t: y, r: x + w, b: y + h };
        if (r.l < BOUND.l || r.r > BOUND.r || r.t < BOUND.t || r.b > BOUND.b) continue;
        let score = i * 0.8;
        for (let j = 0; j < taken.length; j++) {
          const t = taken[j];
          const ox = Math.min(r.r, t.r) - Math.max(r.l, t.l);
          const oy = Math.min(r.b, t.b) - Math.max(r.t, t.t);
          if (ox > 0 && oy > 0) score += ox * oy * 0.5 + 200;
        }
        for (let j = 0; j < curve.length; j++) {
          const c = curve[j];
          if (c[0] > r.l + 1 && c[0] < r.r - 1 && c[1] > r.t + 1 && c[1] < r.b - 1) score += 30;
        }
        if (score === 0) { best = { score: 0, x: x, y: y, r: r }; break; }
        if (!best || score < best.score) best = { score: score, x: x, y: y, r: r };
      }
      if (best) {
        taken.push(best.r);
        it.el.style.left = best.x + 'px';
        it.el.style.top = best.y + 'px';
        it.el.style.visibility = '';
      } else {
        it.el.style.display = 'none';
      }
    });
  }

  const refresh = () => {
    clearTimeout(labelTimer);
    labelTimer = setTimeout(placeLabels, 40);
  };
  chart.on('finished', refresh);
  chart.on('datazoom', refresh);
  window.addEventListener('resize', () => {
    clearTimeout(labelTimer);
    labelTimer = setTimeout(() => { chart.resize(); placeLabels(); }, 160);
  });
  placeLabels();
})();
</script>
</body>
</html>"""


def build_payload(s: pd.Series, legs: list[dict], title: str, subtitle: str,
                  footnote: str, scale: str, threshold: float, unit: str,
                  label_min: float) -> dict:
    """前端消费的数据：每段带上逐点 [毫秒时间戳, 本段累计%, 点位]。"""
    v = s.to_numpy(dtype=float)
    ms = (s.index - pd.Timestamp("1970-01-01")) // pd.Timedelta("1ms")   # 与 pandas 精度无关
    out = []
    # 同类周期挨得太近时，把标注往外错开，减少挤压（前端还有 hideOverlap 兜底）
    last_end = {"bull": None, "bear": None}
    tier = {"bull": 0, "bear": 0}
    for lg in legs:
        sl = slice(lg["start"], lg["end"] + 1)
        p0 = float(v[lg["start"]])
        cum = float(v[lg["end"]] / p0 - 1.0)
        m = months_between(s.index[lg["start"]], s.index[lg["end"]])
        years = m / 12 if m > 0 else max(
            (s.index[lg["end"]] - s.index[lg["start"]]).days / 365.25, 1e-3)
        ann = (1.0 + cum) ** (1.0 / years) - 1.0 if 1.0 + cum > 0 else -1.0
        pts = [[int(ms[i]), round(float(v[i] / p0 - 1.0) * 100, 2), round(float(v[i]), 2)]
               for i in range(lg["start"], lg["end"] + 1)]
        k = lg["kind"]
        prev = last_end[k]
        if prev is None or months_between(prev, s.index[lg["end"]]) > 30:
            tier[k] = 0
        else:
            tier[k] = (tier[k] + 1) % 3
        last_end[k] = s.index[lg["end"]]
        out.append(dict(kind=k,
                        start=s.index[lg["start"]].strftime("%Y.%m"),
                        end=s.index[lg["end"]].strftime("%Y.%m"),
                        months=int(m), cum=round(cum * 100, 2), ann=round(ann * 100, 2),
                        distance=8 + tier[k] * 23,
                        ongoing=bool(lg.get("ongoing")), points=pts))
    pad = int((int(ms[-1]) - int(ms[0])) * 0.06)
    return dict(title=title, subtitle=subtitle, footnote=footnote, unit=unit,
                scale=scale, threshold=threshold, label_min=label_min,
                xmax=int(ms[-1]) + pad, legs=out)


def render_html(path: Path, payload: dict, source: str, echarts_path: Path) -> Path:
    if echarts_path.exists():
        script = "<script>" + echarts_path.read_text(encoding="utf-8") + "</script>"
    else:
        script = ('<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js">'
                  '</script>')
    html = (HTML_TEMPLATE
            .replace("__TITLE__", payload["title"])
            .replace("__SUBTITLE__", payload["subtitle"])
            .replace("__FOOTNOTE__", payload["footnote"])
            .replace("__SOURCE__", source)
            .replace("__ECHARTS_SCRIPT__", script)
            .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False,
                                               separators=(",", ":"))))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


# --------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="把价格/指数序列切成上涨周期与下跌周期，画成参考图样式的牛熊周期图。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = p.add_argument_group("数据")
    src.add_argument("--csv", type=Path, help="CSV 路径（任意列名，自动识别日期列与数值列）")
    src.add_argument("--preset", choices=sorted(PRESETS), help="使用仓库内置数据集")
    src.add_argument("--date-col", help="日期列名（默认自动）")
    src.add_argument("--value-col", help="数值列名（默认 close/value/adjclose…）")
    src.add_argument("--start", help="起始日期，如 1971-01")
    src.add_argument("--end", help="结束日期，如 2020-12")
    src.add_argument("--freq", default="M", choices=["M", "W", "D", "none"],
                     help="重采样频率（默认 M=月末；none 保持原始）")

    cal = p.add_argument_group("口径")
    cal.add_argument("--threshold", type=float, default=20.0, help="牛熊折返阈值 %%，默认 20")
    cal.add_argument("--scale", default="pct", choices=["pct", "log"],
                     help="纵轴口径：pct=简单涨跌幅（默认），log=对数涨跌幅")
    cal.add_argument("--labels", default="all", choices=["all", "big", "none"], help="标注密度")
    cal.add_argument("--label-fontsize", type=float, default=8.6)
    cal.add_argument("--bull-color", default=C["bull"])
    cal.add_argument("--bear-color", default=C["bear"])

    out = p.add_argument_group("输出")
    out.add_argument("--title", help="大标题（默认取文件名/预设名）")
    out.add_argument("--subtitle", help="副标题（默认自动写口径）")
    out.add_argument("--out", type=Path, help="输出路径（默认 tools/out/<名字>_bullbear.<ext>）")
    out.add_argument("--format", default="png", choices=["png", "html", "both"],
                     help="png=静态图（默认），html=交互页，both=两者都出")
    out.add_argument("--unit", default="", help='点位单位，用在悬停卡里，如 "美元/盎司"')
    out.add_argument("--echarts", type=Path, default=ROOT / "web" / "vendor" / "echarts.min.js",
                     help="内联进 HTML 的 ECharts 路径")
    out.add_argument("--table", type=Path, help="另存周期明细 CSV")
    out.add_argument("--dpi", type=int, default=200)
    out.add_argument("--figsize", default="16,7.6", help="英寸，如 16,7.6")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ---------- 取数
    if args.csv:
        path, vcol, name = args.csv, args.value_col, args.csv.stem
    elif args.preset:
        fname, vcol, d0, label = PRESETS[args.preset]
        path, name = DATA / "raw" / fname, label
        args.start = args.start or d0
    else:
        build_parser().print_help()
        print("\n[x] 需要 --csv 或 --preset 之一", file=sys.stderr)
        return 2
    if not path.exists():
        raise SystemExit(f"[x] 文件不存在：{path}")

    s = load_csv(path, args.date_col, vcol)
    if args.freq != "none":
        s = resample_monthly(s) if args.freq == "M" else s.resample(
            {"W": "W-SUN", "D": "D"}[args.freq]).last().dropna()
    if args.start:
        s = s[s.index >= pd.Timestamp(args.start)]
    if args.end:
        s = s[s.index <= pd.Timestamp(args.end) + pd.offsets.MonthEnd(1)]
    s = s.dropna()
    if len(s) < 4:
        raise SystemExit(f"[x] 过滤后样本太少：{len(s)} 个观测")

    v = s.to_numpy(dtype=float)
    if args.scale == "log" and np.any(v <= 0):
        raise SystemExit("[x] 序列里有 ≤0 的值，对数口径不可用（换 --scale pct）")

    # ---------- 切周期
    th = args.threshold / 100.0
    if not 0 < th < 1:
        raise SystemExit("[x] --threshold 需在 (0,100) 之间")
    legs = detect_legs(v, th)
    if not legs:
        raise SystemExit("[x] 没识别出任何周期，试降低 --threshold")

    table = summarise(s, legs)
    if args.table:
        args.table.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.table, index=False, encoding="utf-8-sig")

    # ---------- 标题 / 口径文案
    title = args.title or name
    freq_txt = {"M": "月度", "W": "周度", "D": "日频", "none": "原始频率"}[args.freq]
    n_legs = len(legs)
    scope = f"{s.index[0]:%Y-%m} → {s.index[-1]:%Y-%m}"
    scale_txt = "纵轴对数压缩 ln(末/初)×100" if args.scale == "log" else "纵轴为简单累计涨跌幅"
    subtitle = args.subtitle or (f"以 ±{args.threshold:.0f}% 划分牛熊 · {freq_txt} · {scope} · "
                                 f"{scale_txt} · 共 {n_legs} 段")
    footnote = "每段从 0% 重新起算；标注 = 转折日期 · 持续月数 · 本段累计涨跌幅 · 年化"
    label_min = {"all": 0.0, "big": 30.0, "none": 1e9}[args.labels]

    base = args.out.with_suffix("") if args.out else ROOT / "tools" / "out" / f"{path.stem}_bullbear"
    made: list[Path] = []

    # ---------- 静态图
    if args.format in ("png", "both"):
        plt.rcParams["font.sans-serif"] = CJK_FONTS
        plt.rcParams["axes.unicode_minus"] = False
        fig = plt.figure(figsize=tuple(float(x) for x in args.figsize.split(",")),
                         dpi=args.dpi, facecolor=C["paper"])
        ax = fig.add_axes([0.055, 0.085, 0.915, 0.685])
        ax.set_facecolor(C["paper"])
        draw(fig, ax, s, legs, args.scale,
             args.label_fontsize, label_min, args.bull_color, args.bear_color)
        fig.text(0.048, 0.955, title, fontsize=20, fontweight="bold", color=C["ink"], va="top")
        fig.text(0.050, 0.905, subtitle, fontsize=10.5, color=C["muted"], va="top")
        fig.text(0.992, 0.018, footnote, fontsize=8.5, color=C["muted"],
                 ha="right", va="bottom")
        png = base.with_suffix(".png")
        png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(png, dpi=args.dpi, facecolor=C["paper"])
        plt.close(fig)
        made.append(png)

    # ---------- 交互页
    if args.format in ("html", "both"):
        payload = build_payload(s, legs, title, subtitle, footnote, args.scale,
                                args.threshold, args.unit, label_min)
        made.append(render_html(base.with_suffix(".html"), payload, str(path), args.echarts))

    # ---------- 汇报
    bulls = table[table["类型"] == "上涨周期"]
    bears = table[table["类型"] == "下跌周期"]
    pd.set_option("display.unicode.east_asian_width", True)
    print(f"[✓] {path}  {len(s)} 个观测  {scope}")
    print(f"    上涨 {len(bulls)} 段（中位 {bulls['月数'].median():.0f} 个月，中位累计 "
          f"{bulls['累计涨跌幅'].median():+.0f}%）  "
          f"下跌 {len(bears)} 段（中位 {bears['月数'].median():.0f} 个月，中位累计 "
          f"{bears['累计涨跌幅'].median():+.0f}%）")
    if bears.empty:
        print("    [i] 这段区间里没有触发下跌阈值，只有上涨周期")
    print(table.to_string(index=False))
    for p in made:
        print(f"[✓] 输出 → {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
