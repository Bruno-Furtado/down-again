# -*- coding: utf-8 -*-
"""
Confere as traduções: todos os idiomas com as mesmas chaves e os mesmos {marcadores},
e toda chave usada no HTML/JS existindo no dicionário.

    python3 -m unittest discover -s tests
"""
import json
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import down_again as da  # noqa: E402

STATIC = os.path.join(ROOT, "static")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# chaves montadas em tempo de execução ("note." + estado, "cause." + código...)
DYNAMIC_PREFIXES = ("note.", "cause.")


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


def ui_dict():
    src = read("i18n.js")
    body = src[src.index("const I18N = ") + len("const I18N = "):src.rindex("};") + 1]
    return json.loads(body)


class ParityMixin:
    def check_parity(self, table):
        base = table["en"]
        for lang, texts in table.items():
            self.assertEqual(set(texts), set(base), "chaves diferentes em %s" % lang)
            for key, value in texts.items():
                self.assertEqual(set(PLACEHOLDER.findall(value)), set(PLACEHOLDER.findall(base[key])),
                                 "marcadores diferentes em %s/%s" % (lang, key))
                self.assertTrue(value.strip(), "texto vazio em %s/%s" % (lang, key))


class UiTranslationTests(unittest.TestCase, ParityMixin):
    def test_same_keys_and_placeholders(self):
        table = ui_dict()
        self.assertEqual(set(table), {"en", "pt", "zh"})
        self.check_parity(table)

    def test_every_used_key_exists(self):
        keys = set(ui_dict()["en"])
        used = set()
        for name in ("index.html", "relatorio.html"):
            used |= set(re.findall(r'data-i18n(?:-html|-title)?="([^"]+)"', read(name)))
        for name in ("app.js", "report.js", "common.js"):
            used |= set(re.findall(r'\bt\("([a-zA-Z0-9_.]+)"', read(name)))
        # t("note." + estado) aparece como "note." — esses prefixos são conferidos em test_dynamic_keys_exist
        missing = sorted(k for k in used if k not in keys and k not in DYNAMIC_PREFIXES)
        self.assertEqual(missing, [])

    def test_dynamic_keys_exist(self):
        keys = set(ui_dict()["en"])
        for state in ("isp", "local", "dns", "unknown"):
            self.assertIn("note." + state, keys)
            self.assertIn("cause." + state, keys)
            self.assertIn("cause." + state + ".desc", keys)
        for i in range(1, 6):
            self.assertIn("r.m%d" % i, keys)


class ServerTranslationTests(unittest.TestCase, ParityMixin):
    def test_same_keys_and_placeholders(self):
        self.assertEqual(set(da.TEXTS), {"en", "pt", "zh"})
        self.check_parity(da.TEXTS)

    def test_server_languages_match_ui(self):
        self.assertEqual(set(da.TEXTS), set(ui_dict()))

    def test_tr_and_fallback(self):
        self.assertEqual(da.tr("cause.isp", "pt"), "Provedor")
        self.assertEqual(da.tr("cause.isp", "zh"), "运营商")
        self.assertEqual(da.tr("cause.isp", "xx"), "ISP")
        self.assertEqual(da.cause_label("weird", "en"), "Unknown")
        self.assertEqual(da.fmt_dur(3725, "en"), "1h 02min")
        self.assertEqual(da.fmt_dur(3725, "zh"), "1小时 02分")

    def test_csv_per_language(self):
        s = {"outages": [{"start": 0, "end": 90, "dur": 90, "cause": "isp", "ended_by": "voltou",
                          "ongoing": False, "network": "Wi-Fi Casa;5G"}]}
        pt = da.outages_csv(s, "pt").lstrip("﻿").splitlines()
        en = da.outages_csv(s, "en").lstrip("﻿").splitlines()
        self.assertTrue(pt[0].startswith("Início;Fim;"))
        self.assertTrue(en[0].startswith("Start,End,"))
        self.assertIn('"Wi-Fi Casa;5G"', pt[1])   # separador no SSID vai entre aspas


if __name__ == "__main__":
    unittest.main()
