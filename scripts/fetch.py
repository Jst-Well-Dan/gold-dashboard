"""抓数：每个数据源一个函数，落盘到 data/raw/ 下。

设计原则
- 一律先落 CSV（可追溯、可重算），build 阶段不再联网。
- 有缓存：默认 8 小时内不重复抓，`--force` 强制刷新。
- FRED 必须串行 + 退避（突发会限流）。
"""
from __future__ import annotations

import io
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config import CB_GOLD_NET_SEED, EXTRA_FRED, SERIES
from util import (MANUAL, RAW, curl_text, get, log, parse_fred_csv, save_text,
                  write_series_csv)

MAX_AGE_H = 8.0

FRED_IDS = sorted({s["src"][1] for s in SERIES if s.get("src") and s["src"][0] == "fred"} | set(EXTRA_FRED))
YAHOO_SYMS = sorted({s["src"][1] for s in SERIES if s.get("src") and s["src"][0] == "yahoo"})


# --------------------------------------------------------------------- FRED
def fetch_fred(force: bool = False) -> None:
    out = RAW / "fred"
    out.mkdir(parents=True, exist_ok=True)
    for i, sid in enumerate(FRED_IDS, 1):
        p = out / f"{sid}.csv"
        if not force and p.exists() and time.time() - p.stat().st_mtime < MAX_AGE_H * 3600:
            log(f"  FRED {sid:18s} 缓存命中")
            continue
        try:
            txt = curl_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                            timeout=60, retries=4, sleep=2.5)
            df = parse_fred_csv(txt)
            save_text(p, df.to_csv(index=False))
            log(f"  FRED {sid:18s} {len(df):6d} 行  最新 {df['date'].iloc[-1]} = {df['value'].iloc[-1]}")
        except Exception as e:  # noqa: BLE001
            if p.exists():
                log(f"  FRED {sid:18s} 抓取失败，沿用旧缓存（{e}）")
            else:
                log(f"  FRED {sid:18s} 抓取失败且无缓存：{e}")
        time.sleep(0.8)  # 串行节流，防限流


# -------------------------------------------------------------------- Yahoo
def fetch_yahoo(force: bool = False) -> None:
    from urllib.parse import quote

    out = RAW / "yahoo"
    out.mkdir(parents=True, exist_ok=True)
    for sym in YAHOO_SYMS:
        p = out / f"{sym.replace('^', 'IDX_').replace('=', '_')}.csv"
        if not force and p.exists() and time.time() - p.stat().st_mtime < MAX_AGE_H * 3600:
            log(f"  YAHOO {sym:10s} 缓存命中")
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
            log(f"  YAHOO {sym:10s} {len(df):6d} 行  {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}"
                f" 最新 {df['close'].iloc[-1]:.2f}")
        except Exception as e:  # noqa: BLE001
            log(f"  YAHOO {sym:10s} 失败：{e}")
        time.sleep(0.6)


# ---------------------------------------------------------------------- COT
def fetch_cot(force: bool = False) -> None:
    p = RAW / "cot" / "GOLD_COT.csv"
    if not force and p.exists() and time.time() - p.stat().st_mtime < 24 * 3600:
        log("  CFTC GOLD_COT 缓存命中")
        return
    url = ("https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
           "?$where=cftc_contract_market_code='088691'"
           "&$order=report_date_as_yyyy_mm_dd%20ASC&$limit=5000")
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
    log(f"  CFTC GOLD_COT {len(df)} 行  最新 {df['date'].iloc[-1].date()} MM净多 {df['mm_net'].iloc[-1]:,.0f}")


# ----------------------------------------------------------------- Treasury
def fetch_treasury(force: bool = False) -> None:
    p = RAW / "treasury" / "debt_to_penny.csv"
    if not force and p.exists() and time.time() - p.stat().st_mtime < MAX_AGE_H * 3600:
        log("  TREASURY debt_to_penny 缓存命中")
        return
    url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny"
           "?filter=record_date:gte:1993-04-01&sort=record_date&page[size]=10000")
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
    log(f"  TREASURY 债务 {len(df)} 行  最新 {df['date'].iloc[-1].date()} = {df['value'].iloc[-1] / 1e12:.2f} 万亿")


# ---------------------------------------------------------------------- IMF
def fetch_imf_cofer(force: bool = False) -> None:
    p = RAW / "imf" / "cofer_usd_share.csv"
    if not force and p.exists() and time.time() - p.stat().st_mtime < 7 * 24 * 3600:
        log("  IMF COFER 缓存命中（周更足够）")
        return
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
            log(f"  IMF COFER 美元占比 {len(s)} 期  最新 {s.index[-1]:%Y-%m} = {s.iloc[-1]:.2f}%")
            return
        except Exception as e:  # noqa: BLE001
            log(f"  IMF COFER {freq} 失败：{e}")
    if p.exists():
        log("  IMF COFER 沿用旧缓存")
    else:
        raise RuntimeError("IMF COFER 无数据可用")


# -------------------------------------------------------------------- crypto
def fetch_crypto(force: bool = False) -> None:
    p = RAW / "crypto" / "btc_mcap.csv"
    if not force and p.exists() and time.time() - p.stat().st_mtime < MAX_AGE_H * 3600:
        log("  BLOCKCHAIN 市值 缓存命中")
        return
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
    log(f"  BLOCKCHAIN 市值 {len(df)} 行  最新 {df['date'].iloc[-1].date()} = {df['value'].iloc[-1] / 1e9:.0f}B")


# ----------------------------------------------------------------- 上海金
def fetch_sge(force: bool = False) -> None:
    p = RAW / "cn" / "sge_au9999.csv"
    if not force and p.exists() and time.time() - p.stat().st_mtime < MAX_AGE_H * 3600:
        log("  SGE Au99.99 缓存命中")
        return
    try:
        import akshare as ak
        df = ak.spot_hist_sge(symbol="Au99.99")
        df = df[["date", "close"]].rename(columns={"close": "value"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").sort_values("date")
        p.parent.mkdir(parents=True, exist_ok=True)
        save_text(p, df.to_csv(index=False))
        log(f"  SGE Au99.99 {len(df)} 行  最新 {df['date'].iloc[-1].date()} = {df['value'].iloc[-1]:.2f} 元/克")
    except Exception as e:  # noqa: BLE001
        log(f"  SGE Au99.99 失败（溢价图将留空）：{e}")


# ------------------------------------------------------- 长期金价（1833+）
def fetch_long_gold(force: bool = False) -> None:
    p = RAW / "long_gold_monthly.csv"
    if not force and p.exists() and time.time() - p.stat().st_mtime < 24 * 3600:
        log("  LONG GOLD 缓存命中")
        return
    try:
        r = get("https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv",
                timeout=60, retries=3, sleep=2)
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "value"]
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").sort_values("date")
        save_text(p, df.to_csv(index=False))
        log(f"  LONG GOLD {len(df)} 月  {df['date'].iloc[0]:%Y-%m} → {df['date'].iloc[-1]:%Y-%m}")
    except Exception as e:  # noqa: BLE001
        log(f"  LONG GOLD 失败：{e}")


# ------------------------------------------------------------- 手工维护序列
def ensure_manual() -> None:
    MANUAL.mkdir(parents=True, exist_ok=True)
    p = MANUAL / "cb_gold_net.csv"
    if not p.exists():
        df = pd.DataFrame(CB_GOLD_NET_SEED, columns=["date", "value"])
        df["date"] = df["date"].astype(str) + "-12-31"
        p.write_text(df.to_csv(index=False), encoding="utf-8")
        log(f"  手工序列 cb_gold_net.csv 已初始化（{len(df)} 年，来自 WGC 年度公报，可 yearly 手工更新）")


def fetch_all(force: bool = False) -> None:
    log("== 抓取数据 ==")
    ensure_manual()
    fetch_fred(force)
    fetch_yahoo(force)
    fetch_cot(force)
    fetch_treasury(force)
    fetch_imf_cofer(force)
    fetch_crypto(force)
    fetch_sge(force)
    fetch_long_gold(force)


if __name__ == "__main__":
    import sys
    fetch_all(force="--force" in sys.argv)
