"""每月跑一次：拉取 Caldara-Iacoviello GPR 月度数据，提取威胁指数存为轻量 CSV。

数据页：https://www.matteoiacoviello.com/gpr.htm
直链：https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls
列说明：GPR=近期总指数（1985-2019=100），GPRT=威胁子项，GPRA=行动子项，
         GPRH/GPRHT/GPRHA=历史版（1900 起）。
看板只用 GPRT（威胁）：市场对威胁的反应通常大于已发生的行为。

用法：python scripts/fetch_gpr.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

from util import RAW, log  # noqa: E402

URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
OUT = RAW / "gpr_threat_monthly.csv"


def main() -> None:
    import tempfile
    import urllib.request

    log(f"下载 {URL}")
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as t:
        tmp = t.name
    urllib.request.urlretrieve(URL, tmp)
    d = pd.read_excel(tmp, sheet_name=0, usecols=["month", "GPRT"])
    Path(tmp).unlink(missing_ok=True)
    d = d.dropna(subset=["GPRT"]).copy()
    d["month"] = pd.to_datetime(d["month"]).dt.strftime("%Y-%m")
    d.columns = ["date", "value"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT, index=False)
    log(f"写入 {OUT}：{d['date'].iloc[0]} → {d['date'].iloc[-1]}，共 {len(d)} 个月，"
        f"最新 {float(d['value'].iloc[-1]):.1f}")


if __name__ == "__main__":
    main()
