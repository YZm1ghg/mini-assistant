# -*- coding: utf-8 -*-
"""
对话历史

存成一个 JSONL 文件，一行一条。好处：
    · 追加即可，不用每次重写整个文件
    · 出问题只坏一行，不会全丢
    · 用文本编辑器就能看

格式
----
    每行一个 JSON 对象，字段：
        t        时间戳（Unix 秒，浮点）
        role     "user" 或 "assistant"
        text     内容
        session  只有助手回复才有：对应的 DSH session id
        elapsed  只有助手回复才有：耗时秒数

    坏行会被跳过，不影响其他记录。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from . import config

_lock = threading.Lock()
PATH = config.DATA_DIR / "chat.jsonl"


def append(role: str, text: str, **extra: Any) -> dict:
    """追加一条。"""
    item = {"t": time.time(), "role": role, "text": text}
    item.update(extra)
    with _lock:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def load(limit: int = 200) -> list[dict]:
    """读最近 limit 条（返回顺序 = 时间正序）。"""
    if not PATH.exists():
        return []
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()
    except Exception:                                      # noqa: BLE001
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if isinstance(d, dict) and "role" in d:
                out.append(d)
        except Exception:                                  # noqa: BLE001
            continue                                       # 坏行跳过
    return out


def clear() -> dict:
    """清空历史。"""
    with _lock:
        try:
            if PATH.exists():
                PATH.unlink()
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": str(e)}
    return {"ok": True}


def last_session() -> str:
    """最近一次用的 dsh session id —— 用来续聊。"""
    for item in reversed(load(50)):
        sid = item.get("session")
        if sid:
            return str(sid)
    return ""


def export_markdown() -> str:
    """导出成 Markdown（给人看的）。"""
    items = load(9999)
    if not items:
        return "# 对话记录\n\n（空）\n"
    lines = ["# 对话记录", ""]
    for it in items:
        who = "我" if it.get("role") == "user" else "助手"
        ts = time.strftime("%Y-%m-%d %H:%M:%S",
                           time.localtime(it.get("t") or 0))
        lines.append(f"## {who} · {ts}")
        lines.append("")
        lines.append(str(it.get("text") or ""))
        lines.append("")
    return "\n".join(lines)
