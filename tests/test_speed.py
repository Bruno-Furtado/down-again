# -*- coding: utf-8 -*-
"""
Testes do teste de velocidade: leitura da saída do curl, ping/jitter, validação do plano
enviado pelo painel e estatísticas do período (sem rede; banco temporário).

    python3 -m unittest discover -s tests
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import down_again as da  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_curl_rate(self):
        self.assertEqual(da.parse_curl_rate("90000000 1.234567"), (90000000, 1.234567))
        self.assertEqual(da.parse_curl_rate("1234 0,5"), (1234, 0.5))          # vírgula decimal
        self.assertEqual(da.parse_curl_rate(""), (0, 0.0))
        self.assertEqual(da.parse_curl_rate("lixo"), (0, 0.0))

    def test_ping_stats(self):
        self.assertEqual(da.ping_stats([]), (None, None))
        self.assertEqual(da.ping_stats([10.0]), (10.0, 0.0))
        median, jitter = da.ping_stats([10.0, 12.0, 11.0, 30.0])
        self.assertEqual(median, 12.0)
        self.assertAlmostEqual(jitter, (2 + 1 + 19) / 3)

    def test_parse_settings(self):
        self.assertEqual(da.parse_settings(b'{"plan_down_mbps": 600, "plan_up_mbps": "300.55"}'),
                         {"plan_down_mbps": 600.0, "plan_up_mbps": 300.6})
        self.assertEqual(da.parse_settings(b'{"speedtest_minutes": 240, "weekly_summary_hour": -1, "language": "pt"}'),
                         {"speedtest_minutes": 240, "weekly_summary_hour": -1, "language": "pt"})
        bad = (b'{"plan_down_mbps": -1}', b'{"plan_down_mbps": 1e9}', b'{"plan_down_mbps": "abc"}', b"not json",
               b'{"speedtest_minutes": 7}', b'{"weekly_summary_hour": 24}', b'{"weekly_summary_hour": 9.5}',
               b'{"notify_min_seconds": true}', b'{"language": "xx"}', b'{"ntfy_topic": "x"}', b'{}', b'[1]',
               b'{"plan_down_mbps": NaN}')
        for body in bad:
            with self.assertRaises((ValueError, TypeError), msg=body):
                da.parse_settings(body)


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = da.DB_PATH
        da.DB_PATH = os.path.join(self.tmp, "test.db")
        db = sqlite3.connect(da.DB_PATH)
        db.executescript(da.SCHEMA)
        rows = [(100, 600, 300, 9, 1, None), (200, 200, 150, 10, 2, None),   # 200 < 40% de 600
                (300, 500, 280, 8, 1, None), (400, None, None, None, None, "timeout")]
        db.executemany("INSERT INTO speedtests(ts, down_mbps, up_mbps, ping_ms, jitter_ms, error, manual) VALUES(?,?,?,?,?,?,0)", rows)
        db.commit()
        db.close()

    def tearDown(self):
        da.DB_PATH = self.old

    def test_stats_with_plan(self):
        s = da.speed_stats(0, 1000, {"plan_down_mbps": 600, "plan_up_mbps": 300, "speedtest_minutes": 30, "speedtest_seconds": 5})
        self.assertEqual((s["count"], s["failed"]), (3, 1))
        self.assertAlmostEqual(s["down"]["avg"], (600 + 200 + 500) / 3)
        self.assertEqual((s["down"]["min"], s["down"]["max"]), (200, 600))
        self.assertEqual(s["below40"], 1)
        self.assertEqual(s["plan"], {"down": 600.0, "up": 300.0})

    def test_stats_without_plan_or_tests(self):
        s = da.speed_stats(0, 1000, {})
        self.assertEqual(s["below40"], 0)
        empty = da.speed_stats(5000, 6000, {})
        self.assertEqual((empty["count"], empty["down"]), (0, None))


if __name__ == "__main__":
    unittest.main()
