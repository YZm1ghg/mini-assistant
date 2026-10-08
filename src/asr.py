# -*- coding: utf-8 -*-
"""
语音识别（ASR）

把录到的音频转成文字。

两个引擎：
    ① **FunASR**（阿里，中文最准）      ← pip install funasr
    ② **faster-whisper**（OpenAI 开源） ← pip install faster-whisper

============================================================
关键坑：必须给**本地路径**，不能给模型名
============================================================
    `AutoModel(model="paraformer-zh")` 会触发**联网校验** ——
    去 modelscope/huggingface 查模型有没有更新。
    本机代理不转发这些域名 → SSL 错 → 重试 5 次
    → 总共卡 **34 秒**，然后失败。

    而模型其实**早就下好放本地了**。
    ✅ 所以必须先找到本地目录，直接传路径
       （查找逻辑在 find.py，递归搜 model.pt，不写死层级）

============================================================
输入格式
============================================================
    FunASR 要 16kHz 单声道 wav。
    录进来的可能是 44.1kHz —— 用自写的重采样转一下。
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import audio as A
from . import config

_lock = threading.Lock()
_engine = None            # 模型对象 或 False（表示失败）
_engine_name = ""
_engine_kind = ""
_last_error = ""


def _err(msg: str) -> None:
    global _last_error
    _last_error = msg
    try:
        p = config.DATA_DIR / "asr.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:                                  # noqa: BLE001
        pass


# ============================================================
#  环境准备（必须在 import 模型库之前）
# ============================================================
def _prepare_env() -> None:
    """关掉一切联网检查。

    ⚠ 这些**必须在 import funasr / faster_whisper 之前设**，
      设晚了不生效。
    """
    os.environ.setdefault("MODELSCOPE_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("FUNASR_DISABLE_UPDATE", "1")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy",
              "https_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)


# ============================================================
#  FunASR
# ============================================================
def _mem_ok(need_gb: float = 3.0) -> bool:
    """内存够不够加载一个大模型。

    ⚠⚠ 为什么需要这个检查（踩过）：
      FunASR 的模型 + PyTorch 运行时大概要 2.5~3 GB。
      内存紧张时（实测 4.6GB 可用）会抛 **MemoryError** ——
      而这个异常在 model 加载阶段抛出，代码很难优雅处理，
      而且**卡 33 秒**才失败。

      ✅ 提前查一下，内存不够就**直接跳过 FunASR 用 whisper**，
         不浪费那 33 秒。
    """
    try:
        import ctypes

        class _MEMSTAT(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        st = _MEMSTAT()
        st.dwLength = ctypes.sizeof(_MEMSTAT)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(
            ctypes.byref(st))
        avail = st.ullAvailPhys / 1024 ** 3
        return avail >= need_gb
    except Exception:                                  # noqa: BLE001
        return True                     # 查不到就不拦


def _get_funasr():
    global _engine, _engine_name, _engine_kind
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        # ⚠ 内存不够就别试了 —— 会卡 33 秒然后 MemoryError
        if not _mem_ok(3.0):
            _err("内存不足 3GB，跳过 FunASR")
            _engine = False
            return _engine
        _prepare_env()
        try:
            from funasr import AutoModel          # type: ignore
            from . import find
            local = find.funasr_model()
            src = str(local) if local else "paraformer-zh"
            _engine = AutoModel(model=src, disable_update=True,
                                device="cpu", disable_pbar=True)
            _engine_name = ("FunASR" + ("（本地）" if local
                                        else "（联网）"))
            _engine_kind = "funasr"
        except MemoryError:
            _err("FunASR 内存不足（已自动改用 whisper）")
            _engine = False
            _release_gc()
        except Exception as e:                         # noqa: BLE001
            _err(f"FunASR 加载失败：{type(e).__name__}: "
                 f"{str(e)[:100]}")
            _engine = False
    return _engine


def _release_gc() -> None:
    """加载失败后回收一下内存，免得影响后面的 whisper。"""
    try:
        import gc
        gc.collect()
    except Exception:                                  # noqa: BLE001
        pass


# ============================================================
#  faster-whisper
# ============================================================
def _get_whisper():
    global _engine, _engine_name, _engine_kind
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        _prepare_env()
        try:
            from faster_whisper import WhisperModel  # type: ignore
            from . import find
            local = find.whisper_model()
            _engine = WhisperModel(
                str(local) if local else "tiny",
                device="cpu", compute_type="int8")
            _engine_name = ("faster-whisper"
                            + ("（本地）" if local else "（联网）"))
            _engine_kind = "whisper"
        except Exception as e:                         # noqa: BLE001
            _err(f"whisper 加载失败：{type(e).__name__}: "
                 f"{str(e)[:100]}")
            _engine = False
    return _engine


# ============================================================
#  识别
# ============================================================
@dataclass
class Result:
    ok: bool
    text: str = ""
    backend: str = ""
    elapsed: float = 0.0
    error: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "text": self.text,
                "backend": self.backend,
                "elapsed": round(self.elapsed, 2),
                "error": self.error}


def transcribe_file(path: str, prefer: str = "") -> Result:
    """识别一个音频文件。

    ⚠ 不是 16kHz 单声道的话会**自动转换**。
    """
    t0 = time.time()
    p = Path(path)
    if not p.exists():
        return Result(False, error="文件不存在")

    cfg = config.load()
    engine = prefer or cfg.get("asr_engine") or "funasr"
    if engine == "off":
        return Result(False, error="识别已关")

    # ---- 转成 16k 单声道 ----
    tmp = None
    try:
        au = A.read_wav(str(p))
        if au is not None:
            if au.rate != 16000:
                au = A.resample(au, 16000)
            tmp = Path(tempfile.gettempdir()) / (
                "mini_asr_%d.wav" % os.getpid())
            A.write_wav(tmp, au)
            use = str(tmp)
        else:
            use = str(p)          # 不是 wav，直接交给引擎碰运气
    except Exception:                                  # noqa: BLE001
        use = str(p)

    order = ([engine] if engine in ("funasr", "whisper")
             else ["funasr", "whisper"])

    for kind in order:
        if kind == "funasr":
            m = _get_funasr()
            if not m:
                continue
            try:
                res = m.generate(input=use, batch_size_s=300)
                text = ""
                if res:
                    text = (res[0].get("text") or "").replace(
                        " ", "").strip()
                if text:
                    _cleanup(tmp)
                    return Result(True, text, _engine_name,
                                  time.time() - t0)
            except Exception as e:                     # noqa: BLE001
                _err(f"FunASR 识别失败：{str(e)[:100]}")
        else:
            m = _get_whisper()
            if not m:
                continue
            try:
                segs, _info = m.transcribe(use, language="zh")
                text = "".join(s.text for s in segs).strip()
                if text:
                    _cleanup(tmp)
                    return Result(True, text, _engine_name,
                                  time.time() - t0)
            except Exception as e:                     # noqa: BLE001
                _err(f"whisper 识别失败：{str(e)[:100]}")

    _cleanup(tmp)
    return Result(False, error=_last_error or "没有可用的识别引擎")


def _cleanup(tmp) -> None:
    try:
        if tmp and Path(tmp).exists():
            Path(tmp).unlink()
    except Exception:                                  # noqa: BLE001
        pass


def transcribe_audio(au: Optional[A.Audio]) -> Result:
    """识别一段内存里的音频。"""
    if au is None or not au.samples:
        return Result(False, error="没有音频")
    tmp = Path(tempfile.gettempdir()) / (
        "mini_asr_mem_%d.wav" % os.getpid())
    a = au if au.rate == 16000 else A.resample(au, 16000)
    if not A.write_wav(tmp, a):
        return Result(False, error="写临时文件失败")
    try:
        return transcribe_file(str(tmp))
    finally:
        _cleanup(tmp)


_avail_cache: dict = {}
_avail_at: float = 0.0
_AVAIL_TTL = 300.0


def available() -> dict:
    """哪些引擎能用。

    ⚠⚠ **绝对不能真的去 import**（踩过）：
      原来写的是 `__import__("funasr")` 来检测是否安装 ——
      但 funasr 会连带加载 **PyTorch**，那要 **30 秒**！
      而 /api/state 每次都会调 status() → available()，
      于是整个界面卡 30 秒。

      ✅ 改成查**包在不在**（用 importlib.util.find_spec），
         它只找路径不执行模块代码，**毫秒级**。
         而且结果缓存 5 分钟。
    """
    global _avail_cache, _avail_at
    now = time.time()
    if _avail_cache and now - _avail_at < _AVAIL_TTL:
        return _avail_cache

    import importlib.util

    def _installed(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    out = {
        "funasr": _installed("funasr"),
        "whisper": _installed("faster_whisper"),
    }
    res = {"ok": any(out.values()), "engines": out,
           "loaded": _engine_name or "未加载"}
    _avail_cache = res
    _avail_at = now
    return res


def status() -> dict:
    a = available()
    return {
        "loaded": _engine_name or "未加载",
        "available": a["engines"],
        "ok": a["ok"],
        "error": _last_error,
    }
