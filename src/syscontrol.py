# -*- coding: utf-8 -*-
"""
系统控制

能对这台机器做的事：调音量、调亮度、管进程、电源操作、关屏幕……

设计原则
--------
    · 每个操作都有明确的成功/失败返回值（不是静默失败）
    · 危险操作（关机/杀进程）要**二次确认**
    · 不支持的操作返回 "不支持"，而不是假装成功

跨平台
------
    Windows 走 Win32 API + PowerShell；
    其他系统尽量用系统命令，不行就返回"不支持"。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

try:
    import psutil
except ImportError:                                    # pragma: no cover
    psutil = None                                      # type: ignore

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Result:
    ok: bool
    msg: str = ""
    data: dict = None                              # type: ignore

    def as_dict(self) -> dict:
        d = {"ok": self.ok, "msg": self.msg}
        if self.data:
            d.update(self.data)
        return d


def _run(cmd: list, timeout: int = 20) -> tuple:
    """跑个命令，返回 (returncode, stdout+stderr)。"""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="ignore", timeout=timeout,
            creationflags=_NO_WINDOW)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:                             # noqa: BLE001
        return -1, str(e)


def _ps(script: str, timeout: int = 20) -> tuple:
    """跑一段 PowerShell。"""
    return _run(["powershell", "-NoProfile", "-Command", script],
                timeout)


# ============================================================
#  音量
# ============================================================
_SPK = None
_SPK_FAILED = False


def _speaker():
    """拿默认扬声器对象。

    ⚠⚠ 用法踩过坑：
      旧写法是先 `AudioUtilities.GetSpeakers()` 再
      `.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)`
      然后 cast 成接口指针 —— 但 pycaw 新版本里
      `GetSpeakers()` **返回的已经是包装好的对象**，
      直接 `.volume_percent` / `.EndpointVolume` 就能用，
      再 Activate 反而拿不到东西。

      ✅ 新版本：直接读 `spk.volume_percent`
      ✅ 老版本：退回 `spk.EndpointVolume`

    失败过一次就不再重试（这个调用可能要几百毫秒）。
    """
    global _SPK, _SPK_FAILED
    if _SPK is not None:
        return _SPK
    if _SPK_FAILED:
        return None
    if os.name != "nt":
        _SPK_FAILED = True
        return None
    try:
        from pycaw.pycaw import AudioUtilities    # type: ignore
        _SPK = AudioUtilities.GetSpeakers()
        return _SPK
    except Exception:                                  # noqa: BLE001
        _SPK_FAILED = True
        return None


def _volume_iface():
    """拿 IAudioEndpointVolume 接口（老版本 pycaw 用）。"""
    spk = _speaker()
    if spk is None:
        return None
    try:
        return spk.EndpointVolume
    except Exception:                                  # noqa: BLE001
        return None


def get_volume() -> Result:
    spk = _speaker()
    if spk is None:
        return Result(False, "读不到音量（没装 pycaw？）")
    try:
        # 新版本 pycaw：直接有 volume_percent
        vp = getattr(spk, "volume_percent", None)
        muted = False
        if vp is not None:
            try:
                muted = bool(spk.EndpointVolume.GetMute())
            except Exception:                          # noqa: BLE001
                pass
            return Result(True, "", {
                "percent": round(float(vp), 1), "muted": muted})
        # 老版本：走接口
        ev = _volume_iface()
        if ev is None:
            return Result(False, "读不到音量")
        return Result(True, "", {
            "percent": round(ev.GetMasterVolumeLevelScalar() * 100, 1),
            "muted": bool(ev.GetMute()),
        })
    except Exception as e:                             # noqa: BLE001
        return Result(False, f"读取失败：{e}")


def set_volume(percent: float) -> Result:
    """设音量。percent 0-100。"""
    spk = _speaker()
    if spk is None:
        return Result(False, "设不了音量（没装 pycaw？）")
    p = max(0.0, min(100.0, float(percent)))
    try:
        # 新版本：有 setter
        try:
            spk.volume_percent = int(p)
            return Result(True, f"音量调到 {p:.0f}%", {"percent": p})
        except Exception:                              # noqa: BLE001
            pass
        ev = _volume_iface()
        if ev is None:
            return Result(False, "设不了音量")
        ev.SetMasterVolumeLevelScalar(p / 100.0, None)
        return Result(True, f"音量调到 {p:.0f}%", {"percent": p})
    except Exception as e:                             # noqa: BLE001
        return Result(False, f"设置失败：{e}")


def adjust_volume(delta: float) -> Result:
    """加/减音量。delta 可以为负。"""
    cur = get_volume()
    if not cur.ok:
        return cur
    return set_volume((cur.data or {}).get("percent", 50) + delta)


def mute_toggle() -> Result:
    ev = _volume_iface()
    if ev is None:
        # 没有接口时退回"把音量设成 0 / 恢复"
        cur = get_volume()
        if not cur.ok:
            return Result(False, "不支持静音切换")
        if (cur.data or {}).get("muted"):
            return set_volume(50)
        return set_volume(0)
    try:
        now = bool(ev.GetMute())
        ev.SetMute(not now, None)
        return Result(True, "已静音" if not now else "已取消静音",
                      {"muted": not now})
    except Exception as e:                             # noqa: BLE001
        return Result(False, f"切换失败：{e}")


# ============================================================
#  亮度
# ============================================================
def get_brightness() -> Result:
    """读屏幕亮度（笔记本有，台机显示器一般没有）。"""
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    code, out = _ps(
        "(Get-CimInstance -Namespace root/WMI "
        "-ClassName WmiMonitorBrightness "
        "-EA SilentlyContinue).CurrentBrightness")
    s = out.strip()
    if s.isdigit():
        return Result(True, "", {"percent": int(s)})
    return Result(False, "读不到亮度（外接显示器不支持）")


def set_brightness(percent: float) -> Result:
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    p = max(0, min(100, int(percent)))
    code, out = _ps(
        "(Get-CimInstance -Namespace root/WMI "
        "-ClassName WmiMonitorBrightnessMethods)"
        f".WmiSetBrightness(1,{p})")
    if code == 0:
        return Result(True, f"亮度调到 {p}%", {"percent": p})
    return Result(False, "设不了亮度（外接显示器不支持）")


def adjust_brightness(delta: float) -> Result:
    cur = get_brightness()
    if not cur.ok:
        return cur
    return set_brightness((cur.data or {}).get("percent", 50) + delta)


# ============================================================
#  电源
# ============================================================
def set_power_plan(name: str = "balanced") -> Result:
    """切电源计划。name: performance | balanced | saver"""
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    guids = {
        "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
        "saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
    }
    g = guids.get(name.lower())
    if not g:
        return Result(False, f"不认识这个电源计划：{name}")
    code, _ = _run(["powercfg", "/setactive", g])
    labels = {"performance": "高性能", "balanced": "平衡",
              "saver": "节能"}
    if code == 0:
        return Result(True, f"已切到{labels[name.lower()]}",
                      {"plan": name})
    return Result(False, "切换失败（可能权限不够）")


def current_power_plan() -> Result:
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    code, out = _run(["powercfg", "/getactivescheme"])
    if code != 0:
        return Result(False, "读不到电源计划")
    # 输出形如：Power Scheme GUID: xxx  (平衡)
    name = ""
    if "(" in out and ")" in out:
        name = out[out.rfind("(") + 1:out.rfind(")")]
    return Result(True, "", {"name": name.strip(), "raw": out.strip()})


def schedule_shutdown(minutes: float = 30,
                      action: str = "shutdown") -> Result:
    """定时关机/重启。action: shutdown | restart"""
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    secs = max(30, int(float(minutes) * 60))
    flag = "/s" if action == "shutdown" else "/r"
    code, _ = _run(["shutdown", flag, "/t", str(secs)])
    what = "关机" if action == "shutdown" else "重启"
    if code == 0:
        return Result(True, f"{secs // 60} 分钟后{what}",
                      {"seconds": secs})
    return Result(False, f"设置失败（可能权限不够）")


def cancel_shutdown() -> Result:
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    code, _ = _run(["shutdown", "/a"])
    if code == 0:
        return Result(True, "已取消关机")
    return Result(False, "没有待执行的关机任务")


def lock_screen() -> Result:
    """锁屏。"""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return Result(True, "已锁屏")
        except Exception as e:                         # noqa: BLE001
            return Result(False, f"锁屏失败：{e}")
    code, _ = _run(["loginctl", "lock"])
    return Result(code == 0, "已锁屏" if code == 0 else "锁屏失败")


def screen_off() -> Result:
    """关显示器（不动系统）。"""
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    code, _ = _ps(
        "(Add-Type '[DllImport(\"user32.dll\")]"
        "public static extern int SendMessage(int hWnd,"
        " int hMsg, int wParam, int lParam);' "
        "-Name a -Namespace w);"
        "[w.a]::SendMessage(0xFFFF, 0x0112, 0xF170, 2)")
    return Result(code == 0, "已关屏幕" if code == 0 else "关屏失败")


# ============================================================
#  进程
# ============================================================
def top_processes(limit: int = 10, by: str = "mem") -> Result:
    """占用最高的进程。"""
    if psutil is None:
        return Result(False, "没装 psutil")
    items = []
    try:
        for p in psutil.process_iter(
                ["pid", "name", "memory_info", "cpu_percent"]):
            try:
                mi = p.info.get("memory_info")
                items.append({
                    "pid": p.info["pid"],
                    "name": p.info.get("name") or "?",
                    "mem_mb": round(mi.rss / 1024 / 1024, 1)
                    if mi else 0,
                    "cpu": round(p.info.get("cpu_percent") or 0, 1),
                })
            except Exception:                          # noqa: BLE001
                continue
    except Exception as e:                             # noqa: BLE001
        return Result(False, f"读进程失败：{e}")
    key = "cpu" if by == "cpu" else "mem_mb"
    items.sort(key=lambda x: -(x.get(key) or 0))
    return Result(True, "", {"items": items[:limit], "by": by})


def kill_process(name_or_pid) -> Result:
    """结束进程。认 PID（数字）或名字。"""
    if psutil is None:
        return Result(False, "没装 psutil")
    s = str(name_or_pid).strip()
    targets = []
    try:
        if s.isdigit():
            targets = [psutil.Process(int(s))]
        else:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if s.lower() in (p.info.get("name") or "").lower():
                        targets.append(p)
                except Exception:                      # noqa: BLE001
                    continue
    except Exception as e:                             # noqa: BLE001
        return Result(False, f"找不到进程：{e}")

    if not targets:
        return Result(False, f"没找到「{s}」")

    killed, failed = [], []
    for p in targets[:8]:                  # 一次最多杀 8 个
        try:
            nm = p.name()
            p.kill()
            killed.append(f"{nm}({p.pid})")
        except Exception as e:                         # noqa: BLE001
            failed.append(str(e)[:40])
    if killed:
        return Result(True, f"已结束 {len(killed)} 个："
                            f"{'、'.join(killed[:3])}",
                      {"killed": killed, "failed": failed})
    return Result(False, f"结束失败：{failed[:2]}")


def hung_processes() -> Result:
    """找没响应的进程。"""
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    try:
        import ctypes
        u = ctypes.windll.user32
    except Exception as e:                             # noqa: BLE001
        return Result(False, str(e))
    out = []
    try:
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
                if err == 1460:                        # 超时 = 卡死
                    out.append({"pid": p.info["pid"],
                                "name": p.info.get("name") or "?"})
            except Exception:                          # noqa: BLE001
                continue
    except Exception:                                  # noqa: BLE001
        pass
    return Result(True, "", {"items": out})


# ============================================================
#  网络开关
# ============================================================
def set_wifi(on: bool) -> Result:
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    # ⚠ 禁用/启用网卡需要管理员权限，普通用户会失败
    verb = "enable" if on else "disable"
    code, out = _ps(
        "Get-NetAdapter -Physical | Where-Object "
        "{$_.Name -match 'WLAN|Wi-Fi|无线'} | "
        f"{'Enable' if on else 'Disable'}-NetAdapter "
        "-Confirm:$false")
    if code == 0:
        return Result(True, f"WiFi 已{'打开' if on else '关闭'}")
    return Result(False, "切换失败（需要管理员权限）")


def wifi_status() -> Result:
    if os.name != "nt":
        return Result(False, "只支持 Windows")
    code, out = _ps(
        "Get-NetAdapter -Physical | Where-Object "
        "{$_.Name -match 'WLAN|Wi-Fi|无线'} | "
        "Select-Object -ExpandProperty Status")
    s = out.strip().split("\n")[0].strip() if out.strip() else ""
    return Result(bool(s), "", {"status": s})


# ============================================================
#  其他
# ============================================================
def is_admin() -> bool:
    """当前是不是管理员。"""
    try:
        if os.name == "nt":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:                                  # noqa: BLE001
        return False


def open_path(path: str) -> Result:
    """用系统默认程序打开一个文件/文件夹/网址。"""
    try:
        if os.name == "nt":
            os.startfile(path)                         # type: ignore
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return Result(True, f"已打开 {path}")
    except Exception as e:                             # noqa: BLE001
        return Result(False, f"打不开：{e}")


def status() -> dict:
    v = get_volume()
    return {
        "admin": is_admin(),
        "volume": v.data if v.ok else {},
        "platform": sys.platform,
    }
