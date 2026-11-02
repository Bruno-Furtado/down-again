@AGENTS.md

## Claude Code notes

- To preview the dashboard, run `python3 tools/demo.py` in the background and open `http://localhost:8766` in the browser pane. Don't run `python3 down_again.py` for previews: it writes real data to `dados/`.
- To verify UI changes, read the browser console after each page load and check a mobile viewport (375 px), both themes and all three languages. Switch language with the flag menu or `localStorage.setItem("nm_lang", '"zh"')` and reload. Chinese strings are the usual layout breakers.
- New text needs all three languages (`static/i18n.js` and `TEXTS` in `down_again.py`). Run `python3 -m unittest discover -s tests` before finishing.
- The user writes in Brazilian Portuguese. Reply in Portuguese; code identifiers stay as they are.
