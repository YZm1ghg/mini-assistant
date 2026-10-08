# -*- coding: utf-8 -*-
"""
长期记忆

把聊过的东西存下来，以后能"想起来"。

怎么存
------
    data/memory.jsonl    每条记忆一行
    data/memory_vec.npy  对应的向量（可选）

怎么找
------
    两路并行：
        ① 向量检索 —— 语义相近（"我喜欢吃辣" 能匹配 "川菜"）
        ② 关键词检索 —— 字面匹配（向量模型没装时的兜底）

    两路分数加权相加，取前 N 条。

为什么这么简单
--------------
    不需要数据库。几千条记忆全量算相似度也就几十毫秒，
    存成 JSONL 用记事本就能看、能改、能删。
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import config

_lock = threading.Lock()
MEM_PATH = config.DATA_DIR / "memory.jsonl"
VEC_PATH = config.DATA_DIR / "memory_vec.npy"

# 向量模型（懒加载）
_embedder = None
_embed_failed = False
_embed_lock = threading.Lock()

# 中文停用词：检索时忽略，避免"的了吗"干扰
_STOP = set(
    "的了是我你他她它们在有和与就都而及之类的吗呢吧啊把被给对从到"
    "一个这个那个什么怎么怎样为什么可以能不能会不会然后还是这个"
)


# ============================================================
#  向量
# ============================================================
def _find_local_model() -> Optional[Path]:
    """找本地已下载的向量模型快照目录。

    ✅ 交给 find 模块统一查找。
      它会试这几个地方：
         · ~/.cache/huggingface/hub/models--<作者>--<名字>/snapshots/
         · ~/.cache/torch/sentence_transformers/
         · 各模型根目录（D:\\models 等）
         · 项目自带的 models/
         · MINI_TEXT2VEC 环境变量指定的

      而且**不只认一个模型名** —— 找不到 text2vec 会试
      bge-small-zh / bge-base-zh 这些中文向量模型。
    """
    from . import find
    return find.text2vec_model()


def embed(texts: list[str]) -> list[Optional[list[float]]]:
    """文本 → 向量。模型不可用返回 None（会退回关键词检索）。"""
    global _embedder, _embed_failed
    if _embed_failed:
        return [None] * len(texts)
    if _embedder is None:
        with _embed_lock:
            if _embedder is None and not _embed_failed:
                try:
                    # ⚠⚠ 关键：必须在 import 之前**关掉联网检查**。
                    #
                    #   踩过的坑：不设这些变量时，sentence_transformers
                    #   会去 huggingface.co 做 HEAD 请求校验模型是否更新。
                    #   本机代理不转发它 → 连接被拒 → **重试 5 轮**
                    #   （1+2+4+8+8 秒），整个启动卡死半分钟。
                    #
                    #   模型其实**早就下好放在本地缓存里了**，
                    #   设成离线模式直接用缓存，零网络请求。
                    os.environ.setdefault("HF_HUB_OFFLINE", "1")
                    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
                    os.environ.setdefault("HF_ENDPOINT",
                                          "https://hf-mirror.com")
                    # 清代理（本机不需要，而且它会挡住下载）
                    for _k in ("HTTP_PROXY", "HTTPS_PROXY",
                               "http_proxy", "https_proxy",
                               "ALL_PROXY"):
                        os.environ.pop(_k, None)

                    from sentence_transformers import (
                        SentenceTransformer)

                    # 优先用本地缓存的实体路径 —— 比给模型名更稳
                    local = _find_local_model()
                    name = (str(local) if local
                            else "shibing624/text2vec-base-chinese")
                    _embedder = SentenceTransformer(name)
                except Exception:                      # noqa: BLE001
                    _embed_failed = True
                    return [None] * len(texts)
    try:
        vs = _embedder.encode(texts, normalize_embeddings=True,
                              show_progress_bar=False)
        return [[float(x) for x in v] for v in vs]
    except Exception:                                  # noqa: BLE001
        _embed_failed = True
        return [None] * len(texts)


def has_vector() -> bool:
    """向量检索可用吗？"""
    return embed(["_probe_"])[0] is not None


def _cos(a, b) -> float:
    """余弦相似度。

    ⚠⚠ 不能用 `if not a` 判断空！
       `_load_vecs()` 返回的是 **numpy 数组**，
       而 `not ndarray` 会抛
       "The truth value of an array with more than one element
        is ambiguous"。
       这个异常会被 recall() 的 try/except 吞掉 →
       **向量分永远是 0** → 语义检索整个失效
       （踩过：明明向量相似度 0.55，检索却说找不到）。

    ✅ 用 len() 判断，它对 list 和 ndarray 都安全。
    """
    try:
        if a is None or b is None:
            return 0.0
        la, lb = len(a), len(b)
        if la == 0 or lb == 0 or la != lb:
            return 0.0
    except TypeError:
        return 0.0
    dot = na = nb = 0.0
    for i in range(la):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# ============================================================
#  关键词检索
# ============================================================
def _tokens(s: str) -> set[str]:
    """粗分词：中文按 2 字滑窗，英文按单词。

    ⚠ 不用 jieba 之类，因为：
        ① 多一个依赖
        ② 记忆量小，滑窗足够
    """
    s = (s or "").lower()
    out: set[str] = set()
    # 英文 / 数字
    for w in re.findall(r"[a-z0-9]{2,}", s):
        if w not in _STOP:
            out.add(w)
    # 中文 2 字滑窗
    han = re.findall(r"[\u4e00-\u9fff]+", s)
    for seg in han:
        for i in range(len(seg) - 1):
            g = seg[i:i + 2]
            if g not in _STOP:
                out.add(g)
        if len(seg) == 1:
            out.add(seg)
    return out


def _kw_score(query: str, text: str) -> float:
    """关键词重合度 0~1。"""
    a, b = _tokens(query), _tokens(text)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    # ⚠ 除以 sqrt(|a|*|b|) 而不是 |a|：
    #   否则长文本天然占便宜（词多自然命中多）。
    return inter / math.sqrt(len(a) * len(b))


# ============================================================
#  存取
# ============================================================
def _load() -> list[dict]:
    if not MEM_PATH.exists():
        return []
    out = []
    try:
        for line in MEM_PATH.read_text(
                encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if isinstance(d, dict) and d.get("text"):
                    out.append(d)
            except Exception:                          # noqa: BLE001
                continue                               # 坏行跳过
    except Exception:                                  # noqa: BLE001
        return []
    return out


def _load_vecs() -> list:
    try:
        import numpy as np
        if VEC_PATH.exists():
            return list(np.load(str(VEC_PATH), allow_pickle=True))
    except Exception:                                  # noqa: BLE001
        pass
    return []


def _save_vecs(vecs: list) -> None:
    try:
        import numpy as np
        np.save(str(VEC_PATH), np.array(vecs, dtype=object),
                allow_pickle=True)
    except Exception:                                  # noqa: BLE001
        pass


def remember(text: str, kind: str = "fact",
             extra: dict | None = None) -> dict:
    """记一条。"""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "空内容"}
    item: dict[str, Any] = {
        "t": time.time(),
        "text": text[:2000],
        "kind": kind,
    }
    if extra:
        item.update(extra)

    with _lock:
        MEM_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MEM_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # 向量单独存（避免每次都重算全部）
    v = embed([text])[0]
    if v is not None:
        with _lock:
            vecs = _load_vecs()
            # ⚠ 补齐长度（可能有旧记忆没向量）
            while len(vecs) < len(_load()) - 1:
                vecs.append(None)
            vecs.append(v)
            _save_vecs(vecs)
    return {"ok": True, "item": item}


def remember_exchange(user: str, assistant: str) -> dict:
    """记一轮对话（只记有信息量的）。"""
    u = (user or "").strip()
    a = (assistant or "").strip()
    if not u:
        return {"ok": False}
    # 太短的问题不记（"你好"这类没信息量）
    if len(u) < 4 and len(a) < 20:
        return {"ok": False, "skipped": "太短"}
    return remember(f"问：{u[:400]}\n答：{a[:800]}",
                    kind="exchange")


def recall(query: str, limit: int = 6,
           min_score: float = 0.06) -> list[dict]:
    """找相关的记忆。

    ⚠ min_score 的取值（实测调过）：
        text2vec 中文模型对短查询的相似度普遍在 0.2~0.6，
        但关键词那一路（2 字滑窗）在短句上经常只有 0.05~0.2。
        阈值设 0.15 会**把短查询全滤掉**（踩过：问"我吃什么菜"
        什么都找不到，但 build_context 用同一个查询却找到了）。
        取 0.06 既不会全是噪声，短查询也能出来。
    """
    query = (query or "").strip()
    if not query:
        return []
    items = _load()
    if not items:
        return []

    vecs = _load_vecs()
    qv = embed([query])[0]

    scored: list[tuple[float, dict]] = []
    for i, it in enumerate(items):
        text = str(it.get("text") or "")
        # 关键词分
        kw = _kw_score(query, text)
        # 向量分
        vc = 0.0
        if qv is not None and i < len(vecs) and vecs[i] is not None:
            try:
                vc = _cos(qv, vecs[i])
            except Exception:                          # noqa: BLE001
                vc = 0.0
        # ⚠ 两路加权：有向量时以向量为主
        if qv is not None and vc > 0:
            score = vc * 0.7 + kw * 0.3
        else:
            score = kw
        # 新鲜度微调：新的略加分
        age_days = (time.time() - float(it.get("t") or 0)) / 86400
        score *= (1.0 + 0.05 / (1.0 + age_days))
        if score >= min_score:
            scored.append((score, it))

    scored.sort(key=lambda x: -x[0])
    out = []
    for s, it in scored[:limit]:
        d = dict(it)
        d["score"] = round(s, 3)
        d["when"] = time.strftime(
            "%m-%d %H:%M", time.localtime(float(it.get("t") or 0)))
        out.append(d)
    return out


def build_context(query: str, limit: int = 6) -> str:
    """把相关记忆拼成一段文字，塞给 AI 当背景。"""
    got = recall(query, limit)
    if not got:
        return ""
    lines = ["以下是之前聊到的相关内容，可以参考："]
    for it in got:
        t = str(it.get("text") or "").replace("\n", " ")
        lines.append(f"- [{it['when']}] {t[:300]}")
    return "\n".join(lines)


def stats() -> dict:
    items = _load()
    vecs = _load_vecs()
    return {
        "count": len(items),
        "with_vector": sum(1 for v in vecs if v is not None),
        "vector_ready": not _embed_failed,
        "path": str(MEM_PATH),
        "size_kb": round(MEM_PATH.stat().st_size / 1024, 1)
        if MEM_PATH.exists() else 0,
    }


def forget(index: int) -> dict:
    """删掉第 index 条（按存储顺序，从 0 开始）。"""
    items = _load()
    if index < 0 or index >= len(items):
        return {"ok": False, "error": "序号越界"}
    items.pop(index)
    with _lock:
        MEM_PATH.write_text(
            "\n".join(json.dumps(x, ensure_ascii=False)
                      for x in items) + "\n",
            encoding="utf-8")
    return {"ok": True, "count": len(items)}


def clear() -> dict:
    with _lock:
        for p in (MEM_PATH, VEC_PATH):
            try:
                p.unlink(missing_ok=True)
            except Exception:                          # noqa: BLE001
                pass
    return {"ok": True}
