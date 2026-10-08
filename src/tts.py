# -*- coding: utf-8 -*-
"""
语音合成（TTS）

三个引擎，按优先级自动挑：
    ① **edge-tts**（在线，音质最好）    ← 需要 pip install edge-tts
    ② **SAPI**（Windows 系统自带，离线）← 零依赖
    ③ 都没有 → 静默（不报错）

============================================================
为什么不用 pyttsx3
============================================================
    pyttsx3 本身就是 SAPI 的封装，功能一样。
    而 Windows 上直接 `ctypes` 调 SAPI 只要 **~60 行**，
    还能省一个依赖 —— 所以自己写。

============================================================
播放为什么用 MCI
============================================================
    实测这台机器上 sounddevice 的 WASAPI/MME 播放有电流声，
    只有 winmm 的 MCI 干净。
    （录音反过来 —— 只有 WASAPI 能录，见 recorder.py）
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wt
import io
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from . import audio as A
from . import config

_lock = threading.Lock()
_speaking = False
_edge_failed = False
_last_error = ""


def _err(msg: str) -> None:
    global _last_error
    _last_error = msg
    try:
        p = config.DATA_DIR / "voice.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:                                  # noqa: BLE001
        pass


# ============================================================
#  edge-tts（在线）
# ============================================================
def _synth_edge(text: str, voice: str,
                speed: float) -> Optional[A.Audio]:
    """用 edge-tts 合成。

    ⚠ edge-tts 返回的是 **mp3**，要转成我们能处理的 wav。
      转换靠 ffmpeg（见 audio.mp3_to_wav）。
      没有 ffmpeg 的话这条路走不通 → 自动退回 SAPI。
    """
    global _edge_failed
    if _edge_failed:
        return None
    try:
        import edge_tts                        # type: ignore
    except ImportError:
        _edge_failed = True
        _err("没装 edge-tts")
        return None

    # 语速：edge-tts 用 "+20%" / "-10%" 这种格式
    pct = int(round((float(speed) - 1.0) * 100))
    rate_s = f"{'+' if pct >= 0 else ''}{pct}%"

    async def _run() -> bytes:
        comm = edge_tts.Communicate(text, voice, rate=rate_s)
        buf = io.BytesIO()
        async for chunk in comm.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                buf.write(chunk["data"])
        return buf.getvalue()

    try:
        try:
            mp3 = asyncio.run(_run())
        except RuntimeError:
            # 已经在事件循环里 → 新开线程跑
            out: dict = {}

            def _t() -> None:
                try:
                    out["d"] = asyncio.run(_run())
                except Exception as e:                 # noqa: BLE001
                    out["e"] = e

            th = threading.Thread(target=_t)
            th.start()
            th.join(timeout=90)
            if "e" in out:
                raise out["e"]
            mp3 = out.get("d") or b""
    except Exception as e:                             # noqa: BLE001
        _err(f"edge-tts 合成失败：{type(e).__name__}: {e}")
        return None

    if not mp3:
        _err("edge-tts 返回空")
        return None

    # mp3 → wav
    tmp = Path(tempfile.gettempdir()) / (
        "mini_tts_%d_%d.wav" % (os.getpid(),
                                int(time.time() * 1000) % 1000000))
    try:
        if not A.mp3_to_wav(mp3, tmp):
            _err("mp3 → wav 失败（装个 ffmpeg？）")
            return None
        au = A.read_wav(tmp)
        return au
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:                              # noqa: BLE001
            pass


# ============================================================
#  SAPI（Windows 自带，离线）
# ============================================================
def _sapi_save(text: str, rate: int = 0,
               out_wav: str = "") -> bool:
    """用 SAPI 把文字合成成 wav 文件。

    走 PowerShell 的 System.Speech —— 零依赖，
    而且不用写 COM 胶水代码（PowerShell 帮我们做了）。

    rate 是 SAPI 的语速参数，范围 -10 ~ 10（0 = 正常）。
    """
    if os.name != "nt":
        return False
    # ⚠ 单引号里的单引号要翻倍转义
    safe = text.replace("'", "''")
    out = out_wav.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate = {int(rate)};"
        f"$s.SetOutputToWaveFile('{out}');"
        f"$s.Speak('{safe}');"
        "$s.Dispose();"
    )
    try:
        import subprocess
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return Path(out_wav).exists()
    except Exception as e:                             # noqa: BLE001
        _err(f"SAPI 失败：{e}")
        return False


def _synth_sapi(text: str, speed: float) -> Optional[A.Audio]:
    """用系统语音合成。"""
    if os.name != "nt":
        return None
    # speed 1.0 → rate 0；speed 1.5 → rate 5
    rate = max(-10, min(10, int(round((float(speed) - 1.0) * 10))))
    tmp = Path(tempfile.gettempdir()) / (
        "mini_sapi_%d_%d.wav" % (os.getpid(),
                                 int(time.time() * 1000) % 1000000))
    try:
        if not _sapi_save(text, rate, str(tmp)):
            return None
        return A.read_wav(tmp)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:                              # noqa: BLE001
            pass


def list_sapi_voices() -> list:
    """列出系统语音。"""
    if os.name != "nt":
        return []
    try:
        import subprocess
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech;"
             "(New-Object System.Speech.Synthesis"
             ".SpeechSynthesizer).GetInstalledVoices() | "
             "ForEach-Object {$_.VoiceInfo.Name}"],
            capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return [x.strip() for x in (r.stdout or "").splitlines()
                if x.strip()]
    except Exception:                                  # noqa: BLE001
        return []


# ============================================================
#  对外接口
# ============================================================
def synth(text: str) -> Optional[A.Audio]:
    """合成为音频（不播放）。"""
    text = (text or "").strip()
    if not text:
        return None
    cfg = config.load()
    engine = cfg.get("tts_engine") or "auto"
    speed = float(cfg.get("tts_speed") or 1.0)
    voice = cfg.get("tts_voice") or "zh-CN-XiaoxiaoNeural"

    order = []
    if engine == "edge":
        order = ["edge", "sapi"]
    elif engine == "sapi":
        order = ["sapi"]
    elif engine == "auto":
        order = ["edge", "sapi"]
    elif engine == "off":
        return None
    else:
        order = ["edge", "sapi"]

    for name in order:
        if name == "edge":
            au = _synth_edge(text, voice, speed)
        else:
            au = _synth_sapi(text, speed)
        if au and au.samples:
            return au
    return None


def speak(text: str, blocking: bool = False) -> dict:
    """念一段话。"""
    cfg = config.load()
    if not cfg.get("voice_enabled", True):
        return {"ok": False, "msg": "语音已关"}
    if cfg.get("tts_engine") == "off":
        return {"ok": False, "msg": "TTS 已关"}
    text = (text or "").strip()
    if not text:
        return {"ok": False, "msg": "空文本"}

    def _job() -> None:
        global _speaking
        _speaking = True
        try:
            au = synth(text)
            if au:
                A.play(au)
        finally:
            _speaking = False

    if blocking:
        _job()
        return {"ok": True}
    threading.Thread(target=_job, daemon=True,
                     name="mini-tts").start()
    return {"ok": True}


def stop() -> dict:
    A.stop_playback()
    return {"ok": True}


_st_cache: dict = {}
_st_at: float = 0.0
_ST_TTL = 300.0


def status() -> dict:
    """TTS 状态。

    ⚠ 缓存 5 分钟（踩过）：
      `list_sapi_voices()` 要起一个 **PowerShell 子进程**，
      单次 800ms~1.5s。而 status() 被 /api/state 每 15 秒调一次
      → 界面一直在转圈。
      ✅ 缓存起来。装语音包是很少发生的事。
    """
    global _st_cache, _st_at
    now = time.time()
    if _st_cache and now - _st_at < _ST_TTL:
        return _st_cache

    try:
        import edge_tts                    # noqa: F401
        edge_ok = not _edge_failed
    except ImportError:
        edge_ok = False
    sapi = list_sapi_voices()
    ff = A._find_ffmpeg()
    out = {
        "speaking": _speaking or A.is_playing(),
        "engine": ("edge-tts" if edge_ok and ff
                   else "sapi" if sapi else "无"),
        "edge": edge_ok,
        "edge_ready": bool(edge_ok and ff),
        "sapi": sapi,
        "ffmpeg": ff or "",
        "error": _last_error,
    }
    _st_cache = out
    _st_at = now
    return out
