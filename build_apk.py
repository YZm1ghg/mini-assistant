# -*- coding: utf-8 -*-
"""
构建脚本 —— 把网页打包进三个 APK

用法：
    python build_apk.py            # 打包全部三个
    python build_apk.py phone      # 只打手机版
    python build_apk.py --clean    # 清掉构建产物

============================================================
它做什么
============================================================
    ① 把 mobile/common/www/ 拷进各版本的 app/src/main/assets/www/
    ② 生成 gradle wrapper（第一次运行时）
    ③ 调 gradle assembleRelease
    ④ 把 APK 拷到 mobile/dist/ 并改成好认的名字

============================================================
找工具链
============================================================
    Gradle 和 Android SDK 都不写死路径 —— 按顺序找：
      · JAVA_HOME / ANDROID_HOME / ANDROID_SDK_ROOT 环境变量
      · 常见的安装目录
      · ~/.gradle/wrapper/dists 里已有的 gradle 发行版
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MOBILE = ROOT / "mobile"
WWW = MOBILE / "common" / "www"
DIST = MOBILE / "dist"

VARIANTS = {
    "phone": {"name": "迷你助手", "apk": "mini-phone.apk"},
    "tablet": {"name": "迷你助手-平板", "apk": "mini-tablet.apk"},
    "watch": {"name": "迷你助手-手表", "apk": "mini-watch.apk"},
}


# ============================================================
#  找工具
# ============================================================
def find_gradle() -> str | None:
    """找 gradle.bat。"""
    # ① PATH
    for n in ("gradle.bat", "gradle"):
        p = shutil.which(n)
        if p:
            return p

    # ② ~/.gradle/wrapper/dists 里已经下好的发行版
    home = Path(os.path.expanduser("~"))
    dists = home / ".gradle" / "wrapper" / "dists"
    if dists.exists():
        cands = sorted(dists.glob("gradle-*/**/bin/gradle.bat"),
                       reverse=True)
        if cands:
            return str(cands[0])

    # ③ 常见安装位置
    for base in (r"C:\Gradle", r"D:\Gradle", r"C:\tools\gradle"):
        p = Path(base)
        if p.exists():
            c = sorted(p.glob("gradle-*/bin/gradle.bat"),
                       reverse=True)
            if c:
                return str(c[0])
    return None


def find_sdk() -> str | None:
    """找 Android SDK。"""
    for k in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(k)
        if v and Path(v).exists():
            return v
    home = Path(os.path.expanduser("~"))
    cands = [
        home / "AppData" / "Local" / "Android" / "Sdk",
        home / "Android" / "Sdk",
        Path(r"C:\Android\Sdk"),
        Path(r"D:\Android\Sdk"),
    ]
    for c in cands:
        if c.exists() and (c / "platforms").exists():
            return str(c)
    return None


def find_java() -> str | None:
    """找 JDK。"""
    v = os.environ.get("JAVA_HOME")
    if v and Path(v).exists():
        return v
    home = Path(os.path.expanduser("~"))
    pats = [
        r"C:\Program Files\BellSoft\LibericaJDK-*",
        r"C:\Program Files\Java\jdk-*",
        r"C:\Program Files\Eclipse Adoptium\jdk-*",
        r"C:\Program Files\Microsoft\jdk-*",
    ]
    import glob
    for pat in pats:
        hits = sorted(glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    return None


# ============================================================
#  步骤
# ============================================================
def step(msg: str) -> None:
    print(f"\n  ── {msg}")


def copy_www(variant: str) -> int:
    """把共用网页拷进这一版的 assets。"""
    dst = MOBILE / variant / "app" / "src" / "main" / "assets" / "www"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    n = 0
    for f in WWW.iterdir():
        if f.is_file():
            shutil.copy2(f, dst / f.name)
            n += 1
    return n


def ensure_wrapper(variant: str, gradle: str) -> None:
    """生成 gradle wrapper（有就不用重做）。"""
    d = MOBILE / variant
    if (d / "gradlew.bat").exists():
        return
    try:
        subprocess.run([gradle, "wrapper", "--gradle-version", "8.14.3"],
                       cwd=str(d), capture_output=True, timeout=180)
    except Exception as e:
        print(f"      生成 wrapper 失败（不影响用全局 gradle）: {e}")


def build_one(variant: str, gradle: str, sdk: str,
              java: str) -> dict:
    """构建一个 APK。"""
    d = MOBILE / variant
    step(f"构建 {variant}")

    n = copy_www(variant)
    print(f"      拷了 {n} 个网页文件")

    # local.properties 指向 SDK
    (d / "local.properties").write_text(
        f"sdk.dir={sdk.replace(chr(92), '/')}\n", encoding="utf-8")

    ensure_wrapper(variant, gradle)

    # 优先用 wrapper（版本确定），没有就用全局 gradle
    gw = d / "gradlew.bat"
    exe = str(gw) if gw.exists() else gradle

    env = dict(os.environ)
    env["JAVA_HOME"] = java
    env["ANDROID_HOME"] = sdk
    env["ANDROID_SDK_ROOT"] = sdk
    env["GRADLE_USER_HOME"] = str(
        Path(os.path.expanduser("~")) / ".gradle")

    t0 = time.time()
    r = subprocess.run(
        [exe, "assembleRelease", "--no-daemon", "-q"],
        cwd=str(d), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800)

    el = time.time() - t0
    out = (r.stdout or "") + "\n" + (r.stderr or "")

    if r.returncode != 0:
        return {"ok": False, "err": out[-2500:], "elapsed": el}

    # 找产物
    apks = list((d / "app" / "build" / "outputs" / "apk")
                .rglob("*.apk"))
    if not apks:
        return {"ok": False, "err": "没找到 APK 产物", "elapsed": el}

    src = max(apks, key=lambda p: p.stat().st_size)
    DIST.mkdir(parents=True, exist_ok=True)
    dst = DIST / VARIANTS[variant]["apk"]
    shutil.copy2(src, dst)

    # ⚠⚠ 构建完就把 local.properties 删掉（踩过）
    #
    #   这个文件是给 gradle 指 SDK 路径用的，里面有**本机绝对路径**
    #   （C:/Users/你的用户名/...）。留着的话：
    #     · 提交到 Git 会泄露用户名
    #     · 更重要的是，构建日志把它带进 dex 里也可能漏出去
    #
    #   ✅ 反正是自动生成的，删掉没影响 ——
    #      下次构建会重新写一份。
    lp = d / "local.properties"
    try:
        if lp.exists():
            lp.unlink()
    except Exception:
        pass

    return {"ok": True, "path": dst,
            "size": dst.stat().st_size, "elapsed": el,
            "log": out[-600:] if len(out) > 600 else ""}


def clean() -> None:
    step("清理")
    n = 0
    for d in MOBILE.iterdir():
        if not d.is_dir() or d.name in ("common", "dist"):
            continue
        for sub in ("build", "app/build", ".gradle", "app/.cxx"):
            p = d / sub
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        a = d / "app" / "src" / "main" / "assets"
        if a.exists():
            shutil.rmtree(a, ignore_errors=True)
            n += 1
    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)
        n += 1
    print(f"      清了 {n} 项")


# ============================================================
#  主流程
# ============================================================
def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--clean"]

    print("=" * 66)
    print("  构建 Android APK")
    print("=" * 66)

    if "--clean" in sys.argv:
        clean()
        if not args:
            return 0

    # ---- 环境 ----
    print("\n  工具链:")
    gradle = find_gradle()
    sdk = find_sdk()
    java = find_java()

    for label, v in (("Gradle", gradle), ("Android SDK", sdk),
                     ("JDK", java)):
        mark = "✓" if v else "✗"
        print(f"    {mark} {label:<12} {v or '找不到'}")

    if not gradle:
        print("\n  ✗ 没找到 Gradle。")
        print("   装一个：https://gradle.org/install/")
        print("   或者用 Android Studio 打开 mobile/phone 直接跑。")
        return 1
    if not sdk:
        print("\n  ✗ 没找到 Android SDK。")
        print("   装 Android Studio 会自动带一个，")
        print("   或者设环境变量 ANDROID_HOME 指过去。")
        return 1
    if not java:
        print("\n  ⚠ 没找到 JAVA_HOME，试试看能不能用系统默认的 java")
        java = os.environ.get("JAVA_HOME", "")

    # ---- 网页 ----
    if not WWW.exists() or not (WWW / "app.js").exists():
        print(f"\n  ✗ 网页不全：{WWW}")
        return 1
    print(f"\n  网页: {WWW}")
    for f in sorted(WWW.iterdir()):
        if f.is_file():
            print(f"    {f.name}  {f.stat().st_size/1024:.1f}KB")

    # ---- 选版本 ----
    todo = args if args else list(VARIANTS)
    bad = [v for v in todo if v not in VARIANTS]
    if bad:
        print(f"\n  ✗ 不认识的版本: {bad}")
        print(f"    可选: {list(VARIANTS)}")
        return 1

    print(f"\n  要构建: {', '.join(todo)}")

    # ---- 逐个构建 ----
    results = {}
    for v in todo:
        try:
            results[v] = build_one(v, gradle, sdk, java)
        except subprocess.TimeoutExpired:
            results[v] = {"ok": False, "err": "超时（30 分钟）",
                          "elapsed": 0}
        except Exception as e:
            results[v] = {"ok": False,
                          "err": f"{type(e).__name__}: {e}",
                          "elapsed": 0}

    # ---- 汇总 ----
    print("\n" + "=" * 66)
    print("  结果")
    print("=" * 66)
    n_ok = 0
    for v, r in results.items():
        if r.get("ok"):
            n_ok += 1
            print(f"\n  ✓ {VARIANTS[v]['name']}")
            print(f"      {r['path']}")
            print(f"      {r['size']/1024/1024:.1f} MB"
                  f"  （构建用时 {r['elapsed']:.0f}s）")
        else:
            print(f"\n  ✗ {VARIANTS[v]['name']} 构建失败")
            print(f"      {r.get('err', '')[-1200:]}")

    print()
    print("=" * 66)
    print(f"  成功 {n_ok}/{len(todo)}")
    if n_ok:
        print(f"  APK 在: {DIST}")
    print("=" * 66)
    return 0 if n_ok == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main())
