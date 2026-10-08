# -*- coding: utf-8 -*-
"""
迷你助手 · 启动入口

用法
----
    python run.py              正常启动
    python run.py --doctor     只检查依赖在哪，不启动
    python run.py --port 61000 指定端口
    python run.py --no-open    不自动开浏览器

依赖位置全是**自动查找**的（见 src/find.py）。
查不到用 --doctor 看缺什么，再用环境变量指定。
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

# 让 src 能被 import
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src import config, server                        # noqa: E402


def doctor() -> int:
    """只检查依赖，不启动服务。"""
    from src import find
    r = find.report()

    print()
    print("  " + "=" * 58)
    print("   依赖自检")
    print("  " + "=" * 58)

    items = [
        ("node", "Node.js", "必装 —— dsh 靠它跑", True),
        ("dsh", "DeepSeek Harness", "必装 —— 后端", True),
        ("chatlab", "ChatLab 数据", "看微信消息要用", False),
        ("funasr", "FunASR 识别", "说话输入要用", False),
        ("whisper", "faster-whisper", "说话输入（备选）", False),
        ("text2vec", "中文向量模型", "语义记忆要用", False),
        ("kokoro", "Kokoro 语音", "本地朗读要用", False),
        ("ffmpeg", "ffmpeg", "音频处理要用", False),
        ("browser", "浏览器", "自动打开界面", False),
    ]

    missing_req = []
    missing_opt = []
    for key, label, why, req in items:
        v = r.get(key)
        if isinstance(v, list):
            v = v[0] if v else ""
        if v:
            print(f"   ● {label:<20} {str(v)[:58]}")
        else:
            tag = "必装" if req else "可选"
            print(f"   ○ {label:<20} （没找到）[{tag}] {why}")
            (missing_req if req else missing_opt).append(label)

    print("  " + "-" * 58)
    print(f"   家目录   : {r.get('home')}")
    if r.get("model_roots"):
        print(f"   模型目录 : {'  '.join(r['model_roots'])}")
    print("  " + "=" * 58)

    if missing_req:
        print()
        print("   ⚠ 有必装的没找到，服务可能起不来。")
    if missing_opt or missing_req:
        print()
        print("   可以用环境变量指定位置：")
        for k, d in (
            ("MINI_NODE", "node.exe"),
            ("MINI_DSH", "dsh 的 bin.js"),
            ("MINI_CHATLAB", "ChatLab 数据库目录"),
            ("MINI_MODELS", "模型总目录"),
            ("MINI_FUNASR", "FunASR 模型目录"),
            ("MINI_WHISPER", "whisper 模型目录"),
            ("MINI_TEXT2VEC", "向量模型目录"),
            ("MINI_FFMPEG", "ffmpeg"),
        ):
            print(f"     {k:<16} {d}")
        print()
        print("   也可以直接写进 config.json。")
        print()
    else:
        print("\n  全部就绪。\n")
    return 0 if not missing_req else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="迷你助手 —— 一个极简的本地 AI 助手")
    ap.add_argument("--port", type=int, default=0,
                    help="监听端口（默认自动挑一个不冲突的）")
    ap.add_argument("--host", default="",
                    help="监听地址（默认 127.0.0.1）")
    ap.add_argument("--no-open", action="store_true",
                    help="启动后不自动打开浏览器")
    ap.add_argument("--doctor", action="store_true",
                    help="只检查依赖在哪，不启动服务")
    args = ap.parse_args()

    config.ensure_files()

    if args.doctor:
        return doctor()

    cfg = config.load()
    port = args.port or config.pick_port()
    host = args.host or cfg.get("host") or "127.0.0.1"

    if not args.no_open:
        def _open() -> None:
            time.sleep(1.5)
            try:
                webbrowser.open(f"http://{host}:{port}")
            except Exception:                              # noqa: BLE001
                pass
        threading.Thread(target=_open, daemon=True).start()

    print(f"  即将打开 http://{host}:{port}")

    try:
        server.serve(host, port)
    except OSError as e:
        print(f"\n  启动失败：{e}")
        print(f"  端口 {port} 被占用了，\n"
              f"  试试 python run.py （不带参数会自动换）\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
