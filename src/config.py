# -*- coding: utf-8 -*-
"""
配置管理

一个 config.json 装全部设置。首次运行自动生成。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

# 项目根 = 本文件的上上级
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"

DEFAULTS: dict[str, Any] = {
    # ---- 服务 ----
    "host": "127.0.0.1",
    # ⚠ 端口怎么选的（别随便改成 8000/8080 这类）：
    #
    #   · 8000/8080/3000/5000 这些是**知名服务端口**，
    #     开发机上几乎必有别的东西在跑（这点已经被用户踩到过）
    #   · 49152 往上虽然叫"动态私有段"，但这台机器上
    #     Hyper-V / WSL / Docker 会把很大一块保留掉 ——
    #     今天没冲突不代表明天不冲突
    #
    #   ✅ 所以取 6 万出头的一个号，并且：
    #      · 启动时**实际 bind 测试**
    #      · 被占了就按固定顺序顺延到下一个候选
    #      · 最终结果写回这里 → 下次还用同一个
    #
    #   这样既稳定（书签不会失效）又不会撞。
    "port": 64874,
    # 端口被占时，按这个顺序往后试
    "port_fallback": [64284, 64895, 63140, 64676, 64076],

    # ---- DSH 后端 ----
    # dsh 的 bin.js 路径。留空则自动查找。
    "dsh_bin": "",
    # 用哪个 profile
    "dsh_profile": "headless",
    # 每次请求的超时秒数
    "timeout": 300,
    # 工作目录（dsh 会在这里读写文件）
    "work_dir": "",

    # ---- 语音 ----
    "voice_enabled": True,
    # edge | pyttsx3 | off
    "tts_engine": "edge",
    # edge-tts 的音色
    "tts_voice": "zh-CN-XiaoxiaoNeural",
    "tts_speed": 1.0,
    # funasr | whisper | off
    "asr_engine": "funasr",
    # 录音时长上限（秒）
    "asr_max_seconds": 30,

    # ---- 对话 ----
    # 保留多少条历史
    "history_limit": 200,

    # ---- 技能优先 ----
    # 开：先试本地技能（「现在几点」这类毫秒返回，不走 AI）
    # 关：所有问题都交给 AI
    "skill_first": True,

    # ---- 长期记忆 ----
    # 是否把每轮对话自动记进长期记忆
    "memory_auto": True,
    # 每次提问时召回几条相关记忆当背景
    "memory_recall": 4,

    # ---- 主动助手 ----
    # ⚠ 默认全关。主动打扰人是把双刃剑。
    "proactive": {
        "on": False,
        "wechat_interval": 60,
        "wechat_speak": True,
        "wechat_max": 3,
        "daily": [],
        "quiet": ["23:30", "07:30"],
    },

    # ---- 保险箱 ----
    # 是否自动加密 data/look 下的图
    "vault_on": False,
    # 图落地后多少秒加密（给人/AI 留够看图时间）
    "vault_delay": 120,
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_mtime = 0.0


def load() -> dict[str, Any]:
    """读配置。带 mtime 缓存 —— 改了文件下次调用自动生效。"""
    global _cache, _cache_mtime
    with _lock:
        try:
            mt = CONFIG_PATH.stat().st_mtime
        except OSError:
            mt = 0.0
        if _cache is not None and mt == _cache_mtime:
            return _cache

        data = dict(DEFAULTS)
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    # 只接受已知键，防止手改出错
                    for k in DEFAULTS:
                        if k in raw:
                            data[k] = raw[k]
            except Exception:                              # noqa: BLE001
                pass
        _cache = data
        _cache_mtime = mt
        return data


def save(values: dict[str, Any]) -> dict[str, Any]:
    """写配置（只写已知键）。"""
    global _cache, _cache_mtime
    cur = load()
    for k, v in (values or {}).items():
        if k in DEFAULTS:
            cur[k] = v
    with _lock:
        CONFIG_PATH.write_text(
            json.dumps(cur, ensure_ascii=False, indent=2),
            encoding="utf-8")
        _cache = None
        _cache_mtime = 0.0
    return cur


def get(key: str, default: Any = None) -> Any:
    return load().get(key, DEFAULTS.get(key, default))


def ensure_files() -> None:
    """首次运行时准备好 config.json 和 data 目录。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULTS, ensure_ascii=False, indent=2),
            encoding="utf-8")


def pick_port() -> int:
    """找一个能用的端口。

    顺序：
        ① 配置里写的（默认 64874）
        ② 配置里的 fallback 列表
        ③ 都没有 → 从 61000-65000 用固定哈希顺序现找

    ⚠ 找到后**写回配置**，这样下次还是同一个，
      浏览器书签不会失效。

    ⚠ 为什么要实际 bind 测试而不是只看 netstat：
      netstat 有竞态 —— 查到没占用之后、我们真正 bind 之前，
      别的进程可能已经占上了。直接试绑最准。
    """
    import socket

    def _free(p: int) -> bool:
        """试试能不能真绑上这个端口。

        ⚠⚠ 两个坑（都踩过）：

        ① **不能用 SO_REUSEADDR**
           设了它之后，即使端口已被别的进程 listen，
           bind 也会成功 —— 检测形同虚设。
           不带 SO_REUSEADDR 才能真测出占用。
           （Windows 上 SO_REUSEADDR 的语义和 Linux 不同，
             它允许"抢占"，行为更危险。）

        ② **IPv6 的 ::1 要单独测**
           服务只绑 IPv4 时不必测 IPv6；
           但反过来，如果只测 IPv4 而 IPv6 被占，
           某些配置下监听会失败。这里两个都测。

        ③ bind 完要 **listen(1)** 才算真占住，
           光 bind 有时候测不出"已 listen"的状态。
        """
        # 只测 IPv4 —— 服务默认只绑 127.0.0.1
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # ⚠ 故意**不设** SO_REUSEADDR
            s.bind(("127.0.0.1", p))
            s.listen(1)
            s.close()
        except OSError:
            return False
        except Exception:                              # noqa: BLE001
            return False
        return True

    cfg = load()
    first = int(cfg.get("port") or DEFAULTS["port"])
    order = [first]
    fb = cfg.get("port_fallback")
    if isinstance(fb, list):
        order += [int(x) for x in fb if str(x).isdigit()]
    # 兜底：现找
    import hashlib
    extra = []
    for i in range(61000, 65001):
        h = hashlib.sha256(f"mini-v2-{i}".encode()).hexdigest()
        extra.append((h, i))
    extra.sort()
    order += [p for _h, p in extra[:200] if p not in order]

    for p in order:
        try:
            if _free(p):
                if p != first:
                    # 挪了端口 → 记住
                    save({"port": p})
                return p
        except Exception:                              # noqa: BLE001
            continue
    return first                                        # 实在不行就硬上


def find_dsh_bin() -> str:
    """找 dsh 的 bin.js。

    ✅ 交给 find 模块统一查找。它会试：
        ① 配置里写的
        ② MINI_DSH 环境变量
        ③ npm 全局（问 npm 自己 root -g）
        ④ 常见安装位置（APPDATA、/usr/local/lib…）
        ⑤ pnpm / yarn 的全局目录
        ⑥ 项目自己的 node_modules
        ⑦ PATH 里的 dsh 包装脚本
    """
    # ① 配置优先
    cfg = get("dsh_bin") or ""
    if cfg and Path(cfg).exists():
        return cfg

    from . import find
    p = find.dsh_bin()
    return str(p) if p else ""
