# -*- coding: utf-8 -*-
"""
看图

把图片交给 AI，让它描述或回答问题。

怎么做的
--------
    DSH 的默认模型支持图像。但我们调的是命令行，
    没法直接传图片对象。

    ✅ 所以走「文件路径 + 明确指令」：
        ① 把图复制到一个**固定位置**（data/look/）
        ② 问 AI："请读取 D:\...\look_xxx.jpg 这张图，回答：..."
        ③ AI 自己会调它的读文件工具把图打开

    ⚠ 关键：临时图不能放在会被自动清理的目录，
      否则 AI 去读时文件已经没了 —— 表现就是「AI 说看不到图」。

能做什么
--------
    · 看屏幕（截屏 → 分析）
    · 看任意图片文件
    · 手机相机拍的照片
"""
from __future__ import annotations

import base64
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import config, dsh

LOOK_DIR = config.DATA_DIR / "look"

# 允许的图片后缀
_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _ensure() -> Path:
    LOOK_DIR.mkdir(parents=True, exist_ok=True)
    return LOOK_DIR


def _stage(src: Path) -> Path:
    """把图复制到固定位置，避免被别的清理逻辑删掉。"""
    _ensure()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = LOOK_DIR / f"look_{ts}{src.suffix.lower()}"
    try:
        shutil.copy2(src, dst)
    except Exception:                                  # noqa: BLE001
        return src                                     # 拷不了就用原图
    return dst


# ============================================================
#  截屏
# ============================================================
def screenshot() -> dict:
    """截全屏 → 返回文件路径。"""
    _ensure()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = LOOK_DIR / f"screen_{ts}.png"
    try:
        from PIL import ImageGrab
        # ⚠ all_screens=True 才能截到多显示器
        img = ImageGrab.grab(all_screens=True)
        img.save(out)
        return {"ok": True, "path": str(out),
                "size": f"{img.width}x{img.height}"}
    except Exception as e:                             # noqa: BLE001
        return {"ok": False, "error": f"截屏失败：{e}"}


def camera_shot(index: int = 0) -> dict:
    """用摄像头拍一张。"""
    _ensure()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = LOOK_DIR / f"cam_{ts}.jpg"
    try:
        import cv2                                # type: ignore
    except ImportError:
        return {"ok": False, "error": "没装 opencv-python"}
    cap = None
    try:
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            return {"ok": False, "error": f"打不开摄像头 {index}"}
        # 丢掉前几帧（自动曝光要时间）
        for _ in range(5):
            cap.read()
            time.sleep(0.08)
        ok, frame = cap.read()
        if not ok:
            return {"ok": False, "error": "读取画面失败"}
        cv2.imwrite(str(out), frame)
        return {"ok": True, "path": str(out),
                "size": f"{frame.shape[1]}x{frame.shape[0]}"}
    except Exception as e:                             # noqa: BLE001
        return {"ok": False, "error": f"拍照失败：{e}"}
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:                              # noqa: BLE001
            pass


# ============================================================
#  交给 AI
# ============================================================
def describe(path: str, question: str = "",
             session: str = "") -> dict:
    """让 AI 看图。

    question 留空则让它自由描述。
    """
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"图片不存在：{path}"}
    if p.suffix.lower() not in _EXTS:
        return {"ok": False, "error": f"不支持的格式：{p.suffix}"}

    staged = _stage(p)
    q = (question or "详细描述这张图片里有什么").strip()

    # ⚠ 指令要**明确说读文件**，否则 AI 可能只当图片是个路径字符串
    prompt = (
        f"请先读取这个图片文件：{staged}\n"
        f"然后用中文回答：{q}\n\n"
        f"要求：\n"
        f"  · 只回答关于这张图的内容，不要解释你是怎么读的\n"
        f"  · 如果图里有文字/代码/表格，请如实转述关键部分\n"
        f"  · 看不清或不存在就直说"
    )

    r = dsh.ask(prompt, session_id=session)
    if not r.ok:
        return {"ok": False, "error": r.error,
                "path": str(staged)}
    return {
        "ok": True,
        "text": r.text,
        "path": str(staged),
        "session": r.session_id,
        "elapsed": round(r.elapsed, 2),
    }


def to_data_url(path: str) -> str:
    """图片 → data URL（给网页 <img> 用）。"""
    p = Path(path)
    if not p.exists():
        return ""
    ext = p.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
            "webp": "webp", "gif": "gif", "bmp": "bmp"}.get(
        ext, "png")
    try:
        b = base64.b64encode(p.read_bytes()).decode()
        return f"data:image/{mime};base64,{b}"
    except Exception:                                  # noqa: BLE001
        return ""


def list_shots(limit: int = 40) -> list[dict]:
    """列出最近看过的图。"""
    _ensure()
    out = []
    try:
        files = sorted(
            [f for f in LOOK_DIR.rglob("*")
             if f.is_file() and f.suffix.lower() in _EXTS],
            key=lambda x: -x.stat().st_mtime)
    except Exception:                                  # noqa: BLE001
        return []
    for f in files[:limit]:
        try:
            st = f.stat()
            kind = ("截屏" if f.name.startswith("screen_")
                    else "拍照" if f.name.startswith("cam_")
                    else "看图")
            out.append({
                "name": f.name,
                "path": str(f),
                "kind": kind,
                "kb": round(st.st_size / 1024, 1),
                "when": time.strftime("%m-%d %H:%M",
                                      time.localtime(st.st_mtime)),
            })
        except Exception:                              # noqa: BLE001
            continue
    return out


def cleanup(days: int = 7) -> dict:
    """删掉 N 天前看过的图（省空间）。"""
    _ensure()
    cut = time.time() - days * 86400
    n = 0
    mb = 0.0
    try:
        for f in LOOK_DIR.rglob("*"):
            if not f.is_file():
                continue
            try:
                st = f.stat()
                if st.st_mtime < cut:
                    mb += st.st_size / 1024 / 1024
                    f.unlink()
                    n += 1
            except Exception:                          # noqa: BLE001
                continue
    except Exception as e:                             # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "removed": n, "mb": round(mb, 1)}


def status() -> dict:
    _ensure()
    n = 0
    mb = 0.0
    try:
        for f in LOOK_DIR.rglob("*"):
            if f.is_file():
                n += 1
                mb += f.stat().st_size / 1024 / 1024
    except Exception:                                  # noqa: BLE001
        pass
    cam = False
    try:
        import cv2                             # type: ignore  # noqa
        cam = True
    except ImportError:
        pass
    return {"dir": str(LOOK_DIR), "count": n,
            "mb": round(mb, 1), "camera": cam}
