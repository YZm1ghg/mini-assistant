# 安装教程

从**零**开始，一步步装到能跑。

> **⚠️ 先看这条：**
> 这个项目**核心零第三方依赖**（只靠 Python 标准库就能聊天、跑技能、
> 看系统状态）。下面哪些是可选的，每步都标了。
>
> **超懒人版**（Windows）：
> ```
> ① 装 Python           https://www.python.org/downloads/  （勾 Add to PATH）
> ② 装 Node.js          https://nodejs.org/                （一路下一步）
> ③ 装 dsh              npm install -g @deepseek-ai/dsh
> ④ 下载本项目          解压
> ⑤ 双击「启动.bat」
> ```
> 就这五步。下面是把每步讲清楚。

---

## 目录

1. [装 Python](#1-装-python)
2. [装 Node.js](#2-装-nodejs)
3. [装 DeepSeek Harness](#3-装-deepseek-harness)
4. [下载本项目](#4-下载本项目)
5. [装 Python 依赖](#5-装-python-依赖)
6. [自检](#6-自检)
7. [启动](#7-启动)
8. [（可选）语音功能](#8-可选语音功能)
9. [（可选）微信功能](#9-可选微信功能)
10. [（可选）手机 / 平板 / 手表](#10-可选手机--平板--手表)
11. [常见问题](#常见问题)

---

## 1. 装 Python

### 下载

**官网**：<https://www.python.org/downloads/>

**要 3.10 或更高。** 页面上那个黄色大按钮就是最新版。

### 安装

**⚠️ 装的时候一定要勾这两个：**

```
☑ Add python.exe to PATH          ← 安装向导第一页最下面，必须勾！
☑ Install pip                     ← 默认就勾着，别取消
```

**不勾第一个的话**，命令行里敲 `python` 会提示「不是内部或外部命令」。

### 验证

按 `Win + R`，输入 `cmd`，回车，然后敲：

```cmd
python --version
```

应该看到：

```
Python 3.12.x
```

**⚠️ Windows 应用商店的 Python 别用** —— 它的路径很怪，
`pythonw.exe` 有时候找不到，会引出一堆麻烦。老老实实去官网下安装包。

### 装 pip（一般自带）

```cmd
python -m pip --version
```

看到版本号就行。没有的话：

```cmd
python -m ensurepip --upgrade
```

---

## 2. 装 Node.js

### 下载

**官网**：<https://nodejs.org/>

**要 18 或更高。** 点左边那个 **LTS** 按钮（长期支持版，更稳）。

### 安装

**一路「下一步」就行**，不用改任何选项。

### 验证

**新开一个 cmd**（重要，不新开读不到 PATH）：

```cmd
node --version
npm --version
```

应该看到两行版本号。

---

## 3. 装 DeepSeek Harness

这是 AI 后端，本项目套在它外面。

### 安装

```cmd
npm install -g @deepseek-ai/dsh
```

**⚠️ 国内网络慢的话，先换 npm 源：**

```cmd
npm config set registry https://registry.npmmirror.com
```

### 验证

```cmd
dsh --version
```

看到版本号就成。

**⚠️ 如果提示「不是内部或外部命令」** —— npm 的全局目录没在 PATH 里。
先跑这个看看：

```cmd
npm root -g
```

然后把这个路径**的上一级**加进系统 PATH。

### 首次使用要登录

```cmd
dsh
```

第一次会让你配置 API key 之类的。按提示做。

> **⚠️ 本项目不碰你的 key。** dsh 自己管，我们只是调它的命令行。

---

## 4. 下载本项目

### 方式 A：下载压缩包（推荐新手）

**https://github.com/YZm1ghg/mini-assistant/releases**

下载 `mini-assistant-source.zip`，解压到任意目录。

**⚠️ 路径别带中文。** 有些 Python 包对中文路径支持不好。

```
✅ D:\mini-assistant
✅ C:\tools\mini-assistant
❌ D:\我的项目\迷你助手
```

### 方式 B：git clone

```cmd
git clone https://github.com/YZm1ghg/mini-assistant.git
```

**⚠️ 国内 clone 不动的话**，用方式 A。

---

## 5. 装 Python 依赖

打开 cmd，`cd` 到你解压的目录：

```cmd
cd /d D:\mini-assistant
```

然后：

```cmd
pip install -r requirements.txt
```

### 国内网络慢的话

**清华源**（推荐）：

```cmd
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**永久换源**（以后都不用加 `-i`）：

```cmd
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### 装了什么

`requirements.txt` 里有 7 个包，**全是可选的**，对应不同功能：

| 包 | 管什么 | 不装会怎样 |
|---|---|---|
| `psutil` | 系统监控、音量、进程 | 「CPU 占用」「进程排行」失效 |
| `sounddevice` | 录音 | 不能说话输入，**能打字** |
| `edge-tts` | 在线朗读 | 退回系统离线语音 |
| `numpy` | 记忆向量检索 | 退回关键词匹配 |
| `Pillow` | 截图 | 截屏功能关掉 |
| `opencv-python` | 摄像头 | 只能截屏不能拍照 |
| `cryptography` | 保险箱加密 | 保险箱关掉 |

**⚠️ 一个都不想装也行** —— 直接跳到下一步，程序会自己降级。

---

## 6. 自检

```cmd
python run.py --doctor
```

它会检查所有外部依赖，输出类似：

```
  ==========================================================
   依赖自检
  ==========================================================
   ● Node.js              <node 目录>\node.exe
   ● DeepSeek Harness     <npm 目录>\@deepseek-ai\dsh\...\bin.js
   ● ChatLab 数据          <家目录>\.chatlab\data\databases
   ● FunASR 识别           <模型目录>\...\snapshots\master
   ○ faster-whisper       （没找到）[可选] 说话输入（备选）
   ● 中文向量模型           <缓存目录>\huggingface\hub\...
   ○ Kokoro 语音           （没找到）[可选] 本地朗读要用
   ● ffmpeg               <npm 目录>\ffmpeg-static\ffmpeg.exe
   ● 浏览器                <浏览器目录>\msedge.exe
  ----------------------------------------------------------
   家目录   : <你的家目录>
   模型目录 : <你的模型目录>
  ==========================================================

   可以用环境变量指定位置：
     MINI_NODE        node.exe
     MINI_DSH         dsh 的 bin.js
     MINI_CHATLAB     ChatLab 数据库目录
     MINI_MODELS      模型总目录
     MINI_FUNASR      FunASR 模型目录
     MINI_WHISPER     whisper 模型目录
     MINI_TEXT2VEC    向量模型目录
     MINI_FFMPEG      ffmpeg

   也可以直接写进 config.json。
```

**「●」= 找到了　「○」= 没找到**

带 `[可选]` 的说明只是没装那个功能，不影响其他。

**⚠️ 找不到也不用慌** —— 对应功能自动关掉，其他照常。

**找不到的话有四种办法（按推荐顺序）：**

**① 装到默认位置**（最省事）

程序会自己去常见位置找。

**② 装完告诉它一声**（用环境变量）

```cmd
set MINI_MODELS=D:\models
python run.py
```

支持的变量见上面 `--doctor` 输出里列的那些。

**③ 写进 config.json**

```json
{
  "dsh_bin": "C:\\完整\\路径\\bin.js"
}
```

**④ 随它去**

没找到的功能显示「未启用」，其他一切正常。

**⚠️ 分享 `--doctor` 的截图前记得看一眼** ——
里面显示的是你机器上的真实路径，会暴露用户名。

---

## 7. 启动

```cmd
python run.py
```

浏览器会自动打开界面。

**或者双击 `启动.bat`**（Windows 上用这个最省事）。

### 常用参数

```cmd
python run.py --doctor          # 只自检，不启动
python run.py --no-open         # 启动但不自动开浏览器
python run.py --port 61000      # 指定端口（默认 64874）
python run.py --host 0.0.0.0    # 手机要连的话必须加这个
```

### 想让它一直跑

**别关那个黑窗口** —— 关了就停了。

要最小化到托盘、开机自启的话，自己写个计划任务，或者用
[nssm](https://nssm.cc/) 之类的工具包成服务。

---

## 8. （可选）语音功能

### 说话输入（语音识别）

**需要下模型，装之前想清楚。**

#### FunASR（中文最准，推荐）

```cmd
pip install funasr
```

**模型约 1GB，内存要 3GB 以上。**

模型会自动下载到 `~/.cache/modelscope`。
国内网络慢的话，用 ModelScope 手动下（见 README）。

**⚠️ 内存不够会报 `MemoryError`。** 程序会自动跳过它，改用 whisper。

#### faster-whisper（体积小）

```cmd
pip install faster-whisper
```

模型 tiny 只有 75MB。

#### 两个都不用？

**没关系。** 打字聊天完全不受影响，只是不能用麦克风。

### 朗读（语音合成）

**`edge-tts` 已经装了**（在 recommendations 里）。

**⚠️ 但 mp3 → wav 要 ffmpeg。** 装一个：

```cmd
npm install -g ffmpeg-static
```

或者去 <https://ffmpeg.org/download.html> 下载，加到 PATH。

**没有 ffmpeg 会退回系统语音**（Windows 自带，离线，音质一般）。

### 检查语音状态

浏览器界面右侧栏，或者：

```cmd
curl http://127.0.0.1:64874/api/voice
```

---

## 9. （可选）微信功能

**⚠️ 这一节只对 Windows 有效。**

### 为什么不能直接读微信

**微信 4.x 的数据库全部是 SQLCipher 加密的**（实测 36 个库一个明文都没有）。

直接读需要从内存里抠密钥 + 自己实现 SQLCipher 解密 ——
这是个独立的大工程，而且微信每次升级都可能失效。

**✅ 所以走 [ChatLab](https://chatlab.fun) 的导出路子。**

### 装 ChatLab

**官网**：<https://chatlab.fun>

或者：

```cmd
npm install --global chatlab-cli
```

### 导出一次

按 ChatLab 的说明把微信聊天记录导出。

导出后数据在：

```
~/.chatlab/data/databases/
    chat_xxx.db        ← 每个会话一个库
    ...
```

**⚠️ 这一步本来就要做** —— 微信的库是滚动的
（`message_0/1/2` 分片），直接读原始库历史消息会不全。

### 验证

```cmd
curl http://127.0.0.1:64874/api/wx/status
```

看到 `"sessions": 数字` 就成。

### 用不上？

**不装完全没问题。** 微信相关的功能会显示「未找到数据」。

---

## 10. （可选）手机 / 平板 / 手表

### 直接装 APK

**https://github.com/YZm1ghg/mini-assistant/releases**

下载对应你设备的 APK，传到手机装上。

**⚠️ 三个 APK 都是 debug 签名** —— Android 会提示「来自未知来源」，
允许一下就行。

### 第一次打开要填地址

1. **电脑上**跑 `python run.py --host 0.0.0.0`
2. 记下打印的端口（默认 `64874`）
3. **电脑上**跑 `ipconfig`，找 `IPv4 地址`，形如 `192.168.x.x`
4. **手机上**打开 App，填 `IP:端口`

**⚠️ 手机和电脑要在同一个 Wi-Fi。**

### 自己构建 APK

需要 JDK 17+、Android SDK、Gradle 8.x：

```cmd
python build_apk.py            # 三个都打
python build_apk.py phone      # 只打手机版
```

详见 [mobile/README.md](mobile/README.md)。

---

## 常见问题

### `python` 不是内部或外部命令

**装 Python 时没勾「Add to PATH」。**

两个办法：
1. 重装，勾上那个框
2. 手动加：把 `Python安装目录` 和 `Python安装目录\Scripts` 加进系统 PATH

### `pip` 装包报 SSL 错

**网络问题。** 换国内源：

```cmd
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### `dsh` 找不到

```cmd
npm root -g
```

把这个路径**的上一级**加进系统 PATH，重启 cmd。

或者在本项目 `config.json` 里手填：

```json
{
  "dsh_bin": "C:\\完整\\路径\\bin.js"
}
```

### 启动报端口被占用

**程序会自动换端口。** 看启动时打印的那行：

```
监听  : http://127.0.0.1:64284
```

**⚠️ 用实际打印的端口，不要死记 64874。**

### 麦克风录不到声音

**⚠️ 先看这条：** Windows 现代音频驱动**不再支持**老的录音接口，
本项目用 `sounddevice`（WASAPI）—— 必须装它：

```cmd
pip install sounddevice
```

**还不行的话：**
- Windows 设置 → 隐私 → 麦克风 → 允许应用访问
- 检查麦克风是不是被静音了
- 换个录音设备试试

### 界面卡 / 慢

**⚠️ 正常应该是毫秒级。** 如果慢到几十秒：

1. 看看是不是某个依赖在联网（`--doctor` 会显示）
2. 检查 `data/` 目录是不是特别大
3. 重启一下程序

### 想彻底重置

删掉 `data/` 目录和 `config.json`，重启就是全新状态。

```cmd
rmdir /s /q data
del config.json
```

**⚠️ 这会删掉你所有对话记录和记忆。**

### 想分享给朋友 / 传上 GitHub

**先跑这个：**

```cmd
python -B check_privacy.py --fix
```

它会检查有没有你的 IP、主机名、用户名、录音、截图、密钥……

**看到 `✓✓ 没有发现个人信息` 才能分享。**

---

## 需要什么（一张表）

| 组件 | 版本 | 必需？ | 从哪来 |
|---|---|---|---|
| **Python** | 3.10+ | ✅ | [python.org](https://www.python.org/downloads/) |
| **Node.js** | 18+ | ✅ | [nodejs.org](https://nodejs.org/) |
| **DeepSeek Harness** | 0.2+ | ✅ | `npm i -g @deepseek-ai/dsh` |
| psutil | 5.9+ | ⭕ 推荐 | `pip install psutil` |
| sounddevice | 0.4+ | ⭕ 录音要 | `pip install sounddevice` |
| edge-tts | 6.1+ | ⭕ 朗读要 | `pip install edge-tts` |
| numpy | 1.24+ | ⭕ 记忆要 | `pip install numpy` |
| Pillow | 10+ | ⭕ 截图要 | `pip install Pillow` |
| opencv-python | 4.8+ | ⭕ 拍照要 | `pip install opencv-python` |
| cryptography | 41+ | ⭕ 保险箱要 | `pip install cryptography` |
| funasr | 1.0+ | 🔵 语音识别 | `pip install funasr` |
| faster-whisper | 1.0+ | 🔵 语音识别 | `pip install faster-whisper` |
| ChatLab | 最新 | 🔵 微信要 | [chatlab.fun](https://chatlab.fun) |
| ffmpeg | 最新 | 🔵 在线朗读要 | [ffmpeg.org](https://ffmpeg.org/download.html) |

**✅ = 不装跑不起来　⭕ = 装了好用　🔵 = 特定功能才要**

---

## 最小安装（能跑就行）

```cmd
:: 1. 装 Python（官网，勾 Add to PATH）
:: 2. 装 Node.js（官网，一路下一步）
:: 3. 装 dsh
npm install -g @deepseek-ai/dsh

:: 4. 下载解压本项目，cd 进去
cd /d D:\mini-assistant

:: 5. 什么都不装，直接跑
python run.py
```

**就这五步。** 语音、微信、截图这些功能会显示「未启用」，
但**聊天、技能、系统监控**全部可用。

---

## 许可

MIT
