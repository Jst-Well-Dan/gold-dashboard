"""脱钩证明图 · 独立预览（不进主看板管线）

算两组滚动相关并输出 tools/out/decoupling_preview.html（双击即看）：
  图1：金价日对数收益 vs 10Y TIPS 实际利率日变动 —— 滚动相关（1年/2年窗口）
  图2：金价周对数收益 vs 美联储资产负债表周变动率 —— 滚动相关（1年/2年窗口）

用"涨跌的相关"而不用"价格水平的相关"：两个同时上趋势的水平序列，
算相关恒为正高值，看不出脱钩；涨跌的相关才能反映驱动关系是否断裂。
"""
from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "tools" / "out"
OUT.mkdir(parents=True, exist_ok=True)


def load_csv(name: str, val_col: str) -> pd.Series:
    df = pd.read_csv(RAW / name, parse_dates=["date"])
    s = pd.Series(df[val_col].to_numpy(), index=pd.DatetimeIndex(df["date"]))
    s = s.sort_index()
    return s


def rolling_corr(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    """对齐后再算滚动 Pearson 相关（pairwise complete）。"""
    df = pd.DataFrame({"a": a, "b": b}).dropna()
    return df["a"].rolling(window).corr(df["b"])


def downsample(idx: pd.DatetimeIndex, vals: list, max_n: int = 1500):
    pts = [[d.strftime("%Y-%m-%d"), (None if pd.isna(v) else round(float(v), 3))] for d, v in zip(idx, vals)]
    pts = [p for p in pts if p[1] is not None]
    if len(pts) > max_n:
        step = len(pts) / max_n
        pts = [pts[int(i * step)] for i in range(max_n)]
    return pts


def main() -> None:
    gold = load_csv("yahoo/GC_F.csv", "adjclose")
    tips = load_csv("fred/DFII10.csv", "value")
    walcl = load_csv("fred/WALCL.csv", "value")

    # ---- 图1：日频 ----
    g_ret = gold.apply(lambda x: x).apply(float).pipe(lambda s: __import__("numpy").log(s).diff())
    t_chg = tips.diff()
    c1_1y = rolling_corr(g_ret, t_chg, 252)
    c1_2y = rolling_corr(g_ret, t_chg, 504)

    # ---- 图2：周频（周五收盘对齐 WALCL 周三值） ----
    g_w = gold.resample("W-FRI").last()
    g_wret = __import__("numpy").log(g_w).diff()
    w_chg = walcl.pct_change() * 100
    w_idx = w_chg.index
    # 把 WALCL 对齐到当周周五（WALCL 发布日为周三）
    w_fri = w_chg.copy()
    w_fri.index = w_fri.index + pd.Timedelta(days=2)
    c2_1y = rolling_corr(g_wret, w_fri, 52)
    c2_2y = rolling_corr(g_wret, w_fri, 104)

    payload = {
        "fig1": {
            "w1y": downsample(c1_1y.index, c1_1y.tolist()),
            "w2y": downsample(c1_2y.index, c1_2y.tolist()),
        },
        "fig2": {
            "w1y": downsample(c2_1y.index, c2_1y.tolist()),
            "w2y": downsample(c2_2y.index, c2_2y.tolist()),
        },
    }

    def pre2022(s: pd.Series) -> float | None:
        v = s.loc[: "2021-12-31"].dropna()
        return round(float(v.mean()), 2) if len(v) else None

    def latest(s: pd.Series) -> float | None:
        v = s.dropna()
        return round(float(v.iloc[-1]), 2) if len(v) else None

    def year_min(s: pd.Series, year: str) -> float | None:
        v = s.loc[year].dropna()
        return round(float(v.min()), 2) if len(v) else None

    stats = {
        "fig1_now_2y": latest(c1_2y),
        "fig1_pre2022": pre2022(c1_2y),
        "fig1_2023min": year_min(c1_2y, "2023"),
        "fig1_end": str(c1_2y.dropna().index[-1].date()),
        "fig2_now_2y": latest(c2_2y),
        "fig2_pre2022": pre2022(c2_2y),
        "fig2_end": str(c2_2y.dropna().index[-1].date()),
    }
    payload["stats"] = stats

    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    out = OUT / "decoupling_preview.html"
    out.write_text(html, encoding="utf-8")
    print("wrote", out)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>脱钩证明图 · 预览</title>
<style>
:root{
  --paper:#f7f5f0; --card:#fff; --ink:#1f1a12; --ink-2:#4b4437; --muted:#8a8375;
  --line:#e6ddc9; --gold:#a8892a; --up:#b8402f; --down:#2c7a54;
  --radius:14px; --shadow:0 1px 2px rgba(31,26,18,.04),0 8px 24px -16px rgba(31,26,18,.35);
  --sans:Inter,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:400 15px/1.65 var(--sans)}
.wrap{max-width:1240px;margin:0 auto;padding:32px 24px 60px}
.kicker{font-size:12px;letter-spacing:.18em;color:var(--gold)}
h1{margin:10px 0 6px;font-size:28px;font-weight:800}
.sub{margin:0 0 8px;color:var(--muted);font-size:13.5px;max-width:80ch}
.verdict{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);
  background:var(--card);border-radius:999px;padding:7px 16px;font-size:13.5px;font-weight:600;
  box-shadow:var(--shadow);margin:12px 0 22px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--up)}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:18px 20px 12px;box-shadow:var(--shadow);margin-bottom:16px}
.card h3{margin:0;font-size:16px;font-weight:700}
.note{margin:6px 0 2px;font-size:12.5px;color:var(--muted);line-height:1.6;max-width:96ch}
.note b{color:var(--ink-2)}
.canvas{width:100%;height:380px;margin-top:8px}
.method{margin-top:20px;padding:14px 16px;border-left:2px solid #d4a853;background:rgba(255,255,255,.6);
  font-size:12.5px;color:var(--ink-2);border-radius:0 8px 8px 0}
.method code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.tabs{display:flex;gap:6px;margin:10px 0 0}
.tabs button{border:1px solid var(--line);background:#fff;color:var(--ink-2);font:inherit;
  font-size:11.5px;line-height:1;padding:5px 10px;border-radius:7px;cursor:pointer}
.tabs button.on{background:var(--gold);border-color:var(--gold);color:#fff;font-weight:600}
</style>
</head>
<body>
<div class="wrap">
  <div class="kicker">ROLLING CORRELATION · PREVIEW</div>
  <h1>脱钩证明图 <span style="font-size:13px;font-weight:400;color:var(--muted)">预览版 · 未进主看板</span></h1>
  <p class="sub">两张图回答同一个问题：<b>金价涨跌和"老驱动"（实际利率 / 扩表）还同步吗？</b>用滚动相关看驱动关系何时断裂。悬停看数值，shift + 滚轮缩放，拖拽平移。</p>
  <div class="verdict"><span class="dot"></span><span id="verdict">计算中…</span></div>

  <div class="card">
    <h3>图 1 · 金价 vs 10Y TIPS 实际利率：涨跌的滚动相关</h3>
    <p class="note">金价<b>日对数收益</b> vs 实际利率<b>日变动（百分点）</b>的滚动 Pearson 相关。2022 年前稳定在 <b>-0.2 左右</b>（利率上 → 金价跌）；2022–23 年加息 + 金价回调，负相关反而<b>加强到 -0.5</b>；2024 年后金价顶着高利率创新高，曲线才塌向 0——真正的脱钩是 2024 年后的事。竖线为 2022-01（美联储开启加息周期）。</p>
    <div class="tabs" data-fig="fig1"><button data-w="w1y">1 年窗口</button><button data-w="w2y" class="on">2 年窗口</button></div>
    <div class="canvas" id="c1"></div>
  </div>

  <div class="card">
    <h3>图 2 · 金价 vs 美联储资产负债表：涨跌的滚动相关</h3>
    <p class="note">金价<b>周对数收益</b> vs WALCL <b>周环比（%）</b>的滚动相关。QE 年代应为<strong>正相关</strong>（扩表 → 金价涨）；2022 年缩表后若曲线塌向 0 / 转负，即"扩表解释力让位给央行购金等新驱动"。竖线同为 2022-01。</p>
    <div class="tabs" data-fig="fig2"><button data-w="w1y">1 年窗口</button><button data-w="w2y" class="on">2 年窗口</button></div>
    <div class="canvas" id="c2"></div>
  </div>

  <div class="method" id="method"></div>
</div>
<script src="../../web/vendor/echarts.min.js"></script>
<script>
const D = __DATA__;
const C = { gold:'#b8942e', up:'#b8402f', down:'#2c7a54', blue:'#43689b',
  ink:'#1f1a12', ink2:'#4b4437', muted:'#8a8375', line:'#e6ddc9' };
const FONT = 'Inter,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif';
const toMs = d => { const q = String(d).split('-'); return Date.UTC(+q[0], +q[1]-1, +q[2]); };
const verdict = document.getElementById('verdict');
verdict.textContent =
  '实际利率：2022 年前均值 ' + D.stats.fig1_pre2022 + '，2023 年曾到 ' + D.stats.fig1_2023min +
  '（教科书式负相关最强时），当前 ' + D.stats.fig1_now_2y + '（脱钩）；' +
  '扩表：2022 年前均值 ' + D.stats.fig2_pre2022 + ' → 当前 ' + D.stats.fig2_now_2y +
  '（截至 ' + D.stats.fig1_end + '）';
document.getElementById('method').innerHTML =
  '口径：<code>corr(Δln 金价, Δ实际利率)</code> 日频，窗口 252 / 504 交易日；' +
  '<code>corr(Δln 金价周, Δln WALCL)</code> 周频（周五收盘对齐当周 WALCL），窗口 52 / 104 周；' +
  '均为 pairwise complete。数据：COMEX GC=F（Yahoo）、DFII10 / WALCL（FRED）。' +
  '注意：这是"涨跌同步性"，不是"价格水平相关"——后者恒为高正值，无信息量。';

function makeOption(fig, w) {
  const pts = D[fig][w].map(p => [toMs(p[0]), p[1]]);
  return {
    animationDuration: 400, textStyle: { fontFamily: FONT },
    grid: { left: 8, right: 14, top: 30, bottom: 6, containLabel: true },
    tooltip: { trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,.97)', borderColor: C.line, borderWidth: 1,
      textStyle: { color: C.ink, fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: C.gold, width: 1, type: 'dashed' } },
      valueFormatter: v => (v === null || v === undefined ? '—' : v.toFixed(2)) },
    legend: { top: 0, left: 0, textStyle: { color: C.ink2, fontSize: 11.5 } },
    xAxis: { type: 'time', splitLine: { show: false },
      axisLine: { lineStyle: { color: C.line } }, axisTick: { show: false },
      axisLabel: { color: C.muted, fontSize: 10.5 } },
    yAxis: { type: 'value', min: -1, max: 1, interval: 0.5,
      axisLine: { lineStyle: { color: C.line } }, axisTick: { show: false },
      axisLabel: { color: C.muted, fontSize: 10.5 },
      splitLine: { lineStyle: { color: '#f1ecdf' } } },
    series: [{
      name: w === 'w2y' ? '滚动相关（2 年窗口）' : '滚动相关（1 年窗口）',
      type: 'line', data: pts, showSymbol: false, sampling: 'lttb',
      lineStyle: { width: 1.8, color: w === 'w2y' ? C.up : C.blue },
      itemStyle: { color: w === 'w2y' ? C.up : C.blue },
      areaStyle: { color: w === 'w2y' ? 'rgba(184,64,47,.08)' : 'rgba(67,104,155,.08)' },
      markLine: { symbol: 'none', silent: true, animation: false, data: [
        { yAxis: 0, lineStyle: { color: C.muted, type: 'dashed', width: 1 }, label: { show: false } },
        { xAxis: toMs('2022-01-01'),
          lineStyle: { color: C.gold, type: 'dashed', width: 1 },
          label: { formatter: '2022 加息', color: C.muted, fontSize: 10, position: 'insideEndTop' } },
      ]},
    }],
    dataZoom: [{ type: 'inside', throttle: 60, zoomOnMouseWheel: 'shift', moveOnMouseWheel: false }],
  };
}
const charts = {};
function draw(fig, el) {
  if (!charts[fig]) charts[fig] = echarts.init(document.getElementById(el));
  const w = document.querySelector('.tabs[data-fig="' + fig + '"] .on').dataset.w;
  charts[fig].setOption(makeOption(fig, w), { notMerge: true });
}
draw('fig1', 'c1'); draw('fig2', 'c2');
document.querySelectorAll('.tabs').forEach(box => {
  box.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
    box.querySelectorAll('button').forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    const fig = box.dataset.fig;
    charts[fig].setOption(makeOption(fig, btn.dataset.w), { notMerge: true });
  }));
});
window.addEventListener('resize', () => Object.values(charts).forEach(c => c.resize()));
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
