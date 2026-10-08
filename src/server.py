# -*- coding: utf-8 -*-
"""
HTTP 服务

一个很小的服务器：给网页提供接口，并托管 index.html。

接口
----
    GET  /              网页
    GET  /api/state     状态（后端可用？语音引擎？）
    POST /api/ask       问一句      {text, session}
    POST /api/voice     念一段      {text}
    POST /api/stop      打断播放
    POST /api/record    录音 N 秒   {seconds}
    POST /api/asr       识别录音
    GET  /api/history   读历史
    POST /api/clear     清空历史
    GET  /api/config    读配置
    POST /api/config    写配置

    ---- 长期记忆 ----
    GET  /api/memory        读记忆列表 + 统计
    POST /api/memory/add    手动记一条      {text, kind}
    POST /api/memory/find   检索            {query}
    POST /api/memory/forget 删一条          {index}
    POST /api/memory/clear  清空

    ---- 看图 ----
    GET  /api/look/status   状态
    GET  /api/look/list     最近看过的图
    POST /api/look/shot     截屏
    POST /api/look/cam      拍照
    POST /api/look/see      看图提问        {path, question}
    GET  /api/look/img      取图（给 <img>）?name=

    ---- 微信 ----
    GET  /api/wx/status     状态
    GET  /api/wx/sessions   会话列表
    GET  /api/wx/recent     谁最近找过我（?hours=24）
    GET  /api/wx/new        未播报的新消息
    POST /api/wx/seen       标记已读        {items}
    POST /api/wx/speak      念出未播报的
    POST /api/wx/reset      重置已读

    ---- 主动助手 ----
    GET  /api/proactive           状态
    POST /api/proactive/conf      改配置  {values}
    POST /api/proactive/check     立即跑一轮

    ---- 保险箱 ----
    GET  /api/vault/status   状态
    GET  /api/vault/list     卷内文件
    POST /api/vault/archive  手动收一轮
    POST /api/vault/export   导出到目录    {dest}
"""
from __future__ import annotations

import json
import mimetypes
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import (chat, config, dsh, find, intent, look,
               memory, proactive, skills, syscontrol, sysmon,
               vault, voice, wechat)

UI = config.ROOT / "ui"


def _json_default(o):
    try:
        return str(o)
    except Exception:                                      # noqa: BLE001
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "MiniAssistant/1.0"
    protocol_version = "HTTP/1.1"

    # ---- 工具 ----
    def _send(self, code: int, body: bytes,
              ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:                                  # noqa: BLE001
            pass

    def _ok(self, obj) -> None:
        self._send(200, json.dumps(obj, ensure_ascii=False,
                                   default=_json_default).encode())

    def _err(self, msg: str, code: int = 500) -> None:
        self._send(code, json.dumps({"ok": False, "error": msg},
                                    ensure_ascii=False).encode())

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            d = json.loads(raw.decode("utf-8", errors="replace") or "{}")
            return d if isinstance(d, dict) else {}
        except Exception:                                  # noqa: BLE001
            return {}

    def log_message(self, fmt, *args) -> None:
        pass                                               # 静音

    # ---- 路由 ----
    def do_GET(self) -> None:                              # noqa: N802
        try:
            self._get()
        except Exception:                                  # noqa: BLE001
            traceback.print_exc()
            self._err("服务器内部错误")

    def do_POST(self) -> None:                             # noqa: N802
        try:
            self._post()
        except Exception:                                  # noqa: BLE001
            traceback.print_exc()
            self._err("服务器内部错误")

    def _get(self) -> None:
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)

        if p in ("/", "/index.html"):
            f = UI / "index.html"
            if not f.exists():
                self._err("缺少 ui/index.html", 404)
                return
            self._send(200, f.read_bytes(),
                       "text/html; charset=utf-8")
            return

        if p == "/api/state":
            self._ok({
                "ok": True,
                "backend": dsh.available(),
                "voice": voice.status(),
                "session": chat.last_session(),
                "config": config.load(),
                "memory": memory.stats(),
                "wechat": wechat.status(),
                "vault": vault.status(),
                "proactive": proactive.status(),
                "found": find.report(),
            })
            return

        # ---- 功能接口 ----
        if self._get_features(p, q):
            return

        if p == "/api/history":
            self._ok({"ok": True, "items": chat.load(
                int(config.get("history_limit") or 200))})
            return

        if p == "/api/config":
            self._ok({"ok": True, "values": config.load(),
                      "defaults": config.DEFAULTS,
                      "path": str(config.CONFIG_PATH)})
            return

        if p == "/api/export":
            md = chat.export_markdown()
            self._send(200, md.encode("utf-8"),
                       "text/markdown; charset=utf-8")
            return

        # 静态文件（如果有）
        rel = p.lstrip("/")
        if rel and ".." not in rel:
            f = (UI / rel).resolve()
            try:
                if str(f).startswith(str(UI.resolve())) \
                        and f.is_file():
                    ct = (mimetypes.guess_type(str(f))[0]
                          or "application/octet-stream")
                    self._send(200, f.read_bytes(),
                               ct + ("; charset=utf-8"
                                     if ct.startswith("text")
                                     else ""))
                    return
            except Exception:                              # noqa: BLE001
                pass

        self._err("没这个接口：" + p, 404)

    # ---- 功能接口（GET） ----
    def _get_features(self, p: str, q: dict) -> bool:
        """返回 True 表示已处理。"""
        # ==================== 长期记忆 ====================
        if p == "/api/memory":
            self._ok({"ok": True, "stats": memory.stats(),
                      "items": memory._load()[-60:]})
            return True

        if p == "/api/memory/find":
            query = (q.get("query") or [""])[0]
            self._ok({"ok": True,
                      "items": memory.recall(query, limit=8)})
            return True

        # ==================== 看图 ====================
        if p == "/api/look/status":
            self._ok({"ok": True, **look.status()})
            return True

        if p == "/api/look/list":
            self._ok({"ok": True, "items": look.list_shots()})
            return True

        if p == "/api/look/img":
            name = (q.get("name") or [""])[0]
            if not name or ".." in name:
                self._err("非法文件名", 400)
                return True
            # 先从保险箱找，再从明文目录找
            data = vault.get_image(name)
            src = ""
            if data is None:
                cand = Path(name)
                if not cand.is_absolute():
                    cand = config.DATA_DIR / "look" / name
                try:
                    if cand.exists():
                        data = cand.read_bytes()
                        src = str(cand)
                except Exception:                          # noqa: BLE001
                    data = None
            if data is None:
                self._err("找不到图", 404)
                return True
            ext = name.rsplit(".", 1)[-1].lower()
            mime = {"png": "image/png", "jpg": "image/jpeg",
                    "jpeg": "image/jpeg", "webp": "image/webp",
                    "gif": "image/gif", "bmp": "image/bmp"}.get(
                        ext, "image/png")
            self._send(200, data, mime)
            return True

        # ==================== 微信 ====================
        if p == "/api/wx/status":
            self._ok({"ok": True, **wechat.status()})
            return True

        if p == "/api/wx/sessions":
            self._ok({"ok": True, "items": wechat.sessions()})
            return True

        if p == "/api/wx/recent":
            try:
                hours = float((q.get("hours") or ["24"])[0])
            except Exception:                              # noqa: BLE001
                hours = 24.0
            self._ok(wechat.who_contacted(hours=hours))
            return True

        if p == "/api/wx/new":
            items = wechat.pick_new()
            self._ok({"ok": True, "count": len(items),
                      "items": items[-30:],
                      "speak_text": wechat.broadcast_text(items)})
            return True

        # ==================== 主动助手 ====================
        if p == "/api/proactive":
            self._ok({"ok": True, **proactive.status(),
                      "conf": proactive.get_conf()})
            return True

        # ==================== 保险箱 ====================
        if p == "/api/vault/status":
            self._ok({"ok": True, **vault.status()})
            return True

        if p == "/api/vault/list":
            self._ok({"ok": True, "items": vault.list_images()})
            return True

        # ==================== 系统监控 ====================
        if p == "/api/sysmon":
            full = (q.get("full") or ["0"])[0] in ("1", "true")
            self._ok({"ok": True, **sysmon.snapshot(full=full)})
            return True

        if p == "/api/sysmon/proc":
            try:
                n = int((q.get("limit") or ["10"])[0])
            except Exception:                          # noqa: BLE001
                n = 10
            by = (q.get("by") or ["mem"])[0]
            self._ok({"ok": True,
                      "items": sysmon.processes(n, by)})
            return True

        if p == "/api/sysmon/temp":
            self._ok({"ok": True, "items": sysmon.temps()})
            return True

        # ==================== 系统控制 ====================
        if p == "/api/sys/volume":
            self._ok(syscontrol.get_volume().as_dict())
            return True

        if p == "/api/sys/brightness":
            self._ok(syscontrol.get_brightness().as_dict())
            return True

        if p == "/api/sys/power":
            self._ok(syscontrol.current_power_plan().as_dict())
            return True

        if p == "/api/sys/stuck":
            self._ok(syscontrol.hung_processes().as_dict())
            return True

        # ==================== 技能 / 意图 ====================
        if p == "/api/skills":
            self._ok({"ok": True, **skills.status()})
            return True

        if p == "/api/intent":
            text = (q.get("text") or [""])[0]
            self._ok({"ok": True, **intent.judge(text).as_dict()})
            return True

        return False

    def _post(self) -> None:
        p = urlparse(self.path).path
        data = self._body()

        # ---- 问一句 ----
        if p == "/api/ask":
            text = str(data.get("text") or "").strip()
            if not text:
                self._err("内容为空", 400)
                return
            sid = str(data.get("session") or "").strip()
            if not sid:
                sid = chat.last_session()
            new = bool(data.get("new"))

            chat.append("user", text)

            # ---- 先试技能 / 判断意图 ----
            #
            # ⚠⚠ 这一步是性能关键（踩过）：
            #   「现在几点」走一趟 AI 要 3~5 秒，
            #   而本地取系统时间只要几微秒。
            #
            #   所以先过一遍意图判断：
            #     · 命中技能 → 直接返回，**完全不走 AI**
            #     · 是 task  → 给 AI 加更强的提示（让它动手）
            #     · 其他     → 正常问
            #
            #   ⚠ 但可以在设置里关掉（skill_first=False），
            #     有些人希望所有问题都让 AI 回答。
            verdict = None
            if config.get("skill_first", True) and \
                    not data.get("no_skill"):
                try:
                    verdict = intent.judge(text)
                except Exception as e:                 # noqa: BLE001
                    print(f"[意图] 判断失败: {e}")
                    verdict = None

            if verdict is not None and verdict.reply:
                chat.append("assistant", verdict.reply,
                            skill=verdict.skill, elapsed=0)
                if (config.get("voice_enabled")
                        and data.get("speak", True)):
                    voice.speak(verdict.reply)
                self._ok({"ok": True, "text": verdict.reply,
                          "session": sid, "elapsed": 0,
                          "skill": verdict.skill,
                          "fast": True})
                return

            # 是任务的话，加一句提示让 AI 动手而不是空谈
            if verdict is not None and verdict.kind == "task":
                text = text + "\n\n（请直接动手完成，不要只给建议）"

            # ---- 带上相关记忆当背景 ----
            #
            # ⚠ 这一步是"长期记忆"真正起作用的地方：
            #   光存不取等于没存。每次提问先召回几条相关的，
            #   塞进 prompt 里，AI 才能"想起来"。
            prompt = text
            n_recall = int(config.get("memory_recall") or 0)
            if n_recall > 0:
                try:
                    ctx = memory.build_context(text, n_recall)
                except Exception:                          # noqa: BLE001
                    ctx = ""
                if ctx:
                    prompt = (f"{ctx}\n\n"
                              f"（以上是背景资料，不必逐条回应）\n\n"
                              f"我的问题：{text}")

            events: list[dict] = []

            def on_ev(ev: dict) -> None:
                # 只留前端关心的
                if ev.get("type") in ("text", "status", "error"):
                    events.append(ev)

            t0 = time.time()
            r = dsh.ask(prompt, session_id="" if new else sid,
                        on_event=on_ev)
            print(f"[问] {text[:30]!r} → ok={r.ok} "
                  f"{time.time()-t0:.1f}s", flush=True)

            if r.ok:
                chat.append("assistant", r.text,
                            session=r.session_id,
                            elapsed=round(r.elapsed, 2))
                # ---- 自动记进长期记忆 ----
                if config.get("memory_auto"):
                    try:
                        memory.remember_exchange(text, r.text)
                    except Exception:                      # noqa: BLE001
                        pass
                if (config.get("voice_enabled")
                        and data.get("speak", True)):
                    voice.speak(r.text)
                self._ok({"ok": True, "text": r.text,
                          "session": r.session_id,
                          "elapsed": round(r.elapsed, 2),
                          "usage": r.usage})
            else:
                self._ok({"ok": False, "error": r.error,
                          "text": r.text})
            return

        # ---- 念一段 ----
        if p == "/api/voice":
            self._ok(voice.speak(str(data.get("text") or ""),
                                 blocking=bool(data.get("blocking"))))
            return

        if p == "/api/stop":
            self._ok(voice.stop_speaking())
            return

        # ---- 录音 + 识别 ----
        if p == "/api/record":
            secs = float(data.get("seconds")
                         or config.get("asr_max_seconds") or 5)
            secs = max(1.0, min(60.0, secs))
            self._ok(voice.record(secs))
            return

        if p == "/api/asr":
            path = str(data.get("path") or "")
            if not path:
                path = str(config.DATA_DIR / "rec.wav")
            r = voice.transcribe(path)
            self._ok({"ok": r.ok, "text": r.text,
                      "backend": r.backend,
                      "elapsed": round(r.elapsed, 2),
                      "error": r.error})
            return

        # ---- 历史 / 配置 ----
        if p == "/api/clear":
            self._ok(chat.clear())
            return

        if p == "/api/config":
            values = data.get("values")
            if not isinstance(values, dict):
                self._err("values 必须是对象", 400)
                return
            self._ok({"ok": True,
                      "values": config.save(values)})
            return

        # ---- 功能接口 ----
        if self._post_features(p, data):
            return

        self._err("没这个接口：" + p, 404)

    # ---- 功能接口（POST） ----
    def _post_features(self, p: str, d: dict) -> bool:
        """返回 True 表示已处理。"""
        # ==================== 长期记忆 ====================
        if p == "/api/memory/add":
            self._ok(memory.remember(
                str(d.get("text") or ""),
                str(d.get("kind") or "fact")))
            return True

        if p == "/api/memory/forget":
            try:
                i = int(d.get("index"))
            except Exception:                              # noqa: BLE001
                self._err("index 必须是数字", 400)
                return True
            self._ok(memory.forget(i))
            return True

        if p == "/api/memory/clear":
            self._ok(memory.clear())
            return True

        # ==================== 看图 ====================
        if p == "/api/look/shot":
            s = look.screenshot()
            if s.get("ok"):
                vault.touch(s["path"])     # 保护起来，别马上收走
            self._ok(s)
            return True

        if p == "/api/look/cam":
            s = look.camera_shot(int(d.get("index") or 0))
            if s.get("ok"):
                vault.touch(s["path"])
            self._ok(s)
            return True

        if p == "/api/look/see":
            path = str(d.get("path") or "")
            if not path:
                # 没给就现截一张
                s = look.screenshot()
                if not s.get("ok"):
                    self._ok(s)
                    return True
                path = s["path"]
            vault.touch(path)              # ⚠ 让保险箱让别人先看
            self._ok(look.describe(
                path, str(d.get("question") or ""),
                session=str(d.get("session") or "")))
            return True

        # ==================== 微信 ====================
        if p == "/api/wx/seen":
            items = d.get("items")
            if isinstance(items, list):
                wechat.mark_seen(items)
            self._ok({"ok": True})
            return True

        if p == "/api/wx/speak":
            items = wechat.pick_new()
            if not items:
                self._ok({"ok": True, "msg": "没有新消息"})
                return True
            txt = wechat.broadcast_text(
                items, int(d.get("max") or 5))
            if txt:
                voice.speak(txt)
            wechat.mark_seen(items)
            self._ok({"ok": True, "count": len(items),
                      "text": txt})
            return True

        if p == "/api/wx/reset":
            self._ok(wechat.reset_seen())
            return True

        # ==================== 主动助手 ====================
        if p == "/api/proactive/conf":
            values = d.get("values")
            if not isinstance(values, dict):
                self._err("values 必须是对象", 400)
                return True
            self._ok({"ok": True,
                      "conf": proactive.set_conf(values)})
            return True

        if p == "/api/proactive/check":
            self._ok(proactive.check_now())
            return True

        # ==================== 保险箱 ====================
        if p == "/api/vault/archive":
            self._ok(vault.archive(force=bool(d.get("force"))))
            return True

        if p == "/api/vault/export":
            dest = str(d.get("dest") or "")
            if not dest:
                dest = str(config.DATA_DIR / "export")
            self._ok(vault.export_all(dest))
            return True

        # ==================== 系统控制 ====================
        if p == "/api/sys/volume":
            v = d.get("value")
            if v is None:
                self._ok(syscontrol.get_volume().as_dict())
            else:
                self._ok(syscontrol.set_volume(v).as_dict())
            return True

        if p == "/api/sys/volume/adjust":
            self._ok(syscontrol.adjust_volume(
                float(d.get("delta") or 0)).as_dict())
            return True

        if p == "/api/sys/mute":
            self._ok(syscontrol.mute_toggle().as_dict())
            return True

        if p == "/api/sys/brightness":
            v = d.get("value")
            if v is None:
                self._ok(syscontrol.get_brightness().as_dict())
            else:
                self._ok(syscontrol.set_brightness(v).as_dict())
            return True

        if p == "/api/sys/kill":
            self._ok(syscontrol.kill_process(
                d.get("target") or "").as_dict())
            return True

        if p == "/api/sys/lock":
            self._ok(syscontrol.lock_screen().as_dict())
            return True

        if p == "/api/sys/screen_off":
            self._ok(syscontrol.screen_off().as_dict())
            return True

        if p == "/api/sys/shutdown":
            action = str(d.get("action") or "shutdown")
            minutes = float(d.get("minutes") or 30)
            self._ok(syscontrol.schedule_shutdown(
                minutes, action).as_dict())
            return True

        if p == "/api/sys/cancel_shutdown":
            self._ok(syscontrol.cancel_shutdown().as_dict())
            return True

        # ==================== 技能 ====================
        if p == "/api/skills/run":
            text = str(d.get("text") or "")
            r = skills.try_run(text)
            if r is None:
                self._ok({"ok": False, "matched": False,
                          "error": "没有匹配的技能，交给 AI"})
            else:
                self._ok({"ok": r.ok, "matched": True,
                          "skill": r.skill, "text": r.text,
                          "elapsed": round(r.elapsed, 4)})
            return True

        return False


def serve(host: str = "", port: int = 0) -> None:
    cfg = config.load()
    host = host or cfg.get("host") or "127.0.0.1"
    config.ensure_files()

    # ⚠ 端口不写死 —— 实际试绑，被占了自动顺延
    #   （详见 config.pick_port 的说明）
    if port:
        use_port = int(port)
    else:
        use_port = config.pick_port()
    port = use_port

    # ---- 起后台服务 ----
    #
    # ⚠ 主动助手和保险箱都要**常驻线程**：
    #   前者定时查微信，后者定时收图。
    #   放在服务启动时拉起来，退出时一起结束（daemon）。
    try:
        proactive.start()
        vault.start()
    except Exception as e:                                 # noqa: BLE001
        print(f"  [警告] 后台线程启动失败：{e}")

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True

    b = dsh.available()
    v = voice.status()
    m = memory.stats()
    w = wechat.status()
    pv = proactive.status()
    st = vault.status()
    fd = find.report()

    def _dot(ok_: bool) -> str:
        return "●" if ok_ else "○"

    print()
    print("  " + "=" * 58)
    print("   迷你助手 · Mini Assistant")
    print("  " + "=" * 58)
    print(f"   地址     : http://{host}:{port}")
    print(f"   工作目录 : {config.ROOT}")
    print("  " + "-" * 58)
    print(f"   {_dot(b.get('ok'))} 后端   : "
          f"{'可用' if b.get('ok') else '不可用 —— ' + str(b.get('error'))}")
    print(f"   {_dot(v.get('tts') not in (None, '未加载'))} 朗读   : "
          f"{v.get('tts') or '未加载'}")
    print(f"   {_dot(v.get('asr') not in (None, '未加载'))} 识别   : "
          f"{v.get('asr') or '未加载'}")
    print(f"   {_dot(m.get('count', 0) > 0)} 记忆   : "
          f"{m.get('count', 0)} 条"
          f"{'（语义检索可用）' if m.get('vector_ready') else ''}")
    print(f"   {_dot(w.get('ok', False))} 微信   : "
          f"{w.get('sessions', 0)} 个会话"
          f"{'' if w.get('ok') else ' —— ' + str(w.get('error'))}")
    print(f"   {_dot(pv.get('on', False))} 主动   : "
          f"{'开' if pv.get('on') else '关'}"
          f"{'（安静时段）' if pv.get('quiet_now') else ''}")
    print(f"   {_dot(st.get('on', False))} 保险箱 : "
          f"{'开' if st.get('on') else '关'} · "
          f"{st.get('files', 0)} 个文件")
    print("  " + "-" * 58)
    print("   自动查到的依赖:")
    for key, label in (("node", "node"), ("dsh", "dsh"),
                       ("funasr", "FunASR"), ("whisper", "whisper"),
                       ("text2vec", "向量模型"),
                       ("kokoro", "Kokoro"), ("ffmpeg", "ffmpeg"),
                       ("browser", "浏览器")):
        val = fd.get(key) or ""
        if val:
            print(f"     {label:<10} {str(val)[:52]}")
        else:
            print(f"     {label:<10} （没找到）")
    if fd.get("chatlab"):
        print(f"     {'ChatLab':<10} {str(fd['chatlab'][0])[:52]}")
    if fd.get("model_roots"):
        print(f"     {'模型目录':<10} "
              f"{'  '.join(str(x) for x in fd['model_roots'])[:52]}")
    print("  " + "=" * 58)
    print(f"   配置     : {config.CONFIG_PATH}")
    print("  " + "=" * 58)
    print()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已退出")
    finally:
        srv.server_close()
