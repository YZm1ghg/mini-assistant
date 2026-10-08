# 迷你助手 · 手机 / 平板 / 手表

三个独立的 Android 应用，连你自己电脑上的「迷你助手」服务。

**⚠️ 这三个 APK 里没有任何地址、端口、密钥。**
后端地址由你在手机上填一次，之后记住。

---

## 快速开始

### 1. 先在电脑上把服务跑起来

```bash
cd 极简开源版
python run.py
```

启动时会打印一行类似这样的地址：

```
  监听     : http://0.0.0.0:64874
```

**记住那个端口号**（默认 `64874`）。

> 如果服务只监听 `127.0.0.1`，手机就连不上。
> 用 `python run.py --host 0.0.0.0` 让它监听所有网卡。

### 2. 查电脑的局域网 IP

```cmd
ipconfig
```

找 `IPv4 地址`，形如 `192.168.x.x`。

> ⚠️ 手机和电脑必须在**同一个 Wi-Fi** 下。

### 3. 装 APK 并填地址

把 `mobile/dist/` 里的 APK 拷到手机装上，打开后：

```
后端地址  →  填  192.168.x.x:64874
```

点「连接」。第一次连上会验证一下，通了才保存。

**懒得查 IP？** 点「自动搜索」—— 它会在常见网段里扫一遍。

---

## 三个版本的区别

| | 手机 | 平板 | 手表 |
|---|---|---|---|
| APK | `mini-phone.apk` | `mini-tablet.apk` | `mini-watch.apk` |
| 布局 | 单栏 | 左侧栏 + 主区 | 全屏麦克风 |
| 打字 | 主界面 | 主界面 | 点右上角键盘图标 |
| 历史 | 60 条 | 60 条 | 最近 6 条 |

**网页是同一套** —— 只有布局不同。改 `mobile/common/www/`
里的文件，三个版本一起更新。

---

## 从源码构建

```bash
python build_apk.py            # 三个都打
python build_apk.py phone      # 只打手机版
python build_apk.py --clean    # 清构建产物
```

### 需要什么

| 工具 | 版本 | 从哪来 |
|---|---|---|
| JDK | 17 或更高 | [adoptium.net](https://adoptium.net/) |
| Android SDK | API 34 | 装 [Android Studio](https://developer.android.com/studio) 会自带 |
| Gradle | 8.x | [gradle.org](https://gradle.org/install/) |

构建脚本会自己找这三个 —— 按顺序试：
环境变量（`JAVA_HOME` / `ANDROID_HOME`）→ 常见安装目录
→ `~/.gradle/wrapper/dists`。

**找不到会告诉你去哪装，不会静默失败。**

### 构建产物

```
mobile/dist/
├── mini-phone.apk    2.3 MB
├── mini-tablet.apk   2.3 MB
└── mini-watch.apk    2.3 MB
```

---

## 项目结构

```
mobile/
├── common/www/           网页（三版共用）
│   ├── index.html        手机
│   ├── tablet.html       平板
│   ├── watch.html        手表
│   ├── app.js            逻辑
│   └── style.css         样式
│
├── phone/                手机工程
│   ├── settings.gradle
│   ├── build.gradle
│   ├── gradle.properties
│   └── app/
│       ├── build.gradle
│       └── src/main/
│           ├── AndroidManifest.xml
│           ├── java/.../MainActivity.java
│           └── res/values/
│
├── tablet/               平板工程（同上）
├── watch/                手表工程（同上）
└── dist/                 打好的 APK
```

**`app/src/main/assets/` 是构建时生成的**（从 `common/www` 拷过来），
不用手改，也别提交到 Git。

---

## 权限说明

| 权限 | 干什么 | 不给会怎样 |
|---|---|---|
| `INTERNET` | 连你电脑上的服务 | 用不了 |
| `RECORD_AUDIO` | 语音输入 | 只能打字 |
| `ACCESS_NETWORK_STATE` | 看网络状态 | 没影响 |

**麦克风是可选权限。** 不给也能正常打字聊天。

---

## 连不上怎么办

按顺序排：

**① 电脑上服务起着吗**

浏览器打开 `http://127.0.0.1:64874` 看看。

**② 服务监听的是哪个地址**

```
监听 : http://127.0.0.1:64874   ← 只有本机能连
监听 : http://0.0.0.0:64874     ← 局域网能连 ✓
```

`127.0.0.1` 那个情况下手机连不上，要 `--host 0.0.0.0` 重启。

**③ 手机和电脑同一个 Wi-Fi 吗**

手机连的是不是同一个路由器？有没有连到访客网络
（访客网络通常不能访问内网）？

**④ 防火墙**

Windows 第一次会弹窗问「是否允许」，点**允许**。

手动放行（管理员 PowerShell）：

```powershell
netsh advfirewall firewall add rule name="迷你助手" ^
  dir=in action=allow protocol=TCP localport=64874
```

**⑤ 地址写对了吗**

`192.168.x.x:64874` —— **`http://` 可以不写**（会自动补），
但**端口别漏**。

**⑥ 都不行**

点菜单里的「改后端地址」重填一次。

---

## 为什么界面用网页而不是原生

| | 网页 | 原生 |
|---|---|---|
| 三版共用 | ✓ 改一次三处生效 | ✗ 写三遍 |
| 跟桌面版一致 | ✓ 同样的配色和逻辑 | ✗ 要重做 |
| 改界面 | 记事本就行 | 要装 Android Studio |
| 性能 | 够用 | 更好 |

聊天框这个场景用不着原生渲染。

---

## 隐私

- **地址只存在你手机本地**（WebView 的 localStorage）
- **数据不经过任何第三方** —— 直接连你自己的电脑
- 代码里搜不到任何 IP、端口、token
- 清空：「菜单 → 清空本地记录」

### 分享前检查

```bash
python ../check_privacy.py
```

---

## 许可

MIT
