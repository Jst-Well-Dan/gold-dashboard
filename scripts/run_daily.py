"""一键跑：抓数 → 计算 → 出单文件看板。

用法：
    python scripts/run_daily.py              # 抓数（8 小时内有缓存就跳过）+ 重建
    python scripts/run_daily.py --force      # 强制重抓所有数据
    python scripts/run_daily.py --rebuild    # 只用已有 data/ 重建页面（不联网）
    python scripts/run_daily.py --serve      # 跑完起一个本地静态服务看效果
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import build_board  # noqa: E402
import build_status  # noqa: E402
import compute  # noqa: E402
import fetch  # noqa: E402
from util import DOCS, log  # noqa: E402


def main() -> None:
    args = set(sys.argv[1:])
    t0 = time.time()

    if "--rebuild" not in args:
        warnings = fetch.fetch_all(force="--force" in args)
    else:
        log("== 跳过抓数（--rebuild）==")
        warnings = []

    compute.main()
    build_board.build()
    build_status.build()

    log(f"完成，用时 {time.time() - t0:.1f}s → docs/index.html + docs/status.html")

    if warnings:
        bar = "=" * 64
        log(bar)
        log("⚠ 注意：以下接口本次未拿到新数据（看板已用旧缓存继续出图）：")
        for w in warnings:
            log(f"  ⚠ {w}")
        log("  逐项状态见 docs/status.html 与 data/fetch_manifest.json；下次运行会自动重试。")
        log(bar)
        try:
            import winsound  # Windows 蜂鸣提醒
            winsound.Beep(880, 300)
        except Exception:  # noqa: BLE001
            pass

    if "--serve" in args:
        import http.server
        import socketserver

        port = 8765
        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
            *a, directory=str(DOCS), **kw)
        with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
            log(f"本地预览： http://127.0.0.1:{port}/index.html （Ctrl+C 退出）")
            httpd.serve_forever()


if __name__ == "__main__":
    main()
