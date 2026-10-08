# 迷你助手 · Mini Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#)
[![Zero Config](https://img.shields.io/badge/config-auto--detected-green.svg)](#自动查找外部依赖)

一个**极简**的本地 AI 助手。后端接 [DeepSeek Harness](https://www.npmjs.com/package/@deepseek-ai/dsh)，
前端是一个单页网页，带语音、长期记忆、看图、微信播报和加密。

还有**手机 / 平板 / 手表**三个独立的 Android 应用（[看这里](mobile/README.md)）。

> **目标：能读懂、能改、能跑起来。**
> 没有动画、没有皮肤、没有任何装饰性元素。
>
> **原则：不硬编码任何路径。** 所有外部依赖自动查找，
> 换个电脑直接跑，不用翻代码改。

---

## 亮点

| | |
|---|---|
| **零配置启动** | 自动找 Node / dsh / 模型 / ffmpeg，找不到会告诉你去哪装 |
| **技能优先** | 29 个命令本地直答，**毫秒级**（「现在几点」19ms，走 AI 要 25 秒）|
| **依赖最简** | 自写音频（替 soundfile+numpy）、自写 SAPI（替 pyttsx3）|
| **绿色可移植** | 整个目录拷走就能用，数据都在 `data/` 里 |
| **隐私优先** | 全本地运行，自带 `check_privacy.py` 一键体检 |
| **三端覆盖** | 桌面网页 + 手机 + 平板 + 手表 |

---

## 目录

- [是什么](#是什么)
- [亮点](#亮点)
- [快速开始](#快速开始)
- [自动查找外部依赖](#自动查找外部依赖)
- [手机 / 平板 / 手表](#手机--平板--手表)
- [配置项](#配置文件)
- [隐私](#隐私)
- [踩过的坑](#踩过的坑)
- [许可](#许可)

---

## 是什么

一个套在 `dsh` 外面的轻量界面。`dsh` 本身是命令行工具，
这个项目给它加了这些：

| 功能 | 一句话 |
|---|---|
| **聊天** | 不用开终端，鼠标点点就能聊 |
| **语音** | 说话转文字、回复念出来 |
| **长期记忆** | 聊过的东西记得住，以后能想起来 |
| **看图** | 截屏/拍照 → AI 分析 |
| **微信播报** | 谁找过你、说了什么，能念出来 |
| **保险箱** | 敏感图自动加密，密钥绑本机 |
| **系统监控** | CPU / 内存 / 磁盘 / 显卡 / 温度 / 网络 |
| **系统控制** | 音量 / 亮度 / 进程 / 电源 / 锁屏 |
| **技能系统** | 29 个命令毫秒级直答，不用等 AI |
| **意图识别** | 自动判断该走技能还是走 AI |

---

## 快速开始

### 1. 环境要求

| 需要 | 版本 | 必装？ | 干什么用 |
|---|---|---|---|
| **Python** | 3.10 或更高 | ✅ 必装 | 跑这个程序 |
| **Node.js** | 18 或更高 | ✅ 必装 | `dsh` 靠它跑 |
| **DeepSeek Harness** | 0.2+ | ✅ 必装 | AI 后端 |

---

#### Python 3.10+

**下载地址**：<https://www.python.org/downloads/>

装的时候**一定要勾 `Add Python to PATH`**（安装向导第一页最下面那个勾），
不勾的话命令行里敲 `python` 会提示找不到。

> Windows 应用商店里也有 Python，但**别用那个** ——
> 它的路径很怪，`pythonw.exe` 有时候找不到，会引出一堆麻烦。
> 老老实实去官网下安装包装。

验证：

```cmd
python --version
```

应该输出 `Python 3.10.x` 或更高。

---

#### Node.js 18+

**下载地址**：<https://nodejs.org/zh-cn/download>

选 **LTS 版本**（长期支持版），Windows 装 `.msi`，双击一路下一步。

验证：

```cmd
node --version
npm --version
```

两个都要有输出。`npm` 是跟 `node` 一起装的，不用单独下。

> 如果 `node` 有了但 `npm` 提示找不到，重装一次 Node.js。

---

#### DeepSeek Harness

**npm 地址**：<https://www.npmjs.com/package/@deepseek-ai/dsh>
**GitHub**：<https://github.com/deepseek-ai/deepseek-harness>

装完 Node.js 之后，命令行里执行：

```cmd
npm install -g @deepseek-ai/dsh
```

> `-g` 是装到全局。不加的话只有当前目录能用。

验证：

```cmd
dsh --version
```

国内网络慢的话换淘宝镜像：

```cmd
npm config set registry https://registry.npmmirror.com
npm install -g @deepseek-ai/dsh
```

---

### 2. 装 Python 依赖

```cmd
pip install -r requirements.txt
```

国内慢的话加镜像：

```cmd
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**核心只有 4 个包**（`soundfile`、`numpy`、`edge-tts`、`pyttsx3`），
都是纯 Python，不需要编译器。

#### 可选功能对应的包

装了哪个功能就亮哪个，**没装的自动降级，不会崩**。

| 功能 | 装什么 | 大小 | 说明 |
|---|---|---|---|
| 🔊 **朗读音质好** | `pip install edge-tts` | 小 | 在线，微软语音，**推荐** |
| 🔊 朗读离线 | `pip install pyttsx3` | 小 | 用系统自带语音，音质一般 |
| 🎤 **听你说话** | `pip install funasr` | 模型 ~950MB | 中文最准，**推荐** |
| 🎤 听你说话（备选） | `pip install faster-whisper` | 模型 ~75MB | 体积小，中文一般 |
| 🧠 **语义记忆** | `pip install sentence-transformers` | 模型 ~400MB | **强烈建议** |
| 📷 摄像头拍照 | `pip install opencv-python` | 中 | 只用截屏的话不需要 |

一条命令全装：

```cmd
pip install edge-tts pyttsx3 funasr faster-whisper sentence-transformers opencv-python -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**没有模型也能装完** —— 模型是第一次用到时自动下载的。

---

#### 模型下载地址

程序会**自动找**这些模型（找到就用，找不到功能自动关）。
也可以手动下载后设环境变量 `MINI_MODELS` 指向模型目录。

| 模型 | 从哪下 | 放哪 |
|---|---|---|
| **FunASR 中文识别**<br>`speech_seaco_paraformer_large` | [ModelScope](https://modelscope.cn/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch)<br>[HuggingFace](https://huggingface.co/funasr) | `<模型目录>\funasr\...` |
| **中文向量模型**<br>`text2vec-base-chinese` | [HuggingFace](https://huggingface.co/shibing624/text2vec-base-chinese) | 自动下到 `~/.cache/huggingface/` |
| **faster-whisper tiny** | 首次运行自动下 | `<模型目录>\whisper\tiny\` |
| **Kokoro 中文语音**（可选） | [HuggingFace](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) | `<模型目录>\kokoro-zh\` |

> **国内下载慢**：设 `HF_ENDPOINT=https://hf-mirror.com` 走镜像。
> 程序里已经默认设好了。

**不用 FunASR 大模型的话**，把 `config.json` 的 `asr_engine` 改成
`whisper`，只用 75MB 的小模型。

---

#### 微信消息（可选）

想让它念微信新消息，需要先用 **[ChatLab](https://chatlab.fun)** 把聊天记录导出来。

**官网**：<https://chatlab.fun>
**文档**：<https://docs.chatlab.fun/cn/>
**GitHub**：<https://github.com/ChatLab/ChatLab>

装法有两种：

**① 桌面版**（简单）—— 官网或 [Releases](https://github.com/ChatLab/ChatLab/releases)
下载安装包，双击装。

**② 命令行版**（需要 Node.js 22+）：

```cmd
npm install --global chatlab-cli
clb web
```

装好后把微信聊天记录**导出并导入 ChatLab**，
数据库会落在 `~/.chatlab/data/databases/`。

**怎么导出聊天记录**：看官方文档
<https://docs.chatlab.fun/cn/usage/how-to-export>

> ⚠️ 本程序**只读**这些数据库，不改不动。
> 数据库是明文的 SQLite，所以读起来稳。

---

#### ffmpeg（可选）

处理音频要用。**一般不用管** —— 如果你装了
[node 版本的 ffmpeg-static](https://www.npmjs.com/package/ffmpeg-static)
或者系统里已经有，程序自己找得到。

手动装：<https://ffmpeg.org/download.html>
下完把 `ffmpeg.exe` 所在目录加进 PATH。

---

### 3. 跑起来

```cmd
python run.py
```

浏览器自动打开 `http://127.0.0.1:64874`。

**先自检一下依赖在哪：**

```cmd
python run.py --doctor
```

```
  ==========================================================
   依赖自检
  ==========================================================
   ● Node.js            <node 目录>\node.exe
   ● DeepSeek Harness   <用户目录>\npm\node_modules\@deepseek-ai\dsh\lib\bin.js
   ● ChatLab 数据        <用户目录>\\<用户目录>\.chatlab\\data\databases
   ● FunASR 识别         <模型目录>\funasr\...
   ● 中文向量模型         <用户目录>\\<缓存目录>\huggingface\hub\models--shibing624--...
   ● ffmpeg             <用户目录>\npm\node_modules\ffmpeg-static\ffmpeg.exe
   ● 浏览器              <浏览器目录>\msedge.exe
  ----------------------------------------------------------
   家目录   : <用户目录>
   模型目录 : <你的模型目录>
  ==========================================================

  全部就绪。
```

其它参数：

```cmd
python run.py --port 61000    # 手动指定端口
python run.py --no-open       # 不自动开浏览器
python run.py --doctor        # 只检查依赖，不启动
```

启动后的横幅也会列出所有自动查到的依赖。
`●` = 可用，`○` = 没装/没开。

#### 关于端口

默认 `64874`，**不会跟别的程序撞**。为什么挑这么个号：

| 别用 | 原因 |
|---|---|
| 8000 / 8080 / 3000 / 5000 | 知名服务端口，开发机上几乎必有别的东西在跑 |
| 49152 往上 | 虽然叫「动态私有段」，但 Windows 上 Hyper-V / WSL / Docker 会保留掉一大块 |

而且**不写死** —— 启动时会**实际试绑**：

1. 先试配置里的端口
2. 被占了 → 按顺序试备选（`port_fallback`）
3. 都占 → 现找
4. 最终结果**写回配置** → 下次还用同一个（书签不会失效）

> ⚠️ 检测用的是「不带 `SO_REUSEADDR` 的实际 bind + listen」。
> 带 `SO_REUSEADDR` 的话，即使端口已被占用 bind 也会成功，
> 检测就形同虚设了。

手动指定：`python run.py --port 61000`

---

## 依赖都是自动找的

**没有任何写死的路径。** 所有「外部东西在哪」都集中在一个模块
（`src/find.py`），每项都做多路探测：

| 找什么 | 探测顺序 |
|---|---|
| **Node.js** | 环境变量 → PATH → 常见安装位置 → nvm / fnm 目录 |
| **dsh** | 环境变量 → 配置 → 问 `npm root -g` → 常见位置 → pnpm → 项目自带 → PATH |
| **ChatLab** | 环境变量 → `~/.chatlab`、`~/ChatLab`、`~/Documents/ChatLab`、AppData… → 项目自带 |
| **FunASR** | 环境变量 → 各模型目录**递归搜 `model.pt`**（不写死层级）→ ModelScope 缓存 |
| **向量模型** | 环境变量 → HF 缓存（试 text2vec / bge 多个名字）→ torch 缓存 → 项目自带 |
| **ffmpeg** | 环境变量 → PATH → 常见位置 |
| **浏览器** | 环境变量 → PATH → Edge / Chrome 常见位置 |

查不到就**优雅降级**（功能关闭，不崩），并告诉你缺什么。

### 找不到时怎么办

设环境变量，或直接写进 `config.json`：

| 环境变量 | 指定什么 |
|---|---|
| `MINI_NODE` | `node.exe` 路径 |
| `MINI_DSH` | dsh 的 `bin.js` 路径 |
| `MINI_CHATLAB` | ChatLab 数据库目录 |
| `MINI_MODELS` | 模型总目录（下面找 funasr / whisper / text2vec） |
| `MINI_FUNASR` | FunASR 模型目录 |
| `MINI_WHISPER` | whisper 模型目录 |
| `MINI_TEXT2VEC` | 向量模型目录 |
| `MINI_FFMPEG` | ffmpeg 路径 |
| `MINI_BROWSER` | 浏览器路径 |

Windows 上临时设：

```cmd
set MINI_MODELS=<模型目录>
python run.py
```

---

## 功能详解

### 长期记忆

**怎么工作：**

1. 每次聊完，那一轮对话自动存进 `data/memory.jsonl`
2. 你下次提问时，先从前面的记忆里**召回最相关的几条**
3. 把它们拼成背景塞给 AI —— 这样它才能"想起来"

**怎么找：**

两条路加权：

| 路子 | 作用 | 依赖 |
|---|---|---|
| **向量检索** | 语义相近（"我喜欢吃辣" 能匹配 "川菜"）| sentence-transformers |
| **关键词检索** | 字面匹配（兜底）| 无 |

没装向量模型时自动只用关键词，功能不中断。

**向量模型：** `shibing624/text2vec-base-chinese`（768 维，中文效果好）

> ⚠️ **重要**：程序会设 `HF_HUB_OFFLINE=1`。
> 不设的话 `sentence_transformers` 会去 huggingface.co
> 做 HEAD 请求校验更新，本机代理不转发 → 连接被拒 →
> **重试 5 轮**，启动卡死半分钟。
> 模型其实早就下好了，离线模式直接用缓存。

**在界面上：** 侧栏 →「记忆库」。可以搜、可以看、可以清空。

### 看图

**三种来源：**
- 「看屏幕」—— 截全屏（支持多显示器）
- 「拍照看图」—— 摄像头
- 直接问 AI 关于某个图片文件

**怎么交给 AI 的：**

调的是命令行，没法直接传图片对象。所以：

1. 把图复制到 `data/look/`
2. 问 AI："请读取 `D:\...\look_xxx.jpg` 这张图，回答：..."
3. AI 自己会调它的读文件工具把图打开

> ⚠️ 临时图**不能放在会被自动清理的目录**，
> 否则 AI 去读时文件已经没了 —— 表现就是「AI 说看不到图」。

### 微信播报

**数据从哪来：** 读 ChatLab 的 SQLite 数据库（`~/.chatlab/data/databases/`）。

> 为什么不用 WeFlow 的 `wcdb_api.dll`：
> DLL 要配 `keys.json` 解密主库，版本一变就崩。
> ChatLab 已经把这些活干完了，落成明文 SQLite —— 我们只读，稳定得多。

**能做什么：**
- 列出所有会话（谁、多少条、最后什么时候）
- 「谁最近找过我」（可指定小时数）
- 侦测新消息（只报增量，不重复）
- 自动分类：**急 / 普通 / 广告**（广告不播报）
- 把新消息念出来

**怎么认出"我自己"：**

这是最容易错的一步 —— **同一个人的账号名在不同会话库里不一样**。
（具体叫什么由你自己的微信号决定，程序里不做任何假设。）

所以用三条规则判断，**而不是靠一张写死的名字表**：

1. **特征词** —— 名字是「我 / 自己 / me / 本人」这类
2. **账号名形态** —— 像 `wxid_` 开头，或者大小写混杂的
   纯字母数字串。微信账号 id 通常是这个样子，
   而联系人一般是真名
3. **排除会话同名者** —— 名字和会话名一样的那是对方

三条都不中的按"是对方"处理。
判成"我"的会跳过，不参与「谁找过我」和新消息播报。

### 主动助手

不等你问，它自己做的事：

- **微信播报** —— 定时查新消息，有就念
- **定时提醒** —— 每天某点说一句话（道早安、提醒睡觉）

**全是开关控制的，默认全关。**

> 主动打扰人是把双刃剑 —— 没让你主动开就不该响。

**安静时段**支持跨午夜（`23:30, 07:30` = 晚上十一点半到早上七点半不打扰）。

### 保险箱

**做什么：** 把看过的截图/照片自动加密存起来。

**怎么加密的：**

单一加密卷（tar 打包 + AES-256-GCM），不是一图一密文。好处：
- 文件数少了不会爆目录
- 元数据（原名/时间）一起加密，看不出存了什么
- 有认证标签，改一个字节就报错

**密钥怎么管：**

用 Windows DPAPI 绑到「本机 + 当前用户」：
- 你自己打开**不用输密码**
- 别人拷走文件也**解不开**

**使用保护（重要）：**

刚出的图不能马上加密 —— AI 可能还要看。所以：

1. 出图后登记保护（90 秒）
2. AI 每次读图会**续期**
3. 归档时跳过保护期内的文件

> ⚠️ 延迟设太短的话，AI 还没看图就被收走了，
> 表现就是「AI 说看不到图」。

---

## 配置文件

所有设置都在 `config.json`，第一次运行自动生成。

### 服务

| 键 | 默认 | 说明 |
|---|---|---|
| `host` | `127.0.0.1` | 改成 `0.0.0.0` 可让局域网访问 |
| `port` | `64874` | 端口 |

### 后端

| 键 | 默认 | 说明 |
|---|---|---|
| `dsh_bin` | 空 | dsh 的 `bin.js` 路径。留空自动查找 |
| `dsh_profile` | `headless` | 用哪个 profile |
| `timeout` | `300` | 单次请求超时（秒） |
| `work_dir` | 空 | AI 的工作目录。留空 = 程序所在目录 |

### 语音

| 键 | 默认 | 说明 |
|---|---|---|
| `voice_enabled` | `true` | 默认是否朗读 |
| `tts_engine` | `edge` | `edge` / `pyttsx3` / `off` |
| `tts_voice` | `zh-CN-XiaoxiaoNeural` | 音色 |
| `tts_speed` | `1.0` | 语速 |
| `asr_engine` | `funasr` | `funasr` / `whisper` / `off` |

### 记忆

| 键 | 默认 | 说明 |
|---|---|---|
| `memory_auto` | `true` | 自动记住对话 |
| `memory_recall` | `4` | 每次召回几条当背景（0 = 关） |

### 主动助手

| 键 | 默认 | 说明 |
|---|---|---|
| `proactive.on` | `false` | 总开关 |
| `proactive.wechat_interval` | `60` | 每多少秒查一次微信 |
| `proactive.wechat_max` | `3` | 一次最多念几条 |
| `proactive.daily` | `[]` | 每天定时说的话 |
| `proactive.quiet` | `["23:30","07:30"]` | 安静时段 |

### 保险箱

| 键 | 默认 | 说明 |
|---|---|---|
| `vault_on` | `false` | 是否自动加密 |
| `vault_delay` | `120` | 图落地后多少秒加密 |

---

## 文件结构

```
极简开源版/
├── run.py              启动入口
├── config.json         配置（自动生成）
├── requirements.txt
├── README.md
├── 启动.bat
│
├── src/
│   ├── find.py         ⭐ 自动查找依赖位置
│   ├── config.py       读写配置
│   ├── dsh.py          调 dsh 命令行        ⭐核心
│   ├── chat.py         对话历史
│   ├── memory.py       长期记忆（向量+关键词）
│   ├── voice.py        语音输入输出
│   ├── look.py         看图（截屏/拍照/分析）
│   ├── wechat.py       微信消息（读 ChatLab）
│   ├── proactive.py    主动助手
│   ├── vault.py        加密保险箱
│   └── server.py       HTTP 服务
│
├── ui/
│   └── index.html      网页（单文件，零依赖）
│
└── data/
    ├── chat.jsonl      对话历史
    ├── memory.jsonl    长期记忆
    ├── memory_vec.npy  记忆向量
    ├── look/           看图缓存
    ├── vault/          加密卷
    └── wechat_seen.json 微信已读记录
```

---

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/state` | 全部状态 |
| POST | `/api/ask` | 问一句 `{text, session, speak}` |
| POST | `/api/voice` | 念一段 `{text}` |
| POST | `/api/record` `/api/asr` | 录音 / 识别 |
| GET | `/api/history` `/api/export` | 历史 / 导出 Markdown |
| GET/POST | `/api/config` | 读 / 写配置 |
| **GET** | `/api/memory` | 记忆列表 + 统计 |
| POST | `/api/memory/add` `/forget` `/clear` | 增 / 删 / 清空 |
| GET | `/api/memory/find?query=` | 语义检索 |
| GET | `/api/look/status` `/list` | 看图状态 / 列表 |
| POST | `/api/look/shot` `/cam` `/see` | 截屏 / 拍照 / 分析 |
| GET | `/api/wx/status` `/sessions` `/recent` `/new` | 微信查询 |
| POST | `/api/wx/seen` `/speak` `/reset` | 标记已读 / 播报 / 重置 |
| GET | `/api/proactive` | 主动助手状态 |
| POST | `/api/proactive/conf` `/check` | 改配置 / 立即跑 |
| GET | `/api/vault/status` `/list` | 保险箱状态 / 文件 |
| POST | `/api/vault/archive` `/export` | 收一轮 / 导出 |

---

## 实现笔记

踩过的坑，写下来省得再踩。

### 1. 会话续聊

`dsh` 的 headless profile 支持多轮：第一次提问会返回一个
session id，之后每次带着这个 id 问，就落在同一个会话里。

`--session-id` 传**不存在的 id 会报错退出**，不会自动新建。

### 2. 流式事件

`--json` 输出**逐行 JSON**，正文在 `type == "text"`：

```json
{"type":"session","sessionId":"..."}
{"type":"status","phase":"turn_start","turn":1}
{"type":"text","text":"正文"}
{"type":"final","text":"..."}
```

### 3. numpy 数组不能用 `not` 判断 ⚠️

```python
if not a:          # ✗ ndarray 会抛 ValueError
if len(a) == 0:    # ✓
```

> 这个异常被 `try/except` 吞掉后**完全静默** ——
> 表现是「向量相似度明明 0.55，检索却说找不到」。
> 排查了半小时才发现。

### 4. HuggingFace 必须离线模式

```python
os.environ["HF_HUB_OFFLINE"] = "1"          # 必须在 import 前
from sentence_transformers import SentenceTransformer
```

不设的话会联网做 HEAD 校验，代理拦掉 → 重试 5 轮 → 卡 30 秒。

### 5. FunASR 要给本地路径

```python
AutoModel(model=r"<模型目录>\funasr\...  # ✓
AutoModel(model="paraformer-zh")                           # ✗ 会联网
```

### 6. 播放音频用 MCI

Windows 上只有 `winmm` 的 MCI 能干净播放（`sounddevice` 的
WASAPI/MME 在某些机器上有电流声）。

**临时文件名必须纯 ASCII** —— MCI 对中文/空格路径要转义，很容易出错。

### 7. 环境变量要清代理

启动时清掉 `HTTP_PROXY` 等。本机服务不需要代理，
而代理通常不转发 `127.0.0.1`，会导致"服务明明开着却连不上"。

### 8. 微信"我"的识别

同一个人的账号名在不同会话库里不一样，必须多层判断
（详见上面「微信播报」一节）。

### 9. force 语义要一致

`tick(force=True)` 原本只跳过了开头的检查，
但后面 `can_speak()` 又检查一遍开关和安静时段 →
半夜手动触发照样被拦，什么都不发生。

修法：`can_speak(force)` 把 force 一路传下去。

---

## 已知限制

- **没有流式显示**：等 AI 全部答完才一次显示。`dsh --json` 其实有流式事件，想改打字机效果的话在 `src/dsh.py` 的 `on_event` 回调里处理。
- **单用户**：设计上就是单人本地用。
- **保险箱整卷读写**：每次读要解密整个卷。卷到 GB 级会慢，那时该改成增量格式。
- **微信是只读的**：不会帮你回消息，只能看和念。
- **历史不分会话**：只有一个 `chat.jsonl`。

---

## 为什么这么简单

这个项目刻意**不做**很多东西：

| 不做 | 原因 |
|---|---|
| 花哨的动画/皮肤 | 看久了累，对功能没帮助 |
| 自定义主题 | 一套配色够用 |
| 插件系统 | 需要时直接改代码更快 |
| 数据库 | JSONL 用文本编辑器就能看，出问题只坏一行 |
| 前端框架 | 一个 HTML 文件，改起来不用编译 |
| 云同步 | 数据都在本地，不往外发 |

代码量控制在能一次读完的规模 —— 想改什么直接翻源码。

---

## 隐私

**这个程序全部在本地跑。** 数据不会往外面发。

### 数据存在哪

| 文件 | 内容 |
|---|---|
| \data/chat.jsonl\ | 对话记录 |
| \data/memory.jsonl\ | 长期记忆 |
| \data/memory_vec.npy\ | 记忆向量 |
| \data/rec.wav\ | 最近一次录音 |
| \data/look/\ | 看过的截图和照片 |
| \data/vault/\ | 加密保险箱 |
| \config.json\ | 你的设置 |

**全部在程序目录下的 \data/\ 和 \config.json\。**
删掉它们 = 完全重置。

### 什么情况下会联网

| 操作 | 连到哪 | 能关吗 |
|---|---|---|
| 对话 | DeepSeek Harness（你配的后端）| 换本地模型 |
| edge-tts 朗读 | 微软的语音服务 | 换成 \sapi\（系统自带，离线） |
| 首次下载模型 | HuggingFace / ModelScope | 手动下好放本地 |
| 微信**不联网** | —— | 只读本地数据库 |

**不想联网的话：**
\\cmd
set HF_HUB_OFFLINE=1
set MODELSCOPE_OFFLINE=1
\再把 \	ts_engine\ 改成 \sapi\。

### 如果你想分享这份代码

`.gitignore` 已经帮你挡住了这些不该提交的东西：

```
data/         你的对话、记忆、录音、截图
config.json   你的设置
*.dvn         保险箱（含密钥）
*.wav *.jpg   录音和图片
*.npy         向量数据
*.db          聊天数据库
__pycache__/  编译缓存（含你的绝对路径）
```

提交前跑一遍：

```bash
python -B check_privacy.py          # 只检查
python -B check_privacy.py --fix    # 检查 + 自动删掉不该带的
```

`-B` 别省 —— 不加的话 Python 会生成 `__pycache__/`
（里面有你的绝对路径），检查完反而不干净。

**它查什么：**

| 检查项 | 内容 |
|---|---|
| 不该带的文件 | 录音 / 截图 / 数据库 / 向量 / `local.properties` |
| 本机标识 | **主机名 / 用户名 / 家目录 / IP / 网关 / DNS / MAC / Wi-Fi 名** |
| 密钥 | OpenAI / GitHub / AWS / 私钥 / DPAPI 密文 |
| **APK 内部** | 三个 APK 的**每一个字节** |
| 外链 | 白名单外的域名 |

⚠️ **特别注意**：`data/` 里全是你的私人东西。
一旦提交上去，就算之后删掉，Git 历史里还能翻出来。

## 许可

MIT
