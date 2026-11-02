# -*- coding: utf-8 -*-
"""
Confere os arquivos do painel: tudo que está na lista permitida existe, o manifesto do app
aponta para ícones servidos, e o HTML só referencia arquivos da lista.

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


class StaticFilesTests(unittest.TestCase):
    def test_every_allowed_file_exists(self):
        for route, (name, ctype) in da.STATIC_FILES.items():
            self.assertTrue(os.path.isfile(os.path.join(da.STATIC, name)), route)
            self.assertTrue(ctype, route)

    def test_manifest_icons_are_served(self):
        with open(os.path.join(da.STATIC, "manifest.webmanifest"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue(manifest["icons"])
        for icon in manifest["icons"]:
            self.assertIn(icon["src"], da.STATIC_FILES, icon["src"])

    def test_html_references_only_served_files(self):
        for page in ("index.html", "relatorio.html"):
            with open(os.path.join(da.STATIC, page), encoding="utf-8") as f:
                html = f.read()
            for ref in re.findall(r'(?:src|href)="(/[^"?#]*)', html):
                if not ref.startswith("/api/"):      # rotas da API não são arquivos estáticos
                    self.assertIn(ref, da.STATIC_FILES, "%s → %s" % (page, ref))


if __name__ == "__main__":
    unittest.main()
