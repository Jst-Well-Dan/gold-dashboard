"""抓数：每个数据源一个函数，落盘到 data/raw/ 下。

设计原则
- 一律先落 CSV / JSON（可追溯、可重算），build 阶段不再联网。
- **抓不抓由 manifest.Ledger 判断**：TTL 按指标频率分档
  （日 8h / 周 2d / 月 12d / 季 30d / 年 300d）。不再用文件 mtime ——
  GitHub Actions 里 checkout 与 cache 恢复都会把 mtime 刷成「现在」，
  用 mtime 判断必然失效（要么永不更新，要么每天全量重抓）。
- 每次运行（成功 / 跳过 / 降级 / 失败）都记进 data/fetch_manifest.json，
  既供 docs/status.html 展示，也是下一次 TTL 判断的唯一依据。
- FRED 必须串行 + 退避（突发会限流）。
"""
from __future__ import annotations

import io
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from config import EXTRA_FRED, SERIES
from manifest import Ledger
from util import (MANUAL, RAW, curl_text, get, json_write, log, parse_fred_csv,
                  save_text, write_series_csv)

FRED_IDS = sorted({s["src"][1] for s in SERIES if s.get("src") and s["src"][0] == "fred"} | set(EXTRA_FRED))
YAHOO_SYMS = sorted({s["src"][1] for s in SERIES if s.get("src") and s["src"][0] == "yahoo"})


# --------------------------------------------------------------------- FRED
def fetch_fred(L: Ledger) -> None:
    out = RAW / "fred"
    out.mkdir(parents=True, exist_ok=True)
    for sid in FRED_IDS:
        key = f"fred:{sid}"
        p = out / f"{sid}.csv"
        due, why = L.due(key, p)
        if not due:
            log(f"  FRED {sid:18s} 跳过（{why}）")
            L.skip(key, p, why)
            continue
        try:
            txt = curl_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                            timeout=60, retries=4, sleep=2.5)
            df = parse_fred_csv(txt)
            if df.empty:
                raise RuntimeError("返回空表")
            save_text(p, df.to_csv(index=False))
            msg = f"{len(df)} 行  最新 {df['date'].iloc[-1]} = {df['value'].iloc[-1]:g}"
            log(f"  FRED {sid:18s} {msg}")
            L.ok(key, p, msg)
        except Exception as e:  # noqa: BLE001
            if p.exists():
                log(f"  FRED {sid:18s} 抓取失败，沿用旧缓存（{e}）")
                L.stale(key, p, str(e))
            else:
                log(f"  FRED {sid:18s} 抓取失败且无缓存：{e}")
                L.fail(key, str(e))
        time.sleep(0.8)  # 串行节流，防限流


# -------------------------------------------------------------------- Yahoo
def fetch_yahoo(L: Ledger) -> None:
    out = RAW / "yahoo"
    out.mkdir(parents=True, exist_ok=True)
    for sym in YAHOO_SYMS:
        key = f"yahoo:{sym}"
        p = out / f"{sym.replace('^', 'IDX_').replace('=', '_')}.csv"
        due, why = L.due(key, p)
        if not due:
            log(f"  YAHOO {sym:10s} 跳过（{why}）")
            L.skip(key, p, why)
            continue
        try:
            # 注意：range=max 会让 Yahoo 自动降采样成月线，必须用 period1/period2
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}"
                   "?period1=0&period2=2000000000&interval=1d&includeAdjustedClose=true")
            r = get(url, timeout=40, retries=3, sleep=2)
            res = r.json()["chart"]["result"][0]
            ts = res["timestamp"]
            q = res["indicators"]["quote"][0]
            adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
            df = pd.DataFrame({
                "date": [datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in ts],
                "close": q["close"],
                "adjclose": adj if adj else q["close"],
            }).dropna(subset=["close"])
            df["date"] = pd.to_datetime(df["date"])
            df = df.drop_duplicates("date").sort_values("date")
            save_text(p, df.to_csv(index=False))
            msg = (f"{len(df)} 行  {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}"
                   f" 最新 {df['close'].iloc[-1]:.2f}")
            log(f"  YAHOO {sym:10s} {msg}")
            L.ok(key, p, msg)
        except Exception as e:  # noqa: BLE001
            if p.exists():
                log(f"  YAHOO {sym:10s} 抓取失败，沿用旧缓存（{e}）")
                L.stale(key, p, str(e))
            else:
                log(f"  YAHOO {sym:10s} 抓取失败且无缓存：{e}")
                L.fail(key, str(e))
        time.sleep(0.6)


# ---------------------------------------------------------------------- COT
def fetch_cot(L: Ledger) -> None:
    key = "cot:GOLD_COT"
    p = RAW / "cot" / "GOLD_COT.csv"
    due, why = L.due(key, p)
    if not due:
        log(f"  CFTC GOLD_COT 跳过（{why}）")
        L.skip(key, p, why)
        return
    url = ("https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
           "?$where=cftc_contract_market_code='088691'"
           "&$order=report_date_as_yyyy_mm_dd%20ASC&$limit=5000")
    try:
        r = get(url, timeout=60, retries=3, sleep=2)
        rows = r.json()
        df = pd.DataFrame({
            "date": [x["report_date_as_yyyy_mm_dd"][:10] for x in rows],
            "mm_long": [float(x.get("m_money_positions_long_all") or 0) for x in rows],
            "mm_short": [float(x.get("m_money_positions_short_all") or 0) for x in rows],
            "swap_long": [float(x.get("swap_positions_long_all") or 0) for x in rows],
            "swap_short": [float(x.get("swap__positions_short_all") or 0) for x in rows],
            "open_interest": [float(x.get("open_interest_all") or 0) for x in rows],
        })
        df["mm_net"] = df["mm_long"] - df["mm_short"]
        df["swap_net"] = df["swap_long"] - df["swap_short"]
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").sort_values("date")
        p.parent.mkdir(parents=True, exist_ok=True)
        save_text(p, df.to_csv(index=False))
        msg = f"{len(df)} 行  最新 {df['date'].iloc[-1].date()} MM净多 {df['mm_net'].iloc[-1]:,.0f} 手"
        log(f"  CFTC GOLD_COT {msg}")
        L.ok(key, p, msg)
    except Exception as e:  # noqa: BLE001
        if p.exists():
            log(f"  CFTC GOLD_COT 抓取失败，沿用旧缓存（{e}）")
            L.stale(key, p, str(e))
        else:
            log(f"  CFTC GOLD_COT 抓取失败且无缓存：{e}")
            L.fail(key, str(e))


# ----------------------------------------------------------------- Treasury
def fetch_treasury(L: Ledger) -> None:
    key = "treasury:debt_to_penny"
    p = RAW / "treasury" / "debt_to_penny.csv"
    due, why = L.due(key, p)
    if not due:
        log(f"  TREASURY debt_to_penny 跳过（{why}）")
        L.skip(key, p, why)
        return
    url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny"
           "?filter=record_date:gte:1993-04-01&sort=record_date&page[size]=10000")
    try:
        r = get(url, timeout=90, retries=3, sleep=2)
        data = r.json()["data"]
        df = pd.DataFrame({
            "date": [x["record_date"] for x in data],
            "value": [float(x["tot_pub_debt_out_amt"] or 0) for x in data],
        })
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").sort_values("date")
        p.parent.mkdir(parents=True, exist_ok=True)
        save_text(p, df.to_csv(index=False))
        msg = f"{len(df)} 行  最新 {df['date'].iloc[-1].date()} = {df['value'].iloc[-1] / 1e12:.2f} 万亿"
        log(f"  TREASURY 债务 {msg}")
        L.ok(key, p, msg)
    except Exception as e:  # noqa: BLE001
        if p.exists():
            log(f"  TREASURY 债务 抓取失败，沿用旧缓存（{e}）")
            L.stale(key, p, str(e))
        else:
            log(f"  TREASURY 债务 抓取失败且无缓存：{e}")
            L.fail(key, str(e))


# ---------------------------------------------------------------------- IMF
def fetch_imf_cofer(L: Ledger) -> None:
    key = "imf:cofer"
    p = RAW / "imf" / "cofer_usd_share.csv"
    due, why = L.due(key, p)
    if not due:
        log(f"  IMF COFER 跳过（{why}）")
        L.skip(key, p, why)
        return
    err = ""
    for freq in ("Q", "A"):
        try:
            url = ("https://api.imf.org/external/sdmx/2.1/data/IMF.STA,COFER,7.0.1/"
                   f"G001.AFXRA.CI_USD.SHRO_PT.{freq}?startPeriod=1995")
            r = get(url, timeout=60, retries=3, sleep=2, headers={"Accept": "application/json"})
            d = r.json()
            series = d["dataSets"][0].get("series")
            if not series:
                raise RuntimeError("空数据")
            obs = list(series.values())[0]["observations"]
            periods = d["structure"]["dimensions"]["observation"][0]["values"]
            rows = []
            for k, v in obs.items():
                per = periods[int(k)]["id"]          # 1995-Q1 / 1995
                val = v[0]
                if val is None:
                    continue
                if freq == "Q":
                    y, q = per.split("-Q")
                    ts = pd.Timestamp(year=int(y), month=(int(q) - 1) * 3 + 1, day=1)
                else:
                    ts = pd.Timestamp(year=int(per), month=1, day=1)
                rows.append((ts, float(val)))
            s = pd.Series({t: v for t, v in rows}).sort_index()
            write_series_csv(p, s)
            msg = f"{len(s)} 期  最新 {s.index[-1]:%Y-%m} = {s.iloc[-1]:.2f}%"
            log(f"  IMF COFER 美元占比 {msg}")
            L.ok(key, p, msg)
            return
        except Exception as e:  # noqa: BLE001
            err = f"{freq}: {e}"
            log(f"  IMF COFER {freq} 失败：{e}")
    if p.exists():
        log("  IMF COFER 沿用旧缓存")
        L.stale(key, p, err or "Q/A 两个口径都失败")
    else:
        L.fail(key, err or "Q/A 两个口径都失败")


# -------------------------------------------------------------------- crypto
def fetch_crypto(L: Ledger) -> None:
    key = "crypto:btc_mcap"
    p = RAW / "crypto" / "btc_mcap.csv"
    due, why = L.due(key, p)
    if not due:
        log(f"  BLOCKCHAIN 市值 跳过（{why}）")
        L.skip(key, p, why)
        return
    try:
        r = get("https://api.blockchain.info/charts/market-cap?format=json&timespan=all",
                timeout=90, retries=3, sleep=2)
        vals = r.json()["values"]
        df = pd.DataFrame({
            "date": [datetime.fromtimestamp(v["x"], timezone.utc).date().isoformat() for v in vals],
            "value": [float(v["y"]) for v in vals],
        })
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").sort_values("date")
        p.parent.mkdir(parents=True, exist_ok=True)
        save_text(p, df.to_csv(index=False))
        msg = f"{len(df)} 行  最新 {df['date'].iloc[-1].date()} = {df['value'].iloc[-1] / 1e9:.0f}B"
        log(f"  BLOCKCHAIN 市值 {msg}")
        L.ok(key, p, msg)
    except Exception as e:  # noqa: BLE001
        if p.exists():
            log(f"  BLOCKCHAIN 市值 抓取失败，沿用旧缓存（{e}）")
            L.stale(key, p, str(e))
        else:
            log(f"  BLOCKCHAIN 市值 抓取失败且无缓存：{e}")
            L.fail(key, str(e))


# ----------------------------------------------------------------- 上海金
def fetch_sge(L: Ledger) -> None:
    key = "sge:au9999"
    p = RAW / "cn" / "sge_au9999.csv"
    due, why = L.due(key, p)
    if not due:
        log(f"  SGE Au99.99 跳过（{why}）")
        L.skip(key, p, why)
        return
    try:
        import akshare as ak
        df = ak.spot_hist_sge(symbol="Au99.99")
        df = df[["date", "close"]].rename(columns={"close": "value"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").sort_values("date")
        p.parent.mkdir(parents=True, exist_ok=True)
        save_text(p, df.to_csv(index=False))
        msg = f"{len(df)} 行  最新 {df['date'].iloc[-1].date()} = {df['value'].iloc[-1]:.2f} 元/克"
        log(f"  SGE Au99.99 {msg}")
        L.ok(key, p, msg)
    except Exception as e:  # noqa: BLE001
        if p.exists():
            log(f"  SGE Au99.99 失败，沿用旧缓存（{e}）")
            L.stale(key, p, str(e))
        else:
            log(f"  SGE Au99.99 失败（溢价图将留空）：{e}")
            L.fail(key, str(e))


# ------------------------------------------------- WGC 官方回报（CNY 口径）
WGC_URL = ("https://fsapi.gold.org/api/gold-returns/v12Crypto/charts/"
           "chart-table-combined/chart/cny/yesterday")
WGC_DIR = RAW / "wgc"
WGC_PATH = WGC_DIR / "gold_returns_cny.json"
WGC_STATUS = WGC_DIR / "fetch_status.json"


def fetch_wgc_returns(L: Ledger) -> None:
    """WGC 黄金回报官方口径（CNY bucket）。

    成功 → 落盘 data/raw/wgc/gold_returns_cny.json；失败 → 沿用旧缓存（若有）。
    status json 仍照写：compute.py 用它判断是否要在图上标「沿用旧数据」。
    """
    key = "wgc:returns"

    def _status(ok: bool, msg: str, asof=None) -> None:
        json_write(WGC_STATUS, dict(
            ok=ok, message=msg, asOf=asof,
            time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))

    def _asof() -> str | None:
        try:
            return json.loads(WGC_PATH.read_text(encoding="utf-8")).get("chartData", {}).get("asOfDate")
        except Exception:  # noqa: BLE001
            return None

    due, why = L.due(key, WGC_PATH)
    if not due:
        asof = _asof()
        log(f"  WGC 回报(CNY) 跳过（{why}，asOf={asof}）")
        _status(True, "缓存命中", asof)
        L.skip(key, WGC_PATH, why)
        return
    try:
        r = get(WGC_URL, timeout=60, retries=3, sleep=2)
        data = r.json()
        rows = data.get("chartData", {}).get("tableData", {}).get("rows", [])
        if not rows:
            raise RuntimeError("WGC 返回空 rows")
        asof = data.get("chartData", {}).get("asOfDate")
        save_text(WGC_PATH, json.dumps(data, ensure_ascii=False))
        msg = f"{len(rows)} 行  asOf={asof}"
        log(f"  WGC 回报(CNY) {msg}")
        _status(True, f"asOf={asof}", asof)
        L.ok(key, WGC_PATH, msg)
    except Exception as e:  # noqa: BLE001
        asof = _asof()
        if WGC_PATH.exists():
            age_d = (time.time() - WGC_PATH.stat().st_mtime) / 86400
            msg = f"抓取失败，已沿用 {age_d:.1f} 天前的缓存 (asOf={asof})：{e}"
            log(f"  ⚠ WGC 回报 {msg}")
            _status(False, msg, asof)
            L.stale(key, WGC_PATH, str(e))
        else:
            log(f"  ✖ WGC 回报抓取失败且无缓存：{e}")
            _status(False, f"抓取失败且无缓存：{e}")
            L.fail(key, str(e))


# --------------------------------------------- WGC 黄金相关性矩阵（CNY 口径）
WGC_CORR_URL = ("https://fsapi-china.gold.org/api/gold-returns/v12Crypto/charts/"
                "correlations/cny/false/false/weekly/1YEAR")
WGC_CORR_PATH = WGC_DIR / "gold_correlations_cny.json"
WGC_CORR_STATUS = WGC_DIR / "correlations_status.json"


def fetch_wgc_correlations(L: Ledger) -> None:
    """WGC 相关性矩阵（CNY 口径，周频，近 6 年窗口）。"""
    key = "wgc:correlations"

    def _status(ok: bool, msg: str, asof=None) -> None:
        json_write(WGC_CORR_STATUS, dict(
            ok=ok, message=msg, asOf=asof,
            time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))

    def _asof() -> str | None:
        try:
            return json.loads(WGC_CORR_PATH.read_text(encoding="utf-8")).get("chartData", {}).get("asOfDate")
        except Exception:  # noqa: BLE001
            return None

    due, why = L.due(key, WGC_CORR_PATH)
    if not due:
        asof = _asof()
        log(f"  WGC 相关性矩阵 跳过（{why}，asOf={asof}）")
        _status(True, "缓存命中", asof)
        L.skip(key, WGC_CORR_PATH, why)
        return
    try:
        r = get(WGC_CORR_URL, timeout=90, retries=3, sleep=2)
        data = r.json()
        out = data.get("chartData", {}).get("output", {})
        if not out:
            raise RuntimeError("WGC correlations 返回空矩阵")
        asof = data.get("chartData", {}).get("asOfDate")
        save_text(WGC_CORR_PATH, json.dumps(data, ensure_ascii=False))
        msg = f"{len(out)} 资产  asOf={asof}"
        log(f"  WGC 相关性矩阵(CNY) {msg}")
        _status(True, f"asOf={asof}", asof)
        L.ok(key, WGC_CORR_PATH, msg)
    except Exception as e:  # noqa: BLE001
        asof = _asof()
        if WGC_CORR_PATH.exists():
            age_d = (time.time() - WGC_CORR_PATH.stat().st_mtime) / 86400
            msg = f"抓取失败，已沿用 {age_d:.1f} 天前的缓存 (asOf={asof})：{e}"
            log(f"  ⚠ WGC 相关性矩阵 {msg}")
            _status(False, msg, asof)
            L.stale(key, WGC_CORR_PATH, str(e))
        else:
            log(f"  ✖ WGC 相关性矩阵抓取失败且无缓存：{e}")
            _status(False, f"抓取失败且无缓存：{e}")
            L.fail(key, str(e))


# --------------------------------------------- WGC 央行季度储备（报告口径）
# ------------------------------------------ WGC GDT 央行季度净购金（头条口径）
# 《Gold Demand Trends》季度报告里的央行一章：含未上报国的估算（Metals Focus），
# 也就是媒体引用的那个「央行买了多少吨」。WGC 的 CBD 仪表盘只有 IMF 主动上报国，
# 而且存量差分会被修订和漏报污染（实测中位仅头条的 55%，且多个季度为负），不能替代。
GDT_BASE = "https://www.gold.org/goldhub/research/gold-demand-trends"
GDT_API = "https://fsapi.gold.org/api/v12"
GDT_CSV = WGC_DIR / "cb_gold_net_q.csv"
GDT_SLUG_RE = re.compile(r"gold-demand-trends-q([1-4])-(20\d\d)")
GDT_CHART_RE = re.compile(r"charts/js/([a-z0-9-]+)/(\d+)")


def _q_end(year: int, quarter: int) -> date:
    """(2026, 3) → 2026-09-30"""
    m = quarter * 3
    return date(year + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def _gdt_quarters(raw: str) -> list[tuple[str, float]]:
    """图表接口 → [(2014-Q1, 118.8), ...]

    返回体是 `_self._opt = {...}` 包裹的 JS，需抠出配平花括号内的配置对象。
    """
    m = re.search(r"_self\._opt\s*=\s*(\{.*)", raw, re.S)
    if not m:
        raise RuntimeError("图表接口里没有 _opt 配置")
    txt = m.group(1)
    depth, end, in_str, esc = 0, None, False, False
    for i, ch in enumerate(txt):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise RuntimeError("图表配置花括号不配平")
    opt = json.loads(txt[:end])
    holder = opt if opt.get("series") else opt.get("chart", {})
    years = (holder.get("xAxis") or {}).get("categories") or []
    by_q = {str(s.get("name")): s.get("data") or [] for s in holder.get("series", [])}
    if not years or not all(f"Q{n}" in by_q for n in (1, 2, 3, 4)):
        raise RuntimeError(f"季度图结构异常：{len(years)} 年 / series={sorted(by_q)}")
    rows: list[tuple[str, float]] = []
    today = date.today()
    for q in (1, 2, 3, 4):
        for y, v in zip(years, by_q[f"Q{q}"]):
            try:
                val = round(float(v), 1)
            except (TypeError, ValueError):
                continue
            # 图表把还没结束的季度占位成 0，不是真数据
            if val == 0 and _q_end(int(y), q) > today:
                continue
            rows.append((f"{int(y)}-Q{q}", val))
    return sorted(rows, key=lambda r: (int(r[0][:4]), int(r[0][-1])))


def _gdt_read(p: Path) -> list[tuple[str, float]]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines()[1:]:
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 2:
            try:
                out.append((parts[0], float(parts[1])))
            except ValueError:
                pass
    return out


def fetch_wgc_gdt(L: Ledger) -> None:
    """全自动：列表页找最新一期 slug → central-banks 子页找图表 id → 取季度矩阵。

    不需要登录、不需要勾条款；`/download/file/*.xlsx` 那个端点是 403，所以绕开 xlsx。
    新一期报告发布前，抓到的 slug 不变，TTL（季 30 天）会跳过重复请求。
    """
    key = "wgc:gdt"
    due, why = L.due(key, GDT_CSV)
    if not due:
        L.skip(key, GDT_CSV, why)
        return
    try:
        html = get(GDT_BASE, timeout=60).text
        found = {(int(y), int(q), f"gold-demand-trends-q{q}-{y}")
                 for q, y in GDT_SLUG_RE.findall(html)}
        if not found:
            raise RuntimeError("报告列表页里没有 GDT slug")
        _y, _q, slug = max(found)
        page = get(f"{GDT_BASE}/{slug}/central-banks", timeout=60).text
        refs = sorted(set(GDT_CHART_RE.findall(page)))
        if not refs:
            raise RuntimeError(f"{slug}/central-banks 里没有图表 id")
        rows = None
        for _slug2, cid in refs:
            raw = get(f"{GDT_API}/charts/js/{_slug2}/{cid}", timeout=60).text
            if all(f'"name":"Q{n}"' in raw for n in (1, 2, 3, 4)):
                rows = _gdt_quarters(raw)
                break
        if not rows:
            raise RuntimeError(f"{slug} 里没找到季度购金图")
        # 站点改版可能返回残缺序列，别把好缓存冲掉
        old = _gdt_read(GDT_CSV)
        if old and (len(rows) < len(old) or rows[-1][0] < old[-1][0]):
            raise RuntimeError(f"新数据退化（{len(rows)} 季 / 末季 {rows[-1][0]}，"
                               f"旧 {len(old)} 季 / 末季 {old[-1][0]}）")
        save_text(GDT_CSV, "quarter,value\n" + "".join(f"{k},{v}\n" for k, v in rows))
        L.ok(key, GDT_CSV, f"{slug}：{len(rows)} 季，末季 {rows[-1][0]} = {rows[-1][1]:g} 吨")
    except Exception as e:  # noqa: BLE001
        old = _gdt_read(GDT_CSV)
        if old:
            L.stale(key, GDT_CSV, f"{e}（沿用 {len(old)} 季旧缓存，末季 {old[-1][0]}）")
        else:
            L.fail(key, f"E {key}: {e}")


# ------------------------------------------------- GPR 地缘政治威胁指数（月度）
# Caldara & Iacoviello 的 Geopolitical Risk 指数，取 Threats 子项（GPRT，类别 1-5）。
# 官网只有 BIFF8 格式的 .xls（2.7 MB），靠 xlrd 读；每月初更新一次。
GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
GPR_CSV = RAW / "gpr_threat_monthly.csv"


def _gpr_read(path: Path) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as fh:
        next(fh, None)
        for ln in fh:
            parts = ln.strip().split(",")
            if len(parts) != 2:
                continue
            try:
                rows.append((parts[0], float(parts[1])))
            except ValueError:
                pass
    return rows


def fetch_gpr(L: Ledger) -> None:
    key = "gpr:threat"
    if not L.due(key, "m"):
        return
    try:
        r = get(GPR_URL, timeout=180)
        df = pd.read_excel(io.BytesIO(r.content), sheet_name=0, engine="xlrd",
                           usecols=["month", "GPRT"])
        df["month"] = pd.to_datetime(df["month"], errors="coerce")
        df = df.dropna().sort_values("month")
        df = df[df["month"] >= pd.Timestamp("1985-01-01")]
        if df.empty:
            raise ValueError("解析后无有效月度数据")
        new = [(d.strftime("%Y-%m"), float(v)) for d, v in zip(df["month"], df["GPRT"])]

        old = _gpr_read(GPR_CSV)
        if old and (len(new) < len(old) or new[-1][0] < old[-1][0]):
            raise ValueError(f"退化保护：新 {len(new)} 月/末 {new[-1][0]}，"
                             f"旧 {len(old)} 月/末 {old[-1][0]}")

        save_text(GPR_CSV, "date,value\n" + "".join(f"{d},{v!r}\n" for d, v in new))
        L.ok(key, GPR_CSV, f"GPRT 月度 {len(new)} 期，末月 {new[-1][0]} = {new[-1][1]:.1f}")
        log(f"  GPR 威胁指数 {len(new)} 月  {new[0][0]} → {new[-1][0]}（{new[-1][1]:.1f}）")
    except Exception as e:  # noqa: BLE001
        old = _gpr_read(GPR_CSV)
        if old:
            L.stale(key, GPR_CSV, f"{e}（沿用 {len(old)} 月旧缓存，末月 {old[-1][0]}）")
        else:
            L.fail(key, f"E {key}: {e}")


def fetch_manual(L: Ledger) -> None:
    """不联网，只登记状态：文件在不在、最新一期到哪。"""
    pairs = [("manual:london_gold", MANUAL / "london_gold_daily.csv")]
    for key, p in pairs:
        if not p.exists():
            L.fail(key, f"手工文件缺失：{p.name}")
            log(f"  MANUAL {p.name} 缺失")
            continue
        last = ""
        try:
            with p.open(encoding="utf-8") as fh:
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
            if len(lines) > 1:
                last = lines[-1].split(",", 1)[0]
        except Exception:  # noqa: BLE001
            pass
        if key == "manual:london_gold":
            note = f"历史基底，最新一期 {last}；此后的数据由 Yahoo GC=F 自动接续"
        else:
            note = f"手工维护，最新一期 {last}" if last else "手工维护"
        L.manual(key, p, note)
        log(f"  MANUAL {p.name} 手工维护  最新 {last or '—'}")


# ------------------------------------------------------------------- 总入口
def fetch_all(force: bool = False) -> list[str]:
    log("== 抓取数据 ==")
    L = Ledger(force=force)
    for fn in (fetch_fred, fetch_yahoo, fetch_cot, fetch_treasury, fetch_imf_cofer,
               fetch_crypto, fetch_sge,
               fetch_wgc_returns, fetch_wgc_correlations, fetch_wgc_gdt,
               fetch_gpr, fetch_manual):
        fn(L)
    payload = L.save()

    counts = payload["run"]["counts"]
    log(f"  台账：成功 {counts['ok']} / 跳过 {counts['skip']} / 降级 {counts['stale']}"
        f" / 失败 {counts['fail']} / 手工 {counts['manual']} → data/fetch_manifest.json")

    warnings = []
    for key, item in payload["items"].items():
        if item["status"] in ("stale", "fail"):
            warnings.append(f"[{item['status']}] {item['label']}：{item['message']}")
    return warnings


if __name__ == "__main__":
    import sys

    fetch_all(force="--force" in sys.argv)
