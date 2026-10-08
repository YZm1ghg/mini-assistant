# 迷你助手 v1.0.0

一个**极简**的本地 AI 助手。后端接 [DeepSeek Harness](https://www.npmjs.com/package/@deepseek-ai/dsh)。

**这一版包含桌面端 + 手机 / 平板 / 手表三个 Android 应用。**

---

## 下载哪个

| 文件 | 说明 |
|---|---|
| `mini-assistant-source.zip` | **源码**（桌面端 + 移动端全部代码） |
| `mini-phone.apk` | 手机版 |
| `mini-tablet.apk` | 平板版（左侧栏 + 更宽阅读区） |
| `mini-watch.apk` | 手表版（全屏麦克风，适配小圆屏） |

⚠️ **APK 里没有任何地址、端口、密钥。**
装了之后第一次打开会让你填**你自己电脑**的地址。

---

## 桌面端怎么跑

需要：Python 3.10+ / Node.js 18+ / DeepSeek Harness

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 自检（会告诉你缺什么、去哪装）
python run.py --doctor

# 3. 启动
python run.py
```

浏览器会自动打开。

**换个电脑直接跑** —— 所有外部依赖（Node / dsh / 模型 / ffmpeg）
都是自动查找的，不用改代码。

---

## 手机版怎么用

1. 电脑上跑 `python run.py`，记住端口（默认 `64874`）
2. 电脑上 `ipconfig` 查自己的局域网 IP
3. 手机装 APK，打开后填 `IP:端口`

⚠️ 手机和电脑要在**同一个 Wi-Fi** 下。

> 服务默认监听 `127.0.0.1`（只有本机连得上）。
> 手机要连的话用 `python run.py --host 0.0.0.0`。

---

## 这一版有什么

### 桌面端

| 功能 | 说明 |
|---|---|
| 聊天 | 单页网页界面，不用开终端 |
| 语音 | edge-tts 在线朗读 / Windows SAPI 离线；FunASR 或 whisper 识别 |
| **技能系统** | **29 个命令本地直答，毫秒级**（走 AI 要 25 秒）|
| 意图识别 | 自动判断该走技能还是走 AI |
| 系统监控 | CPU / 内存 / 磁盘 / 显卡 / 温度 / 网络 / 进程 |
| 系统控制 | 音量 / 亮度 / 进程 / 电源 / 锁屏 / 卡死检测 |
| 长期记忆 | 本地 JSONL + 向量检索 |
| 看图 | 截屏 / 拍照 → AI 分析 |
| 微信 | 读 ChatLab 数据库，识别谁找过你 |
| 保险箱 | AES-256-GCM + Windows DPAPI |

### 移动端

三个独立的 WebView 应用，共用一套网页。
**不含任何硬编码地址。**

---

## 依赖说明

**核心只需要两个**（其余都是可选的，没装会自动关掉对应功能）：

```
sounddevice   # 录音（Windows 现代驱动只支持 WASAPI，绕不过去）
edge-tts      # 在线语音合成
```

**自己实现的**（省掉依赖）：
- `soundfile` + `numpy` → 用标准库 `wave` + `array` 重写
- `pyttsx3` → 直接 ctypes 调 Windows SAPI

详见 [README](https://github.com/YZm1ghg/mini-assistant#依赖说明)。

---

## 隐私

**全部本地运行，数据不经过任何第三方。**

- 对话记录 / 记忆 / 录音 / 截图都在 `data/` 目录
- 保险箱密钥绑本机（Windows DPAPI），不存密码
- 仓库自带 `check_privacy.py`，分享前可一键体检

```bash
python -B check_privacy.py --fix
```

---

## 校验下载

```bash
# 下载后验证文件完整性
sha256sum -c SHA256SUMS.txt
```

---

## 许可

MIT
