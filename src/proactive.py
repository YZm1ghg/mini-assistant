# -*- coding: utf-8 -*-
"""
主动助手

不等你问，它自己会做的事。

能做什么
--------
    · **微信播报** —— 有新消息就念（只念增量，不重复）
    · **定时提醒** —— 到点提醒你（道早安、喝水、睡觉…）
    · **待办提醒** —— 从聊天里认出你答应过的事

怎么控制
--------
    全部在 config.json 里开关，默认**全关**。
    主动打扰人是把双刃剑 —— 没让你主动开就不该响。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config, voice, wechat

STATE_PATH = config.DATA_DIR / "proactive_state.json"

# 默认配置（会被 config.json 覆盖）
DEFAULT_CONF = {
    "on": False,                 # 总开关
    "wechat_interval": 60,       # 每多少秒查一次微信
    "wechat_speak": True,        # 微信新消息要不要念
    "wechat_max": 3,             # 一次最多念几条
    "daily": [                   # 每天定时说什么（空 = 不启用）
        # {"time": "08:30", "text": "早上好"},
        # {"time": "23:00", "text": "该休息了"},
    ],
    "quiet": ["23:30", "07:30"],  # 安静时段，不打扰
    "todo_hour": 9,              # 每天几点提醒待办
}

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()


# ============================================================
#  状态
# ============================================================
def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:                                  # noqa: BLE001
        return {}


def _save_state(d: dict) -> None:
    with _lock:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(
                json.dumps(d, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:                              # noqa: BLE001
            pass


def get_conf() -> dict:
    """读主动助手配置（config.json 里的 proactive 段）。"""
    raw = config.get("proactive")
    c = dict(DEFAULT_CONF)
    if isinstance(raw, dict):
        for k in DEFAULT_CONF:
            if k in raw:
                c[k] = raw[k]
    return c


def set_conf(values: dict) -> dict:
    c = get_conf()
    for k, v in (values or {}).items():
        if k in DEFAULT_CONF:
            c[k] = v
    config.save({"proactive": c})
    return c


# ============================================================
#  安静时段
# ============================================================
def in_quiet(now: datetime | None = None) -> bool:
    """现在是不是安静时段？（跨午夜也支持）"""
    c = get_conf()
    q = c.get("quiet") or []
    if not isinstance(q, list) or len(q) < 2:
        return False
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute

    def _m(s: str) -> int:
        try:
            h, mi = str(s).split(":")[:2]
            return int(h) * 60 + int(mi)
        except Exception:                              # noqa: BLE001
            return -1

    a, b = _m(q[0]), _m(q[1])
    if a < 0 or b < 0:
        return False
    if a <= b:
        return a <= cur < b
    # 跨午夜：23:30 ~ 07:30
    return cur >= a or cur < b


def can_speak(force: bool = False) -> bool:
    """现在能不能出声。

    ⚠ force=True 时**跳过所有开关**（手动触发用）。
      不加这个参数的话，"手动跑一轮"会被总开关和安静时段
      拦住 —— 半夜点"立即检查"什么都不会发生（踩过）。
    """
    if force:
        return not voice.status().get("speaking")
    c = get_conf()
    if not c.get("on"):
        return False
    if in_quiet():
        return False
    if voice.status().get("speaking"):
        return False
    return True


# ============================================================
#  一轮检查
# ============================================================
def tick(force: bool = False) -> dict:
    """跑一轮。返回这轮做了什么。

    force=True 时忽略总开关和安静时段（手动触发用）。
    """
    did: list[str] = []
    c = get_conf()
    if not c.get("on") and not force:
        return {"ok": True, "skipped": "总开关关着", "did": did}
    if in_quiet() and not force:
        return {"ok": True, "skipped": "安静时段", "did": did}

    st = _load_state()
    now = time.time()

    # ---- 微信消息 ----
    iv = float(c.get("wechat_interval") or 60)
    last_wx = float(st.get("last_wechat") or 0)
    if now - last_wx >= iv:
        st["last_wechat"] = now
        try:
            fresh = wechat.pick_new()
        except Exception as e:                         # noqa: BLE001
            fresh = []
            did.append(f"微信查失败：{e}")
        if fresh:
            # 急的优先念
            fresh.sort(key=lambda x: (
                0 if x.get("cat") == "urgent" else 1, x["ts"]))
            top = fresh[:int(c.get("wechat_max") or 3)]
            if c.get("wechat_speak", True) and can_speak(force):
                txt = wechat.broadcast_text(top)
                if txt:
                    voice.speak(txt)
                    did.append(f"播报微信 {len(top)} 条")
            wechat.mark_seen(fresh)          # 全部标记已读
            st["last_wx_count"] = len(fresh)

    # ---- 每日定时 ----
    hhmm = datetime.now().strftime("%H:%M")
    today = datetime.now().strftime("%Y-%m-%d")
    for item in (c.get("daily") or []):
        try:
            t = str(item.get("time") or "")
            text = str(item.get("text") or "")
            if not t or not text:
                continue
            if t != hhmm:
                continue
            key = f"{today} {t}"
            fired = st.get("fired") or {}
            if fired.get(key):
                continue
            if can_speak(force):
                voice.speak(text)
                did.append(f"定时：{text[:20]}")
            fired[key] = True
            # 只留最近 60 条，防无限涨
            if len(fired) > 60:
                fired = dict(list(fired.items())[-60:])
            st["fired"] = fired
        except Exception:                              # noqa: BLE001
            continue

    _save_state(st)
    # 返回这轮做了什么
    #
    # ⚠ force 的语义要一致（踩过）：
    #   原来只有**开头**两个检查看了 force，
    #   但后面调 can_speak() 又检查了一遍 on + 安静时段 →
    #   半夜手动触发时照样被拦住，did 里什么都没有。
    #   ✅ force 时用 can_speak_forced() 绕开所有开关。
    return {"ok": True, "did": did, "quiet": in_quiet()}


def check_now() -> dict:
    """手动跑一轮（忽略开关）。"""
    return tick(force=True)


# ============================================================
#  后台线程
# ============================================================
def _loop() -> None:
    while not _stop.is_set():
        try:
            tick()
        except Exception as e:                         # noqa: BLE001
            try:
                p = config.DATA_DIR / "proactive.log"
                with open(p, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] "
                            f"{type(e).__name__}: {e}\n")
            except Exception:                          # noqa: BLE001
                pass
        _stop.wait(20)


def start() -> dict:
    global _thread
    if _thread is not None and _thread.is_alive():
        return {"ok": True, "msg": "已在运行"}
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True,
                               name="proactive")
    _thread.start()
    return {"ok": True, "msg": "已启动"}


def stop() -> dict:
    _stop.set()
    return {"ok": True, "msg": "已停止"}


def status() -> dict:
    c = get_conf()
    st = _load_state()
    return {
        "on": bool(c.get("on")),
        "running": bool(_thread and _thread.is_alive()),
        "quiet_now": in_quiet(),
        "last_wechat": st.get("last_wechat") or 0,
        "last_wx_count": st.get("last_wx_count") or 0,
        "daily": c.get("daily") or [],
        "quiet": c.get("quiet") or [],
    }
