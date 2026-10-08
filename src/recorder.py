# -*- coding: utf-8 -*-
"""
录音 —— 结论：Windows 上必须走 WASAPI

============================================================
实测结论（18 种组合全部失败）
============================================================
    我用 Win32 的老录音接口 `waveIn` 试了：
        3 个设备 × 6 种格式（1/2 声道 × 8k/16k/44.1k/48k）
        共 18 种组合

    结果**全部 `dwBytesRecorded = 0`** —— 一个字节都没收到。

    但同一台机器上 `sounddevice`（底层是 PortAudio，
    走 WASAPI）能正常录到数据。

    原因：**现代 Windows 音频驱动已经不支持 waveIn 了。**
    微软从 Vista 起推 WASAPI，Realtek 这类新的驱动栈
    干脆就不实现老的 waveIn MME 接口 ——
    `waveInOpen` 会返回成功（它不检查驱动能力），
    但 `waveInStart` 之后拿不到任何数据。

============================================================
这意味着什么
============================================================
    ❌ **录音去不掉 sounddevice**（或者等价的 WASAPI 封装）

    其他能砍的都砍了：
        soundfile  → 自己用标准库 wave + array 实现  ✅
        numpy      → 自己用标准库 array 实现          ✅
        sounddevice → 去不掉，WASAPI 绕不过去        ❌

    ✅ 所以策略是：**录音做成可选**
       · 装了 sounddevice → 用它的 WASAPI 录音
       · 没装 → 录音功能关掉，界面显示"未启用"
         但打字聊天、朗读、其他功能全都不受影响

============================================================
为什么不自己写 WASAPI
============================================================
    理论上可以用 ctypes 直接调 COM 接口：
        IMMDeviceEnumerator → IAudioClient → IAudioCaptureClient
    大概要写 800~1000 行 COM 胶水代码，而且：
        · COM 接口的 vtable 调用很容易写错
        · 音频回调线程的同步很容易出 bug
        · 不同驱动的 format negotiation 差异很大

    **投入产出比太低。** sounddevice 是个成熟的封装，
    为了"少一个依赖"重写 1000 行易错的 COM 代码不划算。

    ⚠ 所以这里明确写清楚：**录音需要 sounddevice**，
      不是"忘了改"，是"权衡后决定不改"。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading
from typing import Optional

# 复用自写的音频数据结构
from .audio import Audio, resample


# ============================================================
#  可用性检查
# ============================================================
def _sd():
    """尝试导入 sounddevice。"""
    try:
        import sounddevice as sd                # type: ignore
        return sd
    except ImportError:
        return None


def available() -> dict:
    """录音能不能用。"""
    sd = _sd()
    if sd is None:
        return {
            "ok": False,
            "reason": "没装 sounddevice",
            "hint": "pip install sounddevice",
            "note": "不装也能用 —— 只是不能说话输入，"
                    "打字聊天不受影响",
        }
    try:
        dev = sd.query_devices(kind="input")
        return {"ok": True, "device": dev.get("name", ""),
                "rate": int(dev.get("default_samplerate") or 16000)}
    except Exception as e:                             # noqa: BLE001
        return {"ok": False, "reason": f"没有可用录音设备：{e}"}


def list_input_devices() -> list:
    """列出录音设备。"""
    sd = _sd()
    if sd is None:
        return []
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if (d.get("max_input_channels") or 0) > 0:
                out.append({
                    "index": i,
                    "name": d.get("name") or f"设备{i}",
                    "channels": d.get("max_input_channels"),
                    "rate": int(d.get("default_samplerate") or 0),
                })
    except Exception:                                  # noqa: BLE001
        pass
    return out


# ============================================================
#  录音
# ============================================================
def record(seconds: float = 5.0, rate: int = 16000,
           device=None) -> Optional[Audio]:
    """录一段音。

    ⚠ 走 sounddevice 的 WASAPI（waveIn 在老接口上收不到数据，
      详见模块文档）。
    """
    sd = _sd()
    if sd is None:
        return None
    frames = int(rate * max(1.0, min(60.0, seconds)))
    try:
        data = sd.rec(frames, samplerate=rate, channels=1,
                      dtype="float32", device=device)
        sd.wait()
    except Exception:                                  # noqa: BLE001
        return None

    # sounddevice 返回的是有 .reshape 的对象（numpy 或类似）
    try:
        samples = [float(x) for x in data.reshape(-1)]
    except Exception:                                  # noqa: BLE001
        try:
            samples = [float(x[0]) for x in data]
        except Exception:                              # noqa: BLE001
            return None

    au = Audio(samples, rate)
    # 检查有没有真录到声音
    peak = max((abs(x) for x in samples[:rate * 2]), default=0.0)
    if peak < 0.0005:
        return None
    return au


def start_async(seconds: float = 5.0, rate: int = 16000,
                on_done=None) -> dict:
    """后台录一段，录完调 on_done(Audio 或 None)。"""
    def _job() -> None:
        au = record(seconds, rate)
        if on_done:
            try:
                on_done(au)
            except Exception:                          # noqa: BLE001
                pass
    threading.Thread(target=_job, daemon=True,
                     name="mini-record").start()
    return {"ok": True, "seconds": seconds}


def status() -> dict:
    a = available()
    return {
        "engine": "sounddevice (WASAPI)",
        "available": a.get("ok", False),
        "device": a.get("device", ""),
        "reason": a.get("reason", ""),
        "hint": a.get("hint", ""),
        "devices": len(list_input_devices()),
    }
