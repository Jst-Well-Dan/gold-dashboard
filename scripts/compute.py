"""计算层：把 data/raw/ 的原始序列算成看板需要的一切。

产出 data/board.json，包含
- hero      : 顶部三块（国际金价、人民币金价、地上存量市值）
- sections  : 六大板块的指标卡 + 当前状态叙述
- charts    : 18 张历史洞察图的数据（前端 board.js 按 id 渲染）
- meta      : 数据来源 / 更新时间
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import (ABOVE_GROUND_TONNES, CHARTS, SECTIONS, SERIES,
                    TROY_OZ_PER_TONNE, UNIT_LABELS)
from util import DATA, MANUAL, RAW, json_write, load_series_csv, log, to_series

TROY_OZ_PER_GRAM = 1 / 31.1034768
BULL_BEAR_THRESHOLD = 20.0   # 黄金牛熊划分阈值（%）：涨跌 20% 才算换周期

# 这些 ETF 用复权收盘价（把分红再投资算进去），避免除息日的锯齿
ETF_ADJ = {"SPY", "QQQ", "TLT", "IEF", "SHV", "GLD"}
FY_A = 100.0  # 应付利息占收入的历史危险阈值（%）


# ------------------------------------------------------------------ 读原始数据
def load_raw() -> dict[str, pd.Series]:
    f: dict[str, pd.Series] = {}
    for s in SERIES:
        if s.get("derived"):
            continue
        kind, ref = s["src"]
        try:
            if kind == "fred":
                f[s["id"]] = load_series_csv(RAW / "fred" / f"{ref}.csv")
            elif kind == "yahoo":
                name = ref.replace("^", "IDX_").replace("=", "_")
                df = pd.read_csv(RAW / "yahoo" / f"{name}.csv")
                col = "adjclose" if (s["id"] in ETF_ADJ and "adjclose" in df.columns) else "close"
                f[s["id"]] = to_series(df, "date", col)
            elif kind == "cot":
                df = pd.read_csv(RAW / "cot" / f"{ref}.csv")
                f[s["id"]] = to_series(df, "date", "mm_net")
                f["_cot"] = df
            elif kind == "treasury":
                f[s["id"]] = load_series_csv(RAW / "treasury" / "debt_to_penny.csv")
            elif kind == "imf":
                f[s["id"]] = load_series_csv(RAW / "imf" / "cofer_usd_share.csv")
            elif kind == "crypto":
                f[s["id"]] = load_series_csv(RAW / "crypto" / "btc_mcap.csv")
            elif kind == "manual":
                f[s["id"]] = load_series_csv(MANUAL / f"{ref}.csv")
            if s.get("scale"):
                f[s["id"]] = f[s["id"]] * s["scale"]
        except FileNotFoundError:
            log(f"  ! 缺少数据 {s['id']}（{kind}:{ref}）")
    return f


# 全部图表统一起点：1971 年 8 月美元与黄金脱钩（此前是金本位/布雷顿森林，口径不可比）
HISTORY_START = "1971-01-01"


def load_long_gold() -> pd.Series:
    s = load_series_csv(RAW / "long_gold_monthly.csv")
    s.index = pd.to_datetime(s.index).to_period("M").to_timestamp()
    s = s.groupby(level=0).last()
    return s[s.index >= HISTORY_START]


def load_optional(series_id: str) -> pd.Series | None:
    """读取只作输入的 FRED 序列（如 CPIAUCNS）。"""
    p = RAW / "fred" / f"{series_id}.csv"
    if not p.exists():
        return None
    return load_series_csv(p)


def load_sge() -> pd.Series | None:
    p = RAW / "cn" / "sge_au9999.csv"
    if not p.exists():
        return None
    return load_series_csv(p)


# --------------------------------------------------------------------- 派生量
def derive(f: dict[str, pd.Series]) -> dict[str, pd.Series]:
    d: dict[str, pd.Series] = {}

    if "CPIAUCSL" in f:
        d["CPI_YOY"] = (f["CPIAUCSL"].pct_change(12) * 100).dropna()
    if "PCEPILFE" in f:
        d["PCE_YOY"] = (f["PCEPILFE"].pct_change(12) * 100).dropna()

    if "FYOINT" in f and "FYFR" in f:
        j = pd.concat([f["FYOINT"], f["FYFR"]], axis=1, keys=["i", "r"], sort=True).dropna()
        d["INTEREST_RATIO"] = (j["i"] / j["r"] * 100).dropna()

    # 财政压力指数：付息/收入(45%) + 赤字/GDP(25%) + 债务/GDP(30%)，利息项带非线性放大
    if "INTEREST_RATIO" in d and "GFDEGDQ188S" in f and "FYFSGDA188S" in f:
        base = pd.DataFrame({
            "interest": d["INTEREST_RATIO"],
            "deficit": f["FYFSGDA188S"].abs(),
            "debt": f["GFDEGDQ188S"],
        }).sort_index().ffill()
        base = base.dropna()
        if len(base) > 20:
            def norm(col: pd.Series, lo: float, hi: float) -> pd.Series:
                return ((col - lo) / (hi - lo) * 100).clip(0, 100)
            i_s = norm(base["interest"], 5, 35)
            # 付息/收入超过 15% 后加速：超过部分的权重按 (1+((x-15)/20)^1.5) 放大
            ampl = 1 + (((base["interest"] - 15).clip(lower=0) / 20) ** 1.5)
            i_s = (i_s * ampl).clip(0, 100)
            score = 0.45 * i_s + 0.25 * norm(base["deficit"], 0, 12) + 0.30 * norm(base["debt"], 40, 140)
            d["FISCAL_STRESS"] = score.clip(0, 100).round(1)

    # 人民币金价 + 上海金溢价
    gold_daily = f.get("GOLD")
    fx = f.get("DEXCHUS")
    if gold_daily is not None and fx is not None:
        fx_d = fx.reindex(fx.index.union(gold_daily.index)).ffill().reindex(gold_daily.index)
        d["GOLD_CNY"] = (gold_daily * fx_d * TROY_OZ_PER_GRAM).dropna()
        sge = load_sge()
        if sge is not None:
            parity = (gold_daily * fx_d * TROY_OZ_PER_GRAM).dropna()
            j = pd.concat([sge.reindex(sge.index.union(parity.index)).ffill(),
                           parity], axis=1, keys=["sge", "parity"], sort=True).dropna()
            d["SHANGHAI_PREMIUM"] = ((j["sge"] / j["parity"] - 1) * 100).dropna()

    # 金价动量：多空排列状态用「金价 - 200 日均线」的偏离度表示（正=多头排列）
    if gold_daily is not None and len(gold_daily) > 220:
        g = gold_daily
        ma20 = g.rolling(20).mean()
        ma60 = g.rolling(60).mean()
        ma200 = g.rolling(200).mean()
        state = ((g > ma20).astype(int) + (g > ma60).astype(int) + (g > ma200).astype(int))
        d["GOLD_MA"] = ma200.dropna()
        f["_gold_ma_state"] = state.dropna()
        f["_gold_ma"] = pd.DataFrame({"p": g, "ma20": ma20, "ma60": ma60,
                                      "ma200": ma200}).dropna()

    # 黄金年度涨跌幅（用月度长序列，覆盖 1916+）
    lg = load_long_gold()
    annual = lg.groupby(lg.index.year).last()
    this_year = lg.index[-1].year
    prev = annual[annual.index < this_year]
    prev.index = pd.to_datetime([f"{y}-12-31" for y in prev.index])
    if len(prev) > 2:
        # 只保留完整年份，避免「年初至今」被当成整年收益
        d["GOLD_ANNUAL_CHANGE"] = (prev.pct_change() * 100).dropna()
        d["GOLD_ANNUAL_CHANGE"] = d["GOLD_ANNUAL_CHANGE"][d["GOLD_ANNUAL_CHANGE"].index >= "1916-01-01"]
    if this_year in annual.index and len(prev):
        f["_gold_ytd"] = float((annual.iloc[-1] / prev.iloc[-1] - 1) * 100)

    return d


# --------------------------------------------------------------------- 小工具
def pct_change_lookback(s: pd.Series, days: int) -> float | None:
    """相对「至少 days 天前的最后一个观测」的变化率（%）。"""
    if len(s) < 2:
        return None
    cutoff = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= cutoff]
    if past.empty:
        return None
    base = past.iloc[-1]
    cur = s.iloc[-1]
    if base == 0 or not np.isfinite(base) or not np.isfinite(cur):
        return None
    return float((cur / base - 1) * 100)


def diff_lookback(s: pd.Series, days: int) -> float | None:
    if len(s) < 2:
        return None
    cutoff = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= cutoff]
    if past.empty:
        return None
    return float(s.iloc[-1] - past.iloc[-1])


def percentile(s: pd.Series, days: int) -> float | None:
    cutoff = s.index[-1] - pd.Timedelta(days=days)
    w = s[s.index >= cutoff]
    if len(w) < 8:
        return None
    cur = s.iloc[-1]
    return float((w < cur).sum() / len(w) * 100)


# 均值回归锚：近 10 年均值 ±1.5σ，只给有稳定中枢的序列加（趋势型不加，加了是误导）
BAND_K = 1.5
BAND_DAYS = 3650
BAND_SUFFIX = "深色实线为均值，点线为 \u00b11.5 倍标准差（随窗口重算）。"
BAND_CARD_IDS = {"NFCI", "GVZCLS", "DFII10", "T10YIE", "CPI_YOY", "PCE_YOY", "UNRATE", "GOLD_COT"}
BAND_CHART_IDS = {"shanghai_premium", "gpr_threat"}   # gold_ma_gap 的两条点线自带「拉伸/超跌」措辞，note 里已说明，不再拼后缀


def band_stats(s: pd.Series) -> dict | None:
    w = s.dropna()
    w = w[w.index >= w.index[-1] - pd.Timedelta(days=BAND_DAYS)]
    if len(w) < 30:
        return None
    mu, sd = float(w.mean()), float(w.std())
    if sd <= 0:
        return None
    r = lambda v: round(v, 3)
    return dict(mean=r(mu), up=r(mu + BAND_K * sd), dn=r(mu - BAND_K * sd), k=BAND_K)


def band_stats_log(s: pd.Series) -> dict | None:
    """对数空间的均值 ± BAND_K 倍标准差（取指数后即几何均值与乘法区间）。

    跨数量级的比值/价格序列（如 1 BTC 值多少盎司黄金，0.17–38）必须在对数空间算：
    算术标准差会算出负的下界（上例约 −0.6 盎司），对数轴上根本画不出来。
    """
    w = s.dropna()
    w = w[w.index >= w.index[-1] - pd.Timedelta(days=BAND_DAYS)]
    w = w[w > 0]
    if len(w) < 30:
        return None
    lw = np.log(w)
    mu, sd = float(lw.mean()), float(lw.std())
    if sd <= 0:
        return None
    r = lambda v: round(float(np.exp(v)), 3)
    return dict(mean=r(mu), up=r(mu + BAND_K * sd), dn=r(mu - BAND_K * sd),
                k=BAND_K, log=True)


def delta_meta(spec: dict) -> tuple[str, str]:
    """图头摘要的变化量口径：(mode, suffix)。

    mode='pct' → 涨跌幅，后缀 %；mode='diff' → 点差，后缀按单位走
    （百分点序列 pp，汇率无后缀，指数/头寸/吨用中文量词）。
    """
    mode = spec.get("delta")
    if mode is None:
        mode = "diff" if spec["unit"] in ("percent", "cny_per_usd") else "pct"
    if mode == "pct":
        return mode, "%"
    suffix = {"percent": "pp", "cny_per_usd": "",
              "index": "点", "contracts": "手", "tons": "吨"}.get(spec["unit"], "")
    return mode, suffix


def change_windows(s: pd.Series, freq: str, is_rate: bool) -> list[dict]:
    specs = {
        "d": [("5 日", 5), ("20 日", 20), ("3 月", 91), ("同比", 365)],
        "w": [("4 周", 28), ("13 周", 91), ("同比", 365)],
        "m": [("环比", 30), ("3 月", 91), ("同比", 365)],
        "q": [("环比", 91), ("同比", 365)],
        "a": [("同比", 365)],
    }[freq]
    out = []
    for label, days in specs:
        v = diff_lookback(s, days) if is_rate else pct_change_lookback(s, days)
        out.append({"label": label, "value": None if v is None else round(v, 2)})
    return out


def hist_points(s: pd.Series, max_n: int = 420) -> list[list]:
    """完整历史（用于点开后的交互图）。

    自适应降采样：保留最近 140 个观测的原始密度，更早的部分按步长抽样，
    这样「全部」区间也够看，又不至于把页面撑到几 MB。
    """
    s = s.dropna()
    n = len(s)
    if n > max_n:
        keep = 140
        step = max(1, int(np.ceil((n - keep) / max(1, max_n - keep))))
        s = pd.concat([s.iloc[:-keep].iloc[::step], s.iloc[-keep:]])
    return ts_points(s, "D", 4)


def ts_points(s: pd.Series, freq: str = "auto", precision: int = 4) -> list[list]:
    s = s.dropna()
    s = s[s.index >= HISTORY_START]
    if freq == "M":
        s = s.groupby(s.index.to_period("M")).last()
        s.index = s.index.to_timestamp()
        fmt = "%Y-%m"
    elif freq == "Y":
        s = s.groupby(s.index.year).last()
        idx = pd.to_datetime([f"{y}-01-01" for y in s.index])
        s.index = idx
        fmt = "%Y"
    elif freq == "W":
        s = s.groupby(s.index.to_period("W")).last()
        s.index = s.index.start_time
        fmt = "%Y-%m-%d"
    else:
        fmt = "%Y-%m-%d"
    return [[t.strftime(fmt), round(float(v), precision)] for t, v in s.items()]


# ------------------------------------------------------------------ 卡片组装
def build_cards(f: dict[str, pd.Series], d: dict[str, pd.Series]) -> dict[str, list]:
    by_section: dict[str, list] = {s["key"]: [] for s in SECTIONS}
    for spec in SERIES:
        sid = spec["id"]
        s = d.get(sid) if spec.get("derived") else f.get(sid)
        if s is None or len(s) < 2:
            continue
        s = s.dropna()
        delta_mode, delta_suffix = delta_meta(spec)
        is_rate = delta_mode == "diff"
        unit = UNIT_LABELS.get(spec["unit"], "")

        card = dict(
            id=sid, name=spec["name"],
            note=spec["note"] + (BAND_SUFFIX if sid in BAND_CARD_IDS else ""),
            unit=unit,
            unit_key=spec["unit"],
            delta_mode=delta_mode, delta_suffix=delta_suffix,
            gold=spec["gold"], freq=spec["freq"],
            value=round(float(s.iloc[-1]), spec["decimals"]),
            date=s.index[-1].strftime("%Y-%m-%d"),
            changes=change_windows(s, spec["freq"], is_rate),
            pct={k: (None if (v := percentile(s, day)) is None else round(v, 1))
                 for k, day in (("1y", 365), ("3y", 1095), ("10y", 3650))},
            hist=hist_points(s),
            bands=band_stats(s) if sid in BAND_CARD_IDS else None,
        )
        if sid == "GOLD_COT":
            cot = f.get("_cot")
            if cot is not None and len(cot):
                last = cot.iloc[-1]
                card["cot"] = dict(
                    mm_net=int(last["mm_net"]), mm_long=int(last["mm_long"]),
                    mm_short=int(last["mm_short"]), swap_net=int(last["swap_net"]),
                    oi=int(last["open_interest"]),
                )
        if sid == "GOLD_MA":
            st = f.get("_gold_ma_state")
            ma = f.get("_gold_ma")
            card["ma_state"] = int(st.iloc[-1]) if st is not None and len(st) else None
            if ma is not None and len(ma):
                last = ma.iloc[-1]
                card["ma"] = dict(price=round(float(last["p"]), 2),
                                  ma20=round(float(last["ma20"]), 2),
                                  ma60=round(float(last["ma60"]), 2),
                                  ma200=round(float(last["ma200"]), 2))
                card["note"] = ("三条均线的排列状态是趋势的代理：金价站在 20/60/200 日线之上为多头排列。"
                                "曲线本身是 200 日均线，长期趋势的中枢。")
        if sid == "GOLD_ANNUAL_CHANGE" and "_gold_ytd" in f:
            card["value"] = round(f["_gold_ytd"], 2)
            card["changes"] = []
            if "GOLD" in f:
                card["date"] = f["GOLD"].index[-1].strftime("%Y-%m-%d")
            card["note"] = "年初至今涨跌幅（当年未走完，年末会补成完整年度收益）。"
        if sid == "INTEREST_RATIO":
            card["gold_label"] = "付息/收入"
        by_section[spec["section"]].append(card)
    return by_section


# -------------------------------------------------------------------- 叙述生成
def fmt(v: float, nd: int = 1) -> str:
    return f"{v:,.{nd}f}"


def build_states(f: dict[str, pd.Series], d: dict[str, pd.Series],
                 cards: dict[str, list]) -> dict[str, dict]:
    def card(sid: str) -> dict | None:
        for lst in cards.values():
            for c in lst:
                if c["id"] == sid:
                    return c
        return None

    def gv(sid: str) -> float | None:
        c = card(sid)
        return None if c is None else c["value"]

    states: dict[str, dict] = {}

    # ---------------- 美元与流动性
    pts = []
    nfci = gv("NFCI")
    if nfci is not None:
        tone = "warn" if nfci > 0 else "good"
        txt = ("金融条件紧于平均，短期压制风险偏好" if nfci > 0
               else "金融条件松于平均，为风险资产和黄金提供流动性支撑")
        pts.append(dict(label="金融条件", value=fmt(nfci, 2), tone=tone, text=txt))
    dxy = gv("DTWEXBGS")
    if dxy is not None:
        ch = card("DTWEXBGS")["changes"][2]["value"]  # 3 月
        tone = "bad" if (ch or 0) > 1 else ("good" if (ch or 0) < -1 else "neutral")
        txt = ("美元走强，以美元计价的黄金承压" if tone == "bad"
               else "美元走弱，金价的计价分母在收缩" if tone == "good"
               else "美元方向不明，对金价的边际影响有限")
        pts.append(dict(label="广义美元", value=fmt(dxy, 2), tone=tone, text=txt))
    cny = gv("DEXCHUS")
    if cny is not None:
        pts.append(dict(label="美元/人民币", value=fmt(cny, 3), tone="neutral",
                        text="汇率是人民币金价的第二驱动，与美元金价叠加"))
    bull = sum(1 for p in pts if p["tone"] == "good")
    bear = sum(1 for p in pts if p["tone"] == "bad")
    verdict = "偏利多" if bull > bear else ("偏利空" if bear > bull else "中性")
    states["dollarliquidity"] = dict(verdict=verdict, points=pts)

    # ---------------- 通胀与增长（宏观象限）
    cpi = gv("CPI_YOY")
    pce = gv("PCE_YOY")
    unrate = gv("UNRATE")
    ip = gv("IPMAN")
    ip3m = card("IPMAN")["changes"][1]["value"] if card("IPMAN") else None
    growth_weak = (ip3m is not None and ip3m < 0) or (unrate is not None and unrate > 4.5)
    infl_high = (pce is not None and pce > 2.5) or (cpi is not None and cpi > 3)
    quadrant, qtext, qtone = "—", "数据不足", "neutral"
    if pce is not None or cpi is not None:
        if growth_weak and infl_high:
            quadrant, qtext, qtone = "滞胀", "最利多黄金：滞胀环境下黄金的保险价值凸显", "good"
        elif growth_weak and not infl_high:
            quadrant, qtext, qtone = "衰退", "看降息预期能否兑现，兑现则利多", "good"
        elif (not growth_weak) and infl_high:
            quadrant, qtext, qtone = "过热", "实际利率易维持高位，压制金价", "bad"
        else:
            quadrant, qtext, qtone = "金发姑娘", "中性偏空：要看实际利率和美元方向", "bad"
    pts = [dict(label="宏观象限", value=quadrant, tone=qtone, text=qtext)]
    if pce is not None:
        tone = "good" if pce > 2.5 else ("bad" if pce < 2 else "neutral")
        txt = ("通胀高于目标，降息空间受限，但中期支撑黄金的通胀对冲逻辑" if pce > 2.5
               else "通胀接近或低于目标，降息预期可能升温" if pce < 2
               else "略高于目标，政策利率可能维持较久")
        pts.append(dict(label="核心通胀", value=f"{pce:.2f}%", tone=tone, text=txt))
    if ip is not None:
        tone = "good" if (ip3m or 0) < 0 else "bad"
        pts.append(dict(label="制造业", value=fmt(ip, 1), tone=tone,
                        text=(f"近 3 月 {ip3m:+.2f}%，动能走弱，避险需求抬头" if (ip3m or 0) < 0
                              else f"近 3 月 {ip3m:+.2f}%，经济韧性对实际利率形成上行压力")))
    if unrate is not None:
        tone = "good" if unrate > 4.5 else ("bad" if unrate < 4 else "neutral")
        pts.append(dict(label="失业率", value=f"{unrate:.1f}%", tone=tone,
                        text=("就业市场压力增大，可能推动美联储转鸽" if unrate > 4.5
                              else "就业强劲，支撑利率维持高位" if unrate < 4
                              else "就业市场稳定，政策无迫切转向")))
    states["inflationgrowth"] = dict(verdict=quadrant, points=pts)

    # ---------------- 财政与信用
    pts = []
    stress = gv("FISCAL_STRESS")
    if stress is not None:
        stage = ("货币化隐忧" if stress >= 80 else
                 "金融抑制" if stress >= 65 else
                 "压力抬升" if stress >= 50 else "温和漂移")
        pts.append(dict(label="财政压力评分", value=f"{stress:.0f}/100",
                        tone="good" if stress >= 65 else "neutral",
                        text=f"当前处于「{stage}」阶段，评分越高代表财政对金价的支撑越强"))
    ir = gv("INTEREST_RATIO")
    if ir is not None:
        pts.append(dict(label="付息/收入", value=f"{ir:.1f}%",
                        tone="good" if ir > 20 else "neutral",
                        text=f"政府每收 100 元税，有 {ir:.0f} 元要拿去还利息"
                             + ("，利息支出已成财政最大单项压力" if ir > 20 else "，利息负担尚可")))
    debt = gv("GFDEGDQ188S")
    if debt is not None:
        pts.append(dict(label="债务/GDP", value=f"{debt:.0f}%",
                        tone="good" if debt > 100 else "neutral",
                        text=("已超过二战峰值（106%），和平时期史无前例" if debt > 106
                              else "已超过 100%，进入历史高位区间" if debt > 100
                              else "仍在可控范围")))
    deficit = gv("FYFSGDA188S")
    if deficit is not None:
        pts.append(dict(label="赤字/GDP", value=f"{abs(deficit):.1f}%",
                        tone="good" if abs(deficit) > 6 else "neutral",
                        text="赤字超过 6%，处于非衰退期的历史极端水平" if abs(deficit) > 6
                        else "赤字较大，财政纪律承压" if abs(deficit) > 3.5 else "赤字在可控范围"))
    cb = gv("CB_GOLD_NET")
    if cb is not None:
        pts.append(dict(label="央行年购金", value=f"{cb:.0f} 吨", tone="good",
                        text="央行持续购金反映对美元储备体系的担忧，是需求端的结构性支撑"))
    verdict = "偏利多" if (stress or 0) >= 65 else "中性"
    states["fiscalcredit"] = dict(verdict=verdict, points=pts)

    # ---------------- 机会成本
    pts = []
    r10 = gv("DFII10")
    r5 = gv("DFII5")
    if r10 is not None:
        tone = "good" if r10 < 1 else ("bad" if r10 > 2 else "neutral")
        pts.append(dict(label="实际利率", value=f"{r10:.2f}%", tone=tone,
                        text=("低实际利率降低持有黄金的机会成本" if r10 < 1 else
                              "高实际利率是黄金最直接的逆风，但 2022 年后相关性明显减弱"
                              if r10 > 2 else "实际利率中性，对金价压制有限")))
    bei = gv("T10YIE")
    if bei is not None:
        tone = "good" if bei > 2.5 else ("bad" if bei < 2 else "neutral")
        pts.append(dict(label="通胀预期", value=f"{bei:.2f}%", tone=tone,
                        text=("通胀预期高于 2.5%，黄金的通胀对冲价值更受重视" if bei > 2.5
                              else "通胀预期偏低，黄金的通胀叙事暂时弱化")))
    bull = sum(1 for p in pts if p["tone"] == "good")
    bear = sum(1 for p in pts if p["tone"] == "bad")
    states["opportunitycost"] = dict(
        verdict="偏利多" if bull > bear else ("偏利空" if bear > bull else "中性"), points=pts)

    # ---------------- 风险温度
    pts = []
    cot = card("GOLD_COT")
    if cot and cot.get("cot"):
        p1y = cot["pct"]["1y"]
        pts.append(dict(label="投机净多", value=f"{cot['cot']['mm_net']:,} 手",
                        tone="warn" if (p1y or 0) > 80 else ("good" if (p1y or 0) < 25 else "neutral"),
                        text=(f"处于近 1 年 {p1y:.0f}% 分位，多头拥挤度偏高，回撤风险上升"
                              if (p1y or 0) > 80 else
                              f"处于近 1 年 {p1y:.0f}% 分位，投机头寸偏低，反向支撑" if (p1y or 0) < 25
                              else f"处于近 1 年 {p1y:.0f}% 分位，投机头寸中性")))
    ma = card("GOLD_MA")
    if ma and ma.get("ma_state") is not None:
        st = ma["ma_state"]
        pts.append(dict(label="均线动量",
                        value={3: "多头排列", 2: "偏多", 1: "偏空", 0: "空头排列"}.get(st, "—"),
                        tone="good" if st >= 2 else ("bad" if st == 0 else "neutral"),
                        text=f"金价站在 {st}/3 条均线之上（20/60/200 日）"))
    gvz = gv("GVZCLS")
    if gvz is not None:
        pts.append(dict(label="黄金波动率", value=f"{gvz:.1f}",
                        tone="warn" if gvz > 25 else "neutral",
                        text=("突破 25，需警惕短期剧烈波动" if gvz > 25
                              else "处于低波动区间，低波动期后常伴随方向性突破")))
    gld = gv("GLD")
    if gld is not None:
        ch = card("GLD")["changes"][2]["value"]
        pts.append(dict(label="黄金 ETF", value=f"${gld:.2f}",
                        tone="good" if (ch or 0) > 0 else "bad",
                        text=f"近 3 月 {ch:+.1f}%，西方机构配置意愿的代理变量"))
    states["risktemperature"] = dict(verdict="观察", points=pts)

    # ---------------- 官方市场
    pts = []
    lg = load_long_gold()
    if len(lg) > 2:
        pts.append(dict(label="金价走势", value=f"${gv('GOLD'):,.0f}" if gv("GOLD") else "",
                        tone="good",
                        text="长历史视角下，金价仍处于 2022 年以来这一轮上行的高位区间"))
    gs = None
    silver = gv("SILVER")
    gold_px = gv("GOLD")
    if silver and gold_px:
        gs = gold_px / silver
        pts.append(dict(label="金银比", value=f"{gs:.1f}",
                        tone="good" if gs > 80 else ("bad" if gs < 50 else "neutral"),
                        text=("金银比超过 80，白银相对低估或衰退信号" if gs > 80
                              else "金银比低于 50，工业与投机需求旺盛" if gs < 50
                              else "金银比处于长期均值附近")))
    oil = gv("OIL")
    if oil and gold_px:
        pts.append(dict(label="金油比", value=f"{gold_px / oil:.1f}",
                        tone="neutral", text="金油比高企代表避险需求相对更强、通胀传导偏弱"))
    prem = gv("SHANGHAI_PREMIUM")
    if prem is not None:
        pts.append(dict(label="上海金溢价", value=f"{prem:+.2f}%",
                        tone="good" if prem < 0 else "bad",
                        text=("国内金价低于国际折算价，实物需求偏弱" if prem < 0
                              else "国内买家愿意支付溢价，实物需求强")))
    score = 0
    if gs is not None and gs > 80:
        score += 1
    if prem is not None and prem > 0:
        score += 1
    for sid in ("XAU", "HUI"):
        c_ = card(sid)
        g_ = card("GOLD")
        if c_ and g_:
            x = c_["changes"][-1]["value"]
            y = g_["changes"][-1]["value"]
            if x is not None and y is not None and x > y:
                score += 1
                break
    verdict = "偏利多" if score >= 2 else ("偏利空" if score == 0 else "中性")
    states["officialmarket"] = dict(verdict=verdict, points=pts)
    return states


# -------------------------------------------------------------------- 图表数据
def _bull_bear_legs(v: np.ndarray, th: float) -> list[dict]:
    """±阈值折返法切牛熊：自高点回撤 ≥th 转熊、自低点反弹 ≥th 转牛。

    与 tools/bullbear_cycle.py 里的 detect_legs 同源（那边是独立脚本，故不互相引用）。
    返回 [{kind, start, end}]，索引为序列下标；相邻两段共享转折点。
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


def bull_bear_payload(s: pd.Series, threshold_pct: float) -> dict:
    """前端消费的牛熊数据：每段带 [毫秒时间戳, 本段累计%, 点位] 逐点。"""
    v = s.to_numpy(dtype=float)
    ms = (s.index - pd.Timestamp("1970-01-01")) // pd.Timedelta("1ms")
    legs = []
    for lg in _bull_bear_legs(v, threshold_pct / 100.0):
        p0 = float(v[lg["start"]])
        cum = float(v[lg["end"]] / p0 - 1.0)
        months = (s.index[lg["end"]].to_period("M") - s.index[lg["start"]].to_period("M")).n
        years = months / 12 if months > 0 else max(
            (s.index[lg["end"]] - s.index[lg["start"]]).days / 365.25, 1e-3)
        ann = (1.0 + cum) ** (1.0 / years) - 1.0 if 1.0 + cum > 0 else -1.0
        pts = [[int(ms[i]), round(float(v[i] / p0 - 1.0) * 100, 1), round(float(v[i]), 1)]
               for i in range(lg["start"], lg["end"] + 1)]
        legs.append(dict(
            kind=lg["kind"],
            start=s.index[lg["start"]].strftime("%Y.%m"),
            end=s.index[lg["end"]].strftime("%Y.%m"),
            months=int(months), cum=round(cum * 100, 1), ann=round(ann * 100, 1),
            ongoing=bool(lg.get("ongoing")), points=pts))
    # 右侧留白给最后一段的峰谷标注
    pad = int((int(ms[-1]) - int(ms[0])) * 0.06)
    return dict(legs=legs, xmax=int(ms[-1]) + pad, unit=" 美元/盎司")


def build_charts(f: dict[str, pd.Series], d: dict[str, pd.Series]) -> dict[str, dict]:
    lg = load_long_gold()
    out: dict[str, dict] = {}

    def meta(cid: str) -> dict:
        c = next(c for c in CHARTS if c["id"] == cid)
        note = c["note"] + (BAND_SUFFIX if cid in BAND_CHART_IDS else "")
        return dict(title=c["title"], note=note)

    # 1 国际金价（对数）—— load_long_gold 已裁到 1971 起
    out["gold_long_log"] = dict(
        series=[dict(name="伦敦金（美元/盎司）", points=ts_points(lg, "M", 2))],
        log=True, unit="美元/盎司",
        **meta("gold_long_log"))

    # 2 人民币金价（对数）
    cny = d.get("GOLD_CNY")
    if cny is not None:
        out["cny_gold"] = dict(
            series=[dict(name="人民币金价（元/克）", points=ts_points(cny, "M", 2))],
            log=True, unit="元/克", **meta("cny_gold"))

    # 3 上海金溢价
    prem = d.get("SHANGHAI_PREMIUM")
    if prem is not None:
        out["shanghai_premium"] = dict(
            series=[dict(name="上海金溢价（%）", points=ts_points(prem, "D", 3))],
            unit="%", zero_line=True, bands=band_stats(prem), **meta("shanghai_premium"))

    # 3b 地缘政治风险（GPR 威胁指数，Caldara-Iacoviello 月度；缺数时跳过，更新跑 scripts/fetch_gpr.py）
    try:
        gpr = load_series_csv(RAW / "gpr_threat_monthly.csv")
    except FileNotFoundError:
        gpr = None
        log("  ! 缺少数据 GPR（gpr_threat_monthly.csv）")
    if gpr is not None and len(gpr) > 30:
        last_g = float(gpr.iloc[-1])
        out["gpr_threat"] = dict(
            series=[dict(name="GPR 威胁指数", points=ts_points(gpr, "M", 1))],
            unit="", bands=band_stats(gpr),
            extra=f"最新 {last_g:.0f}（1985–2019 均值=100）",
            **meta("gpr_threat"))

    # 4 黄金牛熊周期（±阈值折返法，每段从 0% 重新起算）
    out["gold_bullbear"] = dict(
        **bull_bear_payload(lg.loc[HISTORY_START:], BULL_BEAR_THRESHOLD),
        label_min=100, scale="pct", threshold=BULL_BEAR_THRESHOLD,
        **meta("gold_bullbear"))

    # 5 距高点回撤
    dd = (lg / lg.cummax() - 1) * 100
    worst = dd.min()
    out["gold_drawdown"] = dict(
        series=[dict(name="回撤（%）", points=ts_points(dd, "M", 2))],
        unit="%", area=True, extra=f"历史最深回撤 {worst:.0f}%", **meta("gold_drawdown"))

    # 6 年度涨跌幅（用长序列）
    annual_ret = d.get("GOLD_ANNUAL_CHANGE")
    if annual_ret is not None:
        annual_ret = annual_ret.loc[HISTORY_START:]
        pts = [[f"{t.year}", round(float(v), 2)] for t, v in annual_ret.items()]
        up = sum(1 for _, v in pts if v > 0)
        out["gold_annual"] = dict(
            series=[dict(name="年度涨跌幅（%）", points=pts)],
            unit="%", bar=True, sign_color=True,
            extra=f"{len(pts)} 年中上涨 {up} 年（{up / len(pts) * 100:.0f}%）",
            **meta("gold_annual"))

    # 8 黄金 vs 大类资产
    windows = [("1 年", 1), ("3 年", 3), ("5 年", 5), ("10 年", 10), ("20 年", 20)]
    assets = [("黄金", "GOLD"), ("标普500", "SPY"), ("纳指100", "QQQ"),
              ("长债 TLT", "TLT"), ("中债 IEF", "IEF"), ("短债 SHV", "SHV")]
    rows = []
    for label, sid in assets:
        s = f.get(sid)
        row = dict(name=label, values=[])
        for _, yrs in windows:
            start = s.index[-1] - pd.DateOffset(years=yrs) if s is not None and len(s) else None
            if s is None or start is None:
                row["values"].append(None)
                continue
            sub = s[s.index >= start]
            if len(sub) < 2 or sub.iloc[0] <= 0:
                row["values"].append(None)
                continue
            ann = (sub.iloc[-1] / sub.iloc[0]) ** (1 / yrs) - 1
            row["values"].append(round(float(ann * 100), 2))
        rows.append(row)
    out["asset_returns"] = dict(
        windows=[w for w, _ in windows], rows=rows, unit="%", **meta("asset_returns"))

    # 9 比特币的黄金计价：1 BTC 值多少盎司黄金
    #   原先是「双轴价格对比」，与本文件否掉「金价 vs 油价」双轴的理由相同：两条各自缩放的线
    #   只能看出「都涨了」。换成单轴比值后是一条可读的线——升 = 贬值对冲的钱更偏好比特币，降 = 回到黄金。
    #   均值 ±1.5σ 与其他图同一套视觉语言，但在对数空间算（见 band_stats_log）。
    btc = f.get("BTC_USD")
    if btc is not None:
        gm = lg[lg.index >= "2014-01-01"]
        gm.index = gm.index.to_period("M")
        bm = btc[btc.index >= pd.Timestamp("2014-01-01")]
        bm = bm.groupby(bm.index.to_period("M")).last()
        ratio = (bm / gm.reindex(bm.index)).dropna()
        if len(ratio) > 24:
            ratio.index = ratio.index.to_timestamp()
            out["gold_vs_btc"] = dict(
                series=[dict(name="1 BTC 值多少盎司黄金", points=ts_points(ratio, "M", 2))],
                log=True, unit=" 盎司", bands=band_stats_log(ratio),
                extra=(f"当前 1 BTC = {float(ratio.iloc[-1]):.1f} 盎司黄金 · "
                       f"历史区间 {float(ratio.min()):.2f} — {float(ratio.max()):.0f} 盎司"),
                **meta("gold_vs_btc"))

    # 12 市值对比（已下线：三序列同一对数轴只讲「体量」一个数字，见头图「地上黄金存量市值」）
    # 14 金油比（取代双轴「金价 vs 油价」：两条各自缩放的双轴看不出相关，比率才是一根可读的线）
    oil = f.get("OIL")
    gold_px = f.get("GOLD")
    if oil is not None and gold_px is not None:
        # 2020-04 WTI 结算价为负，先剔除再算比率（否则比值飞出天际）
        j = pd.concat([gold_px, oil[oil > 1]], axis=1, keys=["g", "o"], sort=True).dropna()
        ratio = (j["g"] / j["o"]).dropna()
        if len(ratio) > 30:
            last_r = float(ratio.iloc[-1])
            med_r = round(float(ratio.median()), 1)
            out["gold_oil_ratio"] = dict(
                series=[dict(name="金油比（倍）", points=ts_points(ratio, "M", 2))],
                log=True, unit=" 倍", median=med_r,
                extra=f"当前 {last_r:.1f} 倍 · 2000 年以来中位数 {med_r} 倍",
                **meta("gold_oil_ratio"))

    # 15 金银比 / 17 矿股比率：已下线（金银比与金油比保留在「官方市场」状态叙述里）
    # 19 金价相对 200 日均线的偏离度（动量的正确画法：三条均线排列 → 一条可读的偏离度）
    ma = f.get("_gold_ma")
    if ma is not None and len(ma) > 2:
        gap = ((ma["p"] / ma["ma200"] - 1) * 100).dropna()
        last_gap = float(gap.iloc[-1])
        out["gold_ma_gap"] = dict(
            series=[dict(name="偏离度（%）", points=ts_points(gap, "M", 2))],
            unit="%", zero_line=True, fill_sign=True, bands=band_stats(gap),
            extra=f"最新 {last_gap:+.1f}%（200 日均线{'上方' if last_gap >= 0 else '下方'}）",
            **meta("gold_ma_gap"))

    # 18 美联储资产负债表 vs 金价
    walcl = f.get("WALCL")
    if walcl is not None:
        g = lg[lg.index >= "2003-01-01"]
        out["walcl_gold"] = dict(
            series=[dict(name="美联储总资产（万亿美元）", points=ts_points(walcl, "W", 3)),
                    dict(name="金价（美元/盎司）", points=ts_points(g, "M", 2), axis=1)],
            dual=True, unit="", **meta("walcl_gold"))

    return out


# ----------------------------------------------------------------------- main
def main() -> None:
    log("== 计算 ==")
    f = load_raw()
    d = derive(f)
    cards = build_cards(f, d)
    states = build_states(f, d, cards)

    sections = []
    # 「历史洞察」里被分到板块的图，不再出现在主图上
    pinned = {cid for sec in SECTIONS for cid in sec.get("charts", [])}
    for sec in SECTIONS:
        want = sec.get("cards")
        sec_cards = cards.get(sec["key"], [])
        if want == "hide":
            sec_cards = []
        elif isinstance(want, list):          # 只保留白名单里的卡片
            sec_cards = [c for c in sec_cards if c["id"] in want]
        # 板块内的图：指标卡升级成的图（kind=card）+ 从历史洞察并进来的大图（kind=insight）
        entries = [dict(id=c["id"], kind="card") for c in sec_cards]
        entries += [dict(id=cid, kind="insight") for cid in sec.get("charts", [])]
        sections.append(dict(
            key=sec["key"], title=sec["title"], subtitle=sec["subtitle"],
            anchor=sec["anchor"], cards=sec_cards, charts=entries,
            state=states.get(sec["key"], dict(verdict="—", points=[])),
        ))

    gold = f.get("GOLD")
    gold_cny = d.get("GOLD_CNY")
    hero = {}
    if gold is not None:
        hero["gold"] = dict(
            value=round(float(gold.iloc[-1]), 1), date=gold.index[-1].strftime("%Y-%m-%d"),
            chg_1d=round(float(gold.pct_change().iloc[-1] * 100), 2),
            chg_ytd=round(float(gold.iloc[-1] / gold[gold.index.year == gold.index[-1].year].iloc[0] * 100 - 100), 2),
            chg_1y=round(float(gold.iloc[-1] / gold[gold.index <= gold.index[-1] - pd.Timedelta(days=365)].iloc[-1] * 100 - 100), 2),
        )
        oz = ABOVE_GROUND_TONNES * TROY_OZ_PER_TONNE
        hero["gold"]["mcap_trillion"] = round(float(gold.iloc[-1] * oz / 1e12), 1)
        hero["gold"]["above_ground"] = f"{ABOVE_GROUND_TONNES:,} 吨"
    if gold_cny is not None:
        hero["gold_cny"] = dict(
            value=round(float(gold_cny.iloc[-1]), 1), date=gold_cny.index[-1].strftime("%Y-%m-%d"),
            chg_1d=round(float(gold_cny.pct_change().iloc[-1] * 100), 2),
        )

    charts = build_charts(f, d)

    payload = dict(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        generated_at_local=datetime.now().strftime("%Y-%m-%d %H:%M"),
        hero=hero,
        sections=sections,
        charts=charts,
        chart_order=[c["id"] for c in CHARTS if c["id"] in charts and c["id"] not in pinned],
        sources=[
            "宏观指标：FRED（圣路易斯联储）—— 实际收益率、通胀预期、美元指数、失业率、联储资产负债表、财政数据",
            "金融条件：芝加哥联储 NFCI",
            "金价与资产：COMEX 黄金期货主力连续、Yahoo Finance（ETF、金银油、矿股指数）",
            "长期金价：datasets/gold-prices 月度伦敦金价（1833 年起；金价走势图从 1971 年起）",
            "央行与储备：世界黄金协会 WGC（央行净购金）、IMF COFER（美元储备占比）",
            "交易商头寸：CFTC 持仓报告（Disaggregated Futures Only）",
            "比特币：Blockchain.com 市值、Yahoo Finance 价格",
            "上海金：上海黄金交易所 Au99.99（akshare）",
        ],
    )
    json_write(DATA / "board.json", payload)
    log(f"  卡片 {sum(len(v) for v in cards.values())} 张 / 图表 {len(charts)} 张 → data/board.json"
        f"（{round((DATA / 'board.json').stat().st_size / 1024)} KB）")


if __name__ == "__main__":
    main()
