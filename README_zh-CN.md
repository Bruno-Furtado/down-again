# down-again

![down-again — 网络又断了？现在你有证据了。](docs/cover.png)

适用于长期开机电脑的家庭网络断线监控工具。它每隔几秒检测一次网络连接，提供可在手机上
打开的实时面板，并能生成可打印的报告，方便在网络频繁中断时向宽带运营商投诉。

![macOS](https://img.shields.io/badge/macOS-11%2B%20tested-blue)
![Linux](https://img.shields.io/badge/Linux-experimental-orange)
![Windows](https://img.shields.io/badge/Windows-experimental-orange)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

[English](README.md) · [Português](README_pt-BR.md) · **中文**

> 面板和报告的界面语言为巴西葡萄牙语。

## 功能

- **实时状态**：显示"Online"（在线）或"Sem internet"（断网），附带计时器和可能原因。
- **连接路径**：电脑 → 路由器 → 互联网 → 网站，直观显示连接在哪一环中断。
- **最近 24 小时一览**：页面顶部显示 24 小时、7 天和 30 天内的断线次数。
- **Wi-Fi 信息**：网络名称、信号强度、信道和连接速率（使用网线时显示"cabo"）。
- **实时延迟图表**（1 小时 / 6 小时 / 24 小时 / 7 天），失败的检测会高亮显示。
- **每日时间线**：每天一条 24 小时色带，每次断线按原因着色。
- **分析**：哪个时段最常断线、责任归属（运营商、本地网络还是 DNS），以及可筛选的断线列表。
- **运营商报告**：可打印或保存为 PDF 的文档，包含检测方法、摘要、每日统计表和全部断线记录，并可导出 CSV。
- **手机通知**：通过 [ntfy](https://ntfy.sh) 推送。网络恢复后会收到"X 时断开，Y 时恢复"的消息。
- **离线可用**：不依赖 CDN 或网络字体。即使外网中断，也能在家庭局域网内打开面板。
- **零依赖**：仅使用 Python 标准库和 SQLite。

## 截图

<p align="center">
  <img src="docs/demo.gif" width="320" alt="手机面板：在线、运营商断线计时、恢复、时间线和主题切换">
</p>

| 深色主题 | 浅色主题 |
|---|---|
| ![面板深色主题](docs/dashboard-dark.png) | ![面板浅色主题](docs/dashboard-light.png) |

**时间线与分析**：将鼠标悬停在某次断线上，可查看原因、时长和 Wi-Fi 信号。

![每日时间线、按小时和按原因统计的断线](docs/insights.png)

**运营商报告**：可打印或保存为 PDF。

![可打印的可用率报告](docs/report.png)

> 截图使用的是模拟数据。

## 支持的平台

| 平台 | 状态 | 后台运行方式 |
|---|---|---|
| **macOS 11+** | ✅ 已在真机上测试 | LaunchAgent + `caffeinate` |
| **Linux**（Raspberry Pi OS、Ubuntu、Debian 等） | ⚠️ 实验性：**尚未在真机上测试** | systemd 用户服务 |
| **Windows 10/11** | ⚠️ 实验性：**尚未在真机上测试** | 任务计划程序 |

网络检测、数据库、面板和报告在所有平台上都相同。只有一小部分与系统相关：查找路由器、ping 参数、读取 Wi-Fi 信息以及后台启动。这部分有基于各系统示例输出的测试，但 Linux 和 Windows **尚未在真机上运行过**。
如果你在其中某个系统上试用，无论是否成功，都欢迎[提交 issue](https://github.com/Bruno-Furtado/down-again/issues) 并附上 `check` 的输出。

用网线连接的 **Raspberry Pi** 非常适合作为专用监控设备：便宜、安静、耗电极低。

## 工作原理

down-again 每 5 秒进行三项检测：

1. **路由器**：ping 默认网关。
2. **按 IP 访问互联网**：与 `1.1.1.1`、`8.8.8.8` 或 `208.67.222.222` 的 443 端口建立 TCP 连接，任一成功即可。
3. **按域名访问网站**：请求 `http://captive.apple.com/hotspot-detect.html`，依赖 DNS 正常工作。

**连续 2 次检测失败**才记为一次断线。断线从第一次失败的检测开始，到第一次成功的检测结束。可能原因的判断规则如下：

| 观察到的情况 | 原因 |
|---|---|
| 路由器有响应，互联网无响应 | **运营商** |
| 路由器无响应，或电脑断开了网络 | **本地网络 / Wi-Fi** |
| 互联网可通过 IP 访问，但域名无法解析 | **DNS** |
| 路由器从不响应 ping，无法区分本地与运营商 | **无法确定** |

电脑睡眠、关机或停电的时间会标记为**未监控**，不计入可用率，也绝不会被算作断线。

## 环境要求

- 一台保持开机的电脑，运行上述平台之一。
- Python 3.8 或更高版本：
  - **macOS**：`python3` 随 Command Line Tools 提供（`xcode-select --install`）。
  - **Linux**：大多数发行版已预装。
  - **Windows**：从 [python.org](https://www.python.org/downloads/) 安装，并勾选 **Add Python to PATH**。
- Linux 可选：`iw` 或 `nmcli`，用于读取 Wi-Fi 信息。
- 最好使用**网线**连接路由器，这样记录到的断线就能指向运营商，而不是 Wi-Fi 信号弱。

## 快速开始

**macOS / Linux**

```bash
git clone https://github.com/Bruno-Furtado/down-again.git ~/down-again
cd ~/down-again
python3 down_again.py check     # 单次诊断
python3 down_again.py           # 启动监控和面板（Ctrl+C 停止）
```

**Windows**（PowerShell）

```powershell
git clone https://github.com/Bruno-Furtado/down-again.git C:\down-again
cd C:\down-again
py down_again.py check
py down_again.py
```

在该电脑上打开 `http://localhost:8000`。在手机上使用 `http://<电脑名称>.local:8000`（macOS 和 Linux）、`http://<电脑名称>:8000` 或电脑的 IP 地址。监控启动时终端会显示这些地址。
如果系统询问是否允许 Python 接受传入连接，请允许（在 Windows 上选择**专用**网络）。

> macOS：不要把文件夹放在"桌面""文稿"或"下载"中。macOS 会阻止后台程序访问这些文件夹。

### 后台运行

```bash
python3 down_again.py install     # 立即启动，并在每次登录时自动启动
python3 down_again.py uninstall   # 移除自动启动（数据保留在 dados/）
```

在 Windows 上，用 `py` 代替 `python3`。

### 将电脑配置为服务器

**macOS**
- 系统偏好设置 → 节能：开启**防止电脑自动进入睡眠**和**断电后自动启动**。
- 用户与群组 → 登录选项：开启**自动登录**，这样停电恢复后监控会自动重新运行。开启 FileVault 时无法使用此选项。
- 想要更好记的网址，可以在 共享 → 电脑名称 中重命名 Mac（例如 `balboa` 对应 `http://balboa.local:8000`）。

**Linux / Raspberry Pi**（实验性）
- 运行 `sudo loginctl enable-linger $USER`，让服务在开机时无需登录即可启动。
- `.local` 地址需要 `avahi-daemon`。Raspberry Pi OS 已预装，其他系统请用包管理器安装。
- 如果启用了防火墙：`sudo ufw allow 8000/tcp`。
- 笔记本电脑请关闭挂起。

**Windows**（实验性）
- 设置 → 系统 → 电源：将**睡眠**设为**从不**。
- 将网络配置文件设为**专用**，以便手机访问面板。
- 后台任务在你登录 Windows 时启动。若要在停电后自动恢复，请开启自动登录，或在每次重启后登录。

## 手机通知（ntfy）

断网期间无法向外发送任何消息，因此 down-again 会把消息放入队列，等网络恢复后再发送。监控程序本身停止运行时（电脑关机或停电），它也会发出提醒。

1. 安装 **ntfy** 应用（iOS / Android）。
2. 订阅面板"Avisos no celular"区域中显示的主题。
3. 点击 **Enviar teste**（发送测试）。

## 配置

`dados/config.json` 会在首次运行时自动创建。修改后请重启 down-again。

| 键 | 默认值 | 说明 |
|---|---|---|
| `bind` | `0.0.0.0` | 监听地址。设为 `127.0.0.1` 时面板仅限本机访问 |
| `port` | `8000` | 面板端口 |
| `allowed_hosts` | `[]` | 面板允许使用的额外主机名。IP、`localhost`、`*.local` 和本机名称始终允许 |
| `interval` | `5` | 检测间隔（秒） |
| `timeout` | `2` | 每次检测的超时时间（秒） |
| `fail_threshold` | `2` | 连续失败多少次计为一次断线 |
| `keep_samples_days` | `120` | 原始检测数据的保留天数（断线记录永久保存） |
| `ntfy_server` | `https://ntfy.sh` | ntfy 服务器（可自行部署） |
| `ntfy_topic` | 随机 | ntfy 主题。设为 `""` 可关闭通知 |
| `notify_min_seconds` | `0` | 仅通知时长不低于该值的断线 |
| `notify_monitor_gap_minutes` | `5` | 监控停止运行达到该时长时发出提醒 |

## API

除特别说明外，所有接口均返回 JSON。日期范围参数为 `from`/`to`，格式 `YYYY-MM-DD`，跨度不超过 400 天。

| 接口 | 说明 |
|---|---|
| `GET /api/status` | 当前状态、最近一次检测和网络信息 |
| `GET /api/glance` | 最近 24 小时、7 天和 30 天的断线次数 |
| `GET /api/summary?from=&to=` | 指定时段的完整统计 |
| `GET /api/timeseries?hours=` | 用于图表的延迟和失败聚合数据 |
| `GET /api/outages.csv?from=&to=` | CSV 格式的断线列表（以 `;` 分隔，适配 Excel） |
| `GET /api/config` | 面板上显示的公开配置 |
| `POST /api/test-notify` | 发送测试通知（需要 `X-Down-Again: 1` 请求头） |

## 安全

down-again 专为**可信的家庭网络**设计，没有登录功能。

- **不要把端口暴露到互联网**（不要做端口转发）。任何能访问它的人都能看到断线历史和 ntfy 主题。
- `Host` 不是 IP、`localhost`、`*.local`、本机名称，也不在 `allowed_hosts` 中的请求会被拒绝，以防止局域网设备上打开的网站发起 DNS 重绑定攻击。
- 测试通知接口要求自定义请求头，其他网站无法触发，并且有频率限制。
- 响应带有严格的 Content-Security-Policy（只允许应用自身的脚本）、`nosniff`，并禁止被嵌入框架。
- 只提供固定列表中的静态文件，从不根据 URL 拼接文件路径。
- `dados/` 目录以 `0700` 权限创建，`config.json` 以 `0600` 权限创建。Windows 上这些权限不起作用，请将文件夹放在你的用户目录中。
- **ntfy 主题相当于密码**：知道它的人可以读取和发送通知。如需更高隐私，请自行部署 ntfy。

如需报告安全漏洞，请提交[私密安全公告](https://github.com/Bruno-Furtado/down-again/security/advisories/new)，不要发布公开 issue。

## 项目结构

```
down-again/
├── down_again.py      # 监控、HTTP 服务器、统计和命令行（仅用标准库）
├── static/
│   ├── index.html     # 面板
│   ├── app.js         # 面板逻辑
│   ├── relatorio.html # 可打印的运营商报告
│   ├── report.js      # 报告逻辑
│   ├── common.js      # 共享的格式化、时间线和图表
│   └── style.css      # 样式（明暗主题，移动端优先）
├── tests/             # 各系统解析器的测试（路由、ping、Wi-Fi）
├── tools/
│   ├── demo.py        # 带 7 天模拟数据的演示面板
│   ├── capture.mjs    # 重新生成 docs/ 中的图片
│   └── cover.html     # 封面模板
├── docs/              # README 图片
├── AGENTS.md          # AI 编程助手指南（Codex、Claude Code 等）
└── dados/             # 运行时创建：config.json、down-again.db、down-again.log（不纳入 git）
```

## 开发

```bash
python3 -m unittest discover -s tests   # 解析器测试（macOS、Linux 和 Windows 的输出）
python3 tools/demo.py                   # http://localhost:8766：模拟一周数据、虚拟 Wi-Fi、关闭通知
node tools/capture.mjs                  # 重新生成 docs/ 图片（需要 Chrome 和 ffmpeg，且演示服务正在运行）
```

演示服务写入临时目录（`DOWNAGAIN_DATA`），绝不会写入 `dados/`。
项目约束（Python 3.8、仅标准库、离线可用、严格 CSP）和验证步骤请参阅 [AGENTS.md](AGENTS.md)。
欢迎提交 Pull Request，尤其欢迎能在 Linux 和 Windows 上测试的贡献者。

## 许可证

[MIT](LICENSE)
