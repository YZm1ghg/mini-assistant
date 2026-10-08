# -*- coding: utf-8 -*-
"""
自动查找 · find

所有"外部依赖在哪"的问题都集中在这里。

为什么要有这个模块
------------------
    如果让各个模块自己写死路径，结果是：
    **换个电脑就跑不起来**，用户得自己翻代码改。

    所以统一到这里，每个都做**多路探测 + 环境变量覆盖**：
        ① 用户显式指定的（环境变量 / config.json）
        ② 常见安装位置
        ③ 项目自己的目录（绿色版会带）
        ④ 系统能查到的（注册表 / PATH / where）

    查不到就返回 None，让调用方优雅降级 —— 不崩。

环境变量
--------
    MINI_CHATLAB    ChatLab 数据库目录
    MINI_MODELS     模型总目录（下面找 funasr/ whisper/ text2vec/）
    MINI_DSH        dsh 的 bin.js
    MINI_NODE       node.exe
    MINI_FFMPEG     ffmpeg.exe
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import sys
from pathlib import Path
from typing import Optional


# ============================================================
#  基础工具
# ============================================================
def home() -> Path:
    """用户家目录。跨平台。"""
    for k in ("MINI_HOME", "USERPROFILE", "HOME"):
        v = os.environ.get(k)
        if v:
            p = Path(v)
            if p.exists():
                return p
    return Path.home()


def _first_existing(cands: list) -> Optional[Path]:
    for c in cands:
        if c is None:
            continue
        try:
            p = Path(c)
            if p.exists():
                return p
        except Exception:                              # noqa: BLE001
            continue
    return None


def _which(*names: str) -> Optional[Path]:
    """在 PATH 里找。"""
    for n in names:
        p = shutil.which(n)
        if p:
            return Path(p)
    return None


def _env(*names: str) -> Optional[str]:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


# ============================================================
#  node / dsh
# ============================================================
def node() -> Optional[Path]:
    """找 node.exe。

    ① MINI_NODE 环境变量
    ② PATH
    ③ 常见安装位置
    ④ nvm / fnm 的管理目录
    """
    v = _env("MINI_NODE")
    if v and Path(v).exists():
        return Path(v)

    p = _which("node.exe", "node")
    if p:
        return p

    cands = [
        Path(r"<node 目录>\node.exe"),
        Path(r"C:\Program Files (x86)\nodejs\node.exe"),
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
        Path("/opt/homebrew/bin/node"),
    ]
    # nvm-windows / fnm
    for base in (
        home() / "AppData" / "Roaming" / "nvm",
        home() / ".nvm" / "versions" / "node",
        home() / "AppData" / "Local" / "fnm_multishells",
        home() / ".local" / "share" / "fnm" / "node-versions",
    ):
        try:
            if base.exists():
                for d in sorted(base.rglob("node.exe"),
                                reverse=True):
                    cands.append(d)
        except Exception:                              # noqa: BLE001
            continue
    return _first_existing(cands)


def dsh_bin() -> Optional[Path]:
    """找 dsh 的 bin.js。

    ① MINI_DSH 环境变量
    ② npm 全局（APPDATA/npm、/usr/local/lib、/usr/lib）
    ③ PATH 里的 dsh（可能是 .cmd/.sh 包装）
    ④ pnpm / yarn 全局
    ⑤ npx 缓存
    """
    v = _env("MINI_DSH")
    if v and Path(v).exists():
        return Path(v)

    rel = Path("@deepseek-ai") / "dsh" / "lib" / "bin.js"
    cands: list[Path] = []

    # ---- npm 全局 ----
    for base in (
        _env("APPDATA") and
        Path(_env("APPDATA")) / "npm" / "node_modules",
        home() / "AppData" / "Roaming" / "npm" / "node_modules",
        Path("/usr/local/lib/node_modules"),
        Path("/usr/lib/node_modules"),
        home() / ".npm-global" / "lib" / "node_modules",
    ):
        if base:
            cands.append(Path(base) / rel)

    # ---- npm 的 prefix（从 npm 自己问）----
    try:
        r = subprocess.run(
            ["npm", "root", "-g"], capture_output=True, text=True,
            encoding="utf-8", errors="ignore", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            shell=(os.name == "nt"))
        root = (r.stdout or "").strip()
        if root and Path(root).exists():
            cands.append(Path(root) / rel)
    except Exception:                                  # noqa: BLE001
        pass

    # ---- pnpm ----
    for base in (
        _env("PNPM_HOME") and Path(_env("PNPM_HOME")),
        home() / "AppData" / "Local" / "pnpm",
        home() / ".local" / "share" / "pnpm",
    ):
        if base:
            cands.append(Path(base) / "node_modules" / rel)

    # ---- 项目自己的 node_modules（本地安装）----
    try:
        from . import config
        cands.append(config.ROOT / "node_modules" / rel)
    except Exception:                                  # noqa: BLE001
        pass

    hit = _first_existing(cands)
    if hit:
        return hit

    # ---- 兜底：PATH 里有 dsh 就用它 ----
    p = _which("dsh.cmd", "dsh", "dsh.ps1", "dsh.sh")
    return p


# ============================================================
#  ChatLab（微信数据）
# ============================================================
def chatlab_dirs() -> list[Path]:
    """找 ChatLab 的数据库目录。可能有好几个位置。

    ① MINI_CHATLAB 环境变量
    ② 家目录下的 .chatlab / ChatLab / chatlab
    ③ Windows 的 AppData / 文档
    ④ 项目自己的 data/chatlab
    """
    out: list[Path] = []

    v = _env("MINI_CHATLAB")
    if v:
        out.append(Path(v))
        # 也可能是父目录，往下找一层
        out.append(Path(v) / "data" / "databases")

    h = home()
    bases = [
        h / ".chatlab",
        h / "ChatLab",
        h / "chatlab",
        h / "Documents" / "ChatLab",
        h / "文档" / "ChatLab",
        h / "AppData" / "Roaming" / "ChatLab",
        h / "AppData" / "Local" / "ChatLab",
        Path("/Applications/ChatLab"),
        h / ".local" / "share" / "chatlab",
    ]
    for b in bases:
        out.append(b / "data" / "databases")
        out.append(b / "databases")
        out.append(b)

    # 项目自己带一份（绿色版）
    try:
        from . import config
        out.append(config.DATA_DIR / "chatlab")
    except Exception:                                  # noqa: BLE001
        pass

    # 只留真的存在且**里面有 chat_*.db** 的
    good: list[Path] = []
    seen: set[str] = set()
    for p in out:
        try:
            rp = p.resolve()
        except Exception:                              # noqa: BLE001
            continue
        # ⚠ 用 resolve() 后的路径去重 ——
        #   不同候选（如 ~/.chatlab/data/databases 和
        #   ~/.chatlab/databases）可能指向同一个地方
        key = str(rp).lower()
        if key in seen:
            continue
        seen.add(key)
        if not p.exists():
            continue
        # 自己就是数据库目录
        if list(p.glob("chat_*.db")):
            good.append(rp)
            continue
        # 或者下层有
        try:
            for sub in p.rglob("chat_*.db"):
                sub_key = str(sub.parent.resolve()).lower()
                if sub_key not in seen:
                    seen.add(sub_key)
                    good.append(sub.parent.resolve())
                break
        except Exception:                              # noqa: BLE001
            continue
    return good


# ============================================================
#  模型
# ============================================================
def model_roots() -> list[Path]:
    """模型总目录的候选位置。"""
    out: list[Path] = []
    v = _env("MINI_MODELS")
    if v:
        out.append(Path(v))
    for p in (
        Path(r"<模型目录>"), Path(r"C:\models"), Path("E:/models"),
    ):
        out.append(p)
    out.append(home() / "models")
    try:
        from . import config
        out.append(config.ROOT / "models")
    except Exception:                                  # noqa: BLE001
        pass
    return [p for p in out if p and p.exists()]


def funasr_model() -> Optional[Path]:
    """找 FunASR 中文识别模型。

    ⚠ 必须返回**本地目录**，不能只给模型名 ——
      给名字会触发联网校验，被代理拦掉后既慢又失败。

    ⚠⚠ 目录层级很容易搞错（踩过）：
      真实位置是
          D:\\models\\funasr\\models\\iic--...\\snapshots\\master
                        ↑ 多了一层 funasr
      而有的机器是
          D:\\models\\models\\iic--...\\snapshots\\master
      还有 ModelScope 官方缓存
          ~/.cache/modelscope/models/iic--...
      所以不能写死层级 —— 直接**递归找 model.pt**，
      找到后校验同目录有没有 config.yaml（区分 ASR 模型和别的）。

    ① MINI_FUNASR 环境变量（最优先）
    ② 各模型根目录下递归搜
    ③ ModelScope 缓存
    """
    v = _env("MINI_FUNASR")
    if v:
        p = Path(v)
        if (p / "model.pt").exists():
            return p
        for sub in p.rglob("model.pt"):
            return sub.parent
        return None

    roots = list(model_roots())
    ms = _env("MODELSCOPE_CACHE")
    if ms:
        roots.append(Path(ms))
    roots += [
        home() / ".cache" / "modelscope",
        home() / ".cache" / "modelscope" / "hub",
        home() / ".cache" / "funasr",
    ]

    # 中文 ASR 模型目录名的特征词
    keys = ("speech_seaco_paraformer", "speech_paraformer",
            "sensevoicesmall", "sensevoice")
    best: Optional[Path] = None
    for root in roots:
        try:
            if not root.exists():
                continue
        except Exception:                              # noqa: BLE001
            continue
        try:
            for mp in root.rglob("model.pt"):
                d = mp.parent
                name = str(d).lower()
                if not any(k in name for k in keys):
                    continue
                # 校验是完整模型（有 config.yaml 或 config.json）
                if not ((d / "config.yaml").exists()
                        or (d / "config.json").exists()):
                    continue
                # 多个的话，取路径最短的（最可能是正规位置）
                if best is None or len(str(d)) < len(str(best)):
                    best = d
        except Exception:                              # noqa: BLE001
            continue
        if best is not None:
            return best
    return best


def whisper_model() -> Optional[Path]:
    """找 faster-whisper 的本地模型。"""
    v = _env("MINI_WHISPER")
    if v:
        p = Path(v)
        if (p / "model.bin").exists():
            return p
        for sub in p.rglob("model.bin"):
            return sub.parent

    cands: list[Path] = []
    for root in model_roots():
        for n in ("whisper/tiny", "whisper/base", "whisper/small",
                  "faster-whisper/tiny", "tiny", "base"):
            cands.append(root / n.replace("/", os.sep))
    for p in cands:
        if (p / "model.bin").exists():
            return p
    return None


def text2vec_model() -> Optional[Path]:
    """找中文向量模型。

    HuggingFace 缓存结构：
        ~/.cache/huggingface/hub/models--<作者>--<名字>/snapshots/<提交>/
    """
    v = _env("MINI_TEXT2VEC")
    if v:
        p = Path(v)
        if (p / "config.json").exists():
            return p
        for sub in p.rglob("config.json"):
            return sub.parent

    roots = [
        home() / ".cache" / "huggingface" / "hub",
        home() / ".cache" / "torch" / "sentence_transformers",
        home() / "AppData" / "Local" / "huggingface" / "hub",
    ]
    names = [
        "models--shibing624--text2vec-base-chinese",
        "models--shibing624--text2vec-large-chinese",
        "models--BAAI--bge-small-zh-v1.5",
        "models--BAAI--bge-base-zh-v1.5",
    ]
    for root in roots + model_roots():
        for n in names:
            try:
                snap = root / n / "snapshots"
                if snap.exists():
                    for s in sorted(snap.iterdir(), reverse=True):
                        if (s / "config.json").exists():
                            return s
                # 不在 HF 缓存结构里，直接是模型目录
                d = root / n.replace("models--", "")
                if (d / "config.json").exists():
                    return d
            except Exception:                          # noqa: BLE001
                continue
        # 项目自带的
        for n in ("text2vec-base-chinese", "bge-small-zh-v1.5"):
            d = root / n
            try:
                if (d / "config.json").exists():
                    return d
            except Exception:                          # noqa: BLE001
                continue
    return None


def kokoro_model() -> Optional[Path]:
    """找 Kokoro 中文语音合成模型（可选）。"""
    for root in model_roots():
        for n in ("kokoro-zh", "Kokoro-82M-v1.1-zh", "kokoro"):
            d = root / n
            try:
                if d.exists():
                    return d
            except Exception:                          # noqa: BLE001
                continue
    return None


# ============================================================
#  其他
# ============================================================
def ffmpeg() -> Optional[Path]:
    """找 ffmpeg（切音频要用）。"""
    v = _env("MINI_FFMPEG")
    if v and Path(v).exists():
        return Path(v)
    p = _which("ffmpeg.exe", "ffmpeg")
    if p:
        return p
    return _first_existing([
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"D:\ffmpeg\bin\ffmpeg.exe"),
        Path("/usr/local/bin/ffmpeg"),
        Path("/opt/homebrew/bin/ffmpeg"),
    ])


def browser() -> Optional[Path]:
    """找一个能开网页 / 做无头截图的浏览器。"""
    v = _env("MINI_BROWSER")
    if v and Path(v).exists():
        return Path(v)
    p = _which("msedge.exe", "chrome.exe", "google-chrome",
               "chromium", "msedge", "chrome")
    if p:
        return p
    return _first_existing([
        Path(r"C:\Program Files (x86)\Microsoft\Edge"
             r"\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge"
             r"\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome"
             r"\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome"
             r"\Application\chrome.exe"),
        Path("/Applications/Google Chrome.app/Contents/MacOS"
             "/Google Chrome"),
        Path("/usr/bin/google-chrome"),
    ])


# ============================================================
#  总览（给界面/日志用）
# ============================================================
_report_cache: dict = {}
_report_at: float = 0.0
_REPORT_TTL = 120.0          # 秒


def report(fresh: bool = False) -> dict:
    """一次把关键依赖都查一遍，返回结果。

    ⚠⚠ 必须缓存（踩过）：
      这个函数里有几个**很慢**的操作：
        · funasr_model() 要递归搜 model.pt（扫全盘）
        · dsh_bin() 可能要跑 `npm root -g`（启动子进程）
        · browser() / ffmpeg() 要查 PATH 和多个目录

      实测**每次 4.5 秒**。而 /api/state 会被界面每 15 秒
      调一次、启动横幅也调 —— 不缓存的话整个界面都是卡的。

      ✅ 结果缓存 120 秒。依赖不太可能在两分钟内变。
         真要重查传 fresh=True。
    """
    global _report_cache, _report_at
    now = time.time()
    if (not fresh and _report_cache
            and now - _report_at < _REPORT_TTL):
        return _report_cache

    n = node()
    d = dsh_bin()
    cl = chatlab_dirs()
    out = {
        "home": str(home()),
        "node": str(n) if n else "",
        "dsh": str(d) if d else "",
        "chatlab": [str(x) for x in cl],
        "funasr": str(funasr_model() or ""),
        "whisper": str(whisper_model() or ""),
        "text2vec": str(text2vec_model() or ""),
        "kokoro": str(kokoro_model() or ""),
        "ffmpeg": str(ffmpeg() or ""),
        "browser": str(browser() or ""),
        "model_roots": [str(x) for x in model_roots()],
    }
    _report_cache = out
    _report_at = now
    return out


def clear_cache() -> None:
    """清掉 report 缓存（装了新东西后手动刷用）。"""
    global _report_cache, _report_at
    _report_cache = {}
    _report_at = 0.0
