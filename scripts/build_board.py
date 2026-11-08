"""构建：把 payload + 样式 + 脚本 + ECharts 内联成单文件 docs/index.html。

这样双击就能看（file:// 也能用），丢掉服务也能带走，方便归档和发人。
"""
from __future__ import annotations

import json
from pathlib import Path

from util import DATA, DOCS, ROOT, json_read, log

WEB = ROOT / "web"


def build() -> Path:
    payload = json_read(DATA / "board.json")
    template = (WEB / "template.html").read_text(encoding="utf-8")
    css = (WEB / "board.css").read_text(encoding="utf-8")
    js = (WEB / "board.js").read_text(encoding="utf-8")
    echarts = (WEB / "vendor" / "echarts.min.js").read_text(encoding="utf-8")

    payload_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    sources = "\n".join(f"<li>{s}</li>" for s in payload.get("sources", []))

    html = (template
            .replace("{{CSS}}", css)
            .replace("{{ECHARTS}}", echarts)
            .replace("{{PAYLOAD}}", payload_js)
            .replace("{{JS}}", js)
            .replace("{{SOURCES}}", sources)
            .replace("{{GENERATED}}", payload.get("generated_at_local", "")))

    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "index.html"
    out.write_text(html, encoding="utf-8")

    # 根目录跳转壳：双击根目录 index.html 也能进 docs/（与既有仓库惯例一致）
    (ROOT / "index.html").write_text(
        """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>黄金研究看板</title>
<meta http-equiv="refresh" content="0; url=docs/index.html">
<style>body{background:#1f1a12;color:#d4a853;font:15px/1.7 Inter,"PingFang SC",sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
a{color:#f0dfb4}</style></head>
<body><div><p>正在打开黄金研究看板…</p>
<p><a href="docs/index.html">如果没有自动跳转，点这里</a></p></div>
<script>location.replace("docs/index.html");</script></body></html>
""", encoding="utf-8")
    log(f"  → docs/index.html（{round(out.stat().st_size / 1024)} KB）")
    return out


if __name__ == "__main__":
    build()
