# -*- coding: utf-8 -*-
"""
迷你助手 · 核心

一个**极简**的本地 AI 助手：
    · 后端接 DeepSeek Harness（dsh --profile headless）
    · 前端是一个单页网页
    · 支持语音输入、语音播报、历史记录

设计原则
--------
    只做必要的事。没有动画、没有装饰、没有多余的元素。
    界面借用 DSH 自己的克制风格：深灰底 + 单一强调色。

模块
----
    config.py  读写 config.json
    dsh.py     调 dsh 命令行
    chat.py    历史记录
    voice.py   语音输入输出
    server.py  HTTP 服务 + 网页
"""
