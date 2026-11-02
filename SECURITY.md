# Security Policy

This is a personal open-source project. There is no formal SLA, but security reports are welcome and taken seriously.

## Reporting a vulnerability

Please report vulnerabilities privately by opening a
[private security advisory](https://github.com/Bruno-Furtado/down-again/security/advisories/new),
or by email to **brunotfurtado@gmail.com**. Include steps to reproduce and the affected files when possible.
Please don't open a public issue for security matters.

## Scope

down-again runs a small HTTP server meant for a **trusted home network**. It has no login, so exposing its port to the internet is out of scope.
Things that are in scope include:

- reading data or triggering actions from another website (DNS rebinding, CSRF);
- script injection in the dashboard or the report (for example through a Wi-Fi network name);
- reading files outside `static/`;
- command injection in the platform layer (`route`, `ping`, `iw`, `nmcli`, `netsh`, `schtasks`, `systemctl`, `launchctl`).

The repository stores no credentials. The ntfy topic is generated locally in `dados/config.json`, which is git-ignored.
