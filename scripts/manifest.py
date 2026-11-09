"""抓取台账：谁、什么时候抓的、成功没有、TTL 到没到。

为什么需要这张台账
------------------
1. **mtime 在 CI 里不可信。** GitHub Actions 每次都是全新 checkout，配
   `actions/cache` 恢复出来的文件，mtime 会被刷成「恢复那一刻」。所以拿
   `time.time() - stat().st_mtime` 判断缓存，在 CI 里必然误判：要么全部当成
   新鲜永远不抓，要么全部当成过期每天全量重抓。新鲜度只能看这里记的时间戳。
2. **季/年度数据不必每天重抓。** 债务/GDP、赤字/GDP 这类一年只变 1~4 次，
   跟 VIX 用同一个 TTL 是浪费。所以 TTL 按指标频率分档（见 FREQ_TTL_DAYS）。
3. **要能看出「最近一次运行状况」。** `data/fetch_manifest.json` 随仓库提交，
   是跨运行唯一可信的状态（cache 可能被清，台账不会被清），docs/status.html
   直接读它渲染表格。

文件位置：data/fetch_manifest.json（**要提交进仓库**，不在 .gitignore 里）
"""
from __future__ import annotations

import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from config import SERIES
from util import DATA, ROOT, json_write, now_utc

MANIFEST = DATA / "fetch_manifest.json"

# 按发布节奏分档：过了 TTL 才重抓。
# d=8 小时（Actions 每天跑一次，间隔 24h > 8h，日频必然重抓）
FREQ_TTL_DAYS = {"d": 0.33, "w": 2.0, "m": 12.0, "q": 30.0, "a": 300.0}
FREQ_LABEL = {"d": "日频", "w": "周频", "m": "月频", "q": "季频", "a": "年频"}
FREQ_ORDER = ["d", "w", "m", "q", "a"]

GROUP_LABEL = {
    "fred": "FRED（圣路易斯联储）",
    "yahoo": "Yahoo Finance",
    "cot": "CFTC 持仓报告",
    "treasury": "美国财政部",
    "imf": "IMF COFER",
    "crypto": "Blockchain.com",
    "sge": "上海黄金交易所",
    "wgc": "世界黄金协会 WGC",
    "gpr": "地缘政治风险（学术指数）",
    "manual": "手工维护（不联网）",
}

STATUS_LABEL = {
    "ok": "成功",
    "skip": "跳过",
    "stale": "降级",
    "fail": "失败",
    "manual": "手工",
}

# 不在 SERIES 里、但确实要抓/要展示的接口。
# ttl 可覆盖 FREQ_TTL_DAYS（WGC 官网按周更新，给 7 天更贴合）。
EXTRA_SOURCES: dict[str, dict] = {
    "fred:CPIAUCNS": dict(label="CPI 物价指数（未季调，同比原料）", freq="m"),
    "treasury:debt_to_penny": dict(label="美国国债总规模（debt to the penny）", freq="d"),
    "imf:cofer": dict(label="美元在全球外储中的占比", freq="q"),
    "cot:GOLD_COT": dict(label="CFTC 黄金期货持仓（分类报告）", freq="w"),
    "crypto:btc_mcap": dict(label="比特币市值", freq="w"),
    "sge:au9999": dict(label="上海金 Au99.99", freq="d"),
    "manual:london_gold": dict(label="伦敦现货金日频（历史基底，1968 起）", freq="d"),
    "wgc:returns": dict(label="WGC 黄金回报（CNY 口径）", freq="w", ttl=7.0),
    "wgc:correlations": dict(label="WGC 相关性矩阵（CNY 口径）", freq="w", ttl=7.0),
    "gpr:threat": dict(label="GPR 地缘政治威胁指数（Caldara-Iacoviello，月度）", freq="m"),
    "wgc:gdt": dict(label="央行季度净购金（GDT 头条口径）", freq="q"),
}


def registry() -> dict[str, dict]:
    """接口登记表：key `源:标识` → {group, label, freq, ttl_days}。

    主体从 config.SERIES 自动推导，不另维护一份，避免两边漂移。
    """
    reg: dict[str, dict] = {}
    for spec in SERIES:
        src = spec.get("src")
        if not src:
            continue
        key = f"{src[0]}:{src[1]}"
        reg.setdefault(key, dict(group=src[0], label=spec["name"], freq=spec["freq"]))
    for key, spec in EXTRA_SOURCES.items():
        group = key.split(":", 1)[0]
        reg.setdefault(key, dict(group=group, **spec))
    for key, item in reg.items():
        item.setdefault("ttl_days", FREQ_TTL_DAYS.get(item["freq"], 1.0))
    return reg


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _rel(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


class Ledger:
    """一次运行内累积的抓取记录；save() 时落盘。"""

    def __init__(self, force: bool = False) -> None:
        self.force = force
        self.registry = registry()
        self.run_at = now_utc()
        self.trigger = os.environ.get("GITHUB_EVENT_NAME") or "local"
        self.in_ci = bool(os.environ.get("CI"))
        self.items: dict[str, dict] = {}

        old = {}
        if MANIFEST.exists():
            try:
                import json

                old = json.loads(MANIFEST.read_text(encoding="utf-8")).get("items", {})
            except Exception:  # noqa: BLE001
                old = {}
        self.previous = old

    # ------------------------------------------------------------- TTL 判断
    def due(self, key: str, path: Path | None) -> tuple[bool, str]:
        """该不该抓这个接口。返回 (是否抓, 理由)。"""
        spec = self.registry.get(key) or {}
        ttl = float(spec.get("ttl_days") or 1.0)
        freq = spec.get("freq", "d")

        if self.force:
            return True, "强制刷新"
        if path is None or not Path(path).exists():
            return True, "本地无文件"

        rec = self.previous.get(key) or {}
        ts = _parse(rec.get("last_attempt", ""))
        if ts is None:
            # 没有台账：本地用 mtime 兜底；CI 里 mtime 已被 checkout/cache 刷成现在，
            # 不可信，一律重抓（代价只是一次请求）。
            if self.in_ci:
                return True, "无台账记录（CI 环境）"
            age_d = (time.time() - Path(path).stat().st_mtime) / 86400
            if age_d < ttl:
                return False, f"TTL 内（文件 {age_d:.1f} 天前，无台账）"
            return True, "无台账记录"

        age_d = (now_utc() - ts).total_seconds() / 86400
        if age_d >= ttl:
            return True, f"距上次 {age_d:.1f} 天 ≥ {FREQ_LABEL.get(freq, freq)} TTL {ttl:g} 天"
        return False, f"距上次 {age_d:.1f} 天，TTL {ttl:g} 天内不重抓"

    # --------------------------------------------------------------- 记账
    def _base(self, key: str) -> dict:
        spec = self.registry.get(key) or {}
        return dict(
            group=spec.get("group", key.split(":", 1)[0]),
            label=spec.get("label", key),
            freq=spec.get("freq", "d"),
            ttl_days=spec.get("ttl_days"),
        )

    def _put(self, key: str, status: str, path: Path | None, message: str,
             ok: bool, attempted: bool = True) -> None:
        now = _iso(self.run_at)
        prev = self.previous.get(key) or {}
        item = self.items.get(key) or self._base(key)
        item.update(
            status=status,
            last_check=now,
            path=_rel(path),
            message=message,
        )
        # last_attempt 只在真的发了请求时推进。跳过和手工维护都不推进 ——
        # 否则每次 skip 都把时间戳刷新，TTL 永远到不了，就再也不会抓了。
        item["last_attempt"] = now if attempted else prev.get("last_attempt")
        # 只有拿到数据才推进 last_success（跳过不算新的成功，也不算失败）
        item["last_success"] = now if ok else prev.get("last_success")
        self.items[key] = item

    def ok(self, key: str, path: Path, message: str = "") -> None:
        self._put(key, "ok", path, message, ok=True)

    def skip(self, key: str, path: Path, reason: str) -> None:
        self._put(key, "skip", path, reason, ok=False, attempted=False)

    def stale(self, key: str, path: Path, error: str) -> None:
        self._put(key, "stale", path, f"抓取失败，沿用旧数据：{error}", ok=False)

    def fail(self, key: str, error: str) -> None:
        self._put(key, "fail", None, f"抓取失败且无旧数据：{error}", ok=False)

    def manual(self, key: str, path: Path | None, message: str = "手工维护，不由本管线抓取") -> None:
        self._put(key, "manual", path, message, ok=False, attempted=False)

    def missed(self, key: str) -> None:
        """登记表里有、但这次没被任何函数碰到（漏接线时能一眼看出）。"""
        if key not in self.items:
            self._put(key, "fail", None, "本次运行没有触发该接口的抓取", ok=False)

    # --------------------------------------------------------------- 落盘
    def counts(self) -> dict[str, int]:
        c = Counter(it["status"] for it in self.items.values())
        return {k: c.get(k, 0) for k in ("ok", "skip", "stale", "fail", "manual")}

    def save(self) -> dict:
        # 登记表里有、这次却没被任何函数碰到 → 说明漏接线了，记成失败让它显形
        for key in self.registry:
            if key not in self.items:
                self.missed(key)
        # 已经下线的接口（登记表里没有）不留残影
        for key in list(self.items):
            if key not in self.registry:
                del self.items[key]

        payload = dict(
            schema=1,
            updated_at=_iso(self.run_at),
            run=dict(
                at=_iso(self.run_at),
                force=self.force,
                trigger=self.trigger,
                counts=self.counts(),
            ),
            items=dict(sorted(self.items.items())),
        )
        json_write(MANIFEST, payload)
        return payload
