# -*- coding: utf-8 -*-
"""
微信消息

怎么拿到的
----------
    读 ChatLab 的 SQLite 数据库。**只读，不改任何东西。**

    位置：~/.chatlab/data/databases/chat_*.db
    每个 db 是一个会话（好友 或 群），里面有：
        meta     会话名、平台、类型
        member   成员（id、名字）
        message  消息（时间、发送者、内容、类型）

    ⚠ 为什么不用 WeFlow 的 wcdb_api.dll：
      DLL 要配 keys.json 解密主库，而且版本一变就崩。
      ChatLab 已经把这些活儿干完了，落成明文 SQLite ——
      我们只读，稳定得多。

能做什么
--------
    · 谁最近找过我、说了什么
    · 自动分类（重要 / 普通 / 广告）
    · 有新消息时念出来
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config

# ⚠ 数据库位置**不写死** —— 交给 find 模块找。
#
#   原来写的是 Path.home() / ".chatlab" / "data" / "databases"，
#   但 ChatLab 可能装在别处（用户自定义、便携版、别的盘），
#   写死就换台电脑跑不起来。
#
#   find.chatlab_dirs() 会试：
#     · MINI_CHATLAB 环境变量
#     · ~/.chatlab、~/ChatLab、~/Documents/ChatLab、AppData 下…
#     · 项目自带的 data/chatlab
#   而且只返回**里面真有 chat_*.db** 的目录。
def _dirs() -> list[Path]:
    from . import find
    return find.chatlab_dirs()


def _primary_dir() -> Path:
    """主数据库目录（第一个找到的）。找不到就返回一个占位路径。"""
    d = _dirs()
    if d:
        return d[0]
    # 占位：给用户看的错误信息里会用到
    return Path.home() / ".chatlab" / "data" / "databases"


def _all_dbs() -> list[Path]:
    """所有会话数据库文件（可能分布在多个目录）。"""
    out: list[Path] = []
    seen = set()
    for d in _dirs():
        try:
            for f in sorted(d.glob("chat_*.db")):
                try:
                    key = f.resolve()
                except Exception:                      # noqa: BLE001
                    key = f
                if key in seen:
                    continue
                seen.add(key)
                out.append(f)
        except Exception:                              # noqa: BLE001
            continue
    return out


# 消息类型（ChatLab 的编号）
TYPE_NAME = {
    0: "文字", 1: "图片", 3: "语音", 7: "表情", 25: "引用",
    34: "语音", 37: "好友请求", 42: "名片", 43: "视频",
    47: "表情", 48: "位置", 49: "链接/文件", 10000: "系统",
}

# 广告/机器人特征：命中就当垃圾，不播报
_AD_PAT = re.compile(
    r"(优惠|促销|限时|秒杀|返现|领取|红包|助力|砍价|拼团|"
    r"加微信|扫码|关注公众号|点击链接|【.*?】|"
    r"http[s]?://\S{8,})", re.I)

# 紧急特征：命中就优先播报
_URGENT_PAT = re.compile(
    r"(急|马上|立刻|赶紧|尽快|现在|等你|找你有事|"
    r"有空回|在吗|在不在|看到回|电话|打给我|"
    r"几点|什么时候|明天|今天|今晚|deadline|截止)", re.I)

_seen_lock = threading.Lock()
SEEN_PATH = config.DATA_DIR / "wechat_seen.json"


# ============================================================
#  读数据库
# ============================================================
def available() -> dict:
    dirs = _dirs()
    if not dirs:
        return {"ok": False,
                "error": "找不到 ChatLab 数据库目录（设 MINI_CHATLAB 指定）"}
    n = sum(len(list(d.glob("chat_*.db"))) for d in dirs)
    if not n:
        return {"ok": False, "error": "数据库目录是空的"}
    return {"ok": True, "dirs": [str(d) for d in dirs],
            "dir": str(dirs[0]), "sessions": n}


def _open(db: Path) -> sqlite3.Connection:
    # ⚠ mode=ro：只读打开，绝不改动别人的数据
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True,
                           timeout=5)


def sessions() -> list[dict]:
    """列出所有会话。"""
    dirs = _dirs()
    if not dirs:
        return []
    out = []
    for db in _all_dbs():
        try:
            con = _open(db)
            cur = con.cursor()
            cur.execute("SELECT name, platform, type FROM meta "
                        "LIMIT 1")
            row = cur.fetchone()
            cur.execute("SELECT COUNT(*), MAX(ts) FROM message")
            cnt, last = cur.fetchone()
            con.close()
            if not row:
                continue
            name, platform, kind = row
            out.append({
                "name": name or db.stem,
                "platform": platform or "",
                "type": kind or "",
                "count": cnt or 0,
                "last": last or 0,
                "last_str": time.strftime(
                    "%m-%d %H:%M", time.localtime(last or 0)),
                "db": str(db),
                "mb": round(db.stat().st_size / 1024 / 1024, 1),
            })
        except Exception:                              # noqa: BLE001
            continue
    out.sort(key=lambda x: -x["last"])
    return out


def _members(con: sqlite3.Connection) -> dict[int, str]:
    try:
        cur = con.cursor()
        cur.execute("SELECT id, account_name, group_nickname "
                    "FROM member")
        d = {}
        for mid, acct, nick in cur.fetchall():
            d[int(mid)] = (nick or acct or f"#{mid}")
        return d
    except Exception:                                  # noqa: BLE001
        return {}


def _self_ids(members: dict[int, str],
              session_name: str = "") -> set[int]:
    """猜哪些 member.id 是"我自己"。

    ⚠⚠ 这是最容易出错的一步，实测踩过：
       同一个人的账号名在不同会话库里**不一样** ——
       有的库里显示「我」，有的库里显示自己的微信号，
       换个库可能又是别的写法。

       而且这个差异**因人而异** —— 取决于你自己的微信号
       和每个联系人的备注习惯，所以：
       ⚠ **代码里不能假设任何具体的名字**。

       用三条规则判断，而不是查一张名字表：

       ① 特征词：名字是「我/自己/me/本人」这类
       ② 账号名形态：像 wxid_ 开头，或者大小写混杂的
          纯字母数字串（微信账号 id 的典型样子），
          而联系人一般是真名
       ③ 排除会话同名者：名字等于会话名的那是对方

       三条都不中的，按"是对方"处理。

    ✅ 判成"我"的进入 self_ids，读消息时会跳过。
    """
    names = {"我", "自己", "me", "Me", "ME", "myself", "本人",
             "本机", "微信", "微信用户", "我本人"}
    out: set[int] = set()

    for mid, nm in members.items():
        n = (nm or "").strip()
        if not n:
            continue
        # ① 特征词
        if n in names:
            out.add(mid)
            continue
        # ② 账号名形态：像 wxid_ 或随机字母数字串
        if n.lower().startswith("wxid_"):
            out.add(mid)
            continue
        # 纯字母数字、有大小写混杂、长度 6~20、
        # 且不含中文 —— 典型的微信号
        if (6 <= len(n) <= 20
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", n)
                and re.search(r"[a-z]", n)
                and re.search(r"[A-Z0-9]", n)
                and n != session_name):
            out.add(mid)
            continue
        # ③ 名字和会话名一样 → 那是对方，不是我
    return out


def read(db_path: str, limit: int = 30,
         only_theirs: bool = True) -> list[dict]:
    """读某个会话的最近 limit 条消息。

    only_theirs=True 时只返回**别人发的**（我自己发的没意义）。
    """
    p = Path(db_path)
    if not p.exists():
        return []
    try:
        con = _open(p)
        cur = con.cursor()
        members = _members(con)
        mine = _self_ids(members)
        cur.execute(
            "SELECT id, sender_id, ts, type, content "
            "FROM message ORDER BY ts DESC LIMIT ?", (limit * 3,))
        rows = cur.fetchall()
        con.close()
    except Exception:                                  # noqa: BLE001
        return []

    out = []
    for mid, sid, ts, mtype, content in rows:
        sid = int(sid or 0)
        if only_theirs and sid in mine:
            continue
        text = (content or "").strip()
        if not text:
            continue
        # 系统消息跳过
        if mtype == 10000:
            continue
        out.append({
            "id": mid,
            "who": members.get(sid, f"#{sid}"),
            "ts": ts or 0,
            "when": time.strftime("%m-%d %H:%M",
                                  time.localtime(ts or 0)),
            "type": TYPE_NAME.get(mtype, f"类型{mtype}"),
            "mtype": mtype,
            "text": text[:500],
        })
        if len(out) >= limit:
            break
    out.reverse()                                      # 时间正序
    return out


# ============================================================
#  分类
# ============================================================
def classify(text: str) -> str:
    """分三类：ad（广告）/ urgent（急）/ normal。"""
    t = text or ""
    if len(t) < 40 and _AD_PAT.search(t):
        return "ad"
    if _AD_PAT.search(t) and ("【" in t or t.count("http") > 0):
        return "ad"
    if _URGENT_PAT.search(t):
        return "urgent"
    return "normal"


def who_contacted(hours: float = 24, limit: int = 10) -> dict:
    """最近 N 小时谁找过我，说了什么。"""
    dirs = _dirs()
    if not dirs:
        return {"ok": False, "error": "没有数据库"}
    cut = time.time() - hours * 3600
    people: dict[str, dict] = {}

    for db in _all_dbs():
        try:
            con = _open(db)
            cur = con.cursor()
            cur.execute("SELECT name FROM meta LIMIT 1")
            r = cur.fetchone()
            sname = (r[0] if r else db.stem)
            members = _members(con)
            mine = _self_ids(members)
            cur.execute(
                "SELECT sender_id, ts, type, content FROM message "
                "WHERE ts >= ? ORDER BY ts DESC LIMIT 200", (cut,))
            rows = cur.fetchall()
            con.close()
        except Exception:                              # noqa: BLE001
            continue

        for sid, ts, mtype, content in rows:
            sid = int(sid or 0)
            if sid in mine:
                continue                           # 我发的跳过
            text = (content or "").strip()
            if not text or mtype == 10000:
                continue
            cat = classify(text)
            if cat == "ad":
                continue                           # 广告不进列表
            who = members.get(sid, sname)
            e = people.setdefault(who, {
                "who": who, "session": sname, "count": 0,
                "latest": "", "latest_when": "",
                "latest_ts": 0, "urgent": 0,
            })
            e["count"] += 1
            if cat == "urgent":
                e["urgent"] += 1
            if (ts or 0) > e["latest_ts"]:
                e["latest_ts"] = ts or 0
                e["latest"] = text[:200]
                e["latest_when"] = time.strftime(
                    "%m-%d %H:%M", time.localtime(ts or 0))

    items = sorted(people.values(), key=lambda x: -x["latest_ts"])
    return {"ok": True, "hours": hours,
            "count": len(items), "items": items[:limit]}


def pick_new() -> list[dict]:
    """挑出上次检查后**新来的**消息（用来播报）。"""
    if not _dirs():
        return []
    seen = _load_seen()
    fresh: list[dict] = []

    for db in _all_dbs():
        try:
            con = _open(db)
            cur = con.cursor()
            cur.execute("SELECT name FROM meta LIMIT 1")
            r = cur.fetchone()
            sname = r[0] if r else db.stem
            members = _members(con)
            mine = _self_ids(members)
            cur.execute(
                "SELECT id, sender_id, ts, type, content "
                "FROM message ORDER BY ts DESC LIMIT 40")
            rows = cur.fetchall()
            con.close()
        except Exception:                              # noqa: BLE001
            continue

        for mid, sid, ts, mtype, content in rows:
            sid = int(sid or 0)
            if sid in mine or mtype == 10000:
                continue
            key = f"{db.stem}:{mid}"
            if key in seen:
                continue
            text = (content or "").strip()
            if not text:
                continue
            fresh.append({
                "key": key, "who": members.get(sid, sname),
                "session": sname, "when": time.strftime(
                    "%H:%M", time.localtime(ts or 0)),
                "ts": ts or 0, "text": text[:300],
                "type": TYPE_NAME.get(mtype, ""),
                "cat": classify(text),
            })

    fresh.sort(key=lambda x: x["ts"])
    return fresh


def mark_seen(items: list[dict]) -> None:
    """标记已播报，下次不再念。"""
    seen = _load_seen()
    for it in items:
        seen.add(it["key"])
    # 只留最近 3000 条，防文件无限涨
    if len(seen) > 3000:
        seen = set(list(seen)[-3000:])
    _save_seen(seen)


def _load_seen() -> set:
    import json
    if not SEEN_PATH.exists():
        return set()
    try:
        d = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        return set(d if isinstance(d, list) else [])
    except Exception:                                  # noqa: BLE001
        return set()


def _save_seen(s: set) -> None:
    import json
    with _seen_lock:
        try:
            SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            SEEN_PATH.write_text(
                json.dumps(sorted(s), ensure_ascii=False),
                encoding="utf-8")
        except Exception:                              # noqa: BLE001
            pass


def reset_seen() -> dict:
    """重置"已读"记录 —— 下次会重新播报最近的。"""
    _save_seen(set())
    return {"ok": True}


# ============================================================
#  播报
# ============================================================
def broadcast_text(items: list[dict], max_n: int = 5) -> str:
    """把新消息拼成一句念出来。"""
    if not items:
        return ""
    # 急的优先
    urgent = [i for i in items if i["cat"] == "urgent"]
    rest = [i for i in items if i["cat"] != "urgent"]

    lines = []
    for it in (urgent + rest)[:max_n]:
        mark = "（急）" if it["cat"] == "urgent" else ""
        body = it["text"]
        if it["type"] and it["type"] != "文字":
            body = f"[{it['type']}]"
        lines.append(f"{it['who']}{mark}：{body}")
    if len(items) > max_n:
        lines.append(f"还有 {len(items) - max_n} 条")
    return "；".join(lines)


_st_cache: dict = {}
_st_at: float = 0.0
_ST_TTL = 10.0


def status(fresh: bool = False) -> dict:
    """微信模块状态。

    ⚠ 缓存 10 秒（踩过）：
      这里要扫**两遍**所有 db ——
        sessions()  读每个库的 meta + count
        pick_new()  读每个库最近 40 条
      10 个库加起来 500ms 以上。被 /api/state 每 15 秒调一次，
      界面就一直有这个开销。

      ✅ 缓存 10 秒 —— 微信消息不会秒级变化，够用了。
    """
    global _st_cache, _st_at
    now = time.time()
    if (not fresh and _st_cache
            and now - _st_at < _ST_TTL):
        return _st_cache

    a = available()
    if not a.get("ok"):
        out = {"ok": False, "error": a.get("error"),
               "dir": str(_primary_dir())}
    else:
        out = {
            "ok": True,
            "dir": str(_primary_dir()),
            "sessions": len(sessions()),
            "unread": len(pick_new()),
        }
    _st_cache = out
    _st_at = now
    return out
