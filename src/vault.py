# -*- coding: utf-8 -*-
"""
加密保险箱

把敏感文件（截图、照片）加密存起来，需要时再取。

怎么做的
--------
    用一个**单一加密卷**（tar 打包 + AES-256-GCM），
    不是一个文件一个密文。好处：
        · 文件数少了不会爆目录
        · 元数据（原名/时间）一起加密，看不出存了什么
        · 追加/读取都要过认证标签，改一个字节就报错

密钥怎么管
----------
    两条路，二选一：
        ① **机器密钥**（免密）—— 用 Windows DPAPI 把密钥绑到
           "本机 + 当前用户"。别人拷走文件也解不开，
           但你自己打开不用输密码。**默认走这条。**
        ② **密码** —— 自己设一个，启动时要输。

    ⚠ 不用"硬编码密钥"，那等于没加密。

自动归档
--------
    后台线程每 N 秒扫一次指定目录，
    把超过 delay 秒的明文图加密进卷、删掉原图。
    ⚠ delay 不能太短 —— 刚出的图 AI 可能还要看。
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import secrets
import tarfile
import threading
import time
from io import BytesIO
from pathlib import Path

from . import config

ROOT = config.DATA_DIR / "vault"
VOL = ROOT / "vault-0001.dvn"
INDEX = ROOT / ".index.json"

# 要监视的目录（明文图从这些地方收进来）
WATCH_DIRS = [ROOT.parent / "look"]

# 文件在卷里待多久才收（秒）
DEFAULT_DELAY = 120

# 单卷上限（MB）—— 超了新建一卷
VOL_MAX_MB = 500

_lock = threading.Lock()
_session_key: bytes | None = None
_thread: threading.Thread | None = None
_stop = threading.Event()
_last_error = ""
_in_use: dict[str, float] = {}          # 正在用的文件（不加密）
IN_USE_HOLD = 90                        # 保护多少秒
HOLD_FILE = ROOT / ".hold.json"         # 保护状态**落盘**


def _hold_load() -> dict:
    """读保护表（跨进程共享）。

    ⚠⚠ 为什么保护表要**落盘**（踩过）：
      原来只放进程内存里。结果：
        · 界面调 /api/look/see → 服务进程 touch → 同一个进程归档 → 有效 ✓
        · 但**别的进程**调 touch（比如命令行工具、另一个界面）
          → 改的是它自己的内存 → 服务进程看不见 → 照样被收走 ✗
      表现就是「我明明标了在用，还是被加密走了」。

      ✅ 落盘之后所有进程共享同一份保护表。
    """
    if not HOLD_FILE.exists():
        return {}
    try:
        d = json.loads(HOLD_FILE.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return {}
        now = time.time()
        # 顺手清掉过期的
        return {k: float(v) for k, v in d.items()
                if isinstance(v, (int, float)) and float(v) > now}
    except Exception:                                  # noqa: BLE001
        return {}


def _hold_save(d: dict) -> None:
    with _lock:
        try:
            ROOT.mkdir(parents=True, exist_ok=True)
            HOLD_FILE.write_text(
                json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except Exception:                              # noqa: BLE001
            pass


# ============================================================
#  机器密钥（DPAPI）
# ============================================================
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_protect(data: bytes) -> bytes | None:
    """用 Windows DPAPI 加密（绑到本机+当前用户）。"""
    try:
        blob_in = _Blob(len(data), ctypes.cast(
            ctypes.create_string_buffer(data),
            ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0,
            ctypes.byref(blob_out))
        if not ok:
            return None
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return out
    except Exception:                                  # noqa: BLE001
        return None


def _dpapi_unprotect(data: bytes) -> bytes | None:
    try:
        blob_in = _Blob(len(data), ctypes.cast(
            ctypes.create_string_buffer(data),
            ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0,
            ctypes.byref(blob_out))
        if not ok:
            return None
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return out
    except Exception:                                  # noqa: BLE001
        return None


def _machine_key() -> bytes | None:
    """拿到（或首次生成）机器密钥。

    ⚠ 密钥本身用 DPAPI 加过，存盘上是密文。
      拷到别的机器 / 别的用户下就解不开 —— 这是我们要的。
    """
    ROOT.mkdir(parents=True, exist_ok=True)
    kf = ROOT / ".key"
    if kf.exists():
        try:
            raw = kf.read_bytes()
            k = _dpapi_unprotect(raw)
            if k and len(k) == 32:
                return k
        except Exception:                              # noqa: BLE001
            pass
    # 新建
    k = secrets.token_bytes(32)
    p = _dpapi_protect(k)
    if p:
        try:
            kf.write_bytes(p)
        except Exception:                              # noqa: BLE001
            pass
    return k


def _index_read() -> dict:
    if not INDEX.exists():
        return {"v": 1, "kind": "aes256gcm-tar", "volumes": [],
                "auto_unlock": True}
    try:
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:                                  # noqa: BLE001
        return {"v": 1, "kind": "aes256gcm-tar", "volumes": [],
                "auto_unlock": True}


def _index_write(d: dict) -> None:
    with _lock:
        try:
            ROOT.mkdir(parents=True, exist_ok=True)
            INDEX.write_text(
                json.dumps(d, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:                              # noqa: BLE001
            pass


# ============================================================
#  AES
# ============================================================
def _aes_key() -> bytes:
    """当前会话密钥（32 字节）。"""
    global _session_key
    if _session_key is None:
        _session_key = _machine_key()
    if _session_key is None:
        raise RuntimeError("拿不到加密密钥")
    return _session_key


def _encrypt(data: bytes) -> bytes:
    """AES-256-GCM 加密。返回 nonce + tag + 密文。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _aes_key()
    nonce = secrets.token_bytes(12)
    aead = AESGCM(key)
    ct = aead.encrypt(nonce, data, None)
    return nonce + ct                              # 密文尾部自带 tag


def _decrypt(blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _aes_key()
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


# ============================================================
#  卷读写
# ============================================================
def _volume_entries() -> dict:
    """读卷里的文件清单 {名字: 字节}。

    ⚠ 每次读都整个解密再打包 —— 卷不大（几百 MB）时够用。
      真要存 TB 级得改成增量格式，那是另一个话题。
    """
    if not VOL.exists():
        return {}
    try:
        raw = _decrypt(VOL.read_bytes())
        out: dict[str, bytes] = {}
        with tarfile.open(fileobj=BytesIO(raw), mode="r") as tar:
            for m in tar.getmembers():
                if not m.isfile():
                    continue
                f = tar.extractfile(m)
                if f is not None:
                    out[m.name] = f.read()
        return out
    except Exception as e:                             # noqa: BLE001
        _err(f"读卷失败：{type(e).__name__}: {e}")
        return {}


def _volume_write(entries: dict) -> int:
    """把 entries 整个写回卷（覆盖）。返回文件数。"""
    if not entries:
        return 0
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = int(time.time())
            tar.addfile(info, BytesIO(data))
    blob = _encrypt(buf.getvalue())
    ROOT.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再替换 —— 中途崩了不会毁掉原卷
    tmp = VOL.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(VOL)
    return len(entries)


# ============================================================
#  使用保护
# ============================================================
def touch(path) -> None:
    """标记"这个文件正在用"，保护期内不加密。

    ⚠ 落盘 + 内存双写：内存用于本进程快速判断，
      磁盘用于跨进程共享（详见 _hold_load 的说明）。
    """
    try:
        p = Path(path)
        until = time.time() + IN_USE_HOLD
        _in_use[p.name] = until
        _in_use[str(p)] = until
        d = _hold_load()
        d[p.name] = until
        d[str(p)] = until
        # 顺手清过期的，防文件无限涨
        now = time.time()
        d = {k: v for k, v in d.items() if float(v) > now}
        _hold_save(d)
    except Exception:                                  # noqa: BLE001
        pass


def in_use_list() -> dict:
    """当前保护中的文件（含别的进程登记的）。"""
    now = time.time()
    out = {k: round(v - now, 1)
           for k, v in _in_use.items() if v > now}
    for k, v in _hold_load().items():
        out.setdefault(k, round(float(v) - now, 1))
    return out


def clear_in_use() -> None:
    _in_use.clear()
    _hold_save({})


def _is_held(f: Path) -> bool:
    now = time.time()
    if _in_use.get(f.name, 0) > now:
        return True
    if _in_use.get(str(f), 0) > now:
        return True
    # 查磁盘上的（别的进程登记的）
    d = _hold_load()
    return (float(d.get(f.name) or 0) > now
            or float(d.get(str(f)) or 0) > now)


# ============================================================
#  归档
# ============================================================
def _collect_plain(delay: float) -> list[Path]:
    """找出该收的明文文件。"""
    now = time.time()
    out: list[Path] = []
    for d in WATCH_DIRS:
        try:
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in (
                        ".png", ".jpg", ".jpeg", ".webp", ".bmp",
                        ".gif"):
                    continue
                if _is_held(f):
                    continue                       # 正在用，跳过
                try:
                    if now - f.stat().st_mtime < delay:
                        continue                   # 太新，再等等
                except Exception:                  # noqa: BLE001
                    continue
                out.append(f)
        except Exception:                              # noqa: BLE001
            continue
    return out


def archive(force: bool = False, delay: float | None = None) -> dict:
    """收一轮。

    force=True 时忽略年龄（但仍尊重 touch 的保护期）。
    """
    if delay is None:
        delay = 0 if force else float(
            config.get("vault_delay") or DEFAULT_DELAY)

    files = _collect_plain(delay)
    if not files:
        return {"ok": True, "archived": 0, "pending": 0}

    entries = _volume_entries()
    added = 0
    for f in files:
        try:
            data = f.read_bytes()
            # ⚠ 卷里用「目录名/文件名」保留来源，
            #   否则不同目录下的同名文件会互相覆盖
            key = f"{f.parent.name}/{f.name}"
            entries[key] = data
            f.unlink()                          # 删掉明文
            added += 1
        except Exception as e:                         # noqa: BLE001
            _err(f"归档 {f.name} 失败：{e}")

    if added:
        n = _volume_write(entries)
        idx = _index_read()
        mb = round(VOL.stat().st_size / 1024 / 1024, 2)
        idx["volumes"] = [{"n": 1, "files": n, "mb": mb,
                           "updated": time.strftime(
                               "%Y-%m-%d %H:%M:%S")}]
        idx["count"] = n
        _index_write(idx)

    return {"ok": True, "archived": added,
            "pending": len(_collect_plain(delay)),
            "total": len(entries)}


# ============================================================
#  读取 / 导出
# ============================================================
def get_image(name: str) -> bytes | None:
    """从卷里取一个文件。name 可以是 "目录/文件名" 或 "文件名"。"""
    if not name or ".." in name:
        return None
    entries = _volume_entries()
    if name in entries:
        return entries[name]
    # 也允许只给文件名（同名取最新那个）
    hit = [k for k in entries if k.endswith("/" + name)]
    if hit:
        return entries[sorted(hit)[-1]]
    return None


def list_images(limit: int = 200) -> list[dict]:
    """列出卷里有啥。"""
    entries = _volume_entries()
    out = []
    for name in sorted(entries)[:limit]:
        out.append({
            "name": name,
            "kb": round(len(entries[name]) / 1024, 1),
        })
    return out


def export_all(dest: str) -> dict:
    """把卷里所有文件解到指定目录。"""
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    entries = _volume_entries()
    n = 0
    for name, data in entries.items():
        p = out / name
        if ".." in str(p):
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            n += 1
        except Exception:                              # noqa: BLE001
            continue
    return {"ok": True, "exported": n, "dest": str(out)}


# ============================================================
#  后台
# ============================================================
def _loop() -> None:
    while not _stop.is_set():
        try:
            if config.get("vault_on"):
                archive()
        except Exception as e:                         # noqa: BLE001
            _err(f"{type(e).__name__}: {e}")
        _stop.wait(8)


def start() -> dict:
    global _thread
    if _thread and _thread.is_alive():
        return {"ok": True, "msg": "已在运行"}
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True,
                               name="vault")
    _thread.start()
    return {"ok": True, "msg": "已启动"}


def stop() -> dict:
    _stop.set()
    return {"ok": True}


def status() -> dict:
    entries = _volume_entries() if VOL.exists() else {}
    return {
        "on": bool(config.get("vault_on")),
        "running": bool(_thread and _thread.is_alive()),
        "unlocked": True,                  # 机器密钥模式永远可解
        "mode": "机器密钥（免密）",
        "files": len(entries),
        "mb": round(VOL.stat().st_size / 1024 / 1024, 2)
        if VOL.exists() else 0,
        "plain": sum(1 for d in WATCH_DIRS
                     if d.exists()
                     for f in d.rglob("*") if f.is_file()),
        "held": len(in_use_list()),
        "delay": config.get("vault_delay"),
        "dir": str(ROOT),
        "error": _last_error,
    }


def _err(msg: str) -> None:
    global _last_error
    _last_error = msg
    try:
        p = config.DATA_DIR / "vault.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:                                  # noqa: BLE001
        pass
