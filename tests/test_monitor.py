# -*- coding: utf-8 -*-
"""
Testes do monitor com relógio e testes de conexão simulados (sem rede; banco temporário):
quedas, avisos, instabilidade, troca de IP público e resumo diário.

    python3 -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import down_again as da  # noqa: E402

GOOD, LOST = 20.0, None


class MonitorBase(unittest.TestCase):
    def setUp(self):
        self.saved = (da.DATA, da.CONFIG_PATH, da.DB_PATH, da.probe, da.network_info, da.log, da.time)
        da.DATA = tempfile.mkdtemp()
        da.CONFIG_PATH = os.path.join(da.DATA, "config.json")
        da.DB_PATH = os.path.join(da.DATA, "test.db")
        da.network_info = lambda: da.blank_net()
        da.log = lambda msg: None
        # relógio falso: cada teste avança 5 s, como o intervalo real
        self.clock = [datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() - 86400 + 3600]
        fake = types.SimpleNamespace(**{k: getattr(time, k) for k in dir(time) if not k.startswith("_")})
        fake.time = lambda: self.clock[0]
        da.time = fake
        self.cfg = da.load_config()
        self.notifier = da.Notifier(self.cfg)
        self.monitor = da.Monitor(self.cfg, self.notifier)

    def tearDown(self):
        da.DATA, da.CONFIG_PATH, da.DB_PATH, da.probe, da.network_info, da.log, da.time = self.saved

    def feed(self, values, gw_ms=1.0):
        for v in values:
            da.probe = lambda t, v=v: {"gw": "192.168.0.1", "gw_ms": gw_ms, "net_ms": v, "http_ok": v is not None}
            self.monitor.step()
            self.clock[0] += 5

    def rows(self, sql):
        db = da.connect()
        try:
            return db.execute(sql).fetchall()
        finally:
            db.close()


class OutageTests(MonitorBase):
    def test_outage_queues_alert_without_locking(self):
        # Regressão: o aviso de "voltou" usava outra conexão e travava no lock do monitor.
        t0 = time.time()
        self.feed([GOOD] * 3 + [LOST] * 3 + [GOOD])
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(self.rows("SELECT cause, end_ts IS NOT NULL FROM outages"), [("isp", 1)])
        self.assertEqual([r[0] for r in self.rows("SELECT title FROM notifications")], [da.tr("notify.back.title")])

    def test_outage_calls_back_hook(self):
        calls = []
        self.monitor.on_back = lambda: calls.append(1)
        self.feed([LOST] * 3 + [GOOD])
        self.assertEqual(calls, [1])


class InstabilityTests(MonitorBase):
    def test_scattered_failures_are_instability_not_outage(self):
        self.feed([GOOD] * 30)
        self.feed([GOOD, LOST, GOOD, LOST, GOOD, GOOD, LOST, GOOD, LOST, GOOD])   # nunca 2 seguidas
        self.assertIsNotNone(self.monitor.get_status()["unstable"])
        self.feed([GOOD] * 14)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM outages"), [(0,)])
        (kind, start, end, data), = self.rows("SELECT kind, start_ts, end_ts, data FROM events")
        self.assertEqual(kind, "unstable")
        self.assertEqual(json.loads(data)["loss"], 4)
        self.assertGreater(end, start)
        self.assertIsNone(self.monitor.get_status()["unstable"])

    def test_high_latency_is_instability(self):
        self.feed([GOOD] * 40)
        self.feed([400.0] * 6)
        self.feed([GOOD] * 14)
        (data,), = self.rows("SELECT data FROM events WHERE kind='unstable'")
        d = json.loads(data)
        self.assertEqual((d["loss"], d["slow"], d["max_ms"]), (0, 6, 400.0))
        self.assertEqual(d["limit_ms"], 150)

    def test_close_episodes_are_merged(self):
        self.feed([GOOD] * 30)
        self.feed([400.0] * 5 + [GOOD] * 13 + [400.0] * 5 + [GOOD] * 14)
        self.assertEqual(len(self.rows("SELECT id FROM events WHERE kind='unstable'")), 1)

    def test_failures_leading_to_outage_are_not_instability(self):
        self.feed([GOOD] * 30 + [LOST] * 6 + [GOOD] * 14)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM outages"), [(1,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM events"), [(0,)])

    def test_summary_counts_instability(self):
        self.feed([GOOD] * 30 + [400.0] * 6 + [GOOD] * 14)
        s = da.summarize(self.clock[0] - 86400, self.clock[0] + 1)
        self.assertEqual(s["unstable"]["count"], 1)
        self.assertGreater(s["unstable"]["dur_s"], 0)
        self.assertTrue(any(d["uns"] for d in s["days"]))


class GlanceTests(MonitorBase):
    def test_last_24h_strip(self):
        self.feed([GOOD] * 30 + [LOST] * 6 + [GOOD] * 30 + [400.0] * 6 + [GOOD] * 14)
        real = da.time.time
        da.time.time = lambda: self.clock[0]
        g = da.glance()
        da.time.time = real
        self.assertEqual((g["h24"]["count"], g["h24"]["unstable"]), (1, 1))
        self.assertEqual(len(g["out"]), 1)
        self.assertEqual(g["out"][0][2], "isp")
        self.assertEqual(len(g["uns"]), 1)
        self.assertTrue(g["mon"])
        self.assertTrue(all(g["from"] <= a < b <= g["now"] for a, b, *_ in g["mon"] + g["out"] + g["uns"]))


class PublicIpTests(MonitorBase):
    def test_parse_trace(self):
        text = "fl=12\nh=1.1.1.1\nip=203.0.113.7\nts=1\nloc=BR\n"
        self.assertEqual(da.parse_trace(text), "203.0.113.7")
        self.assertIsNone(da.parse_trace("ip=<script>"))
        self.assertIsNone(da.parse_trace(""))

    def check(self, pub, ip):
        db = da.connect()
        try:
            pub.check(db, ip, self.clock[0])
        finally:
            db.close()

    def test_change_after_local_outage_means_router_restart(self):
        pub = da.PublicIP(self.monitor)
        self.feed([GOOD] * 3)
        self.check(pub, "203.0.113.7")
        self.feed([LOST] * 20 + [GOOD] * 2, gw_ms=None)    # roteador sumiu (já tinha respondido antes)
        self.check(pub, "203.0.113.99")
        self.assertEqual(self.rows("SELECT cause, hint FROM outages"), [("local", "router_restart")])
        (data,), = self.rows("SELECT data FROM events WHERE kind='ip_change'")
        self.assertEqual(json.loads(data)["hint"], "router_restart")
        self.assertEqual(pub.status()["ip"], "203.0.113.99")

    def test_change_without_outage_is_silent_reconnect(self):
        pub = da.PublicIP(self.monitor)
        self.check(pub, "203.0.113.7")
        self.feed([GOOD] * 60)
        self.check(pub, "203.0.113.8")
        (data,), = self.rows("SELECT data FROM events WHERE kind='ip_change'")
        self.assertTrue(json.loads(data)["silent"])
        self.check(pub, "203.0.113.8")                      # mesmo IP: nada novo
        self.assertEqual(len(self.rows("SELECT id FROM events")), 1)


class WeeklySummaryTests(MonitorBase):
    def next_sunday_after(self, ts, hour=20):
        d = datetime.fromtimestamp(ts).replace(hour=hour, minute=0, second=0, microsecond=0)
        while d.weekday() != 6 or d.timestamp() <= ts:
            d += timedelta(days=1)
        return d

    def at(self, now):
        """Troca o 'agora' do monitor (datetime.now) dentro do bloco."""
        real = da.datetime
        da.datetime = types.SimpleNamespace(now=lambda: now, fromtimestamp=real.fromtimestamp)
        return real

    def test_last_weekly_due(self):
        sun = datetime(2026, 11, 8, 20, 0)                                   # domingo
        self.assertEqual(da.last_weekly_due(datetime(2026, 11, 8, 20, 0), 20), sun)
        self.assertEqual(da.last_weekly_due(datetime(2026, 11, 8, 19, 59), 20), sun - timedelta(days=7))
        self.assertEqual(da.last_weekly_due(datetime(2026, 11, 11, 9, 0), 20), sun)   # quarta

    def test_summary_of_the_week(self):
        self.feed([GOOD] * 4400 + [LOST] * 12 + [GOOD] * 20)     # ~6h monitoradas, 1 queda
        end = self.next_sunday_after(self.clock[0])
        title, body = da.weekly_summary(end, self.cfg, "en")
        self.assertTrue(title.startswith("This week: 1 outage"))
        self.assertIn("ISP's fault: 1", body)
        title_pt, _ = da.weekly_summary(end, self.cfg, "pt")
        self.assertTrue(title_pt.startswith("Semana: 1 queda"))
        self.assertIsNone(da.weekly_summary(end - timedelta(days=14), self.cfg, "en"))   # nada monitorado

    def test_sent_once_per_week_and_skips_stale(self):
        self.feed([GOOD] * 4400)
        self.cfg["weekly_summary_hour"] = 20
        due = self.next_sunday_after(self.clock[0])
        real = self.at(due + timedelta(minutes=1))
        try:
            db = da.connect()
            self.notifier.weekly(db)
            self.notifier.weekly(db)
            da.datetime = types.SimpleNamespace(now=lambda: due + timedelta(days=9), fromtimestamp=real.fromtimestamp)
            self.notifier.weekly(db)          # domingo seguinte passou há mais de 24h: não manda atrasado
            db.close()
        finally:
            da.datetime = real
        self.assertEqual(len(self.rows("SELECT title FROM notifications")), 1)

    def test_old_daily_setting_migrates(self):
        for old, expected in ((-1, -1), (9, 20)):
            cfg = dict(self.cfg)
            cfg.pop("weekly_summary_hour", None)
            cfg["daily_summary_hour"] = old
            with open(da.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            loaded = da.load_config()
            self.assertEqual(loaded["weekly_summary_hour"], expected)
            with open(da.CONFIG_PATH, encoding="utf-8") as f:
                self.assertNotIn("daily_summary_hour", json.load(f))

    def test_fmt_pct(self):
        self.assertEqual(da.fmt_pct(0.99876, "pt"), "99,88%")
        self.assertEqual(da.fmt_pct(0.99876, "en"), "99.88%")
        self.assertEqual(da.fmt_pct(1.0, "en"), "100%")
        self.assertEqual(da.fmt_pct(0.874, "en", 0), "87%")


if __name__ == "__main__":
    unittest.main()
