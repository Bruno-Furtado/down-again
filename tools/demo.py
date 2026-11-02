#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Painel de demonstração com 7 dias de dados simulados.

Gera o histórico numa pasta descartável (nunca em dados/), passando pelo mesmo Monitor
do down-again com relógio e testes falsos, e depois serve o painel com Wi-Fi fictício.
Avisos ficam desligados: nada é enviado para a internet.

Uso:
  python3 tools/demo.py                 # http://localhost:8766
  python3 tools/demo.py --port 9000 --data /tmp/outra-pasta
"""
import argparse
import os
import random
import shutil
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = 86400
STEP = 20   # segundos entre testes simulados (mais rápido que os 5s reais)


def simulate(app, seed=7):
    rnd = random.Random(seed)
    end = time.time()
    clock = [end - 7 * DAY]

    fake_time = types.SimpleNamespace(time=lambda: clock[0], strftime=time.strftime, sleep=lambda s: None)

    # roteiro: quedas aleatórias (mais à noite), uma sequência "piscando" ontem e o Mac desligado por 3h30
    events, t = [], clock[0] + 3600
    while t < end - 3 * 3600:
        t += rnd.expovariate(1 / (2.5 * 3600))
        evening = 19 <= time.localtime(t).tm_hour <= 23
        if rnd.random() < (0.55 if evening else 0.25):
            cause = rnd.choices(["isp", "local", "dns"], [0.72, 0.18, 0.10])[0]
            dur = rnd.choice([30, 45, 90, 240, 600, 1500, 3000]) * rnd.uniform(0.6, 1.4)
            events.append((t, t + dur, cause))
    flap = end - DAY - 3 * 3600
    events += [(flap + i * 160, flap + i * 160 + 70, "isp") for i in range(5)]
    asleep = (end - 4 * DAY + 2 * 3600, end - 4 * DAY + 5.5 * 3600)

    def state_at(ts):
        return next((c for a, b, c in events if a <= ts < b), "ok")

    def fake_probe(timeout):
        s = state_at(clock[0])
        lat = rnd.gauss(22, 5) + (rnd.random() < 0.03) * rnd.uniform(80, 400)
        return {"gw": None if s == "local" and rnd.random() < .5 else "192.168.0.1",
                "gw_ms": None if s == "local" else max(1, rnd.gauss(3, 1)),
                "net_ms": None if s in ("isp", "local") else max(5, lat), "http_ok": s == "ok"}

    def fake_net():
        weak = state_at(clock[0]) == "local"
        return dict(DEMO_WIFI, rssi=rnd.gauss(-78 if weak else -58, 3))

    real = (app.time, app.probe, app.network_info)
    app.time, app.probe, app.network_info = fake_time, fake_probe, fake_net
    try:
        cfg = dict(app.load_config(), interval=STEP)
        notifier = app.Notifier(cfg)
        notifier.queue = lambda *a: None
        monitor = app.Monitor(cfg, notifier)
        monitor.gap_limit = STEP + 30
        while clock[0] < end - 30:
            if not asleep[0] <= clock[0] < asleep[1]:
                monitor.step()
            clock[0] += STEP + rnd.uniform(-1, 1)
        monitor.stop()
        return monitor.db.execute("SELECT COUNT(*) FROM outages").fetchone()[0]
    finally:
        app.time, app.probe, app.network_info = real


def simulate_speedtests(app, seed=3):
    """Uma semana de testes a cada 4 horas: ~600/300 Mbps, mais lento à noite, alguns bem abaixo do plano."""
    rnd = random.Random(seed)
    db = app.connect()
    end, t = time.time(), time.time() - 7 * DAY
    while t < end - 600:
        evening = 19 <= time.localtime(t).tm_hour <= 23
        factor = rnd.uniform(0.15, 0.35) if rnd.random() < 0.1 else rnd.uniform(0.6, 0.85) if evening else rnd.uniform(0.85, 1.02)
        db.execute("INSERT INTO speedtests(ts, down_mbps, up_mbps, ping_ms, jitter_ms, error, manual) VALUES(?,?,?,?,?,?,0)",
                   (t, 600 * factor, 300 * min(1.0, factor + rnd.uniform(-0.05, 0.08)), rnd.gauss(9, 2), abs(rnd.gauss(1.5, 0.8)), None))
        t += 4 * 3600 + rnd.uniform(-20, 20)
    db.commit()
    db.close()


def fake_speedtest(cfg):
    """'Testar agora' na demonstração: números simulados, sem gastar a rede de quem está testando."""
    time.sleep(4)
    return {"ts": time.time(), "down": random.uniform(540, 620), "up": random.uniform(270, 310),
            "ping": random.uniform(7, 11), "jitter": random.uniform(0.5, 2.5), "error": None}


DEMO_WIFI = {"iface": "en0", "port": "Wi-Fi", "kind": "wifi", "ssid": "Casa_5G",
             "rssi": -54.0, "noise": -92.0, "channel": "149", "tx_rate": 866.0}


def main():
    ap = argparse.ArgumentParser(description="Painel de demonstração do down-again com dados simulados.")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--data", default=os.path.join(tempfile.gettempdir(), "down-again-demo"))
    args = ap.parse_args()

    data = os.path.abspath(args.data)
    if os.path.abspath(os.path.join(ROOT, "dados")) == data:
        sys.exit("Use uma pasta diferente de dados/ (os dados reais).")
    shutil.rmtree(data, ignore_errors=True)
    os.environ["DOWNAGAIN_DATA"] = data
    sys.path.insert(0, ROOT)
    import down_again as app

    print("simulando 7 dias em %s ..." % data, flush=True)
    print("%d quedas geradas" % simulate(app), flush=True)
    simulate_speedtests(app)

    # servidor real, com Wi-Fi e nome fictícios e avisos desligados
    app.network_info = lambda: dict(DEMO_WIFI)
    app.local_addresses = lambda: ("balboa.local", "192.168.0.56")
    app.Notifier.send = lambda self, *a: (False, "desligado na demonstração")
    app.run_speedtest = fake_speedtest
    cfg = app.load_config()
    cfg.update(port=args.port, ntfy_topic="down-again-demo", plan_down_mbps=600, plan_up_mbps=300)
    app.cmd_run(cfg)


if __name__ == "__main__":
    main()
