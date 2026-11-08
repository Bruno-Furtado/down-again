# AGENTS.md

Guide for AI coding agents (Codex, Claude Code, Cursor, Copilot…) and human contributors.
`CLAUDE.md` imports this file, so keep every shared rule here.

## What this is

down-again is a home internet outage monitor that runs on an always-on computer. One Python process does two jobs:

1. **Monitor thread** (`Monitor` in `down_again.py`): every `interval` seconds it pings the router, opens a TCP connection to public IPs and fetches a URL by name. It classifies the result (`ok`, `isp`, `local`, `dns`, `unknown`) and writes it to SQLite.
2. **HTTP server** (`Handler`): serves the dashboard (`static/`) and a small JSON API on the LAN.

When the connection comes back, notifications go out through ntfy (`Notifier`). It uses `curl` on macOS and Linux and `urllib` on Windows. The queue lives in the `notifications` table; code that already holds an open transaction (the monitor) must pass its own connection to `Notifier.queue(..., db=)`, or the second connection waits for the lock and the alert is lost. The notifier also sends a weekly summary (`weekly_summary`, last 7 days) on Sundays at `weekly_summary_hour`, once per week (`meta.weekly_sent`); if the monitor was off at that hour it goes out when it comes back, up to 24 h late. Old configs with `daily_summary_hour` are migrated in `load_config`.

Outside outages, `Stability` keeps a sliding window of the last 12 checks: 4 failed or slow ones (3× the usual median latency, at least 150 ms) open an **unstable** episode, stored in `events` (`kind='unstable'`). `PublicIP` reads the public IP from `https://1.1.1.1/cdn-cgi/trace` every 10 minutes and after each outage; a change becomes an `ip_change` event and, if an outage ended since the last read, sets that outage's `hint` (`router_restart` after a local outage, `reconnect` after an ISP one).

A third thread (`SpeedTester`) runs a speed test every `speedtest_minutes`, or on demand from `POST /api/speedtest`. It runs 6 parallel `curl` transfers to `speed.cloudflare.com`; curl, not Python, so it reaches 500+ Mbps on old Macs. It sets `Monitor.paused` while testing, because a saturated link must not be recorded as an outage. Results go to the `speedtests` table and the plan (`plan_down_mbps` / `plan_up_mbps`) can be saved from the dashboard (`POST /api/settings`, which only accepts the keys validated in `parse_settings`). The demo replaces `run_speedtest` with fake numbers so it never uses the network.

## Platforms

| Platform | Status |
|---|---|
| macOS 11+ | Tested on real hardware. The reference platform. |
| Linux | **Experimental, never run on a real machine.** |
| Windows 10/11 | **Experimental, never run on a real machine.** |

Everything except a small platform layer is shared. The layer lives in the "rede: o que depende do sistema" section of `down_again.py`, plus the install/uninstall functions at the end:

| Concern | macOS | Linux | Windows |
|---|---|---|---|
| Default route | `route -n get default` → `parse_route_macos` | `/proc/net/route` → `parse_route_linux` | `route print -4 0.0.0.0` → `parse_route_windows` |
| Ping | `/sbin/ping -t` | `ping -W` | `ping -n 1 -w <ms>` |
| Ping output | `parse_ping_ms` (shared) | same | same (any UI language) |
| Wi-Fi | `airport`, `networksetup`, `ipconfig` | `iw dev X link` → `parse_iw_link`, `nmcli` → `parse_nmcli` | `netsh wlan show interfaces` → `parse_netsh_wlan` |
| Background | LaunchAgent + `caffeinate` | systemd user unit | Task Scheduler + `pythonw` |

Rules for this layer:
- Pick the platform with `IS_MAC`, `IS_LINUX` and `IS_WIN`. Never call `sys.platform` directly elsewhere.
- Keep command output parsing in **pure `parse_*` functions** (text in, data out). Add a test in `tests/test_parsers.py` with a realistic sample for every new parser or format variant.
- Windows output is localized. Parse by structure and numbers, not by English words. If you must match labels, accept the common translations.
- Missing tools must degrade gracefully. `run_cmd` returns `(-1, "")` instead of raising, and Wi-Fi details are optional.
- Don't describe Linux or Windows as tested until someone confirms it on real hardware. Keep the "experimental" wording in the READMEs and in the CLI warnings.

## Hard constraints

These are not style preferences. Breaking any of them breaks real installs.

- **Python 3.8 compatible.** The target is the Command Line Tools Python on macOS 11. Don't use `match`, `str.removeprefix`, `dict | dict`, `list[int]`-style generics, `zoneinfo`, or `functools.cache`. Check with:
  `python3 -c "import ast; ast.parse(open('down_again.py').read(), feature_version=(3, 8))"` (repeat for `tools/demo.py`).
- **Standard library only.** No pip packages, no `requirements.txt`, no build step.
- **The frontend must work with the internet down.** Vanilla JS and CSS only: no frameworks, no CDNs, no external fonts or images. The one font (Geist, OFL) lives in `static/fonts/app.woff2` and is served by the monitor itself.
- **CSP is strict** (`script-src 'self'`). No inline `<script>` blocks and no inline event handlers (`onclick=`). Put JS in `static/*.js`. Inline `style` attributes are allowed.
- **Static files are allow-listed.** A new file in `static/` must be added to `STATIC_FILES` in `down_again.py`, or it returns 404.
- **Never commit `dados/`.** It holds `config.json` (with the ntfy topic, which works like a password), the database and the log.
- **Every user-visible text exists in English, Portuguese and Chinese.** See "Translations" below.

## Translations

The UI, the report, phone alerts, the CSV and the terminal all come in `en`, `pt` and `zh`.

- **Dashboard and report:** strings live in `static/i18n.js` (a JSON-compatible `I18N` object). Static HTML uses `data-i18n`, `data-i18n-html` or `data-i18n-title`; JS uses `NM.t("key", {vars})`. The language comes from the viewer's browser or the flag buttons in the Settings tab (the report page has a flag menu), and changing it reloads the page. Dates and numbers use `Intl` with the matching locale.
- **Server** (alerts, CSV, terminal): strings live in `TEXTS` in `down_again.py`, and you use `tr("key", lang, **vars)`. The language comes from `language` in `config.json` (`auto` follows the system, see `detect_language`). The CSV and the test alert follow the viewer's language via `?lang=`.
- Add every new key to **all three languages** with the same `{placeholders}`. `tests/test_i18n.py` fails otherwise, and it also checks that every key used in HTML/JS exists.
- Stored values are language-neutral codes (`isp`, `local`, `dns`, `unknown`; `ended_by` uses the historical codes `voltou` and `monitor parado`). Translate them only when displaying.
- Flags are inline SVG (`NM.flag`), because flag emoji don't render on Windows.

## Security rules

- The dashboard stays open all day on old machines: no continuous animations (only the outage ring pulses), and update the DOM through `setText`/`setHTML`/`setClass` in `app.js`, which skip writes when nothing changed. Timers do nothing while the tab is hidden.
- Escape every value that comes from the system, the database or config before it reaches `innerHTML`. Use `NM.esc()` from `static/common.js`. Wi-Fi SSIDs are attacker-controlled strings.
- Tooltips: `data-tip` is rendered with `innerHTML`.
  - Written in an HTML template (`data-tip="${esc(html)}"`): escape the inner values and then the whole attribute.
  - Set via `el.dataset.tip = …`: escape only the inner values.
- Keep these protections in `Handler`:
  - the `Host` allow-list (`host_allowed` plus `own_names`, which blocks DNS rebinding);
  - the `X-Down-Again: 1` header and the cooldown on `POST /api/test-notify` (CSRF and abuse);
  - `SECURITY_HEADERS`;
  - the `MAX_RANGE_DAYS` limit.
- Subprocesses always take argument lists. Never use `shell=True`, and never build commands from request data.
- Values written into the LaunchAgent plist and the systemd unit must be escaped (`xml_escape`, `systemd_quote`).
- Don't log or return secrets beyond what the dashboard needs.

## Layout

```
down_again.py         monitor, notifier, statistics (summarize/glance/timeseries), HTTP handler, CLI
static/index.html     dashboard (4 tabs)         static/app.js     dashboard logic
static/relatorio.html printable ISP report       static/report.js  report logic
static/i18n.js        UI strings for en / pt / zh
static/qr.js          dependency-free QR encoder (byte mode, level M, versions 1-6) for the "open on your phone" card
static/manifest.webmanifest, icon*.png, icon.svg   home-screen app (regenerate icons with `node tools/capture.mjs icons`)
static/common.js      shared helpers (NM.*): i18n (t, flags, language menu), formatting, timeline, hour bars, tooltips
static/style.css      all styles; light/dark tokens on :root
tests/test_parsers.py parser tests with sample outputs from macOS, Linux and Windows
tests/test_i18n.py    translation parity (same keys and placeholders in every language)
tests/test_static.py  every allow-listed static file exists; manifest and HTML only point to served files
tests/test_speed.py   speed test parsing, ping/jitter, settings validation and period stats
tests/test_monitor.py monitor with a fake clock: outages, alert queue, instability, public IP, weekly summary
tools/demo.py         demo server with 7 days of simulated data (never touches dados/)
tools/capture.mjs     regenerates docs/ images via headless Chrome + ffmpeg
tools/cover.html      cover template (one per language via ?lang=)
docs/<lang>/          README images per language: cover.png, demo.gif, dashboard.png, report.png
.github/              CI (tests on Ubuntu, macOS and Windows + Python 3.8), issue/PR templates, dependabot
```

SQLite tables (in `SCHEMA`):
- `samples`: one row per check (`ts`, `state`, `gw_ms`, `net_ms`, `http_ok`, `rssi`), pruned after `keep_samples_days`.
- `outages`: one row per outage (`start_ts`, `end_ts`, `cause`, `ended_by`, `network`, `hint`). `end_ts` is NULL while the outage is ongoing. `hint` was added later; `load_config` adds the column to old databases.
- `gaps` and `sessions`: unmonitored time vs. monitored time.
- `notifications`: outgoing queue, kept until it is sent.
- `speedtests`: one row per speed test (`down_mbps`, `up_mbps`, `ping_ms`, `jitter_ms`, `error`, `manual`), kept forever.
- `events`: instability (`unstable`) and public IP changes (`ip_change`), with details as JSON in `data`.
- `meta`: small key/value state (last public IP, last weekly summary).

The project used to be called `netmon`. `load_config` renames an old `dados/netmon.db`, and the macOS install removes the old `com.netmon.monitor` LaunchAgent. Keep both until old installs are gone.

## Commands

```bash
python3 down_again.py check              # one diagnosis, prints and exits
python3 down_again.py                    # monitor + dashboard on :8000 (uses ./dados)
python3 -m unittest discover -s tests    # parser, translation and security tests
python3 tools/demo.py                    # demo dashboard on :8766 with simulated data (temp dir, alerts off)
node tools/capture.mjs                   # regenerate docs/<lang>/ images (demo must be running; LANGS=en to limit)
node tools/capture.mjs icons             # regenerate the app icons in static/
```

`DOWNAGAIN_DATA=/some/dir` moves the data folder. The demo uses this, so experiments never touch real data.

## How to verify a change

1. Run `python3 -m unittest discover -s tests` and the Python 3.8 syntax check above.
2. Start `python3 tools/demo.py`. Open `http://localhost:8766` and `http://localhost:8766/relatorio`, check that the browser console has no errors (including CSP violations), and check the layout at about 375 px wide and on desktop, in both themes.
3. If you touched the server, check the security behavior. Expected status codes:
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.com' localhost:8766/api/config        # 403
   curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8766/api/test-notify               # 403
   curl -s -o /dev/null -w '%{http_code}\n' --path-as-is localhost:8766/../down_again.py         # 404
   curl -s -o /dev/null -w '%{http_code}\n' 'localhost:8766/api/summary?from=2020-01-01&to=2026-01-01'  # 400
   ```
4. If you touched the platform layer, add or update samples in `tests/test_parsers.py`. If you have access to the real OS, also run `python3 down_again.py check` there and say so in the PR.
5. If you added or changed text, check that `tests/test_i18n.py` passes and look at the page in all three languages.
6. If the UI changed in a visible way, regenerate the images with `node tools/capture.mjs`.

CI (`.github/workflows/ci.yml`) runs the tests on Ubuntu, macOS and Windows, plus Python 3.8, and runs `check` on each OS.

## Conventions

- Code comments are in **Brazilian Portuguese**. Match the surrounding code.
- READMEs exist in three languages: `README.md` (English, primary), `README_pt-BR.md` and `README_zh-CN.md`, each with its own images in `docs/<lang>/`. When you change behavior, config keys, the API or platform support, update all three. Keep them short; details go inside `<details>` blocks.
- Workflow, commit and PR conventions are in [CONTRIBUTING.md](CONTRIBUTING.md): branch `<type>/<description>`, Conventional Commits, What / Why / Notes.
- New config keys go in `DEFAULTS` with a short comment, and in the configuration table of all three READMEs.
- Keep `down_again.py` a single file. Add helpers near the code that uses them, in the existing section order: utilities → platform layer → probes → notifier → monitor → statistics → web server → commands.
- Colors live as CSS variables on `:root`, with dark values under `prefers-color-scheme` and `[data-theme="dark"]`. Don't hard-code colors in JS. Use `var(--…)`.
