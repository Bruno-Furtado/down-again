# -*- coding: utf-8 -*-
"""
Testes do monitor com testes de conexão simulados (sem rede; banco temporário).

    python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import down_again as da  # noqa: E402


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.saved = (da.DATA, da.CONFIG_PATH, da.DB_PATH, da.probe, da.network_info, da.log)
        da.DATA = tempfile.mkdtemp()
        da.CONFIG_PATH = os.path.join(da.DATA, "config.json")
        da.DB_PATH = os.path.join(da.DATA, "test.db")
        da.network_info = lambda: da.blank_net()
        da.log = lambda msg: None
        self.cfg = da.load_config()
        self.notifier = da.Notifier(self.cfg)
        self.monitor = da.Monitor(self.cfg, self.notifier)

    def tearDown(self):
        da.DATA, da.CONFIG_PATH, da.DB_PATH, da.probe, da.network_info, da.log = self.saved

    def feed(self, net_values):
        for v in net_values:
            da.probe = lambda t, v=v: {"gw": "192.168.0.1", "gw_ms": 1.0, "net_ms": v, "http_ok": v is not None}
            self.monitor.step()

    def test_outage_queues_alert_without_locking(self):
        # Regressão: o aviso de "voltou" usava outra conexão e travava no lock do monitor.
        t0 = time.time()
        self.feed([None, None, None, 10.0])
        self.assertLess(time.time() - t0, 5)
        db = da.connect()
        self.assertEqual(db.execute("SELECT cause, end_ts IS NOT NULL FROM outages").fetchall(), [("isp", 1)])
        titles = [r[0] for r in db.execute("SELECT title FROM notifications")]
        self.assertEqual(titles, [da.tr("notify.back.title")])


if __name__ == "__main__":
    unittest.main()
