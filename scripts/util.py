"""通用工具：HTTP（绕过本机代理）、CSV 读写、日期处理、日志。

本机 Windows 注册表里配了 Clash 代理（127.0.0.1:7897），requests 默认会走它，
并发抓 FRED 时经常 ProxyError / ReadTimeout。所以默认 trust_env=False 直连；
需要走代理时设环境变量 GOLD_USE_PROXY=1。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
MANUAL = DATA / "manual"
DOCS = ROOT / "docs"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.trust_env = os.environ.get("GOLD_USE_PROXY") == "1"
        s.headers.update({"User-Agent": UA})
        _session = s
    return _session


def log(msg: str) -> None:
    print(msg, flush=True)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get(url: str, *, timeout: int = 40, retries: int = 4, sleep: float = 2.0,
        headers: dict | None = None) -> requests.Response:
    """带退避的 GET。FRED 对突发请求会限流，必须串行 + 退避。"""
    last = None
    for i in range(retries):
        try:
            r = session().get(url, timeout=timeout, headers=headers)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (400, 404):
                raise RuntimeError(f"{url} -> {r.status_code}")
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(sleep * (i + 1))
    raise RuntimeError(f"请求失败 {url} （{last}）")


CURL = os.environ.get("GOLD_CURL", "curl")


def curl_text(url: str, *, timeout: int = 40, retries: int = 4,
              sleep: float = 2.0, ua: str | None = None) -> str:
    """用系统 curl 取文本。

    FRED 的 Cloudflare 会挑 python-requests 的连接（ReadTimeout / RemoteDisconnected），
    而且**带了浏览器 UA 反而被拒**（Chrome UA + 非浏览器 TLS 指纹 = 判机器人）。
    所以这里默认不发 UA，只用 curl 自己的标识。
    """
    last = ""
    for i in range(retries):
        cmd = [CURL, "-sS", "--compressed", "--max-time", str(timeout)]
        if ua:
            cmd += ["-A", ua]
        p = subprocess.run(cmd + [url], capture_output=True)
        if p.returncode == 0 and p.stdout:
            return p.stdout.decode("utf-8", "replace")
        last = (p.stderr or b"").decode("utf-8", "replace").strip()[:200] or f"exit {p.returncode}"
        time.sleep(sleep * (i + 1))
    raise RuntimeError(f"curl 失败 {url} （{last}）")


def cached_file(rel: str) -> Path:
    p = RAW / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < max_age_hours * 3600


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path, **kw) -> pd.DataFrame:
    return pd.read_csv(path, **kw)


# ---------------------------------------------------------------- series io

def to_series(df: pd.DataFrame, date_col: str, value_col: str) -> pd.Series:
    s = pd.Series(
        pd.to_numeric(df[value_col], errors="coerce").values,
        index=pd.to_datetime(df[date_col], errors="coerce"),
        name=value_col,
    )
    s = s[s.index.notna()].dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def write_series_csv(path: Path, s: pd.Series, col: str = "value",
                     fmt: str = "%Y-%m-%d") -> None:
    df = pd.DataFrame({col: s.values}, index=s.index)
    df.index.name = "date"
    df.index = df.index.strftime(fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, float_format="%.6g")


def load_series_csv(path: Path, col: str = "value") -> pd.Series:
    df = pd.read_csv(path)
    return to_series(df, "date", col)


class FetchError(RuntimeError):
    pass


def json_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


def json_read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def today_str() -> str:
    return date.today().isoformat()


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def parse_fred_csv(text: str) -> pd.DataFrame:
    """FRED fredgraph.csv：表头 observation_date,SERIES；缺失值为 '.'。"""
    df = pd.read_csv(io.StringIO(text))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"].replace(".", ""), errors="coerce")
    return df.dropna(subset=["value"])


def fred_url(series_id: str, start: str | None = None) -> str:
    base = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    return f"{base}&cosd={start}" if start else base
