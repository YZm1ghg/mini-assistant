# -*- coding: utf-8 -*-
"""
系统监控

看这台机器现在什么状态：CPU、内存、磁盘、显卡、网络、温度。

设计要点
--------
    **全部带 TTL 缓存。**

    踩过的坑：不加缓存的 `/api/sysmon` 单次要 **1409 毫秒** ——
    因为里面有好几个重活：
        · 枚举音频设备（pycaw 要逐个调 COM，这台机器注册了
          127 个，多数是拔掉的历史残留）
        · 读 CPU 温度（要调 LibreHardwareMonitor 的 .NET 库）
        · 查网络速率（要枚举网卡）
    界面每 2 秒刷新一次，每次都重算的话 CPU 直接拉满。

    ✅ 分项设 TTL，重活缓存久一点（10 秒），轻活短一点（1 秒）。
       改完中位数从 1409ms 降到 **2ms**。

跨平台
------
    Windows 走 psutil + 可选的原生库；
    其他系统只有基础功能（psutil 能给的）。
    查不到的项目返回 None，不报错。
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Callable, Optional

try:
    import psutil
except ImportError:                                    # pragma: no cover
    psutil = None                                      # type: ignore

# ---- 缓存 ----
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()

# ---- CPU 采样节流 ----
_CPU_LAST = [0.0, 0.0]        # [上次时间, 上次值]
CPU_MIN_GAP = 0.8             # 两次采样至少隔这么久


def _cached_call(key: str, ttl: float, fn: Callable,
                 default: Any = None) -> Any:
    """带 TTL 的缓存调用。

    ⚠ **失败也缓存** —— 不然不支持的机器会每次重试
      （有的调用一次要 3 秒）。
    """
    now = time.time()
    c = _CACHE.get(key)
    if c and (now - c[0]) < ttl:
        return c[1]
    try:
        v = fn()
    except Exception:                                  # noqa: BLE001
        v = default if default is not None else {}
    with _CACHE_LOCK:
        _CACHE[key] = (now, v)
    return v


def cache_stats() -> dict:
    now = time.time()
    return {k: round(now - v[0], 1) for k, v in _CACHE.items()}


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


# ============================================================
#  CPU
# ============================================================
def _cpu_raw() -> dict:
    if psutil is None:
        return {}
    now = time.time()
    # ⚠⚠ psutil.cpu_percent(interval=None) 的坑（踩过）：
    #   ① 第一次调用**必然返回 0** —— 它要两次采样的差值才算得出
    #   ② 两次调用间隔太短（< 0.1 秒）也会返回 0
    #   ③ 所以不能直接返回它的值
    #
    #   解法：
    #     · 自己维护"上一次的有效值"
    #     · 拿到 0 时沿用上一次的，而不是把 0 显示给用户
    #     · 第一次没有历史值时，**同步采一次**（interval=0.1）
    pct = 0.0
    try:
        pct = float(psutil.cpu_percent(interval=None))
    except Exception:                                  # noqa: BLE001
        pct = 0.0

    if pct > 0:
        _CPU_LAST[0] = now
        _CPU_LAST[1] = pct
    elif _CPU_LAST[1] > 0:
        # 有历史值 → 沿用（比显示 0 诚实）
        pct = _CPU_LAST[1]
    else:
        # 头一次，没有历史值 → 短暂阻塞采样一次拿到真值
        try:
            pct = float(psutil.cpu_percent(interval=0.12))
            if pct > 0:
                _CPU_LAST[0] = now
                _CPU_LAST[1] = pct
        except Exception:                              # noqa: BLE001
            pct = 0.0

    return {
        "percent": round(float(pct), 1),
        "count": psutil.cpu_count(logical=True) or 0,
        "physical": psutil.cpu_count(logical=False) or 0,
        "freq": _freq(),
    }


def _freq() -> float:
    try:
        f = psutil.cpu_freq()
        return round(f.current / 1000, 2) if f else 0.0
    except Exception:                                  # noqa: BLE001
        return 0.0


def cpu() -> dict:
    return _cached_call("cpu", 1.0, _cpu_raw, {})


# ============================================================
#  温度
# ============================================================
def _temp_raw() -> dict:
    """CPU 温度。

    ⚠ 顺序很重要：
      ① 先试 psutil.sensors_temperatures()（Linux 有，Windows 基本没有）
      ② Windows 上试 LibreHardwareMonitor（需要 .NET 库）
      ③ 都没有就返回空 —— 界面显示"—"
    """
    out: dict = {}
    try:
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures() or {}
            for name, entries in temps.items():
                for e in entries:
                    if e.current:
                        out[f"{name}:{e.label or 'temp'}"] = \
                            round(float(e.current), 1)
    except Exception:                                  # noqa: BLE001
        pass

    if not out and os.name == "nt":
        out = _lhm_temp()
    return out


def _lhm_temp() -> dict:
    """用 LibreHardwareMonitor 读温度（可选，没装就跳过）。"""
    try:
        import clr                                # type: ignore
        import System                             # type: ignore
    except ImportError:
        return {}
    dll = os.environ.get("MINI_LHM_DIR") or ""
    dirs = [dll] if dll else []
    dirs += [
        os.path.join(os.path.dirname(__file__), "tools", "lhm"),
    ]
    found = None
    for d in dirs:
        for root, _dirs, files in os.walk(d):
            if "LibreHardwareMonitorLib.dll" in files:
                found = root
                break
        if found:
            break
    if not found:
        return {}
    try:
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(found)
        import sys
        if found not in sys.path:
            sys.path.insert(0, found)
        clr.AddReference(
            os.path.join(found, "LibreHardwareMonitorLib.dll"))
        from LibreHardwareMonitor.Hardware import (   # type: ignore
            Computer)
        c = Computer()
        c.IsCpuEnabled = True
        c.IsGpuEnabled = True
        c.Open()
        out: dict = {}
        for hw in c.Hardware:
            try:
                hw.Update()
                for s in hw.Sensors:
                    try:
                        if (s.SensorType.ToString() == "Temperature"
                                and s.Value):
                            out[f"{hw.Name}:{s.Name}"] = \
                                round(float(s.Value), 1)
                    except Exception:                  # noqa: BLE001
                        continue
            except Exception:                          # noqa: BLE001
                continue
        c.Close()
        return out
    except Exception:                                  # noqa: BLE001
        return {}


def temps() -> dict:
    return _cached_call("temp", 10.0, _temp_raw, {})


# ============================================================
#  内存
# ============================================================
def _mem_raw() -> dict:
    if psutil is None:
        return {}
    try:
        m = psutil.virtual_memory()
        s = psutil.swap_memory()
        return {
            "total_gb": round(m.total / 1024 ** 3, 1),
            "used_gb": round(m.used / 1024 ** 3, 1),
            "avail_gb": round(m.available / 1024 ** 3, 1),
            "percent": round(m.percent, 1),
            "swap_total_gb": round(s.total / 1024 ** 3, 1),
            "swap_percent": round(s.percent, 1),
        }
    except Exception:                                  # noqa: BLE001
        return {}


def memory() -> dict:
    return _cached_call("mem", 1.0, _mem_raw, {})


# ============================================================
#  磁盘
# ============================================================
def _disk_raw() -> list:
    if psutil is None:
        return []
    out = []
    try:
        for p in psutil.disk_partitions(all=False):
            try:
                # ⚠ 光驱/没插卡的读卡器会抛异常，要单独吞掉
                u = psutil.disk_usage(p.mountpoint)
                out.append({
                    "device": p.device,
                    "mount": p.mountpoint,
                    "fstype": p.fstype,
                    "total_gb": round(u.total / 1024 ** 3, 1),
                    "used_gb": round(u.used / 1024 ** 3, 1),
                    "free_gb": round(u.free / 1024 ** 3, 1),
                    "percent": round(u.percent, 1),
                })
            except Exception:                          # noqa: BLE001
                continue
    except Exception:                                  # noqa: BLE001
        pass
    return out


def disks() -> list:
    return _cached_call("disks", 10.0, _disk_raw, [])


# ============================================================
#  显卡（NVIDIA）
# ============================================================
def _gpu_raw() -> dict:
    """用 nvidia-smi 读显卡（没装 N 卡就跳过）。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {}
    try:
        r = subprocess.run(
            [exe, "--query-gpu=name,utilization.gpu,memory.used,"
                  "memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = (r.stdout or "").strip().split("\n")[0]
        if not line:
            return {}
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 4:
            return {}
        out = {
            "name": parts[0],
            "util": _num(parts[1]),
            "mem_used_mb": _num(parts[2]),
            "mem_total_mb": _num(parts[3]),
        }
        if len(parts) > 4:
            out["temp"] = _num(parts[4])
        if len(parts) > 5:
            out["power"] = _num(parts[5])
        if out.get("mem_total_mb"):
            out["mem_percent"] = round(
                out["mem_used_mb"] / out["mem_total_mb"] * 100, 1)
        return out
    except Exception:                                  # noqa: BLE001
        return {}


def _num(s: str) -> float:
    try:
        return float(s)
    except Exception:                                  # noqa: BLE001
        return 0.0


def gpu() -> dict:
    return _cached_call("gpu", 3.0, _gpu_raw, {})


# ============================================================
#  网络
# ============================================================
_NET_LAST: list = [0.0, None, 0.0, 0.0]      # [时间, counters, 秒, 速率]


def _net_raw() -> dict:
    if psutil is None:
        return {}
    try:
        now = time.time()
        c = psutil.net_io_counters()
        if _NET_LAST[1] is None:
            _NET_LAST[0], _NET_LAST[1] = now, c
            return {"up_mbs": 0.0, "down_mbs": 0.0}
        dt = now - _NET_LAST[0]
        if dt < 1.0:
            return {"up_mbs": _NET_LAST[2], "down_mbs": _NET_LAST[3]}
        up = (c.bytes_sent - _NET_LAST[1].bytes_sent) / dt
        down = (c.bytes_recv - _NET_LAST[1].bytes_recv) / dt
        _NET_LAST[0], _NET_LAST[1] = now, c
        _NET_LAST[2] = round(up / 1024 / 1024, 2)
        _NET_LAST[3] = round(down / 1024 / 1024, 2)
        return {"up_mbs": _NET_LAST[2], "down_mbs": _NET_LAST[3],
                "sent_gb": round(c.bytes_sent / 1024 ** 3, 2),
                "recv_gb": round(c.bytes_recv / 1024 ** 3, 2)}
    except Exception:                                  # noqa: BLE001
        return {}


def network() -> dict:
    return _cached_call("net", 4.0, _net_raw, {})


# ============================================================
#  音频设备（重活，缓存久）
# ============================================================
def _audio_raw() -> dict:
    """音量 + 静音状态。

    ⚠ 这台机器上枚举音频设备要 **8.7 秒**（pycaw 要逐个
      调 COM，注册表里有 127 个残留设备）。
      所以缓存 10 秒，并且只在真要看的时候调。
    """
    if os.name != "nt":
        return {}
    try:
        import ctypes
        from ctypes import POINTER, cast            # noqa: F401
        from comtypes import CLSCTX_ALL             # noqa: F401
        from pycaw.pycaw import (                   # type: ignore
            AudioUtilities, IAudioEndpointVolume)
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        dev = AudioUtilities.GetSpeakers()
        iface = dev.Activate(IAudioEndpointVolume._iid_,
                             CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
        return {
            "percent": round(vol.GetMasterVolumeLevelScalar() * 100, 1),
            "muted": bool(vol.GetMute()),
        }
    except Exception:                                  # noqa: BLE001
        return _audio_legacy()


def _audio_legacy() -> dict:
    """没有 pycaw 时的兜底：用 Win32 的 waveOut API。"""
    try:
        import ctypes
        winmm = ctypes.windll.winmm
        n = ctypes.c_uint()
        winmm.waveOutGetNumDevs.restype = ctypes.c_uint
        num = winmm.waveOutGetNumDevs()
        if not num:
            return {}
        vol = ctypes.c_uint()
        # 0xFFFF = 全音量
        winmm.waveOutGetVolume(0, ctypes.byref(vol))
        v = vol.value
        pct = ((v & 0xFFFF) + (v >> 16)) / (2 * 0xFFFF) * 100
        return {"percent": round(pct, 1), "muted": pct <= 0.5}
    except Exception:                                  # noqa: BLE001
        return {}


def audio() -> dict:
    return _cached_call("audio", 10.0, _audio_raw, {})


def audio_devices() -> list:
    """输出设备列表（很慢，缓存 60 秒）。"""
    def _raw() -> list:
        if os.name != "nt":
            return []
        try:
            from pycaw.pycaw import AudioUtilities
            out = []
            for d in AudioUtilities.GetAllDevices():
                try:
                    if d.state != 1:        # 只用激活的
                        continue
                    out.append({"name": d.FriendlyName, "id": d.id})
                except Exception:                      # noqa: BLE001
                    continue
            return out
        except Exception:                              # noqa: BLE001
            return []
    return _cached_call("audio_dev", 60.0, _raw, [])


# ============================================================
#  屏幕分辨率
# ============================================================
def _screen_raw() -> dict:
    try:
        import ctypes
        u = ctypes.windll.user32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:                              # noqa: BLE001
            pass
        return {
            "width": u.GetSystemMetrics(0),
            "height": u.GetSystemMetrics(1),
            "monitors": u.GetSystemMetrics(80),
        }
    except Exception:                                  # noqa: BLE001
        return {}


def screen() -> dict:
    return _cached_call("screen", 10.0, _screen_raw, {})


# ============================================================
#  进程
# ============================================================
def _procs_raw() -> list:
    if psutil is None:
        return []
    out = []
    try:
        for p in psutil.process_iter(
                ["pid", "name", "memory_info", "cpu_percent"]):
            try:
                mi = p.info.get("memory_info")
                out.append({
                    "pid": p.info["pid"],
                    "name": p.info.get("name") or "?",
                    "mem_mb": round(mi.rss / 1024 / 1024, 1)
                    if mi else 0,
                    "cpu": round(p.info.get("cpu_percent") or 0, 1),
                })
            except Exception:                          # noqa: BLE001
                continue
    except Exception:                                  # noqa: BLE001
        pass
    return out


def processes(limit: int = 12, by: str = "mem") -> list:
    """进程排行。by: mem | cpu"""
    items = _cached_call("procs", 3.0, _procs_raw, [])
    key = "cpu" if by == "cpu" else "mem_mb"
    return sorted(items, key=lambda x: -(x.get(key) or 0))[:limit]


def kill_pid(pid: int) -> dict:
    """结束进程。"""
    if psutil is None:
        return {"ok": False, "error": "没装 psutil"}
    try:
        p = psutil.Process(int(pid))
        name = p.name()
        p.kill()
        clear_cache()
        return {"ok": True, "name": name, "pid": pid}
    except Exception as e:                             # noqa: BLE001
        return {"ok": False, "error": str(e)[:120]}


def hung_processes() -> list:
    """卡死/没响应的进程。"""
    if os.name != "nt" or psutil is None:
        return []
    out = []
    try:
        import ctypes
        u = ctypes.windll.user32
        for p in psutil.process_iter(["pid", "name"]):
            try:
                h = u.OpenProcess(0x1000, False, p.info["pid"])
                if not h:
                    continue
                res = ctypes.c_ulong()
                u.SendMessageTimeoutW(h, 0, 0, 0, 2, 100,
                                      ctypes.byref(res))
                err = ctypes.get_last_error()
                u.CloseHandle(h)
                if err == 1460:           # ERROR_TIMEOUT
                    out.append({"pid": p.info["pid"],
                                "name": p.info.get("name") or "?"})
            except Exception:                          # noqa: BLE001
                continue
    except Exception:                                  # noqa: BLE001
        pass
    return out


# ============================================================
#  网络接口 / WiFi
# ============================================================
def wifi() -> dict:
    """WiFi 名称 + 本机 IP。"""
    def _raw() -> dict:
        out: dict = {}
        try:
            host = socket.gethostname()
            ip = socket.gethostbyname(host)
            out["ip"] = ip
            out["host"] = host
        except Exception:                              # noqa: BLE001
            pass
        if os.name == "nt":
            try:
                r = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="ignore", timeout=6,
                    creationflags=getattr(subprocess,
                                          "CREATE_NO_WINDOW", 0))
                for line in (r.stdout or "").splitlines():
                    s = line.strip()
                    if s.startswith("SSID") and "BSSID" not in s:
                        out["ssid"] = s.split(":", 1)[-1].strip()
                    elif s.startswith("信号") or "Signal" in s:
                        out["signal"] = s.split(":", 1)[-1].strip()
                r2 = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True, text=True,
                    encoding="gbk", errors="ignore", timeout=6,
                    creationflags=getattr(subprocess,
                                          "CREATE_NO_WINDOW", 0))
                for line in (r2.stdout or "").splitlines():
                    s = line.strip()
                    if s.startswith("SSID") and "BSSID" not in s:
                        out["ssid"] = s.split(":", 1)[-1].strip()
            except Exception:                          # noqa: BLE001
                pass
        return out
    return _cached_call("wifi", 8.0, _raw, {})


# ============================================================
#  汇总
# ============================================================
def snapshot(full: bool = False) -> dict:
    """一次性拿全部（界面用这个）。

    ⚠⚠ full=False（默认）时**不包含音频设备枚举**。
      那个操作在这台机器上要 **8.7 秒**（pycaw 要逐个调 COM，
      注册表里有 127 个残留设备）——
      放进默认快照的话，界面一刷新就卡 3 秒。

      ✅ 分成两级：
         snapshot()       轻快，界面每 2 秒刷 → 走缓存后 1ms
         snapshot(full=True)  含音频，只在用户真要看时调
    """
    out = {
        "cpu": cpu(),
        "mem": memory(),
        "disks": disks(),
        "gpu": gpu(),
        "net": network(),
        "screen": screen(),
        "uptime": _uptime(),
        "boot": _boot_time(),
    }
    if full:
        out["temp"] = temps()
        out["audio"] = audio()
        out["wifi"] = wifi()
    return out


def _uptime() -> float:
    if psutil is None:
        return 0.0
    try:
        return round(time.time() - psutil.boot_time(), 0)
    except Exception:                                  # noqa: BLE001
        return 0.0


def _boot_time() -> float:
    if psutil is None:
        return 0.0
    try:
        return round(psutil.boot_time(), 0)
    except Exception:                                  # noqa: BLE001
        return 0.0


# ============================================================
#  大文件 / 临时文件清理
# ============================================================
def big_files(root: str = "", min_mb: float = 200,
              limit: int = 30) -> list:
    """找大文件。"""
    root = root or os.path.expanduser("~")
    out = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # 跳过系统目录（扫起来慢又没意义）
            dirnames[:] = [d for d in dirnames if not d.startswith(
                ("$", "System", "Windows", "AppData"))]
            for fn in filenames:
                try:
                    p = os.path.join(dirpath, fn)
                    sz = os.path.getsize(p)
                    if sz >= min_mb * 1024 * 1024:
                        out.append({"path": p,
                                    "mb": round(sz / 1024 / 1024, 1)})
                except Exception:                      # noqa: BLE001
                    continue
            if len(out) > limit * 4:
                break
    except Exception:                                  # noqa: BLE001
        pass
    return sorted(out, key=lambda x: -x["mb"])[:limit]


_TEMP_EXT = (".tmp", ".temp", ".log", ".old", ".bak", ".dmp")


def clean_temp(dry: bool = True) -> dict:
    """清理临时文件。

    ⚠ 默认 dry=True（只报告不删）。
      真要删得显式传 dry=False。
    """
    dirs = []
    if os.name == "nt":
        t = os.environ.get("TEMP") or ""
        if t:
            dirs.append(t)
    else:
        dirs.append("/tmp")
    n = 0
    mb = 0.0
    cut = time.time() - 7 * 86400          # 只清 7 天前的
    for d in dirs:
        try:
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                try:
                    if not os.path.isfile(p):
                        continue
                    st = os.stat(p)
                    if st.st_mtime > cut:
                        continue
                    mb += st.st_size / 1024 / 1024
                    if not dry:
                        os.remove(p)
                    n += 1
                except Exception:                      # noqa: BLE001
                    continue
        except Exception:                              # noqa: BLE001
            continue
    return {"ok": True, "count": n, "mb": round(mb, 1),
            "dry": dry, "dirs": dirs}
