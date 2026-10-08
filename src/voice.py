# -*- coding: utf-8 -*-
"""
语音 —— 统一入口

把三个模块包成原来的接口，这样 server.py / proactive.py
不用改一行：

    voice.speak(text)        念出来
    voice.stop_speaking()    打断
    voice.record(seconds)    录一段
    voice.transcribe(path)   识别
    voice.status()           状态

三个模块分工：
    tts.py       合成（edge-tts / SAPI）
    recorder.py  录音（sounddevice / WASAPI）
    asr.py       识别（FunASR / whisper）

============================================================
依赖情况（诚实说明）
============================================================
    tts        依赖 edge-tts（可选）；没有就用 Windows SAPI（零依赖）
    recorder   依赖 sounddevice —— **去不掉**
               现代 Windows 驱动不支持老的 waveIn 接口，
               只能用 WASAPI（sounddevice 是它的封装）
    asr        依赖 funasr 或 faster-whisper（可选）

    没装哪个，对应功能就自动关，**不影响打字聊天**。
"""
from __future__ import annotations

from . import asr, recorder, tts


# ============================================================
#  播放 / 合成
# ============================================================
def speak(text: str, blocking: bool = False) -> dict:
    """念一段话。"""
    return tts.speak(text, blocking)


def stop_speaking() -> dict:
    """打断朗读。"""
    return tts.stop()


def synth(text: str):
    """只合成不播放（给别的地方用）。"""
    return tts.synth(text)


# ============================================================
#  录音
# ============================================================
def record(seconds: float = 5.0, device=None) -> dict:
    """录一段音。

    ⚠ 返回格式兼容老接口：{"ok", "path", "seconds", "peak"}
      失败时给 {"ok": False, "error": "..."}
    """
    from . import config
    chk = recorder.available()
    if not chk.get("ok"):
        return {"ok": False,
                "error": chk.get("reason") or "录音不可用",
                "hint": chk.get("hint") or ""}

    seconds = max(1.0, min(60.0, float(seconds or 5)))
    au = recorder.record(seconds, 16000, device)
    if au is None:
        return {"ok": False,
                "error": "没录到声音（麦克风静音或没权限）"}

    out = config.DATA_DIR / "rec.wav"
    from . import audio as A
    if not A.write_wav(out, au):
        return {"ok": False, "error": "保存录音失败"}

    peak = max((abs(x) for x in au.samples), default=0.0)
    return {"ok": True, "path": str(out),
            "seconds": round(au.seconds, 2),
            "peak": round(peak, 4)}


# ============================================================
#  识别
# ============================================================
def transcribe(path: str) -> asr.Result:
    """识别音频文件。"""
    return asr.transcribe_file(path)


# ============================================================
#  状态
# ============================================================
def status() -> dict:
    """语音总状态。

    ⚠ 键名保持和老接口一致（speaking / tts / asr / error），
      这样界面不用改。
    """
    t = tts.status()
    a = asr.status()
    r = recorder.available()
    return {
        "speaking": t.get("speaking", False),
        # 老接口用 tts / asr 两个字段显示"加载了没"
        "tts": t.get("engine") or "未加载",
        "asr": a.get("loaded") or "未加载",
        "error": t.get("error") or a.get("error") or "",
        # 新增：更详细的信息
        "tts_detail": t,
        "asr_detail": a,
        "recorder": {
            "ok": r.get("ok", False),
            "device": r.get("device", ""),
            "reason": r.get("reason", ""),
            "hint": r.get("hint", ""),
        },
    }


def list_voices() -> dict:
    """列出可用音色。"""
    return {
        "edge": [
            "zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural",
            "zh-CN-YunxiNeural", "zh-CN-YunyangNeural",
            "zh-CN-YunjianNeural", "zh-CN-liaoning-XiaobeiNeural",
            "zh-CN-shaanxi-XiaoniNeural",
            "zh-HK-HiuMaanNeural", "zh-TW-HsiaoChenNeural",
        ],
        "sapi": tts.list_sapi_voices(),
    }
