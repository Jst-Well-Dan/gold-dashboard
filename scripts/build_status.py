"""生成 docs/status.html：每个数据接口最近一次运行时间 + 状态 + 抓到的数据。

信息来自两处，各管一半：
- data/fetch_manifest.json → 运行台账（谁、何时、成功没、为什么跳过）
- data/raw/** 里的真实文件   → 数据本身（最新日期、数值、行数）在渲染时现读，
                               保证表格里的「数据」永远等于磁盘上的内容，不会漂移
"""
from __future__ import annotations

import html
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import SERIES, UNIT_LABELS
from manifest import (FREQ_LABEL, FREQ_TTL_DAYS, GROUP_LABEL, MANIFEST, STATUS_LABEL)
from util import DOCS, ROOT, json_read, log, now_utc

WEB = ROOT / "web"
TZ = timezone(timedelta(hours=8))  # 页面统一北京时间

GROUP_ORDER = ["fred", "yahoo", "cot", "treasury", "imf", "crypto",
               "sge", "wgc", "gpr", "manual"]

# 数据日期距今超过这个天数 → 该行的日期标黄（暴露「抓成功了但上游本身滞后」）
# 季度数据正常滞后约一个季度（~120 天），超过 150 天就不正常了 ——
# 例如 FRED 的债务/GDP 常年落后 7 个月，这里会如实标出来。
LATE_DAYS = {"d": 12, "w": 30, "m": 120, "q": 150, "a": 550}

# 大额数值的显示缩放
SCALE = {"treasury:debt_to_penny": 1e-12, "crypto:btc_mcap": 1e-9}

EXTRA_UNITS = {
    "fred:CPIAUCNS": "指数",
    "treasury:debt_to_penny": "万亿美元",
    "imf:cofer": "%",
    "cot:GOLD_COT": "手",
    "crypto:btc_mcap": "十亿美元",
    "sge:au9999": "元/克",
    "manual:london_gold": "美元/盎司",
    "gpr:threat": "指数",
    "wgc:gdt": "吨",
}

_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")


# ------------------------------------------------------------------ 接口清单
def interface_order() -> dict[str, dict]:
    """key → 元信息。顺序沿用 registry（SERIES 业务顺序 + EXTRA 定义顺序）。"""
    from manifest import registry

    units: dict[str, str] = {}
    for spec in SERIES:
        src = spec.get("src")
        if src:
            units.setdefault(f"{src[0]}:{src[1]}", UNIT_LABELS.get(spec["unit"], ""))
    units.update(EXTRA_UNITS)
    out = {}
    for key, spec in registry().items():
        out[key] = dict(spec, unit=units.get(key, ""))
    return out


# ------------------------------------------------------------------ 读文件
def _probe_csv(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except OSError:
        return {}
    if len(lines) < 2:
        return {}
    header = [h.strip() for h in lines[0].split(",")]
    cells = lines[-1].split(",")

    def pick(*names: str) -> int:
        for n in names:
            if n in header:
                return header.index(n)
        return -1

    d_i = pick("date", "quarter")
    v_i = pick("mm_net", "value", "close")
    if d_i < 0:
        d_i = 0
    if v_i < 0:
        v_i = 1
    raw = cells[v_i].strip() if v_i < len(cells) else ""
    try:
        value = float(raw)
    except ValueError:
        value = None
    return dict(
        rows=len(lines) - 1,
        last_date=cells[d_i].strip() if d_i < len(cells) else "",
        value=value,
        size_kb=path.stat().st_size // 1024,
    )


def _probe_json(path: Path) -> dict:
    try:
        d = json_read(path)
    except Exception:  # noqa: BLE001
        return {}
    cd = d.get("chartData", {}) if isinstance(d, dict) else {}
    last = cd.get("asOfDate") or (cd.get("options") or {}).get("maxDateAvailable") or ""
    rows = len(((cd.get("tableData") or {}).get("rows") or []))
    return dict(rows=rows, last_date=str(last), value=None,
                size_kb=path.stat().st_size // 1024)


def probe(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return _probe_json(path) if path.suffix.lower() == ".json" else _probe_csv(path)


# ------------------------------------------------------------------ 格式化
def parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    m = _QUARTER.match(s)
    if m:
        return datetime(int(m[1]), (int(m[2]) - 1) * 3 + 1, 1, tzinfo=TZ)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def rel(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return ""
    secs = (now - dt).total_seconds()
    if secs < 0:
        return "刚刚"
    if secs < 3600:
        return f"{int(secs // 60)} 分钟前"
    if secs < 86400:
        return f"{int(secs // 3600)} 小时前"
    days = int(secs // 86400)
    if days < 60:
        return f"{days} 天前"
    return f"{days // 30} 个月前"


def fmt_value(value: float | None, unit: str, key: str) -> str:
    if value is None:
        return '<span class="dash">—</span>'
    x = value * SCALE.get(key, 1.0)
    a = abs(x)
    if a >= 1000:
        txt = f"{x:,.0f}"
    elif a >= 100:
        txt = f"{x:,.1f}"
    elif a >= 1:
        txt = f"{x:.2f}"
    else:
        txt = f"{x:.3f}"
    if unit:
        txt += f'<span style="color:var(--muted);font-weight:400"> {html.escape(unit)}</span>'
    return txt


def esc(s: str, limit: int = 200) -> str:
    s = (s or "").strip()
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return html.escape(s)


# ------------------------------------------------------------------ 渲染
def _row(key: str, item: dict, meta: dict, now: datetime) -> str:
    status = item.get("status", "fail")
    freq = item.get("freq") or meta.get("freq", "d")
    path = ROOT / item["path"] if item.get("path") else None
    info = probe(path)

    attempted = parse_iso(item.get("last_attempt"))
    note = ""
    if status == "manual":
        when = '<span class="dash">手工维护</span>'
    else:
        if attempted is None and path is not None and path.exists() and not os.environ.get("CI"):
            # 过渡期（本地已有文件但还没通过台账抓过）：用文件时间兜底，并标注清楚。
            # CI 里这一步跳过 —— 那里的 mtime 是 checkout / cache 恢复时间，没有意义。
            attempted = datetime.fromtimestamp(path.stat().st_mtime, TZ)
            note = "文件时间"
        when = (f'<span class="when">{attempted.astimezone(TZ):%m-%d %H:%M}'
                f'<span class="rel">{note or rel(attempted, now)}</span></span>') if attempted else '<span class="dash">—</span>'

    last_date = info.get("last_date", "")
    dt = parse_date(last_date)
    late = ""
    # 手工维护的数据不承诺新鲜度（如 Wind 固化的历史基底），不按自动源的滞后阈值标黄
    if dt is not None and (now - dt).days > LATE_DAYS.get(freq, 400) and status not in ("fail", "manual"):
        late = " late"
    date_cell = (f'<span class="date{late}">{esc(last_date, 24)}'
                 f'<span class="rel">{rel(dt, now)}</span></span>') if last_date else '<span class="dash">—</span>'

    rows = info.get("rows")
    if rows:
        rows_cell = f"{rows:,}"
    elif info.get("size_kb"):
        # JSON 类接口没有「行」的概念，给个体积更有用
        rows_cell = f'{info["size_kb"]:,} KB'
    else:
        rows_cell = '<span class="dash">—</span>'
    value_cell = fmt_value(info.get("value"), meta.get("unit", ""), key)

    msg_cls = "bad" if status == "fail" else ("warn" if status == "stale" else "")
    message = item.get("message") or ""
    if status == "skip":
        message = message or "未到 TTL，跳过"

    return f"""      <tr>
        <td><span class="badge s-{status}"><i></i>{STATUS_LABEL.get(status, status)}</span></td>
        <td class="label">{esc(item.get("label") or meta.get("label", key), 60)}<span class="k">{html.escape(key)}</span></td>
        <td><span class="freq">{FREQ_LABEL.get(freq, freq)}</span></td>
        <td>{when}</td>
        <td>{date_cell}</td>
        <td class="num">{value_cell}</td>
        <td class="num hide-sm">{rows_cell}</td>
        <td class="msg {msg_cls}">{esc(message, 180)}</td>
      </tr>"""


def _group_block(group: str, rows: list[str]) -> str:
    title = GROUP_LABEL.get(group, group)
    return f"""  <section class="group">
    <h2>{html.escape(title)}<span class="n">{len(rows)} 个接口</span></h2>
    <table>
      <thead>
        <tr>
          <th style="width:78px">状态</th>
          <th>接口</th>
          <th style="width:56px">频率</th>
          <th style="width:104px">最近抓取</th>
          <th style="width:98px">数据截至</th>
          <th class="num" style="width:104px">最新值</th>
          <th class="num hide-sm" style="width:66px">行数/体积</th>
          <th style="width:26%">备注</th>
        </tr>
      </thead>
      <tbody>
{chr(10).join(rows)}
      </tbody>
    </table>
  </section>"""


def build() -> Path:
    now = now_utc()
    template = (WEB / "status_template.html").read_text(encoding="utf-8")

    payload = None
    if MANIFEST.exists():
        try:
            payload = json_read(MANIFEST)
        except Exception:  # noqa: BLE001
            payload = None

    meta = interface_order()

    if not payload:
        subtitle = "还没有台账。先跑一次 <b>python scripts/run_daily.py</b>，这里就会出现每个接口的状态。"
        stats = ""
        alert = '<div class="alert">没有找到 data/fetch_manifest.json，说明还没跑过抓取。</div>'
        groups = ""
    else:
        run = payload.get("run", {})
        counts = run.get("counts", {})
        at = parse_iso(run.get("at") or payload.get("updated_at"))
        trigger = {"schedule": "定时任务", "workflow_dispatch": "手动触发（Actions）",
                   "push": "代码推送触发", "local": "本地运行"}.get(run.get("trigger"), run.get("trigger") or "本地运行")
        badge = f"<b>{at.astimezone(TZ):%Y-%m-%d %H:%M}</b>" if at else "<b>—</b>"
        subtitle = (f"最近一次运行 {badge}（北京时间）· 触发方式 {html.escape(trigger)}"
                    + (" · 强制全量刷新" if run.get("force") else ""))

        stats = "".join(
            f'<div class="stat {k}"><b>{counts.get(k, 0)}</b><span>{STATUS_LABEL[k]}</span></div>'
            for k in ("ok", "skip", "stale", "fail", "manual"))

        n_bad = counts.get("stale", 0) + counts.get("fail", 0)
        if n_bad:
            alert = (f'<div class="alert">本次有 <b>{counts.get("stale", 0)}</b> 个接口降级'
                     f'（抓取失败但沿用旧数据）、<b>{counts.get("fail", 0)}</b> 个失败。'
                     f'下方标黄/标红的行即受影响接口，看板仍可正常打开，但对应指标可能不是最新。</div>')
        else:
            alert = ('<div class="alert ok">本次运行全部正常：没有失败或降级的接口。'
                     f'跳过的 {counts.get("skip", 0)} 个是还没到各自的 TTL，属预期行为。</div>')

        items = payload.get("items", {})
        buckets: dict[str, list[tuple[int, str]]] = {}
        for i, key in enumerate(meta):
            item = items.get(key)
            if not item:
                continue
            buckets.setdefault(item.get("group", key.split(":", 1)[0]), []) \
                   .append((i, _row(key, item, meta[key], now)))

        blocks = []
        for group in GROUP_ORDER:
            if group in buckets:
                rows = [r for _, r in sorted(buckets.pop(group))]
                blocks.append(_group_block(group, rows))
        for group, rows in sorted(buckets.items()):   # 未登记的新组也不丢
            blocks.append(_group_block(group, [r for _, r in sorted(rows)]))
        groups = "\n".join(blocks)

    html_out = (template
                .replace("{{SUBTITLE}}", subtitle)
                .replace("{{STATS}}", stats)
                .replace("{{ALERT}}", alert)
                .replace("{{GROUPS}}", groups)
                .replace("{{GENERATED}}", now.astimezone(TZ).strftime("%Y-%m-%d %H:%M")))

    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "status.html"
    out.write_text(html_out, encoding="utf-8")
    log(f"  → docs/status.html（{round(out.stat().st_size / 1024)} KB）")
    return out


if __name__ == "__main__":
    build()
