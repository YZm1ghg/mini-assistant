# -*- coding: utf-8 -*-
"""
意图识别

在**交给 AI 之前**先判断一下：这句话到底想干什么？

============================================================
它做三件事
============================================================
    ① **先试技能** —— 命中的话毫秒级返回，不走 AI
    ② **判断是不是"干活"** —— 写代码/改文件/跑命令这类
       应该进**任务模式**（带更多工具、更长的思考）
    ③ **判断是不是闲聊** —— 问候聊天就不用开工具

============================================================
为什么不用 AI 判断
============================================================
    用 AI 判断要不要用 AI —— 那本身就是一次 AI 调用。
    而且它要 3~5 秒，比直接问还慢。

    ✅ 用**关键词 + 模式**做粗分类。测下来又快又准：
       「帮我写个脚本」→ task（明确要干活）
       「你好」→ chat（明确是闲聊）
       拿不准的 → 交给 AI 自己决定（走 auto）

============================================================
和语义识别的配合
============================================================
    本地规则管**明确的**情况，模糊的交给 AI。
    这不是妥协 —— 明确的情况本来就占大多数，
    而且规则命中时用户不用等那 3 秒。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

from . import skills

# ---- 任务模式：要动工具/文件/命令 ----
_TASK = re.compile(
    # ① 帮我 + 动词
    r"(帮我|给我|替我|请你?)"
    r"(写|做|改|修|删|建|创建|生成|整理|转换|批量|下载|"
    r"安装|部署|编译|打包|运行|跑|执行|检查|测试|分析|"
    r"读取|打开|保存|导出|抓取|爬|搜索|查找|找一下)"
    # ② 动词 + 名词
    r"|(写|做|改|修|删|建|生成|整理|转换)(个?|一个|一下)?"
    r"(脚本|程序|代码|文件|文档|表格|ppt|PPT|方案|计划|报告|"
    r"网页|页面|工具|函数|类|模块)"
    # ③ 「把 X 整理一下」这种 —— 动词在中间
    r"|把\s*[^\s，。]{1,60}?\s*"
    r"(整理|清理|删除|改|修改|转换|重命名|移动|复制|备份|"
    r"压缩|解压|打包|合并|拆分|排序|去重)"
    # ④ 「对 X 做 Y」
    r"|(整理|清理|处理|分析|检查|修改|转换)\s*一下"
    # ⑤ 直接跑
    r"|(运行|执行|跑|运行一下)\s*(一下|这个|那个)?"
    # ⑥ 打开本机路径
    r"|(查看|看一下|打开)\s*[A-Za-z]:\\"
    # ⑦ 求解答
    r"|(怎么|如何)(做|写|实现|解决|修)"
    r"|(帮我|给我)(看看|看下|查查|检查)",
    re.I)

# ---- 闲聊：问候/寒暄/情绪 ----
_CHAT = re.compile(
    r"^(你好|您好|嗨|哈喽|hello|hi|在吗|在不在|早上好|"
    r"中午好|下午好|晚上好|晚安|早安|再见|拜拜|谢谢|"
    r"多谢|辛苦了|好的|ok|OK|嗯|哦|😂|哈哈)"
    r"[\s!！。.~～]*$",
    re.I)

# ---- 查询类：直接问事实（不算任务，但也不用开工具）----
_QUERY = re.compile(
    r"^(什么是|是什么|啥是|介绍一下|解释一下|告诉我)"
    r"|(为什么|怎么会|什么原因)",
    re.I)


@dataclass
class Verdict:
    kind: str                 # skill | task | chat | query | auto
    text: str = ""            # skill 的直接答案
    skill: str = ""
    elapsed: float = 0.0
    reply: Optional[str] = None      # 直接回复（skill 命中时）

    def as_dict(self) -> dict:
        return {"kind": self.kind, "skill": self.skill,
                "text": self.text, "elapsed": round(self.elapsed, 4),
                "direct": self.reply is not None}


def judge(text: str, use_skill: bool = True) -> Verdict:
    """判断一句话该怎么处理。"""
    t0 = time.time()
    text = (text or "").strip()
    if not text:
        return Verdict("auto")

    # ---- ① 先试技能（最快）----
    if use_skill:
        try:
            r = skills.try_run(text)
        except Exception:                              # noqa: BLE001
            r = None
        if r is not None:
            return Verdict(
                "skill",
                text=r.text, skill=r.skill,
                elapsed=time.time() - t0,
                reply=(r.text if r.ok else None))

    # ---- ② 判断类别 ----
    if _CHAT.match(text):
        kind = "chat"
    elif _TASK.search(text):
        kind = "task"
    elif _QUERY.match(text):
        kind = "query"
    else:
        kind = "auto"

    return Verdict(kind, elapsed=time.time() - t0)


def need_task(text: str) -> bool:
    """是不是要干活。"""
    return judge(text, use_skill=False).kind == "task"


def status() -> dict:
    return {
        "rules": {
            "task": len(_TASK.pattern),
            "chat": len(_CHAT.pattern),
        },
        "skills": len(skills.list_skills()),
    }
