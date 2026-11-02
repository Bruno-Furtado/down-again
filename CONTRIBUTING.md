# Contributing

Thanks for helping! The rules that keep the project working everywhere live in [AGENTS.md](AGENTS.md). Quick reference:

## Workflow
1. Never commit directly to `main`. Create a branch named `<type>/<kebab-description>`, for example `fix/windows-ping-timeout`.
2. Open one PR per change. PRs are squash merged, and the PR title follows Conventional Commits.
3. Fill in the PR body: **What / Why / Notes**.

## Commits
Conventional Commits: `<type>(<scope>): <description>`, lowercase, imperative, no trailing period.
- types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`, `style`, `ci`
- scopes: `monitor`, `platform`, `dashboard`, `report`, `i18n`, `tools`, `docs`

## Before committing
```bash
python3 -m unittest discover -s tests
python3 -c "import ast; ast.parse(open('down_again.py').read(), feature_version=(3, 8))"
python3 tools/demo.py   # then check http://localhost:8766 on desktop and mobile widths
```

## Ground rules
- **Python 3.8 and standard library only.** No pip dependencies and no build step.
- **The dashboard must work offline.** No CDNs or web fonts, and no inline scripts (the CSP blocks them).
- **Every visible text is translated.** Add each new string in English, Portuguese and Chinese: `static/i18n.js` for the dashboard, `TEXTS` in `down_again.py` for the server. `tests/test_i18n.py` fails if a language is missing.
- **Linux and Windows are experimental.** If you test on a real machine, say so in the PR and add any new command output you saw to `tests/test_parsers.py`.
- Keep it simple. Match the style of the surrounding code.
