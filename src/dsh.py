# -*- coding: utf-8 -*-
"""
DSH 后端

调用 dsh 的 headless profile，把它的流式事件转成我们需要的格式。

接口（实测 dsh 0.2.0-rc.2）
---------------------------
    命令行加 --json 之后，输出是**逐行 JSON 事件**。
    常用的几个 type：

        session    首次提问返回，带 sessionId（后面续聊要用）
        status     进度（turn_start / step_start / step_end /
                   turn_end）
        text       正文内容 —— 我们只取这个
        final      收尾，带完整文本
        error      出错

    续聊就是第二次调用时带上 --session-id。

踩过的坑
--------
    · --session-id 传不存在的 id 会**报错退出**，不是新建。
    · dsh 需要 node 在 PATH 里。
    · cwd 决定了它能在哪个目录干活。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import config


@dataclass
class Reply:
    ok: bool
    text: str = ""
    session_id: str = ""
    error: str = ""
    elapsed: float = 0.0
    usage: dict = field(default_factory=dict)


def _node() -> str:
    """找 node.exe。

    ✅ 交给 find 模块统一查找（PATH → 常见位置 → nvm/fnm）
    """
    from . import find
    p = find.node()
    return str(p) if p else ""


_avail_cache: dict = {}
_avail_at: float = 0.0
_AVAIL_TTL = 300.0


def available(fresh: bool = False) -> dict:
    """检查后端是否可用（给前端显示状态用）。

    ⚠ 缓存 5 分钟（踩过）：
      config.find_dsh_bin() 有可能要起 
pm root -g 子进程，
      单次 700~900ms。被 /api/state 每 15 秒调一次就明显卡了。
    """
    global _avail_cache, _avail_at
    now = time.time()
    if (not fresh and _avail_cache
            and now - _avail_at < _AVAIL_TTL):
        return _avail_cache
    node = _node()
    binjs = config.find_dsh_bin()
    if not node:
        res = {"ok": False, "error": "找不到 node.exe"}
    elif not binjs:
        res = {"ok": False,
               "error": "找不到 dsh，请在 config.json 里填 dsh_bin"}
    else:
        res = {"ok": True, "node": node, "dsh": binjs}
    _avail_cache = res
    _avail_at = now
    return res


def ask(question: str, session_id: str = "",
        on_event: Optional[Callable[[dict], None]] = None,
        cancel: Optional[threading.Event] = None) -> Reply:
    """问一句，拿回复。

    on_event(event) 会在每收到一行 dsh 输出时被调用 ——
    前端据此做流式显示。

    ⚠ session_id 传空 = 新建会话；传错的值 dsh 会报错退出。
    """
    t0 = time.time()
    chk = available()
    if not chk.get("ok"):
        return Reply(False, error=chk.get("error", "后端不可用"))

    cfg = config.load()
    cmd = [
        chk["node"], chk["dsh"],
        "--profile", cfg.get("dsh_profile") or "headless",
        "--json",
    ]
    if session_id:
        cmd += ["--session-id", session_id]
    cmd.append(question)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # 清代理：dsh 访问本机服务时代理会捣乱
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy",
              "https_proxy", "ALL_PROXY"):
        env.pop(k, None)

    work = cfg.get("work_dir") or ""
    cwd = work if work and Path(work).exists() else str(config.ROOT)

    timeout = float(cfg.get("timeout") or 300)

    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:                                 # noqa: BLE001
        return Reply(False, error=f"启动 dsh 失败：{e}")

    text_parts: list[str] = []
    sid = session_id
    usage: dict = {}
    err_lines: list[str] = []

    def _read_err() -> None:
        try:
            for line in proc.stderr:                       # type: ignore
                line = line.rstrip()
                if line:
                    err_lines.append(line)
                    if len(err_lines) > 40:
                        err_lines.pop(0)
        except Exception:                                  # noqa: BLE001
            pass

    et = threading.Thread(target=_read_err, daemon=True)
    et.start()

    killed = False
    try:
        for line in proc.stdout:                           # type: ignore
            if cancel is not None and cancel.is_set():
                proc.kill()
                killed = True
                break
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:                              # noqa: BLE001
                continue
            if not isinstance(ev, dict):
                continue

            t = ev.get("type")
            if t == "session":
                sid = ev.get("sessionId") or sid
            elif t == "text":
                text_parts.append(ev.get("text") or "")
            elif t == "status":
                u = ev.get("usage")
                if isinstance(u, dict):
                    usage = u
            elif t == "error":
                err_lines.append(str(ev.get("message")
                                     or ev.get("error") or ev))

            if on_event is not None:
                try:
                    on_event(ev)
                except Exception:                          # noqa: BLE001
                    pass

            if time.time() - t0 > timeout:
                proc.kill()
                killed = True
                break
    except Exception as e:                                 # noqa: BLE001
        try:
            proc.kill()
        except Exception:                                  # noqa: BLE001
            pass
        return Reply(False, error=f"读取输出失败：{e}",
                     session_id=sid, elapsed=time.time() - t0)

    try:
        proc.wait(timeout=10)
    except Exception:                                      # noqa: BLE001
        try:
            proc.kill()
        except Exception:                                  # noqa: BLE001
            pass

    el = time.time() - t0
    code = proc.returncode
    text = "".join(text_parts).strip()

    if killed:
        return Reply(False, text=text,
                     error="已取消" if cancel is not None
                     and cancel.is_set() else "超时",
                     session_id=sid, elapsed=el, usage=usage)

    if not text and code not in (0, None):
        msg = "\n".join(err_lines[-6:]) or f"dsh 退出码 {code}"
        return Reply(False, error=msg[:600], session_id=sid,
                     elapsed=el, usage=usage)

    return Reply(True, text=text, session_id=sid, elapsed=el,
                 usage=usage)
