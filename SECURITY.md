# 安全说明

这个项目**在你自己的电脑上跑，数据不出本机**。
下面把安全相关的设计、边界、和已知限制都讲清楚。

> **⚠️ 先说最重要的三条：**
>
> 1. **默认只监听 `127.0.0.1`** —— 外网连不上
> 2. **不用 `shell=True`** —— 没有命令注入
> 3. **对话内容只发给 `dsh`**（你自己配的后端）—— 不经我们任何服务器

---

## 目录

- [网络](#网络)
- [数据](#数据)
- [加密](#加密)
- [命令执行](#命令执行)
- [第三方依赖](#第三方依赖)
- [分享前检查](#分享前检查)
- [已知限制](#已知限制)
- [报告问题](#报告问题)

---

## 网络

### 默认监听本机

```python
# src/config.py
"host": "127.0.0.1"     # ← 默认值
```

**`127.0.0.1` 是「回环地址」** —— 只有本机能连，
同一个 Wi-Fi 下的其他设备**也连不上**。

### 想给手机连才需要改

```cmd
python run.py --host 0.0.0.0
```

**⚠️ `0.0.0.0` 表示「所有网卡」，局域网内任何设备都能访问。**

**这意味着：**
- ✅ 你自己的手机能连
- ⚠️ 同一个 Wi-Fi 下的**其他人也能连**（如果他知道你的 IP 和端口）

**这种情况下的风险：**
- 别人能看到你的对话记录（通过 `/api/history`）
- 别人能用你的 AI（消耗你的额度）
- 别人能读你的记忆库

**✅ 建议：**
- 只在需要时开 `0.0.0.0`，用完改回来
- 别在**公共 Wi-Fi**（咖啡厅、机场）下开
- 家里的 Wi-Fi 相对安全（但要确保路由器密码够强）

### 这个服务**没有鉴权**

**⚠️ 这是已知限制，不是 bug。**

设计上它是个**本地工具**，默认只监听本机，
加鉴权反而增加复杂度（用户要记密码）。

**如果你要暴露到公网：**
- **不要直接开端口** —— 中间加一层带认证的反向代理（nginx + Basic Auth）
- 或者用 SSH 隧道 / VPN
- 或者只在自己可控的内网用

### 对外发起的连接

程序**只在两种情况下主动联网**：

| 场景 | 连到哪 | 发什么 | 能关吗 |
|---|---|---|---|
| 聊天 | 你在 `dsh` 里配的后端 | 你的问题 + 检索到的记忆 | 用本地模型 |
| edge-tts 朗读 | 微软的语音服务 | **只发要念的那段文字** | `tts_engine` 改成 `sapi` |
| 首次下模型 | HuggingFace / ModelScope | 无 | 手动下好放本地 |

**⚠️ 注意：`dsh` 后端连哪、发什么，由 `dsh` 自己决定，
不在本项目控制范围内。** 你要关心数据去哪，得看 `dsh` 的配置。

**想完全离线：**

```cmd
set HF_HUB_OFFLINE=1
set MODELSCOPE_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
```

再把 `tts_engine` 改成 `sapi`（Windows 系统语音，离线）。

### 代码里没有埋点

**搜一遍就知道：**

```bash
grep -rn "urllib\|requests\|socket\." src/
```

只有这几处，全是**给浏览器开网页**用的：

```
skills.py:  百度 / b站 / 淘宝 / 知乎 / github 的网址（用户说"打开百度"时才用）
server.py:  打印自己的监听地址
memory.py:  hf-mirror.com（只是写进环境变量，不是发请求）
```

**没有统计数据上报，没有崩溃收集，没有任何「回调」。**

---

## 数据

### 全在程序目录下

```
迷你助手/
├── config.json          你的设置（明文 JSON）
└── data/
    ├── chat.jsonl       所有对话记录
    ├── memory.jsonl     长期记忆
    ├── memory_vec.npy   记忆向量
    ├── rec.wav          最近一次录音
    ├── look/            看过的截图和照片
    ├── export/          导出的东西
    ├── proactive_state.json   主动助手状态（哪些播报过了）
    └── *.log            各模块日志
```

### 打包成 exe 之后

**⚠️ 这一点很容易踩坑，程序里专门处理了。**

PyInstaller 的单文件 exe 会把代码解包到**临时目录**
（`%TEMP%\_MEI123456`）然后从那里运行。

**如果直接写在那里，关掉程序数据就没了。**

✅ 所以代码里区分了两种目录：

```python
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).parent   # 数据存 exe 旁边
    RES  = Path(sys._MEIPASS)            # 程序资源在临时目录
else:
    ROOT = RES = Path(__file__).parent   # 源码运行，同一个目录
```

**结果：exe 放在哪，`data/` 就生成在哪。**
把 exe 挪到 U 盘，数据也跟着走。

### 想彻底删掉

```cmd
rmdir /s /q data
del config.json
```

**⚠️ 这会删掉所有对话、记忆、录音、截图。**

### 想加密整个 data 目录

**目前没有做** —— 这是个取舍：

- 做全盘加密的话，每次读写都要解密，会拖慢
- 而且密钥还是存在本机（DPAPI），能进你电脑的人还是能解

**✅ 现在的做法：只加密「敏感图」**（保险箱功能），
文字对话不加密，因为：

1. 加密后**搜索和向量检索都用不了**（要用就得全解密到内存）
2. 威胁模型上，能读到你磁盘的人，基本也能读到你内存

**真要保护的话：** 用 BitLocker 加密整个磁盘，或者把 `data/`
放到 VeraCrypt 容器里。

---

## 加密

### 保险箱（`src/vault.py`）

**算法：AES-256-GCM**

```
① 生成随机 32 字节数据密钥
② 用 Windows DPAPI 加密这个密钥 → 存盘
③ 用数据密钥 AES-256-GCM 加密文件内容
④ 打包成一个 tar 卷
```

### 密钥怎么保护

**用 Windows DPAPI（`CryptProtectData`）：**

```python
ctypes.windll.crypt32.CryptProtectData(...)
```

**DPAPI 是什么：**
- Windows 内置的密钥保护机制
- 密钥**绑定到「这台机器 + 这个用户」**
- 换个电脑、换个用户，**解不开**
- **不需要你记密码**

**✅ 好处：**
- 别人拷走你的 `.key` 文件也没用（换台机器解不开）
- 你不用记密码

**⚠️ 代价：**
- 你**重装系统**或**换电脑**之后，原来的加密卷打不开了
- 忘了导出的话，数据就永远丢了

### GCM 而不是 CBC

**AES-GCM 是「认证加密」：**

| | CBC | GCM |
|---|---|---|
| 加密 | ✅ | ✅ |
| **防篡改** | ❌ 改了数据发现不了 | ✅ 改了会解密失败 |
| 性能 | 慢 | 快（有硬件加速）|

**用 GCM 意味着：** 有人偷偷改了你加密卷里的一个字节，
解密时会**直接报错**，而不是给你一段错误的数据。

### 已知限制

- **没有做抗暴力破解** —— 因为密钥是 DPAPI 保护的，
  不是从密码派生的，所以没有「猜密码」的攻击面
- **没有前向保密** —— 密钥泄露 = 所有历史密文都完蛋
- **没有密钥轮换** —— 改了密钥要重新加密所有东西

**这是个「防止随手翻看」级别的加密，不是「对抗专业取证」级别的。**

---

## 命令执行

### 不用 `shell=True`

**这是最重要的一条。**

```python
# src/dsh.py —— 唯一会执行外部程序的地方（除了系统控制）
cmd = [node, dsh, "--profile", profile, "--json"]
if session_id:
    cmd += ["--session-id", session_id]
cmd.append(question)                    # ← 用户输入是列表里的一个元素

subprocess.Popen(cmd, ...)              # ← 没有 shell=True
```

**✅ 安全的原因：**

`subprocess` 传**列表**时，不走 shell，而是直接调 `CreateProcess`
（Windows）/ `execve`（Linux）。参数之间**不会**被 shell 解释。

**对比一下危险写法：**

```python
# ❌ 危险 —— 用户输入 "a; rm -rf /" 会真的执行 rm
os.system(f'dsh --json "{question}"')

# ❌ 危险 —— 同上
subprocess.run(f'dsh --json "{question}"', shell=True)
```

**本项目的所有外部调用都是列表形式，且**没有一处** `shell=True`。**

**你可以自己验证：**

```bash
grep -rn "shell=True" src/        # 应该没有任何输出
```

### 会被执行的命令清单

**全部列出来（一个不漏）：**

| 模块 | 命令 | 干什么 |
|---|---|---|
| `dsh.py` | `node <dsh的bin.js> ...` | 调 AI 后端 |
| `find.py` | `npm root -g` | 找 npm 全局目录 |
| `audio.py` | `<ffmpeg> -y ...` | mp3 转 wav |
| `sysmon.py` | `<nvidia-smi> --query-gpu=...` | 读显卡状态 |
| `sysmon.py` | `netsh wlan show interfaces` | 读 Wi-Fi 信息 |
| `syscontrol.py` | `powercfg` / `netsh` / `shutdown` | 电源、网络、关机 |
| `tts.py` | `powershell -NoProfile -Command "..."` | 调系统语音合成 |

**⚠️ 注意 `tts.py` 那个 PowerShell：**

```python
script = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    f"$s.Rate = {int(rate)};"
    f"$s.SetOutputToWaveFile('{out}');"
    f"$s.Speak('{safe}');"          # ← safe 是把单引号翻倍转义后的文本
    "$s.Dispose();"
)
```

**这里要念的文字会被拼进 PowerShell 脚本。**

**✅ 防护：** 单引号被翻倍（`'` → `''`），在 PowerShell 单引号字符串
里这是唯一需要转义的字符，所以**注不进去**。

**⚠️ 但这是本项目里**唯一**需要小心的地方** ——
如果你要改进这个项目，改这里之前先想清楚。

**✅ 更安全的做法（可以改进）：**
不用 `-Command` 传脚本，改成写一个 `.ps1` 临时文件再执行，
或者干脆用 `win32com` 直接调 SAPI（不用起 PowerShell）。

### 系统控制能做什么

**这些是「用户主动要求」才执行的：**

| 功能 | 具体动作 |
|---|---|
| 音量 | `pycaw` 或按键模拟 |
| 亮度 | WMI |
| 关机/重启 | `shutdown /s` / `shutdown /r`（**带倒计时，能取消**）|
| 锁屏 | `rundll32 user32.dll,LockWorkStation` |
| 关屏 | 发 `WM_SYSCOMMAND` |
| 结束进程 | `taskkill` |

**⚠️ 注意：**

- **没有「格式化磁盘」「删除系统文件」这类操作**
- 关机/重启**默认带 30 秒倒计时**，来得及取消
- 结束进程需要**进程名**，不会误伤同名系统进程（有保护列表）

**你可以在 `src/syscontrol.py` 里看到完整的保护逻辑。**

---

## 第三方依赖

### 核心零依赖

聊天、技能、系统监控、记忆、微信 —— **只用 Python 标准库**。

### 可选依赖都是「装了才有那个功能」

| 包 | 风险 | 说明 |
|---|---|---|
| `psutil` | 低 | 读系统信息，成熟库 |
| `sounddevice` | 低 | 录音封装（底层是 PortAudio）|
| `edge-tts` | **中** | 会联网到微软 |
| `numpy` | 低 | 数值计算 |
| `Pillow` | 低 | 图像处理 |
| `opencv-python` | 中 | 体积大，但代码成熟 |
| `cryptography` | 低 | 加密库，审计充分 |
| `funasr` / `faster-whisper` | 中 | 要下大模型 |

### 故意**没有**用的库

为了减少依赖，这几个常见的都是自己实现的：

| 常见库 | 自己怎么做的 | 在哪 |
|---|---|---|
| `soundfile` | 标准库 `wave` + `array` | `src/audio.py` |
| `pyttsx3` | ctypes 调 Windows SAPI | `src/tts.py` |
| `pythonnet` | 温度优先用 psutil，不行就算了 | `src/sysmon.py` |

**⚠️ 所以代码里有一堆 `ctypes.windll.xxx`，那是故意的。**

### 供应链建议

```cmd
:: 装之前先看看要装啥
pip install -r requirements.txt --dry-run

:: 或者用 pip-audit 查已知漏洞
pip install pip-audit
pip-audit
```

---

## 分享前检查

**项目自带一个检查脚本** —— 因为「不小心把隐私传上 GitHub」
是这类项目最常见的事故。

```cmd
python -B check_privacy.py          # 只检查
python -B check_privacy.py --fix    # 检查 + 自动删掉不该带的
```

### 它检查什么

| # | 检查项 | 内容 |
|---|---|---|
| 1 | **不该带的文件** | 录音 / 截图 / 数据库 / 向量 / `local.properties` |
| 2 | **本机标识** | 主机名 / 用户名 / 家目录 / **所有 IP** / **网关** / **DNS** / **MAC** / **Wi-Fi 名** |
| 3 | **密钥** | OpenAI / GitHub / AWS / 私钥 / DPAPI 密文 |
| 4 | **APK 内部** | 三个 APK 的**每一个字节**（不是只看文件名）|
| 4b | **角色卡 / 二次元** | 防止把私人设定拷进来 |
| 5 | **外链** | 白名单之外的域名 |

### 为什么 `-B` 不能省

**`-B` 让 Python 不生成 `__pycache__/`。**

`__pycache__` 里的 `.pyc` 会记录**编译时的源文件绝对路径** ——
也就是 `C:\Users\你的名字\...`。

**检查完自己生成一堆带隐私的文件，那就本末倒置了。**

### `.gitignore` 挡了什么

```
data/                对话、记忆、录音、截图
config.json          你的设置
local.properties     本机 SDK 路径（含用户名）
*.dvn *.key          保险箱和密钥
*.npy                向量数据
*.db                 聊天数据库
__pycache__/         编译缓存（含绝对路径）
```

### 三道防线

| 层 | 手段 |
|---|---|
| **第一道** | `.gitignore` —— 从根上不提交 |
| **第二道** | `check_privacy.py` —— 提交前检查 |
| **第三道** | `--fix` —— 发现问题自动清理 |

**⚠️ 但 Git 历史是永久的** —— 如果已经提交了带隐私的文件，
光删掉是没用的，得**重写历史**（`git filter-repo`）。

**所以：每次提交前都跑一遍检查。**

---

## 已知限制

**诚实地列出来：**

### 1. 服务没有鉴权

默认只监听本机，但**改成 `0.0.0.0` 之后局域网内任何人都能用**。

**要暴露到公网的话，必须自己加一层认证。**

### 2. 数据不加密

`data/` 里的对话、记忆、录音都是**明文**。

能读你磁盘的人就能读到这些。

**要保护的话用 BitLocker 或 VeraCrypt。**

### 3. PowerShell 里拼了字符串（两处）

**本项目有 6 处调 PowerShell：5 处是固定脚本，1 处拼了用户文字。**

| 位置 | 拼了什么 | 风险 |
|---|---|---|
| `syscontrol.py` × 5 | **只拼数字和开关**（亮度值、网卡名） | 低 |
| `tts.py` × 1 | **拼了要念的文字** | 中 |

#### `syscontrol.py` 那 5 处（低风险）

```python
# 亮度、网卡开关、关屏 —— 参数是数字或布尔
_ps(f".WmiSetBrightness(1, {pct})")
_ps(f"{'Enable' if on else 'Disable'}-NetAdapter ...")
```

**拼接的变量在上游做过校验：**

- **亮度** —— `max(0, min(100, int(v)))`，只能是 0~100 的整数
- **网卡** —— 只输出 `Enable` 或 `Disable` 两个固定词

**所以注不进去。**

#### `tts.py` 那一处（中风险，但有防护）

```python
safe = text.replace("'", "''")        # 单引号翻倍
script = ("Add-Type -AssemblyName System.Speech; ..."
          f"$s.Speak('{safe}');")
```

**✅ 防护原理：**

在 PowerShell 的**单引号字符串**里，唯一需要转义的字符就是单引号本身
（翻倍即可 —— 类似 SQL 的字符串转义）。

**双引号、反引号、`$()` 在单引号里都是普通字符，不会被解释。**

所以输入 `'; rm -rf /; '` 这类内容会被当成一段普通文本念出来，
**不会被执行**。

**⚠️ 但这是本项目里唯一一处把任意文本拼进命令的地方。**

如果你要改这个项目，动这里之前先想清楚。

**✅ 更稳的做法（欢迎 PR）：**

1. 不用 `-Command`，改成写一个 `.ps1` 临时文件再执行 ——
   参数走文件，不走命令行
2. 或者用 `comtypes` 直接调 SAPI 的 COM 接口 —— 完全不经过 PowerShell
3. 或者用 `-EncodedCommand`（Base64）——
   ⚠ 但那样只是换个地方拼，本质没变

### 4. 微信功能依赖 ChatLab

**不能直接读微信数据库**（微信 4.x 全库加密）。

目前的路径是读 ChatLab 导出的 SQLite。
**这意味着你得先信任 ChatLab。**

### 5. 打的 exe 比较大（564 MB）

因为把 PyTorch 和语音模型依赖都打进去了。

**想要小的话**：从源码跑（417 KB），或者用干净虚拟环境打包。

### 6. 只在 Windows 上测过

用了一堆 Windows 专有 API（DPAPI、SAPI、MCI、WMI）。

**Linux / macOS 上跑不起来**（除非把那些部分重写）。

### 7. 没有自动更新

不会偷偷下载新版本，也不会检查更新。

**这是有意的** —— 减少攻击面。

---

## 报告问题

**发现安全问题的话：**

1. **别开公开 issue** —— 那会把问题暴露给所有人
2. 用 GitHub 的 [Security Advisory](https://github.com/YZm1ghg/mini-assistant/security/advisories/new)
   （只有仓库所有者能看到）
3. 或者直接联系仓库所有者

**报告时带上：**

- 怎么复现
- 影响范围（能干什么）
- 你的环境（Windows 版本 / Python 版本）

---

## 安全清单（自己核对）

**部署前过一遍：**

- [ ] `config.json` 里 `host` 是 `127.0.0.1`（不是 `0.0.0.0`）
- [ ] 没在公共 Wi-Fi 下开 `0.0.0.0`
- [ ] 分享代码前跑了 `python -B check_privacy.py --fix`
- [ ] 知道 `data/` 里是明文，重要数据用了 BitLocker
- [ ] 知道保险箱密钥绑本机，换电脑读不了原来的加密卷
- [ ] 知道聊天内容会发给 `dsh` 后端，那个后端连哪你自己清楚
- [ ] 用 `grep -rn "shell=True" src/` 确认过没有命令注入

**全打勾的话，这个项目对你的风险就很小了。**

---

## 许可

MIT
