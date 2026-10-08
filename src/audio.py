# -*- coding: utf-8 -*-
"""
音频 —— 自己实现，不依赖第三方

============================================================
为什么自己写
============================================================
    原来用了三个库：
        soundfile    读 wav / mp3 → 数组
        numpy        音频数组运算
        sounddevice  录音

    这三个都是「能内置就内置」的典型：
        · 音频样本就是一串 int16 —— 用标准库 `array` 就行
        · 读 wav 格式很简单 —— 标准库 `wave` 直接支持
        · 播放用 Windows 自带的 MCI（winmm）
        · 录音用 Windows 自带的 waveIn

    **砍掉三个依赖，代码只多 ~400 行。**

============================================================
支持什么
============================================================
    ✓ wav 读写（PCM 8/16/24/32 位，单/双声道）
    ✓ mp3 转 wav（用 Windows 自带的 Media Foundation，
                  或者系统里的 ffmpeg，都没有就报错）
    ✓ 播放（MCI，唯一在 Windows 上没电流声的方式）
    ✓ 录音（waveIn）

    ✗ 不支持 ogg / flac（用不上）
"""
from __future__ import annotations

import array
import ctypes
import ctypes.wintypes as wt
import os
import struct
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Optional

# ============================================================
#  音频数据结构
# ============================================================
# 统一用 **单声道 float32** 在内存里表示（-1.0 ~ 1.0）
# 这样处理起来简单，写出去时再转成需要的格式。


class Audio:
    """一段音频。

    samples: array('f')，范围 -1.0 ~ 1.0
    rate:    采样率（Hz）
    channels: 声道数（内存里一般固定 1）
    """

    __slots__ = ("samples", "rate", "channels")

    def __init__(self, samples, rate: int = 24000,
                 channels: int = 1):
        if not isinstance(samples, array.array):
            samples = array.array("f", samples)
        self.samples = samples
        self.rate = int(rate)
        self.channels = int(channels)

    @property
    def seconds(self) -> float:
        if not self.rate or not self.channels:
            return 0.0
        return len(self.samples) / self.rate / self.channels

    def __len__(self) -> int:
        return len(self.samples)


# ============================================================
#  float ↔ int16
# ============================================================
def _f2i16(samples: array.array) -> bytes:
    """float(-1~1) → int16 小端字节。"""
    # ⚠ 先夹到 [-1, 1] —— 超出会溢出成噪声
    out = array.array("h", bytes(2 * len(samples)))
    for i, x in enumerate(samples):
        if x > 1.0:
            x = 1.0
        elif x < -1.0:
            x = -1.0
        out[i] = int(x * 32767)
    return out.tobytes()


def _i16_2f(data: bytes) -> array.array:
    """int16 小端字节 → float(-1~1)。"""
    a = array.array("h")
    a.frombytes(data[:len(data) // 2 * 2])
    return array.array("f", [v / 32768.0 for v in a])


# ============================================================
#  wav 读写（标准库 wave）
# ============================================================
def read_wav(path) -> Optional[Audio]:
    """读 wav。支持 8/16/24/32 位。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with wave.open(str(p), "rb") as w:
            ch = w.getnchannels()
            width = w.getsampwidth()
            rate = w.getframerate()
            n = w.getnframes()
            raw = w.readframes(n)
    except Exception:                                  # noqa: BLE001
        return None

    if width == 2:
        f = _i16_2f(raw)
    elif width == 1:
        # 8 位是无符号的，中心在 128
        f = array.array(
            "f", [(b - 128) / 128.0 for b in raw])
    elif width == 3:
        # 24 位小端有符号
        vals = []
        for i in range(0, len(raw) - 2, 3):
            v = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
            if v & 0x800000:
                v -= 0x1000000
            vals.append(v / 8388608.0)
        f = array.array("f", vals)
    elif width == 4:
        a = array.array("i")
        a.frombytes(raw[:len(raw) // 4 * 4])
        f = array.array("f", [v / 2147483648.0 for v in a])
    else:
        return None

    # 多声道 → 混成单声道（简单平均）
    if ch > 1:
        mono = array.array("f", bytes(4 * (len(f) // ch)))
        for i in range(len(mono)):
            mono[i] = sum(f[i * ch:(i + 1) * ch]) / ch
        f = mono
    return Audio(f, rate)


def write_wav(path, audio: Audio) -> bool:
    """写 wav（16 位 PCM）。"""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = _f2i16(audio.samples)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(audio.channels)
            w.setsampwidth(2)
            w.setframerate(audio.rate)
            w.writeframes(data)
        return True
    except Exception:                                  # noqa: BLE001
        return False


# ============================================================
#  mp3 → wav（Windows Media Foundation）
# ============================================================
def _mf_available() -> bool:
    try:
        ctypes.windll.mfplat.MFStartup(0x00020070, 0)
        ctypes.windll.mfplat.MFShutdown()
        return True
    except Exception:                                  # noqa: BLE001
        return False


def mp3_to_wav(mp3_bytes: bytes, out_path) -> bool:
    """把 mp3 数据转成 wav 文件。

    ⚠ 三条路，按优先级：
      ① 系统里的 ffmpeg（最快最稳）
      ② Windows Media Foundation（系统自带，但调起来麻烦）
      ③ 都没有 → 失败

      ✅ 实际主要靠 ffmpeg。Windows 上用 winget/包管理器
         装一个，或者 node 的 ffmpeg-static。
    """
    # ---- ① ffmpeg ----
    exe = _find_ffmpeg()
    if exe:
        tmp = None
        try:
            tmp = Path(tempfile.gettempdir()) / (
                "mini_mp3_%d.mp3" % (os.getpid()
                                     ^ int(time.time() * 1000)))
            tmp.write_bytes(mp3_bytes)
            r = subprocess.run(
                [exe, "-y", "-loglevel", "error", "-i", str(tmp),
                 "-ar", "24000", "-ac", "1", "-f", "wav",
                 str(out_path)],
                capture_output=True, timeout=120,
                creationflags=getattr(subprocess,
                                      "CREATE_NO_WINDOW", 0))
            return r.returncode == 0 and Path(out_path).exists()
        except Exception:                              # noqa: BLE001
            return False
        finally:
            try:
                if tmp and tmp.exists():
                    tmp.unlink()
            except Exception:                          # noqa: BLE001
                pass

    # ---- ② Media Foundation（略，复杂且不稳）----
    # 真需要时再实现。现在没 ffmpeg 就明确报错，
    # 好过静默失败让用户以为程序坏了。
    return False


def _find_ffmpeg() -> Optional[str]:
    """找 ffmpeg。"""
    import shutil
    v = os.environ.get("MINI_FFMPEG") or ""
    if v and Path(v).exists():
        return v
    p = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if p:
        return p
    for c in (r"C:\ffmpeg\bin\ffmpeg.exe",
              r"D:\ffmpeg\bin\ffmpeg.exe"):
        if Path(c).exists():
            return c
    # node 的 ffmpeg-static
    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        p = (Path(appdata) / "npm" / "node_modules"
             / "ffmpeg-static" / "ffmpeg.exe")
        if p.exists():
            return str(p)
    return None


# ============================================================
#  播放（MCI）
# ============================================================
_mci_lock = threading.Lock()
_playing = False


def play(audio: Audio) -> bool:
    """播放一段音频（同步，播完才返回）。

    ⚠ 为什么用 MCI：
      实测这台机器上 sounddevice 的 WASAPI/MME 都有电流声，
      只有 winmm 的 MCI 干净。
    ⚠ 临时文件名必须纯 ASCII ——
      MCI 对中文/空格路径要转义，很容易出错。
    """
    global _playing
    if os.name != "nt":
        return False
    tmp = None
    try:
        tmp = Path(tempfile.gettempdir()) / (
            "mini_play_%d_%d.wav"
            % (os.getpid(), int(time.time() * 1000) % 1000000))
        if not write_wav(tmp, audio):
            return False

        winmm = ctypes.windll.winmm
        alias = "miniplay%d" % os.getpid()
        buf = ctypes.create_unicode_buffer(512)
        ok = False
        with _mci_lock:
            _playing = True
            try:
                r = winmm.mciSendStringW(
                    'open "%s" type waveaudio alias %s'
                    % (tmp, alias), buf, 512, 0)
                if r == 0:
                    winmm.mciSendStringW(
                        "set %s time format milliseconds" % alias,
                        buf, 512, 0)
                    winmm.mciSendStringW("play %s wait" % alias,
                                         buf, 512, 0)
                    ok = True
            finally:
                _playing = False
                try:
                    winmm.mciSendStringW("close %s" % alias,
                                         buf, 512, 0)
                except Exception:                      # noqa: BLE001
                    pass
        return ok
    except Exception:                                  # noqa: BLE001
        return False
    finally:
        try:
            if tmp and tmp.exists():
                tmp.unlink()
        except Exception:                              # noqa: BLE001
            pass


def stop_playback() -> None:
    """打断正在播的。"""
    try:
        winmm = ctypes.windll.winmm
        buf = ctypes.create_unicode_buffer(512)
        winmm.mciSendStringW("close miniplay%d" % os.getpid(),
                             buf, 512, 0)
    except Exception:                                  # noqa: BLE001
        pass


def is_playing() -> bool:
    return _playing


# ============================================================
#  录音（waveIn）
# ============================================================
class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wt.WORD),
                ("nChannels", wt.WORD),
                ("nSamplesPerSec", wt.DWORD),
                ("nAvgBytesPerSec", wt.DWORD),
                ("nBlockAlign", wt.WORD),
                ("wBitsPerSample", wt.WORD),
                ("cbSize", wt.WORD)]


class _WAVEHDR(ctypes.Structure):
    pass


_WAVEHDR._fields_ = [
    # ⚠ lpData 必须是 c_void_p 而不是 c_char_p ——
    #   c_char_p 在 ctypes 里会被当成"以 null 结尾的字符串"处理，
    #   传二进制缓冲区进去会报 incompatible types。
    ("lpData", ctypes.c_void_p),
    ("dwBufferLength", wt.DWORD),
    ("dwBytesRecorded", wt.DWORD),
    ("dwUser", ctypes.c_void_p),
    ("dwFlags", wt.DWORD),
    ("dwLoops", wt.DWORD),
    ("lpNext", ctypes.c_void_p),
    ("reserved", ctypes.c_void_p),
]

WAVE_FORMAT_PCM = 1
WAVE_MAPPER = 0xFFFFFFFF
CALLBACK_NULL = 0
CALLBACK_EVENT = 0x00050000
WAVE_HEADER_DONE = 0x00000001
WAVE_HEADER_PREPARED = 0x00000002


def record(seconds: float = 5.0, rate: int = 16000,
           device: int = -1) -> Optional[Audio]:
    """录一段音。

    录完返回 Audio，失败返回 None。

    ⚠⚠ 三个坑，全踩过：

    ① **必须显式声明 argtypes**
       ctypes 默认把指针当 int 传，64 位系统上指针 8 字节、
       int 4 字节 → 高位截断 → 传野指针进去。
       waveInOpen 不检查，返回成功；但后面 prepare 静默失败。

    ② **必须用 CALLBACK_EVENT，不能用 CALLBACK_NULL**
       waveIn 是**异步** API。用 CALLBACK_NULL 的话，
       「录满缓冲 → 设 WHDR_DONE 标志」这件事**不会自动发生**，
       只能靠轮询 dwBytesRecorded ——
       而那个值一直是 0，缓冲全是空字节。
       表现：录了 5 秒，拿到 128000 个 0。
       ✅ 传一个 CreateEvent 的句柄，然后 WaitForSingleObject
          等它 —— 这才是官方用法。

    ③ **hdr.lpData 要用 c_void_p**
       写成 c_char_p 的话，ctypes 会当"以 null 结尾的字符串"，
       传二进制缓冲会报 incompatible types。
    """
    if os.name != "nt":
        return None
    winmm = ctypes.windll.winmm
    k32 = ctypes.windll.kernel32

    # ---- 显式声明签名（关键，见上面 ①）----
    winmm.waveInOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
        ctypes.POINTER(_WAVEFORMATEX), ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_uint]
    winmm.waveInOpen.restype = ctypes.c_uint
    winmm.waveInPrepareHeader.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), ctypes.c_uint]
    winmm.waveInPrepareHeader.restype = ctypes.c_uint
    winmm.waveInUnprepareHeader.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), ctypes.c_uint]
    winmm.waveInUnprepareHeader.restype = ctypes.c_uint
    winmm.waveInStart.argtypes = [ctypes.c_void_p]
    winmm.waveInStart.restype = ctypes.c_uint
    winmm.waveInStop.argtypes = [ctypes.c_void_p]
    winmm.waveInStop.restype = ctypes.c_uint
    winmm.waveInClose.argtypes = [ctypes.c_void_p]
    winmm.waveInClose.restype = ctypes.c_uint
    winmm.waveInReset.argtypes = [ctypes.c_void_p]
    winmm.waveInReset.restype = ctypes.c_uint

    k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_wchar_p]
    k32.CreateEventW.restype = ctypes.c_void_p
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
    k32.WaitForSingleObject.restype = wt.DWORD
    k32.CloseHandle.argtypes = [ctypes.c_void_p]

    fmt = _WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_PCM
    fmt.nChannels = 1
    fmt.nSamplesPerSec = int(rate)
    fmt.wBitsPerSample = 16
    fmt.nBlockAlign = 2
    fmt.nAvgBytesPerSec = int(rate) * 2
    fmt.cbSize = 0

    total = int(rate * seconds) * 2
    buf = ctypes.create_string_buffer(total)

    hdr = _WAVEHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
    hdr.dwBufferLength = total
    hdr.dwBytesRecorded = 0
    hdr.dwFlags = 0
    hdr.dwLoops = 0
    hdr.lpNext = None
    hdr.reserved = None

    hwi = ctypes.c_void_p()
    hev = k32.CreateEventW(None, 0, 0, None)           # 手写事件
    if not hev:
        return None
    dev = WAVE_MAPPER if device < 0 else int(device)

    try:
        # ---- 打开（带事件回调）----
        r = winmm.waveInOpen(
            ctypes.byref(hwi), dev, ctypes.byref(fmt),
            ctypes.c_void_p(hev), None,
            CALLBACK_EVENT)
        if r != 0 or not hwi.value:
            return None

        r = winmm.waveInPrepareHeader(hwi, ctypes.byref(hdr),
                                      ctypes.sizeof(hdr))
        if r != 0:
            return None

        r = winmm.waveInStart(hwi)
        if r != 0:
            return None

        # ---- 等事件（而不是轮询）----
        wait_ms = int((seconds + 3) * 1000)
        k32.WaitForSingleObject(hev, wait_ms)

        winmm.waveInStop(hwi)
        winmm.waveInReset(hwi)              # ⚠ 必须 reset，否则
        winmm.waveInUnprepareHeader(       #   unprepare 会失败
            hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))

        got = int(hdr.dwBytesRecorded or 0)
        if got <= 0:
            # 没录到任何数据 —— 兜底用整个缓冲（可能是设备没填充计数）
            if hdr.dwFlags & WAVE_HEADER_DONE:
                got = total
            else:
                return None
        f = _i16_2f(buf.raw[:got])
        peak = max((abs(x) for x in f[:rate * 2]), default=0.0)
        if peak < 0.003:
            return None                    # 麦克风没声 / 被静音
        return Audio(f, rate)
    except Exception:                                  # noqa: BLE001
        return None
    finally:
        try:
            winmm.waveInClose(hwi)
        except Exception:                              # noqa: BLE001
            pass
        try:
            k32.CloseHandle(hev)
        except Exception:                              # noqa: BLE001
            pass


class _WAVEINCAPSW(ctypes.Structure):
    """录音设备能力结构。

    ⚠⚠ 大小必须是 **80 字节**（踩过）：
        wMid(2) + wPid(2) + vDriverVersion(4)
        + szPname[32] 宽字符(64) + dwFormats(4)
        + wChannels(2) + wReserved1(2) = 80

      原来图省事用了 create_string_buffer(64) —— 太小了，
      waveInGetDevCapsW 直接失败返回非 0，
      于是"设备数 0 个"（其实系统里有 2 个麦克风）。
    """
    _fields_ = [
        ("wMid", wt.WORD),
        ("wPid", wt.WORD),
        ("vDriverVersion", wt.DWORD),
        ("szPname", wt.WCHAR * 32),
        ("dwFormats", wt.DWORD),
        ("wChannels", wt.WORD),
        ("wReserved1", wt.WORD),
    ]


def list_input_devices() -> list:
    """列出录音设备。

    ⚠ 不用 sounddevice —— Win32 的 waveInGetNumDevs 就够。
    """
    if os.name != "nt":
        return []
    try:
        winmm = ctypes.windll.winmm
        n = winmm.waveInGetNumDevs()
        out = []
        for i in range(n):
            caps = _WAVEINCAPSW()
            r = winmm.waveInGetDevCapsW(
                i, ctypes.byref(caps), ctypes.sizeof(caps))
            if r == 0:
                out.append({
                    "index": i,
                    "name": (caps.szPname or "").strip("\x00"),
                    "channels": caps.wChannels,
                })
        return out
    except Exception:                                  # noqa: BLE001
        return []


def resample(audio: Audio, new_rate: int) -> Audio:
    """重采样到新采样率。

    ⚠ 用线性插值而不是"丢点/补点" ——
      后者会有明显的金属音。
      语音场景下线性插值够用了（专业场景才需要 sinc）。
    """
    if audio.rate == new_rate or not audio.samples:
        return audio
    src = audio.samples
    ratio = new_rate / float(audio.rate)
    n = int(len(src) * ratio)
    out = array.array("f", bytes(4 * n))
    for i in range(n):
        pos = i / ratio
        i0 = int(pos)
        i1 = min(i0 + 1, len(src) - 1)
        frac = pos - i0
        if i0 >= len(src):
            break
        out[i] = src[i0] * (1 - frac) + src[i1] * frac
    return Audio(out, new_rate)


def speed(audio: Audio, factor: float) -> Audio:
    """变速。factor > 1 变快（音调也变高）。

    ⚠ 这是"改采样率"式的变速，会变调。
      要不变调得用相位声码器，那太重了 ——
      语音场景变调一点点反而更自然。
    """
    if factor <= 0 or not audio.samples:
        return audio
    return Audio(audio.samples, int(audio.rate * factor))


def trim_silence(audio: Audio, threshold: float = 0.01
                 ) -> Audio:
    """掐掉头尾的静音。"""
    s = audio.samples
    n = len(s)
    a, b = 0, n
    while a < n and abs(s[a]) < threshold:
        a += 1
    while b > a and abs(s[b - 1]) < threshold:
        b -= 1
    if a >= b:
        return audio
    # 前后各留 50ms，免得把字头切掉
    pad = int(audio.rate * 0.05)
    a = max(0, a - pad)
    b = min(n, b + pad)
    return Audio(s[a:b], audio.rate)


def concat(items: list) -> Optional[Audio]:
    """拼几段音频。"""
    items = [x for x in items if x and x.samples]
    if not items:
        return None
    rate = items[0].rate
    out = array.array("f")
    for a in items:
        if a.rate != rate:
            a = resample(a, rate)
        out.extend(a.samples)
    return Audio(out, rate)
