# down-again

![down-again — internet down again? Now you have proof.](docs/cover.png)

Home internet outage monitor for an always-on computer. It checks your connection every few seconds,
shows a live dashboard you can open on your phone, and builds a printable report you can send
to your ISP when the service keeps dropping.

![macOS](https://img.shields.io/badge/macOS-11%2B%20tested-blue)
![Linux](https://img.shields.io/badge/Linux-experimental-orange)
![Windows](https://img.shields.io/badge/Windows-experimental-orange)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

**English** · [Português](README_pt-BR.md) · [中文](README_zh-CN.md)

> The dashboard and the report are in Brazilian Portuguese.

## Features

- **Live status**: "Online" or "Sem internet" (no internet), with a running timer and the likely cause.
- **Connection path**: computer → router → internet → websites, showing exactly where the connection stops.
- **Last 24 hours at a glance**: outage counts for 24 h, 7 days and 30 days at the top of the page.
- **Wi-Fi details**: network name, signal strength, channel and link speed (or "cable" on Ethernet).
- **Live latency chart** (1 h / 6 h / 24 h / 7 d) with failed checks highlighted.
- **Daily timeline**: one 24 h strip per day, with every outage colored by cause.
- **Insights**: which hour of the day fails most, who is to blame (ISP vs. local network vs. DNS), and a filterable list of outages.
- **ISP report**: a print/PDF-ready document with methodology, summary, per-day table and every outage, plus a CSV export for spreadsheets.
- **Phone notifications** via [ntfy](https://ntfy.sh). When the connection comes back you get "went down at X, back at Y".
- **Works offline**: no CDNs, no web fonts. The dashboard loads from your local network even while the internet is down.
- **Zero dependencies**: Python standard library and SQLite only.

## Screenshots

<p align="center">
  <img src="docs/demo.gif" width="320" alt="Phone dashboard: online, an ISP outage with a running timer, recovery, timeline and theme switch">
</p>

| Dark theme | Light theme |
|---|---|
| ![Dashboard, dark theme](docs/dashboard-dark.png) | ![Dashboard, light theme](docs/dashboard-light.png) |

**Timeline and insights**: hover an outage to see its cause, duration and Wi-Fi signal.

![Daily timeline, outages by hour and by cause](docs/insights.png)

**ISP report**: print it or save it as PDF.

![Printable availability report](docs/report.png)

> Screenshots use simulated data.

## Supported platforms

| Platform | Status | Runs in the background with |
|---|---|---|
| **macOS 11+** | ✅ Tested on real hardware | LaunchAgent + `caffeinate` |
| **Linux** (Raspberry Pi OS, Ubuntu, Debian…) | ⚠️ Experimental: **not tested on real hardware yet** | systemd user service |
| **Windows 10/11** | ⚠️ Experimental: **not tested on real hardware yet** | Task Scheduler |

The checks, database, dashboard and report are the same everywhere. Only a small layer differs per system: finding the router, ping flags, reading Wi-Fi details and starting in the background. That layer is covered by tests with sample outputs from each system, but Linux and Windows have **not been run on a real machine yet**.
If you try one of them, please [open an issue](https://github.com/Bruno-Furtado/down-again/issues) with the output of `check`, whether it worked or not.

A **Raspberry Pi** on Ethernet makes a great dedicated monitor: cheap, silent, and it uses very little power.

## How it works

Every 5 seconds down-again runs three checks:

1. **Router**: ping the default gateway.
2. **Internet by IP**: open a TCP connection to `1.1.1.1`, `8.8.8.8` or `208.67.222.222` on port 443. One success is enough.
3. **Website by name**: fetch `http://captive.apple.com/hotspot-detect.html`, which needs DNS to work.

An outage is recorded after **2 consecutive failed checks**. The outage starts at the first failed check and ends at the first successful one. The likely cause is:

| What was observed | Cause |
|---|---|
| Router answers, internet does not | **ISP** |
| Router does not answer, or the computer lost the network | **Local network / Wi-Fi** |
| Internet answers by IP, but names do not resolve | **DNS** |
| Router never answers ping, so local and ISP can't be told apart | **Unknown** |

When the computer sleeps, is turned off or loses power, that time is marked as **not monitored** and excluded from availability. It is never counted as an outage.

## Requirements

- A computer that stays on, running one of the platforms above.
- Python 3.8 or later:
  - **macOS**: `python3` comes with the Command Line Tools (`xcode-select --install`).
  - **Linux**: already installed on most distributions.
  - **Windows**: install from [python.org](https://www.python.org/downloads/) and check **Add Python to PATH**.
- Optional, on Linux: `iw` or `nmcli` for Wi-Fi details.
- Ideally an **Ethernet cable** to the router, so a recorded outage points at the ISP and not at weak Wi-Fi.

## Quick start

**macOS / Linux**

```bash
git clone https://github.com/Bruno-Furtado/down-again.git ~/down-again
cd ~/down-again
python3 down_again.py check     # one-off diagnosis
python3 down_again.py           # start monitor + dashboard (Ctrl+C to stop)
```

**Windows** (PowerShell)

```powershell
git clone https://github.com/Bruno-Furtado/down-again.git C:\down-again
cd C:\down-again
py down_again.py check
py down_again.py
```

Open `http://localhost:8000` on that computer. On your phone, use `http://<computer-name>.local:8000` (macOS and Linux) or `http://<computer-name>:8000`, or use the computer's IP address. The terminal prints these addresses when the monitor starts.
If the system asks whether Python may accept incoming connections, allow it (on Windows, for **private** networks).

> macOS: don't put the folder in Desktop, Documents or Downloads. macOS blocks background agents from those folders.

### Run in the background

```bash
python3 down_again.py install     # starts now and at every login
python3 down_again.py uninstall   # removes it (your data stays in dados/)
```

On Windows, use `py` instead of `python3`.

### Prepare the computer to act as a server

**macOS**
- System Preferences → Energy Saver: turn on **Prevent automatic sleeping** and **Start up automatically after a power failure**.
- Users & Groups → Login Options: turn on **automatic login**, so the agent starts again after a power cut. This option isn't available while FileVault is on.
- To get a nicer URL, rename the Mac in Sharing → Computer Name (for example `balboa` gives `http://balboa.local:8000`).

**Linux / Raspberry Pi** (experimental)
- Run `sudo loginctl enable-linger $USER` so the service starts at boot without anyone logging in.
- The `.local` address needs `avahi-daemon`. It is preinstalled on Raspberry Pi OS; elsewhere install it with your package manager.
- If you use a firewall: `sudo ufw allow 8000/tcp`.
- On laptops, disable suspend.

**Windows** (experimental)
- Settings → System → Power: set **Sleep** to **Never**.
- Set your network profile to **Private**, so the dashboard is reachable from your phone.
- The background task starts when you sign in. For it to survive power cuts, enable automatic sign-in or sign in after each restart.

## Phone notifications (ntfy)

You can't send anything out while the internet is down, so down-again queues the message and delivers it when the connection returns. It also warns you when the monitor itself was offline (computer off or power cut).

1. Install the **ntfy** app (iOS / Android).
2. Subscribe to the topic shown on the dashboard, in the "Avisos no celular" section.
3. Tap **Enviar teste** (send test).

## Configuration

`dados/config.json` is created on first run. Restart down-again after editing it.

| Key | Default | Description |
|---|---|---|
| `bind` | `0.0.0.0` | Address to listen on. Use `127.0.0.1` to keep the dashboard on this computer only |
| `port` | `8000` | Dashboard port |
| `allowed_hosts` | `[]` | Extra hostnames for the dashboard. IPs, `localhost`, `*.local` and the computer's own name are always allowed |
| `interval` | `5` | Seconds between checks |
| `timeout` | `2` | Seconds per check |
| `fail_threshold` | `2` | Consecutive failures needed to count as an outage |
| `keep_samples_days` | `120` | How long raw checks are kept (outages are kept forever) |
| `ntfy_server` | `https://ntfy.sh` | ntfy server (you can self-host) |
| `ntfy_topic` | random | ntfy topic. Set it to `""` to disable notifications |
| `notify_min_seconds` | `0` | Only notify about outages at least this long |
| `notify_monitor_gap_minutes` | `5` | Warn when the monitor was offline for at least this long |

## API

All endpoints return JSON unless noted. Date ranges use `from`/`to` as `YYYY-MM-DD`, up to 400 days.

| Endpoint | Description |
|---|---|
| `GET /api/status` | Current state, last check, network info |
| `GET /api/glance` | Outage counts for the last 24 h, 7 days and 30 days |
| `GET /api/summary?from=&to=` | Full statistics for a period |
| `GET /api/timeseries?hours=` | Latency and failures, aggregated for charts |
| `GET /api/outages.csv?from=&to=` | Outage list as CSV (`;`-separated, for Excel) |
| `GET /api/config` | Public settings shown on the dashboard |
| `POST /api/test-notify` | Sends a test notification (requires the `X-Down-Again: 1` header) |

## Security

down-again is meant for a **trusted home network**. It has no login.

- **Do not expose the port to the internet** (no port forwarding). Anyone who can reach it can see your outage history and your ntfy topic.
- Requests whose `Host` isn't an IP, `localhost`, `*.local`, the computer's own name or listed in `allowed_hosts` are rejected. This blocks DNS-rebinding attacks from websites opened on devices in your network.
- The test-notification endpoint requires a custom header, so other websites can't trigger it. It is also rate-limited.
- Responses carry a strict Content-Security-Policy (scripts only from the app itself), `nosniff`, and no framing.
- Only a fixed list of static files is served. Paths are never built from the URL.
- `dados/` is created with `0700` permissions and `config.json` with `0600`. On Windows these permissions have no effect, so keep the folder inside your user profile.
- **The ntfy topic works like a password**: anyone who knows it can read and send notifications. For more privacy, self-host ntfy.

To report a vulnerability, open a [private security advisory](https://github.com/Bruno-Furtado/down-again/security/advisories/new) instead of a public issue.

## Project structure

```
down-again/
├── down_again.py      # monitor, HTTP server, statistics and CLI (stdlib only)
├── static/
│   ├── index.html     # dashboard
│   ├── app.js         # dashboard logic
│   ├── relatorio.html # printable ISP report
│   ├── report.js      # report logic
│   ├── common.js      # shared formatting, timeline and charts
│   └── style.css      # styles (light/dark, mobile-first)
├── tests/             # tests for the per-system parsers (route, ping, Wi-Fi)
├── tools/
│   ├── demo.py        # demo dashboard with 7 days of simulated data
│   ├── capture.mjs    # regenerates the images in docs/
│   └── cover.html     # cover template
├── docs/              # README images
├── AGENTS.md          # guide for AI coding agents (Codex, Claude Code…)
└── dados/             # created at runtime: config.json, down-again.db, down-again.log (git-ignored)
```

## Development

```bash
python3 -m unittest discover -s tests   # parser tests (macOS, Linux and Windows outputs)
python3 tools/demo.py                   # http://localhost:8766: simulated week, fake Wi-Fi, notifications off
node tools/capture.mjs                  # regenerate docs/ images (needs Chrome + ffmpeg, demo running)
```

The demo writes to a temporary folder (`DOWNAGAIN_DATA`), never to `dados/`.
Read [AGENTS.md](AGENTS.md) for the constraints (Python 3.8, stdlib only, works offline, strict CSP) and the verification steps.
Pull requests are welcome, especially from people who can test on Linux and Windows.

## License

[MIT](LICENSE)
