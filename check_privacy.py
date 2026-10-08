# -*- coding: utf-8 -*-
"""
分享前检查 —— 一键确认没有隐私

用法：
    python -B check_privacy.py

检查什么：
    · 本机 IP / 主机名 / 用户名 / 家目录 / MAC
    · 真实姓名昵称微信号
    · 手机号 / 邮箱 / API 密钥 / 私钥
    · 不该带的数据文件（录音 / 截图 / 数据库 / 向量）
    · local.properties（含本机绝对路径）
    · **APK 内部**（dex 和 assets）
    · 非官方外链

⚠ 一定带 -B 参数运行（不生成 __pycache__）。
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ---- 本机信息，用来反查 ----
HOME = str(Path.home())
USER = os.environ.get("USERNAME") or os.environ.get("USER") or ""
HOST = socket.gethostname()


def _ipconfig() -> str:
    """跑一次 ipconfig 拿全文（缓存，因为要解析好几样东西）。"""
    if os.name != "nt":
        return ""
    try:
        r = subprocess.run(["ipconfig", "/all"],
                           capture_output=True, text=True,
                           encoding="gbk", errors="ignore",
                           timeout=25,
                           creationflags=getattr(
                               subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout or ""
    except Exception:
        return ""


def _local_ips() -> set:
    """本机所有 IPv4（含网关、DNS —— 它们也是你的网络指纹）。"""
    out = set()
    txt = _ipconfig()
    for m in re.finditer(r"IPv4[^:]*:\s*([\d.]+)", txt):
        out.add(m.group(1))
    # ⚠ 网关和 DNS 也要算 ——
    #   它们和 IP 一样能定位你在哪个网络
    for m in re.finditer(r"默认网关[^:]*:\s*([\d.]+)", txt):
        out.add(m.group(1))
    for m in re.finditer(r"DNS 服务器[^:]*:\s*([\d.]+)", txt):
        out.add(m.group(1))
    try:
        out.add(socket.gethostbyname(HOST))
    except Exception:
        pass
    return out


def _wifi_names() -> set:
    """连过的 Wi-Fi 名字 —— 这是很强的身份指纹。"""
    if os.name != "nt":
        return set()
    try:
        r = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, encoding="gbk",
            errors="ignore", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {s.strip() for s in
                re.findall(r"SSID\s*:\s*(.+)", r.stdout or "")
                if s.strip()}
    except Exception:
        return set()


def _local_macs() -> set:
    """本机 MAC（带 - 分隔的大写形式）。"""
    if os.name != "nt":
        return set()
    try:
        r = subprocess.run(["getmac", "/fo", "csv", "/nh"],
                           capture_output=True, text=True,
                           encoding="gbk", errors="ignore",
                           timeout=20,
                           creationflags=getattr(
                               subprocess, "CREATE_NO_WINDOW", 0))
        return set(re.findall(
            r"([0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5})",
            r.stdout or ""))
    except Exception:
        return set()


MY_IPS = _local_ips()
MY_MACS = _local_macs()
MY_WIFI = _wifi_names()

# ---- 要查的标识 ----
#
# ⚠ 这些都会**逐字节**去文件里找（含 APK 内部）。
#   加得越全，漏掉的可能越小。
IDENT = [("主机名", HOST),
         ("用户名", USER),
         ("家目录", HOME)]
for ip in MY_IPS:
    IDENT.append(("本机IP", ip))
for m in MY_MACS:
    IDENT.append(("MAC", m))
    IDENT.append(("MAC(无分隔)", m.replace("-", "")))
for w in MY_WIFI:
    IDENT.append(("WiFi名", w))

# ---- 别的模式 ----
DANGER = [
    ("微信ID", r"wxid_[A-Za-z0-9_-]{6,}"),
    ("手机号", r"\b1[3-9]\d{9}\b"),
    ("真实邮箱", r"[\w.+-]+@(?!example|test|mail\.com)[\w-]+"
                 r"\.[a-z]{2,}"),
    ("内网IP", r"\b(?:10|192[.]168|172[.](?:1[6-9]|2\d|3[01]))"
               r"[.]\d{1,3}[.]\d{1,3}\b"),
    ("公网IP", r"\b(?!127[.]|0[.]|255[.]|1[.]|2[.])\d{1,3}"
               r"[.]\d{1,3}[.]\d{1,3}[.]\d{1,3}\b"),
    ("OpenAI密钥", r"sk-[A-Za-z0-9]{16,}"),
    ("GitHub令牌", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("AWS密钥", r"AKIA[0-9A-Z]{16}"),
    ("私钥", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("DPAPI密文", r"safe:v10:"),
]

# ---- 角色卡 / 二次元元素 ----
#
# ⚠ 分享版是**纯工具**，不该带任何：
#     · 私人角色卡（里面是朋友的真名）
#     · 二次元/赛博朋克装饰
#
# ⚠⚠ 这里的词表只能检测**新增**，检测不了"没有"。
#   但它能提醒你：如果你不小心把开发版的东西拷进来了，
#   这一项会立刻报警。
ANIME_WORDS = [
    "角色卡", "立绘", "皮套", "赛博朋克", "霓虹",
    "live2d", "vtuber", "arc reactor", "光环反应堆",
    "sprite_", "mascot_",
]

# 角色卡数据文件（这些文件名一出现就说明混进来了）
ROLE_FILES = ["roles.json", "role_cards.json", "characters.json",
              "persona.json", "roledata.json"]


# ---- 不该带的文件 ----
BAD_EXT = {
    ".wav": "录音", ".mp3": "音频", ".m4a": "音频", ".flac": "音频",
    ".jpg": "图片", ".jpeg": "图片", ".png": "截图", ".webp": "图片",
    ".db": "聊天数据库", ".sqlite": "数据库", ".sqlite3": "数据库",
    ".jsonl": "记录", ".npy": "向量", ".npz": "向量",
    ".dvn": "保险箱卷", ".key": "密钥", ".log": "日志",
    ".pyc": "编译缓存", ".pyo": "编译缓存",
}

# ---- 一定不能带的文件（按名字） ----
BAD_NAMES = {
    "local.properties": "含本机 SDK 绝对路径（用户名会泄露）",
    ".hold.json": "保险箱持有记录",
}

ALLOW_NAMES = {"config.example.json"}

# ---- 允许的外链 ----
OK_HOSTS = (
    "127.0.0.1", "localhost",
    # 官方
    "python.org", "nodejs.org", "npmjs.com", "pypi.org",
    "github.com", "ffmpeg.org", "chatlab.fun",
    "huggingface.co", "hf-mirror.com", "modelscope.cn",
    "sbert.net", "deepseek.com", "deepseek-ai",
    "docs.python.org", "readthedocs.io", "opencv.org",
    # 国内镜像（README 里用来加速下载的，不是隐私）
    "npmmirror.com", "tsinghua.edu.cn", "aliyun.com",
    "ustc.edu.cn", "douban.com",
    # 技能里"打开网站"用的常见站点
    "baidu.com", "bilibili.com", "taobao.com", "zhihu.com",
    "google.com", "bing.com", "weibo.com", "jd.com",
    # 构建工具官网
    "gradle.org", "adoptium.net", "developer.android.com",
    "android.com", "jetbrains.com", "microsoft.com",
    "bell-sw.com", "oracle.com",
    # gradlew.bat 里的许可证链接（Gradle 用 Apache 2.0）
    "apache.org", "opensource.org", "gnu.org",
    # README 里的徽章图片（shields.io 是标准做法）
    "shields.io", "badgen.net",
    # README 里链接到的官方文档
    "pypi.org", "docs.python.org", "support.microsoft.com",
)

TEXT_EXT = {".py", ".md", ".txt", ".html", ".htm", ".js", ".css",
            ".json", ".bat", ".cmd", ".sh", ".ps1", ".gradle",
            ".xml", ".properties", ".java", ".yml", ".yaml",
            ".cfg", ".ini", ".toml"}

SKIP_PARTS = {"__pycache__", ".gradle", "build", ".git"}


def _iter_files(skip_dist: bool = True):
    for f in sorted(ROOT.rglob("*")):
        if not f.is_file():
            continue
        if any(p in f.parts for p in SKIP_PARTS):
            continue
        if skip_dist and "dist" in f.parts and f.suffix == ".apk":
            continue
        yield f


# ============================================================
#  自动修复
# ============================================================
def auto_fix() -> int:
    """删掉「一定不该带」的东西。

    ⚠ 只删**文件**，不碰**内容**。
      自动改文本太危险 —— 正则匹配错了会毁掉代码。
      内容问题只报告，让人自己判断。
    """
    import shutil

    n = 0

    # ① local.properties（gradle 生成，含本机绝对路径）
    for f in ROOT.rglob("local.properties"):
        try:
            f.unlink()
            print(f"    删 {f.relative_to(ROOT)}")
            n += 1
        except Exception as e:
            print(f"    ✗ {f}: {e}")

    # ② 运行时数据目录
    d = ROOT / "data"
    if d.exists():
        try:
            shutil.rmtree(d, ignore_errors=True)
            print(f"    删 data/（运行时数据）")
            n += 1
        except Exception as e:
            print(f"    ✗ data/: {e}")

    # ③ __pycache__（里面是绝对路径）
    for f in list(ROOT.rglob("__pycache__")):
        try:
            shutil.rmtree(f, ignore_errors=True)
            n += 1
        except Exception:
            pass
    # 清理时不要打印太多，只报总数
    if n:
        print(f"    （__pycache__ 一并清了）")

    # ④ 各类不该带的文件
    for f in list(ROOT.rglob("*")):
        if not f.is_file():
            continue
        if any(x in f.parts for x in ("__pycache__", ".gradle",
                                      "build")):
            continue
        if f.name in ALLOW_NAMES:
            continue
        if f.name in BAD_NAMES or f.suffix.lower() in BAD_EXT:
            try:
                f.unlink()
                print(f"    删 {f.relative_to(ROOT)}")
                n += 1
            except Exception:
                pass
        elif f.parts and f.parts[0] == "data":
            try:
                f.unlink()
                n += 1
            except Exception:
                pass

    # ⑤ 构建中间产物（含 assets 拷贝）
    for name in ("phone", "tablet", "watch"):
        for sub in ("build", "app/build", ".gradle",
                    "app/src/main/assets"):
            q = ROOT / "mobile" / name / sub
            if q.exists():
                shutil.rmtree(q, ignore_errors=True)
                n += 1

    return n


def main() -> int:
    fix = "--fix" in sys.argv

    print()
    print("=" * 70)
    print("  分享前隐私检查")
    if fix:
        print("  （--fix 模式：会删掉不该带的文件）")
    print("=" * 70)
    print(f"\n  检查目录 : {ROOT}")
    print(f"  本机信息 : 主机名 {HOST}")
    print(f"             用户名 {USER}")
    print(f"             家目录 {HOME}")
    print(f"             IP     {', '.join(sorted(MY_IPS)) or '(无)'}")
    print(f"             MAC    {len(MY_MACS)} 个")
    if MY_WIFI:
        print(f"             WiFi   {', '.join(sorted(MY_WIFI))[:50]}")

    issues: list[str] = []

    # ---- 1. 文件 ----
    print("\n" + "-" * 70)
    print("  [1] 不该带的文件")
    print("-" * 70)
    bad = []
    for f in _iter_files():
        rel = f.relative_to(ROOT)
        if f.name in ALLOW_NAMES:
            continue
        if f.name in BAD_NAMES:
            bad.append((rel, BAD_NAMES[f.name]))
        elif f.suffix.lower() in BAD_EXT:
            bad.append((rel, BAD_EXT[f.suffix.lower()]))
        elif rel.parts and rel.parts[0] == "data":
            bad.append((rel, "运行时数据"))
    if bad:
        for rel, why in bad:
            print(f"    ⚠ {rel}  （{why}）")
            issues.append(f"文件 {rel}")
        if fix:
            print()
            print("    自动修复:")
            n = auto_fix()
            print(f"      删了 {n} 项")
            # 删完重新查一遍这一节
            bad2 = []
            for f in _iter_files():
                rel = f.relative_to(ROOT)
                if f.name in ALLOW_NAMES:
                    continue
                if (f.name in BAD_NAMES
                        or f.suffix.lower() in BAD_EXT
                        or (rel.parts and rel.parts[0] == "data")):
                    bad2.append(rel)
            if not bad2:
                issues = [x for x in issues
                          if not x.startswith("文件 ")]
                print("      ✓ 清干净了")
    else:
        print("    ✓ 没有")

    # ---- 2. 文本里的标识 ----
    print("\n" + "-" * 70)
    print("  [2] 文本里的本机标识")
    print("-" * 70)
    hits = []
    n = 0
    self_path = Path(__file__).resolve()
    for f in _iter_files():
        if f.suffix.lower() not in TEXT_EXT and f.name != ".gitignore":
            continue
        # 别查自己（里面写着要匹配的关键词）
        if f.resolve() == self_path:
            continue
        n += 1
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for label, key in IDENT:
            if not key or len(key) < 4:
                continue
            # ⚠ **大小写敏感**（踩过）：
            #   忽略大小写地找用户名，会命中英文单词里的片段
            #   （比如 outputXyz 中间的 tXyz），报假问题。
            #   真名在路径里就是原样出现的。
            for m in re.finditer(re.escape(key), t):
                ln = t[:m.start()].count("\n") + 1
                line = t.split("\n")[ln - 1].strip()[:66]
                hits.append((f.relative_to(ROOT), ln, label, key,
                             line))
    print(f"    （查了 {n} 个文本文件）")
    if hits:
        seen = set()
        for rel, ln, label, key, line in hits:
            k = (str(rel), ln, label)
            if k in seen:
                continue
            seen.add(k)
            print(f"    ⚠ {rel}:{ln}  [{label}] {key}")
            print(f"        {line}")
            issues.append(f"{label} {rel}:{ln}")
    else:
        print("    ✓ 没有")

    # ---- 3. 别的敏感模式 ----
    print("\n" + "-" * 70)
    print("  [3] 密钥 / 个人信息")
    print("-" * 70)
    hits2 = []
    self_path = Path(__file__).resolve()
    for f in _iter_files():
        if f.suffix.lower() not in TEXT_EXT and f.name != ".gitignore":
            continue
        # ⚠ 别查自己（踩过）——
        #   这个文件里写着各种要匹配的正则，
        #   不排除的话它自己会命中自己，
        #   报一堆假问题出来。
        if f.resolve() == self_path:
            continue
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for label, pat in DANGER:
            try:
                for m in re.finditer(pat, t):
                    s = m.group(0)
                    if s in ("127.0.0.1", "0.0.0.0",
                             "255.255.255.0", "你的用户名"):
                        continue
                    # 默认端口不是隐私
                    if s == "64874":
                        continue
                    # ⚠ 「端口」这种词不算（README 里会讲端口）
                    if s.startswith("http"):
                        continue
                    ln = t[:m.start()].count("\n") + 1
                    line = t.split("\n")[ln - 1].strip()[:62]
                    hits2.append((f.relative_to(ROOT), ln, label,
                                  s[:34], line))
            except re.error:
                continue
    if hits2:
        seen = set()
        for rel, ln, label, s, line in hits2:
            k = (str(rel), label, s)
            if k in seen:
                continue
            seen.add(k)
            print(f"    ⚠ {rel}:{ln}  [{label}]  {s}")
            print(f"        {line}")
            issues.append(f"{label} {rel}:{ln}")
    else:
        print("    ✓ 没有")

    # ---- 4. APK 内部 ----
    print("\n" + "-" * 70)
    print("  [4] APK 内部")
    print("-" * 70)
    dist = ROOT / "mobile" / "dist"
    apks = sorted(dist.glob("*.apk")) if dist.exists() else []
    if not apks:
        print("    （没有 APK）")
    for p in apks:
        try:
            z = zipfile.ZipFile(p)
        except Exception as e:
            print(f"    ✗ {p.name}: {e}")
            continue
        bad2 = []
        for nm in z.namelist():
            if not (nm.endswith(".dex") or "assets/" in nm
                    or nm.endswith(".arsc")):
                continue
            raw = z.read(nm)

            # ⚠⚠ 用**字节精确匹配**，不要 decode、也不要忽略大小写
            #
            #   踩过两次：
            #   ① 先 decode 再找 → dex 用的是 MUTF-8，
            #      decode 时有些字节会被丢掉或替换，
            #      出现「明明没有却报有」的假阳性。
            #   ② 忽略大小写地找 → 用户名会命中 Android
            #      系统库里的英文单词（比如 outputXyz 中间那段
            #      刚好和某个用户名重了），也是假阳性。
            #
            #   ✅ 直接 raw.count(字节)，大小写敏感。
            #      真名在路径里就是原样出现的，不会漏。
            for label, key in IDENT:
                if not key or len(key) < 4:
                    continue
                try:
                    kb = key.encode("utf-8")
                except Exception:
                    continue
                if kb in raw:
                    bad2.append((nm, label, key))

            # 密钥样式：ASCII，直接字节正则
            for m in re.finditer(rb"(?:sk-|gh[pousr]_|AKIA)"
                                 rb"[A-Za-z0-9]{16,}", raw):
                bad2.append((nm, "密钥",
                             m.group(0).decode("ascii",
                                               "ignore")[:14] + "…"))
        if bad2:
            print(f"    ⚠ {p.name}")
            for nm, label, key in bad2[:6]:
                print(f"        {nm}  [{label}] {key}")
            issues.append(f"APK {p.name}")
        else:
            print(f"    ✓ {p.name}")

    # ---- 4.5 角色卡 / 二次元 ----
    print("\n" + "-" * 70)
    print("  [4b] 角色卡 / 二次元元素")
    print("-" * 70)
    an = []

    # ① 数据文件
    for f in _iter_files(skip_dist=False):
        if f.name.lower() in ROLE_FILES:
            an.append((f.relative_to(ROOT), "角色卡数据文件"))

    # ② 关键词
    self_p = Path(__file__).resolve()
    for f in _iter_files():
        if f.suffix.lower() not in TEXT_EXT:
            continue
        if f.resolve() == self_p:
            continue
        try:
            tx = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for w in ANIME_WORDS:
            for m in re.finditer(re.escape(w), tx, re.I):
                ln = tx[:m.start()].count("\n") + 1
                line = tx.split("\n")[ln - 1].strip()[:60]
                an.append((f"{f.relative_to(ROOT)}:{ln}", w))

    if an:
        for where, what in an[:14]:
            print(f"    ⚠ {where}  {what}")
            issues.append(f"二次元 {where}")
    else:
        print("    ✓ 没有")

    # ---- 5. 外链 ----
    print("\n" + "-" * 70)
    print("  [5] 非官方外链")
    print("-" * 70)
    links = []
    for f in _iter_files():
        if f.suffix.lower() not in TEXT_EXT and f.name != ".gitignore":
            continue
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r"https?://([\w.-]+)", t):
            host = m.group(1).lower()
            if host in ("0.0.0.0", "127.0.0.1", "localhost"):
                continue
            if any(host.endswith(h) or h in host for h in OK_HOSTS):
                continue
            links.append((f.relative_to(ROOT), host))
    if links:
        seen = set()
        for rel, host in links:
            if host in seen:
                continue
            seen.add(host)
            print(f"    ⚠ {rel}  {host}")
            issues.append(f"外链 {host}")
    else:
        print("    ✓ 全是官方地址")

    # ---- 总结 ----
    print("\n" + "=" * 70)
    if issues:
        print(f"  ⚠ 发现 {len(issues)} 个问题，分享前请处理")
        print("=" * 70)
        print()
        for x in issues[:24]:
            print(f"    · {x}")
        print()
        return 1
    print("  ✓✓ 没有发现个人信息，可以分享")
    print("=" * 70)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
