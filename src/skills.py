# -*- coding: utf-8 -*-
"""
技能系统

**不经过 AI 就能直接回答**的一批命令。

============================================================
为什么需要
============================================================
    「现在几点」这种问题，走一趟 AI 要 3~5 秒。
    而系统时间本地取只要 0 微秒。

    ✅ 用正则匹配意图 → 直接执行 → 毫秒级返回。
       匹配不上的才交给 AI。

============================================================
怎么做
============================================================
    每个技能 = 名字 + 一组正则 + 一个处理函数

        Skill("时间", [r"几[点刻]|报时", ...], handler)

    handler(match, text) 返回字符串（会被念出来 + 显示）

    ⚠ 正则按**注册顺序**匹配，越具体的越放前面。
      比如「音量调到 50」要排在「音量」前面。

============================================================
边界
============================================================
    技能只是**快路径**，不是唯一路径。
    匹配失败会返回 None，调用方接着交给 AI。
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from . import config


@dataclass
class Result:
    ok: bool
    text: str = ""
    skill: str = ""
    elapsed: float = 0.0
    error: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "text": self.text,
                "skill": self.skill,
                "elapsed": round(self.elapsed, 4),
                "error": self.error}


@dataclass
class Skill:
    name: str
    patterns: list
    handler: Callable
    desc: str = ""
    _rx: list = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._rx = []
        for p in self.patterns:
            try:
                self._rx.append(re.compile(p, re.I))
            except re.error:
                continue

    def match(self, text: str):
        for r in self._rx:
            m = r.search(text)
            if m:
                return m
        return None


class Registry:
    def __init__(self):
        self._skills: list[Skill] = []
        self._register_builtin()

    def add(self, skill: Skill) -> None:
        self._skills.append(skill)

    def list(self) -> list:
        return [{"name": s.name, "desc": s.desc}
                for s in self._skills]

    def try_run(self, text: str) -> Optional[Result]:
        """试跑。没命中返回 None。"""
        text = (text or "").strip()
        if not text:
            return None
        for s in self._skills:
            m = s.match(text)
            if not m:
                continue
            t0 = time.time()
            try:
                r = s.handler(m, text)
            except Exception as e:                     # noqa: BLE001
                return Result(False, error=f"{s.name} 执行失败："
                              f"{type(e).__name__}: {e}",
                              skill=s.name,
                              elapsed=time.time() - t0)
            if r is None:
                continue                # 技能自己说"我不管"
            if isinstance(r, str):
                r = Result(True, r)
            elif isinstance(r, dict):
                r = Result(r.get("ok", True),
                           str(r.get("text") or r.get("msg") or ""),
                           error=str(r.get("error") or ""))
            r.skill = s.name
            r.elapsed = time.time() - t0
            return r
        return None

    # ========================================================
    #  内置技能
    # ========================================================
    def _register_builtin(self) -> None:
        R = self.add

        # ---- 时间日期 ----
        R(Skill("时间", [r"几[点刻]|什么时间|报时|现在时间"],
                lambda m, t: f"现在是 {datetime.now():%H:%M}",
                "报当前时间"))

        R(Skill("日期", [r"几号|星期几|什么日子|今天日期|几月几号"],
                lambda m, t: (
                    f"今天是 {datetime.now():%Y 年 %m 月 %d 日}，"
                    f"{'一二三四五六日'[datetime.now().weekday()]}"
                    f"曜日"),
                "报日期"))

        # ---- 系统状态 ----
        R(Skill("系统状态",
                [r"系统状态|运行状态|状态如何|系统情况|体检|"
                 r"电脑怎么样|机器状态"],
                lambda m, t: self._sys_overview(),
                "整体状态"))

        R(Skill("CPU", [r"cpu|处理器|占用率"],
                lambda m, t: self._cpu_text(),
                "CPU 占用"))

        R(Skill("内存", [r"内存|memory|吃内存"],
                lambda m, t: self._mem_text(),
                "内存占用"))

        R(Skill("显卡", [r"显卡|gpu|显存"],
                lambda m, t: self._gpu_text(),
                "显卡状态"))

        R(Skill("磁盘", [r"磁盘|硬盘|存储空间|剩多少空间|空间够"],
                lambda m, t: self._disk_text(),
                "磁盘剩余"))

        R(Skill("温度", [r"温度|多热|烫不烫|多少度"],
                lambda m, t: self._temp_text(),
                "温度"))

        R(Skill("网络", [r"网速|网卡|上网|网络状态|下载速度"],
                lambda m, t: self._net_text(),
                "网络速率"))

        R(Skill("开机时长", [r"开机多久|运行多久|开机时间|开了多久"],
                lambda m, t: self._uptime_text(),
                "开机时长"))

        # ---- 音量（具体的放前面）----
        R(Skill("音量设置",
                [r"音量(?:调到|设为|设置|到|调到)\s*(\d{1,3})"],
                self._set_vol, "设音量"))

        R(Skill("音量加减",
                [r"(?:声音|音量)?(?:大|小)(?:一)?(?:点|声)|"
                 r"(?:调|加|减)(?:大|小)(?:声|音量)"],
                self._adjust_vol, "调音量"))

        R(Skill("静音", [r"静音|取消静音|别出声|闭嘴|关掉声音"],
                self._toggle_mute, "静音切换"))

        R(Skill("音量",
                [r"音量|多大声音|声音多大"],
                lambda m, t: self._vol_text(), "看音量"))

        # ---- 亮度 ----
        R(Skill("亮度设置",
                [r"亮度(?:调到|设为|设置|到)\s*(\d{1,3})"],
                self._set_bright, "设亮度"))

        R(Skill("亮度",
                [r"亮度|太亮|太暗|调亮|调暗"],
                lambda m, t: self._bright_text(), "看亮度"))

        # ---- 电源 ----
        R(Skill("锁屏", [r"锁屏|锁定(?:屏幕|电脑)"],
                self._lock, "锁屏"))

        R(Skill("取消关机", [r"取消(?:关机|重启)|别关机"],
                self._cancel_sd, "取消关机"))

        R(Skill("关机重启",
                [r"(?:定时|过?)(\d+)分钟?(?:后)?"
                 r"(关机|重启)|(关机|重启|睡眠|休眠)"],
                self._power, "电源操作"))

        R(Skill("屏幕关闭", [r"关(?:闭)?屏|黑屏|关显示器|息屏"],
                self._screen_off, "关屏"))

        # ---- 进程 ----
        R(Skill("卡死检测", [r"卡死|没响应|无响应|死机|假死"],
                self._hung, "找卡死进程"))

        R(Skill("结束进程",
                [r"(?:结束|杀掉|强制关闭)\s*(?:进程)?\s*(\S+)"],
                self._kill, "结束进程"))

        R(Skill("进程排行",
                [r"谁(?:在)?占(?:用)?(?:内存|cpu|处理器)|"
                 r"最占(?:内存|cpu)|进程排行"],
                self._top_proc, "进程排行"))

        # ---- 打开东西 ----
        R(Skill("打开网页",
                [r"打开(?:网站|网页)\s*(\S+)|"
                 r"(?:百度|b站|哔哩哔哩|淘宝|知乎|github)"],
                self._open_web, "打开网站"))

        R(Skill("打开路径",
                [r"打开\s*([A-Za-z]:\\[^\s]+|\.{0,2}[/\\][^\s]+)"],
                self._open_path, "打开文件/文件夹"))

        # ---- 截图 ----
        R(Skill("截图", [r"截图|截屏|屏幕截图"],
                self._shot, "截屏"))

        # ---- 提醒（交给 proactive）----
        #
        # ⚠ 正则要覆盖这几种说法（踩过）：
        #     「有什么提醒」「有哪些提醒」「有提醒吗」「我的提醒」
        #   原来只写了「有什么/哪些提醒」，
        #   「有提醒吗」匹配不上却被意图层判成 skill → 返回空。
        R(Skill("看提醒",
                [r"有(?:什么|哪些)?提醒(?:吗|么)?",
                 r"提醒(?:列表|有啥|有什么)",
                 r"我的提醒|设了什么提醒|几个提醒"],
                self._list_alarms, "查看提醒"))

        R(Skill("取消提醒",
                [r"(?:取消|删除|清空)(?:所有)?提醒"],
                self._clear_alarms, "清空提醒"))

        # ---- 帮助 ----
        R(Skill("帮助",
                [r"^(?:帮助|你能做什么|有什么功能|会什么)$",
                 r"有哪些技能|技能列表"],
                self._help, "看能做什么"))

    # ========================================================
    #  各技能实现
    # ========================================================
    def _sys_overview(self) -> str:
        from . import sysmon as S
        c = S.cpu()
        m = S.memory()
        g = S.gpu()
        parts = []
        if c:
            parts.append(f"CPU {c.get('percent')}%")
        if m:
            parts.append(f"内存 {m.get('percent')}%"
                         f"（{m.get('used_gb')}/{m.get('total_gb')}G）")
        if g:
            parts.append(f"显卡 {g.get('util')}%"
                         f" {g.get('temp')}度")
        return "；".join(parts) or "读不到系统状态"

    def _cpu_text(self) -> str:
        from . import sysmon as S
        c = S.cpu()
        if not c:
            return "读不到 CPU 信息"
        return (f"CPU 占用 {c.get('percent')}%，"
                f"{c.get('count')} 个逻辑核心，"
                f"{c.get('freq')} GHz")

    def _mem_text(self) -> str:
        from . import sysmon as S
        m = S.memory()
        if not m:
            return "读不到内存信息"
        return (f"内存用了 {m.get('percent')}%，"
                f"{m.get('used_gb')} 共 {m.get('total_gb')} GB，"
                f"还剩 {m.get('avail_gb')} GB")

    def _gpu_text(self) -> str:
        from . import sysmon as S
        g = S.gpu()
        if not g:
            return "没有找到独立显卡"
        return (f"{g.get('name')}，占用 {g.get('util')}%，"
                f"显存 {g.get('mem_used_mb')}/{g.get('mem_total_mb')}"
                f" MB，{g.get('temp')} 度")

    def _disk_text(self) -> str:
        from . import sysmon as S
        ds = S.disks()
        if not ds:
            return "读不到磁盘信息"
        parts = [f"{d['mount']} 剩 {d['free_gb']}G"
                 for d in ds[:4]]
        return "；".join(parts)

    def _temp_text(self) -> str:
        from . import sysmon as S
        t = S.temps()
        if not t:
            return "读不到温度（需要硬件监控库）"
        items = list(t.items())[:3]
        return "；".join(f"{k.split(':')[-1]} {v}度"
                         for k, v in items)

    def _net_text(self) -> str:
        from . import sysmon as S
        n = S.network()
        if not n:
            return "读不到网络信息"
        return (f"上传 {n.get('up_mbs')} MB/s，"
                f"下载 {n.get('down_mbs')} MB/s")

    def _uptime_text(self) -> str:
        from . import sysmon as S
        u = S._uptime()
        if not u:
            return "读不到开机时长"
        h = int(u // 3600)
        m = int((u % 3600) // 60)
        return f"已经开机 {h} 小时 {m} 分钟"

    # ---- 音量 ----
    def _vol_text(self) -> str:
        from . import syscontrol as C
        r = C.get_volume()
        if not r.ok:
            return r.msg or "读不到音量"
        d = r.data or {}
        return (f"音量 {d.get('percent')}%"
                + ("（已静音）" if d.get("muted") else ""))

    def _set_vol(self, m, t) -> str:
        from . import syscontrol as C
        try:
            p = int(m.group(1))
        except Exception:                              # noqa: BLE001
            return "没听清要调到多少"
        r = C.set_volume(p)
        return r.msg if r.ok else (r.msg or "设置失败")

    def _adjust_vol(self, m, t) -> str:
        from . import syscontrol as C
        up = bool(re.search(r"大|加|升", t))
        r = C.adjust_volume(10 if up else -10)
        return r.msg if r.ok else (r.msg or "调整失败")

    def _toggle_mute(self, m, t) -> str:
        from . import syscontrol as C
        r = C.mute_toggle()
        return r.msg if r.ok else (r.msg or "切换失败")

    # ---- 亮度 ----
    def _bright_text(self) -> str:
        from . import syscontrol as C
        r = C.get_brightness()
        if not r.ok:
            return "读不到亮度（外接显示器一般不支持）"
        return f"亮度 {(r.data or {}).get('percent')}%"

    def _set_bright(self, m, t) -> str:
        from . import syscontrol as C
        try:
            p = int(m.group(1))
        except Exception:                              # noqa: BLE001
            return "没听清"
        r = C.set_brightness(p)
        return r.msg if r.ok else (r.msg or "设置失败")

    # ---- 电源 ----
    def _lock(self, m, t) -> str:
        from . import syscontrol as C
        r = C.lock_screen()
        return r.msg if r.ok else (r.msg or "锁屏失败")

    def _screen_off(self, m, t) -> str:
        from . import syscontrol as C
        r = C.screen_off()
        return r.msg if r.ok else (r.msg or "关屏失败")

    def _power(self, m, t) -> str:
        from . import syscontrol as C
        g = m.groups()
        minute = g[0] if g and g[0] else None
        action = (g[1] or g[2] or "关机") if g else "关机"
        if "重启" in t:
            action = "restart"
        elif "关机" in t:
            action = "shutdown"
        elif "睡眠" in t or "休眠" in t:
            return "睡眠功能还没接，你可以直接合上盖子"
        else:
            return "没听清要做什么"

        if minute:
            r = C.schedule_shutdown(float(minute), action)
        else:
            # 没有时间 → 不直接执行危险操作，先问
            what = "关机" if action == "shutdown" else "重启"
            return (f"要{what}的话请说「{what}」并带上时间，"
                    f"比如「30 分钟后{what}」")
        return r.msg if r.ok else (r.msg or "设置失败")

    def _cancel_sd(self, m, t) -> str:
        from . import syscontrol as C
        r = C.cancel_shutdown()
        return r.msg if r.ok else (r.msg or "没有待执行的关机")

    # ---- 进程 ----
    def _top_proc(self, m, t) -> str:
        from . import syscontrol as C
        by = "cpu" if re.search(r"cpu|处理器", t, re.I) else "mem"
        r = C.top_processes(5, by)
        if not r.ok:
            return r.msg or "读不到进程"
        items = (r.data or {}).get("items") or []
        if not items:
            return "没有进程数据"
        key = "cpu" if by == "cpu" else "mem_mb"
        return "；".join(
            f"{x['name']} {x[key]}{'%' if by == 'cpu' else 'MB'}"
            for x in items[:4])

    def _hung(self, m, t) -> str:
        from . import syscontrol as C
        r = C.hung_processes()
        items = (r.data or {}).get("items") or []
        if not items:
            return "没有发现卡死的进程"
        return "发现 " + "、".join(x["name"] for x in items[:4])

    def _kill(self, m, t) -> str:
        from . import syscontrol as C
        try:
            target = m.group(1)
        except Exception:                              # noqa: BLE001
            return "没听清要结束哪个"
        if not target:
            return "没听清"
        r = C.kill_process(target)
        return r.msg if r.ok else (r.msg or "结束失败")

    # ---- 打开 ----
    def _open_web(self, m, t) -> str:
        known = {
            "百度": "https://www.baidu.com",
            "b站": "https://www.bilibili.com",
            "哔哩哔哩": "https://www.bilibili.com",
            "淘宝": "https://www.taobao.com",
            "知乎": "https://www.zhihu.com",
            "github": "https://github.com",
        }
        url = None
        for k, v in known.items():
            if k.lower() in t.lower():
                url = v
                break
        if not url:
            try:
                u = m.group(1)
                if u:
                    url = u if "://" in u else "https://" + u
            except Exception:                          # noqa: BLE001
                pass
        if not url:
            return "没听清要打开什么"
        try:
            webbrowser.open(url)
            return f"已打开 {url}"
        except Exception as e:                         # noqa: BLE001
            return f"打开失败：{e}"

    def _open_path(self, m, t) -> str:
        from . import syscontrol as C
        try:
            p = m.group(1)
        except Exception:                              # noqa: BLE001
            return "没听清路径"
        r = C.open_path(p)
        return r.msg if r.ok else (r.msg or "打不开")

    # ---- 截图 ----
    def _shot(self, m, t) -> str:
        from . import look
        s = look.screenshot()
        if not s.get("ok"):
            return s.get("error") or "截图失败"
        return f"已截屏：{s.get('size')}"

    # ---- 提醒 ----
    def _list_alarms(self, m, t) -> str:
        from . import proactive
        conf = proactive.get_conf()
        daily = conf.get("daily") or []
        if not daily:
            return "现在没有设置提醒"
        return "有 " + "；".join(
            f"{x.get('time')} {x.get('text')}"
            for x in daily[:5])

    def _clear_alarms(self, m, t) -> str:
        from . import proactive
        proactive.set_conf({"daily": []})
        return "提醒已清空"

    # ---- 帮助 ----
    def _help(self, m, t) -> str:
        names = [s.name for s in self._skills
                 if s.name not in ("帮助",)]
        return ("我能直接回答这些（不用等 AI）："
                + "、".join(names[:18])
                + "。其他问题会交给 AI。")


_REG: Registry | None = None


def registry() -> Registry:
    global _REG
    if _REG is None:
        _REG = Registry()
    return _REG


def try_run(text: str) -> Optional[Result]:
    return registry().try_run(text)


def list_skills() -> list:
    return registry().list()


def status() -> dict:
    return {"count": len(registry()._skills),
            "skills": list_skills()}
