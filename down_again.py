#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
down-again — monitor de quedas de internet com painel web.

Feito para rodar num computador ligado 24h (de preferência no cabo do roteador):
testa a conexão a cada poucos segundos, grava tudo em SQLite e serve um painel
em http://<nome-da-maquina>.local:8000 com status ao vivo, linha do tempo e um
relatório imprimível para reclamar com o provedor.

Só biblioteca padrão. Compatível com Python 3.8 (macOS 11 Big Sur).
macOS é a plataforma testada; Linux (ex.: Raspberry Pi) e Windows são experimentais.

Uso:
  python3 down_again.py              roda monitor + painel (Ctrl+C para parar)
  python3 down_again.py check        faz um teste só e mostra o diagnóstico
  python3 down_again.py install      inicia sozinho (macOS: LaunchAgent; Linux: systemd; Windows: Agendador)
  python3 down_again.py uninstall    remove o início automático
"""
import argparse
import csv
import io
import ipaddress
import json
import os
import re
import secrets
import signal
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape as xml_escape

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.environ.get("DOWNAGAIN_DATA") or os.path.join(BASE, "dados"))   # DOWNAGAIN_DATA: usado pelo tools/demo.py
STATIC = os.path.join(BASE, "static")
CONFIG_PATH = os.path.join(DATA, "config.json")
DB_PATH = os.path.join(DATA, "down-again.db")
LOG_PATH = os.path.join(DATA, "down-again.log")
PLIST_LABEL = "com.downagain.monitor"
PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % PLIST_LABEL)
# nome antigo do projeto (netmon): migra o banco e remove o LaunchAgent antigo
OLD_DB_PATH = os.path.join(DATA, "netmon.db")
OLD_PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/com.netmon.monitor.plist")

IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
IS_WIN = sys.platform.startswith("win")
PLATFORM = "macOS" if IS_MAC else "Linux" if IS_LINUX else "Windows" if IS_WIN else sys.platform

DEFAULTS = {
    "bind": "0.0.0.0",             # "127.0.0.1" deixa o painel só nesta máquina
    "port": 8000,
    "allowed_hosts": [],           # nomes extras para o painel (IPs, localhost e *.local já valem)
    "interval": 5,                 # segundos entre testes
    "timeout": 2,                  # segundos por teste
    "fail_threshold": 2,           # falhas seguidas para confirmar uma queda
    "keep_samples_days": 120,      # amostras brutas (quedas ficam para sempre)
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",              # gerado na primeira execução; "" desativa
    "notify_min_seconds": 0,       # só avisa quedas com pelo menos N segundos
    "notify_monitor_gap_minutes": 5,
}

# IPs fixos (sem depender de DNS) e uma URL por nome (exercita DNS + HTTP).
TCP_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443), ("208.67.222.222", 443)]
HTTP_URL = "http://captive.apple.com/hotspot-detect.html"

CAUSES = {
    "isp": "Provedor",
    "local": "Rede local / Wi-Fi",
    "dns": "DNS / sites não abrem",
    "unknown": "Indeterminada",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples(ts REAL, state TEXT, gw_ms REAL, net_ms REAL, http_ok INTEGER, rssi REAL);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS outages(id INTEGER PRIMARY KEY, start_ts REAL, end_ts REAL, cause TEXT, ended_by TEXT,
                                   network TEXT);
CREATE INDEX IF NOT EXISTS outages_start ON outages(start_ts);
CREATE TABLE IF NOT EXISTS gaps(start_ts REAL, end_ts REAL);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, start_ts REAL, end_ts REAL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, ts REAL, title TEXT, body TEXT, tag TEXT, sent_ts REAL);
"""


# --------------------------------------------------------------------------
# utilidades

def log(msg):
    print("[%s] %s" % (time.strftime("%d/%m %H:%M:%S"), msg), flush=True)


def fmt_dur(sec):
    sec = int(round(sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return "%dd %02dh%02d" % (d, h, m)
    if h:
        return "%dh %02dmin" % (h, m)
    if m:
        return "%dmin %02ds" % (m, s)
    return "%ds" % s


def fmt_ts(ts, fmt="%d/%m/%Y %H:%M:%S"):
    return datetime.fromtimestamp(ts).strftime(fmt)


def midnight(ts):
    return datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.execute("PRAGMA journal_mode=WAL")
    return db


def load_config():
    # dados/ guarda o tópico do ntfy (que funciona como senha dos avisos): só o dono lê.
    os.makedirs(DATA, mode=0o700, exist_ok=True)
    os.chmod(DATA, 0o700)
    if os.path.exists(OLD_DB_PATH) and not os.path.exists(DB_PATH):
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(OLD_DB_PATH + ext):
                os.rename(OLD_DB_PATH + ext, DB_PATH + ext)
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        cfg["ntfy_topic"] = "down-again-" + secrets.token_hex(10)
        fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    db = connect()
    db.executescript(SCHEMA)
    db.close()
    return cfg


def run_cmd(args, timeout=5, env=None):
    kw = {"creationflags": 0x08000000} if IS_WIN else {}      # CREATE_NO_WINDOW: sem janela piscando no Windows
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, env=env, **kw)
        return r.returncode, r.stdout.decode("oem" if IS_WIN else "utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


def local_ip():
    """IP desta máquina na rede de casa (UDP 'connect' não envia nada, só escolhe a interface)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def local_addresses():
    """Nome na rede e IP, para mostrar o endereço do painel."""
    if IS_MAC:
        code, out = run_cmd(["scutil", "--get", "LocalHostName"])
        host = out.strip() + ".local" if code == 0 and out.strip() else None
        for iface in ("en0", "en1", "en2"):
            code, out = run_cmd(["ipconfig", "getifaddr", iface])
            if code == 0 and out.strip():
                return host, out.strip()
        return host, local_ip()
    name = socket.gethostname().split(".")[0]
    # Linux com avahi responde em nome.local; no Windows o nome simples é o que funciona na rede
    return (name + ".local" if IS_LINUX else name), local_ip()


# --------------------------------------------------------------------------
# rede: o que depende do sistema
#
# macOS é a plataforma testada. Linux e Windows são EXPERIMENTAIS: os leitores parse_* abaixo
# são funções puras, cobertas por tests/ com saídas de exemplo de cada sistema, mas ainda não
# rodaram em máquinas reais.

def is_ip(s):
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def parse_route_macos(text):
    """`route -n get default` -> (gateway, interface)."""
    gw = re.search(r"gateway:\s*(\S+)", text)
    iface = re.search(r"interface:\s*(\S+)", text)
    return (gw.group(1) if gw else None), (iface.group(1) if iface else None)


def parse_route_linux(text):
    """/proc/net/route -> (gateway, interface) da rota padrão de menor métrica.
    Colunas: Iface Destination Gateway Flags RefCnt Use Metric ...; IPs em hexa little-endian."""
    best = None
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) < 8 or f[1] != "00000000" or not int(f[3], 16) & 0x2:   # 0x2 = RTF_GATEWAY
            continue
        if best is None or int(f[6]) < best[0]:
            best = (int(f[6]), socket.inet_ntoa(struct.pack("<L", int(f[2], 16))), f[0])
    return (best[1], best[2]) if best else (None, None)


def parse_route_windows(text):
    """`route print -4 0.0.0.0` -> (gateway, IP da interface). Lê só números, então vale em qualquer idioma."""
    best = None
    for f in (line.split() for line in text.splitlines()):
        if len(f) >= 5 and f[0] == "0.0.0.0" and f[1] == "0.0.0.0" and is_ip(f[2]) and f[4].isdigit():
            if best is None or int(f[4]) < best[0]:
                best = (int(f[4]), f[2], f[3])
    return (best[1], best[2]) if best else (None, None)


def default_route():
    if IS_MAC:
        code, out = run_cmd(["/sbin/route", "-n", "get", "default"])
        return parse_route_macos(out) if code == 0 else (None, None)
    if IS_LINUX:
        try:
            with open("/proc/net/route") as f:
                return parse_route_linux(f.read())
        except OSError:
            return None, None
    if IS_WIN:
        code, out = run_cmd(["route", "print", "-4", "0.0.0.0"])
        return parse_route_windows(out) if code == 0 else (None, None)
    return None, None


def get_gateway():
    return default_route()[0]


def ping_cmd(host, timeout):
    t = int(max(1, timeout))
    if IS_WIN:
        return ["ping", "-n", "1", "-w", str(t * 1000), host]
    if IS_LINUX:
        return ["ping", "-n", "-c", "1", "-W", str(t), host]
    return ["/sbin/ping", "-n", "-c", "1", "-t", str(t), host]


def parse_ping_ms(text):
    """Tempo da resposta: 'time=3.1 ms' (macOS/Linux), 'tempo=3ms' ou 'time<1ms' (Windows, qualquer idioma).
    Exige 'ms' logo após o número: 'host inacessível' no Windows sai com código 0, mas sem tempo."""
    m = re.search(r"[=<]\s*([\d]+(?:[.,]\d+)?)\s*ms\b", text)
    return float(m.group(1).replace(",", ".")) if m else None


def ping(host, timeout):
    code, out = run_cmd(ping_cmd(host, timeout), timeout=timeout + 2)
    return parse_ping_ms(out)


def wifi_channel(mhz):
    """Frequência (MHz) -> canal Wi-Fi (2,4 / 5 / 6 GHz)."""
    try:
        mhz = int(float(mhz))
    except (TypeError, ValueError):
        return None
    if mhz == 2484:
        return "14"
    if 2412 <= mhz <= 2472:
        return str((mhz - 2407) // 5)
    if 5150 <= mhz <= 5895:
        return str((mhz - 5000) // 5)
    if 5955 <= mhz <= 7115:
        return str((mhz - 5950) // 5)
    return None


def percent_to_dbm(pct):
    """Linux (nmcli) e Windows (netsh) dão o sinal em %; aproximação usual para dBm."""
    return round(pct / 2.0 - 100, 1)


def parse_iw_link(text):
    """`iw dev <iface> link` (Linux)."""
    if "Not connected" in text:
        return {}
    ssid = re.search(r"^\s*SSID:\s*(.+)$", text, re.M)
    sig = re.search(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm", text)
    rate = re.search(r"tx bitrate:\s*([\d.]+)", text)
    freq = re.search(r"freq:\s*([\d.]+)", text)
    return {"ssid": ssid.group(1).strip() if ssid else None, "rssi": float(sig.group(1)) if sig else None,
            "tx_rate": float(rate.group(1)) if rate else None, "channel": wifi_channel(freq.group(1)) if freq else None}


def parse_nmcli(text):
    """`nmcli -t -f ACTIVE,SSID,SIGNAL,CHAN,RATE dev wifi` com LC_ALL=C (Linux). ':' no SSID vem como '\\:'."""
    for line in text.splitlines():
        f = [x.replace("\\:", ":") for x in re.split(r"(?<!\\):", line)]
        if len(f) >= 5 and f[0] == "yes":
            rate = re.match(r"[\d.]+", f[4])
            return {"ssid": f[1] or None, "rssi": percent_to_dbm(int(f[2])) if f[2].isdigit() else None,
                    "channel": f[3] or None, "tx_rate": float(rate.group(0)) if rate else None}
    return {}


def parse_netsh_wlan(text):
    """`netsh wlan show interfaces` (Windows, qualquer idioma). Sem linha SSID = Wi-Fi desconectado."""
    ssid = re.search(r"^\s*SSID\s*:\s*(.*\S)\s*$", text, re.M)    # não casa com BSSID
    if not ssid:
        return {}
    sig = re.search(r":\s*(\d{1,3})\s*%", text)
    chan = re.search(r"^\s*(?:Channel|Canal|Kanal|Canale)\s*:\s*(\d+)", text, re.M | re.I)
    rate = re.search(r"\(Mbps\)\s*:\s*([\d.,]+)", text)
    return {"ssid": ssid.group(1), "rssi": percent_to_dbm(int(sig.group(1))) if sig else None,
            "channel": chan.group(1) if chan else None,
            "tx_rate": float(rate.group(1).replace(",", ".")) if rate else None}


AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
_ports = {"ts": 0, "map": {}}


def hardware_ports():
    """macOS: mapa dispositivo -> nome da porta (en0 -> 'Wi-Fi', en1 -> 'Thunderbolt Ethernet'...)."""
    if time.time() - _ports["ts"] > 600:
        code, out = run_cmd(["/usr/sbin/networksetup", "-listallhardwareports"])
        ports = {}
        for port, dev in re.findall(r"Hardware Port:\s*(.+)\nDevice:\s*(\S+)", out):
            ports[dev] = port.strip()
        _ports.update(ts=time.time(), map=ports)
    return _ports["map"]


def blank_net(iface=None, port=None):
    return {"iface": iface, "port": port, "kind": None, "ssid": None,
            "rssi": None, "noise": None, "channel": None, "tx_rate": None}


def network_info_mac():
    gw, iface = default_route()
    ports = hardware_ports()
    wifi_dev = next((d for d, p in ports.items() if "Wi-Fi" in p or "AirPort" in p), None)
    info = blank_net(iface, ports.get(iface))
    if iface and iface != wifi_dev:
        info["kind"] = "cabo"
        return info
    if not wifi_dev:
        return info
    info["kind"] = "wifi"
    info["iface"] = iface or wifi_dev
    code, out = run_cmd([AIRPORT, "-I"])
    if code == 0:
        def field(key):
            mm = re.search(r"^\s*%s:\s*(.+)$" % key, out, re.M)
            return mm.group(1).strip() if mm else None

        def num(key):
            v = field(key)
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        info.update(ssid=field("SSID"), rssi=num("agrCtlRSSI"), noise=num("agrCtlNoise"),
                    channel=field("channel"), tx_rate=num("lastTxRate"))
    if not info["ssid"]:
        code, out = run_cmd(["/usr/sbin/networksetup", "-getairportnetwork", wifi_dev])
        mm = re.search(r"Network:\s*(.+)", out)
        info["ssid"] = mm.group(1).strip() if mm else None
    if not info["ssid"]:
        code, out = run_cmd(["/usr/sbin/ipconfig", "getsummary", wifi_dev])
        mm = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
        info["ssid"] = mm.group(1).strip() if mm and "redacted" not in mm.group(1) else None
    if not iface:
        info["rssi"] = None   # Wi-Fi sem rota: desconectado, o sinal antigo não vale
    return info


def network_info_linux():
    gw, iface = default_route()
    try:
        wireless = [d for d in os.listdir("/sys/class/net") if os.path.isdir("/sys/class/net/%s/wireless" % d)]
    except OSError:
        wireless = []
    info = blank_net(iface, iface)
    if iface and iface not in wireless:
        info["kind"] = "cabo"
        return info
    if not wireless:
        return info
    info.update(kind="wifi", iface=iface or wireless[0])
    if not iface:
        return info           # Wi-Fi sem rota: desconectado
    code, out = run_cmd(["iw", "dev", iface, "link"])
    data = parse_iw_link(out) if code == 0 else {}
    if not data.get("ssid"):
        code, out = run_cmd(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,CHAN,RATE", "dev", "wifi"],
                            env=dict(os.environ, LC_ALL="C"))
        data = parse_nmcli(out) if code == 0 else {}
    info.update({k: v for k, v in data.items() if v is not None})
    return info


def network_info_windows():
    gw, iface = default_route()
    code, out = run_cmd(["netsh", "wlan", "show", "interfaces"])
    data = parse_netsh_wlan(out) if code == 0 else {}
    info = blank_net(iface, "Wi-Fi" if data else "Ethernet")
    if data:
        info["kind"] = "wifi"
        info.update({k: v for k, v in data.items() if v is not None})
    elif gw:
        info["kind"] = "cabo"
    return info


def network_info():
    """Por onde a máquina está saindo: cabo ou Wi-Fi (nome da rede, sinal, canal, velocidade do link)."""
    if IS_MAC:
        return network_info_mac()
    if IS_LINUX:
        return network_info_linux()
    if IS_WIN:
        return network_info_windows()
    return blank_net()


def network_label(net):
    if not net or not net.get("kind"):
        return "sem rede"
    if net["kind"] == "cabo":
        return "Cabo (%s)" % (net.get("port") or net.get("iface"))
    return "Wi-Fi %s" % net["ssid"] if net.get("ssid") else "Wi-Fi"


# --------------------------------------------------------------------------
# testes de conexão (iguais em todos os sistemas)

def tcp_latency(timeout):
    for host, port in TCP_TARGETS:
        t = time.time()
        try:
            socket.create_connection((host, port), timeout).close()
            return (time.time() - t) * 1000
        except OSError:
            continue
    return None


def http_check(timeout):
    # Roda numa thread porque a resolução de DNS não respeita o timeout do socket.
    result = []

    def worker():
        try:
            req = Request(HTTP_URL, headers={"User-Agent": "down-again"})
            result.append(b"Success" in urlopen(req, timeout=timeout).read(512))
        except Exception:
            result.append(False)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout + 1)
    return bool(result and result[0])


def probe(timeout):
    gw = get_gateway()
    gw_ms = ping(gw, timeout) if gw else None
    net_ms = tcp_latency(timeout)
    http_ok = http_check(timeout) if net_ms is not None else False
    return {"gw": gw, "gw_ms": gw_ms, "net_ms": net_ms, "http_ok": http_ok}


def classify(p, gw_ping_seen):
    if p["net_ms"] is not None:
        return "ok" if p["http_ok"] else "dns"
    if not p["gw"]:
        return "local"          # sem rota padrão: cabo/Wi-Fi desconectado
    if p["gw_ms"] is not None:
        return "isp"            # roteador responde, internet não
    # Roteador não respondeu. Se ele já respondeu a ping antes, o problema é local;
    # se nunca respondeu, ele simplesmente ignora ping e não dá para saber.
    return "local" if gw_ping_seen else "unknown"


# --------------------------------------------------------------------------
# avisos no celular (ntfy) — enviados quando a internet volta

class Notifier:
    def __init__(self, cfg):
        self.cfg = cfg
        self.wake = threading.Event()

    @property
    def enabled(self):
        return bool(self.cfg.get("ntfy_topic"))

    def queue(self, title, body, tag):
        if not self.enabled:
            return
        db = connect()
        db.execute("INSERT INTO notifications(ts, title, body, tag) VALUES(?,?,?,?)",
                   (time.time(), title, body, tag))
        db.commit()
        db.close()
        self.wake.set()

    def send(self, title, body, tags):
        payload = json.dumps({"topic": self.cfg["ntfy_topic"], "title": title,
                              "message": body, "tags": tags}).encode("utf-8")
        url = self.cfg["ntfy_server"].rstrip("/") + "/"
        # macOS/Linux: curl do sistema usa os certificados do sistema (o ssl do Python 3.8 do macOS
        # pode não ter os atuais). Windows: urllib, que usa o repositório de certificados do Windows.
        curl = None if IS_WIN else ("/usr/bin/curl" if os.path.exists("/usr/bin/curl") else shutil.which("curl"))
        if not curl:
            try:
                req = Request(url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "down-again"})
                urlopen(req, timeout=15).read()
                return True, ""
            except Exception as e:
                return False, str(e)
        try:
            # -q primeiro: ignora ~/.curlrc (proxy, -k etc. não mudam o envio)
            r = subprocess.run([curl, "-q", "-sS", "-f", "-m", "15", "-H", "Content-Type: application/json",
                                "--data-binary", "@-", url],
                               input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            return False, str(e)
        return r.returncode == 0, r.stderr.decode("utf-8", "replace").strip()

    def run(self):
        db = connect()
        while True:
            if self.wake.wait(30):
                self.wake.clear()
                time.sleep(3)   # dá um tempo para a conexão recém-voltada estabilizar
            if not self.enabled:
                continue
            rows = db.execute("SELECT id, title, body, tag FROM notifications WHERE sent_ts IS NULL "
                              "ORDER BY id LIMIT 20").fetchall()
            if not rows:
                continue
            if len(rows) == 1:
                title, body, tags = rows[0][1], rows[0][2], [rows[0][3]]
            else:
                title = "%d avisos do monitor" % len(rows)
                body = "\n\n".join("%s\n%s" % (r[1], r[2]) for r in rows)
                tags = [rows[-1][3]]
            ok, err = self.send(title, body, tags)
            if ok:
                ids = [r[0] for r in rows]
                db.execute("UPDATE notifications SET sent_ts=? WHERE id IN (%s)" % ",".join("?" * len(ids)),
                           [time.time()] + ids)
                db.commit()
            else:
                log("aviso não enviado, tento de novo em 30s: %s" % err)


# --------------------------------------------------------------------------
# monitor

class Monitor:
    def __init__(self, cfg, notifier):
        self.cfg = cfg
        self.notifier = notifier
        self.gap_limit = cfg["interval"] + 30     # acima disso o computador dormiu/travou
        self.lock = threading.Lock()
        self.gw_ping_seen = False
        self.pending = []                         # falhas ainda não confirmadas como queda
        self.outage = None
        self.last_ts = None
        self.last_prune = 0
        self.net, self.net_ts = None, 0
        self.db = connect()

        now = time.time()
        last = self.db.execute("SELECT MAX(end_ts) FROM sessions").fetchone()[0]
        # Queda que ficou aberta porque o processo morreu no meio dela.
        self.db.execute("UPDATE outages SET end_ts = COALESCE((SELECT MAX(ts) FROM samples "
                        "WHERE ts >= outages.start_ts), start_ts), ended_by = 'monitor parado' "
                        "WHERE end_ts IS NULL")
        self.session_id = self.db.execute("INSERT INTO sessions(start_ts, end_ts) VALUES(?,?)",
                                          (now, now)).lastrowid
        self.db.commit()
        if last and now - last >= cfg["notify_monitor_gap_minutes"] * 60:
            self._notify_gap(last, now)
        # "sem quedas há X" continua contando da última queda registrada, mesmo após reiniciar
        last_out = self.db.execute("SELECT MAX(end_ts) FROM outages").fetchone()[0]
        self.status = {"state": "starting", "since": last_out or now, "since_start": not last_out, "started": now,
                       "last": None, "probe": None, "outage": None, "pending": 0}

    def get_status(self):
        with self.lock:
            return json.loads(json.dumps(self.status))

    def run(self):
        while True:
            t0 = time.time()
            try:
                self.step()
            except sqlite3.Error as e:
                log("erro no banco: %r" % e)
            time.sleep(max(0.5, self.cfg["interval"] - (time.time() - t0)))

    def step(self):
        ts = time.time()
        p = probe(self.cfg["timeout"])
        if p["gw_ms"] is not None:
            self.gw_ping_seen = True
        state = classify(p, self.gw_ping_seen)
        # Rede/sinal a cada 30s, e a cada teste quando algo falha (registra o sinal na hora da queda).
        if state != "ok" or ts - self.net_ts > 30:
            self.net, self.net_ts = network_info(), ts

        if self.last_ts is not None and ts - self.last_ts > self.gap_limit:
            self._gap(self.last_ts, ts)

        self.db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?)",
                        (ts, state, p["gw_ms"], p["net_ms"], int(p["http_ok"]), self.net.get("rssi")))
        self.db.execute("UPDATE sessions SET end_ts=? WHERE id=?", (ts, self.session_id))

        if state == "ok":
            self.pending = []
            if self.outage:
                self._close(ts, "voltou")
        elif self.outage:
            self.outage["counts"][state] = self.outage["counts"].get(state, 0) + 1
        else:
            self.pending.append((ts, state))
            if len(self.pending) >= self.cfg["fail_threshold"]:
                self._open()

        if ts - self.last_prune > 3600:
            self.db.execute("DELETE FROM samples WHERE ts < ?", (ts - self.cfg["keep_samples_days"] * 86400,))
            self.last_prune = ts
        self.db.commit()
        self.last_ts = ts

        with self.lock:
            st = self.status
            st["last"] = ts
            st["probe"] = {"state": state, "gw": p["gw"], "gw_ms": p["gw_ms"],
                           "net_ms": p["net_ms"], "http_ok": p["http_ok"]}
            st["pending"] = len(self.pending)
            st["net"] = self.net
            if self.outage:
                o = self.outage
                st["state"] = "down"
                st["outage"] = {"start": o["start"], "cause": max(o["counts"], key=o["counts"].get)}
            else:
                st["state"] = "up" if state == "ok" or st["state"] != "starting" else "starting"
                st["outage"] = None

    def _open(self):
        start, state = self.pending[0]
        counts = {}
        for _, s in self.pending:
            counts[s] = counts.get(s, 0) + 1
        oid = self.db.execute("INSERT INTO outages(start_ts, cause, network) VALUES(?,?,?)",
                              (start, state, network_label(self.net))).lastrowid
        self.outage = {"id": oid, "start": start, "counts": counts}
        self.pending = []
        log("QUEDA desde %s — causa provável: %s" % (fmt_ts(start, "%H:%M:%S"), CAUSES[state]))

    def _close(self, ts, ended_by, notify=True):
        o, self.outage = self.outage, None
        cause = max(o["counts"], key=o["counts"].get)
        dur = ts - o["start"]
        self.db.execute("UPDATE outages SET end_ts=?, cause=?, ended_by=? WHERE id=?",
                        (ts, cause, ended_by, o["id"]))
        with self.lock:
            self.status.update(since=ts, since_start=False)
        log("voltou após %s (%s)" % (fmt_dur(dur), CAUSES[cause]))
        if notify and dur >= self.cfg["notify_min_seconds"]:
            today = self.db.execute("SELECT COUNT(*) FROM outages WHERE start_ts >= ?",
                                    (midnight(ts),)).fetchone()[0]
            self.notifier.queue(
                "Internet voltou",
                "Caiu às %s e voltou às %s (%s).\nCausa provável: %s.\nQuedas hoje: %d."
                % (fmt_ts(o["start"], "%H:%M:%S"), fmt_ts(ts, "%H:%M:%S"), fmt_dur(dur), CAUSES[cause], today),
                "green_circle")

    def _gap(self, a, b):
        self.db.execute("INSERT INTO gaps VALUES(?,?)", (a, b))
        self.pending = []
        if self.outage:
            self._close(a, "monitor parado", notify=False)
        with self.lock:
            self.status.update(since=b, since_start=True)
        log("monitor ficou parado %s (computador dormiu ou travou)" % fmt_dur(b - a))
        if b - a >= self.cfg["notify_monitor_gap_minutes"] * 60:
            self._notify_gap(a, b)

    def _notify_gap(self, a, b):
        self.notifier.queue(
            "Monitor ficou sem rodar",
            "De %s até %s (%s). Computador desligado, dormindo ou falta de luz — "
            "esse período aparece como 'não monitorado'." % (fmt_ts(a, "%d/%m %H:%M"), fmt_ts(b, "%d/%m %H:%M"),
                                                           fmt_dur(b - a)),
            "warning")

    def stop(self):
        if self.outage and self.last_ts:
            self._close(self.last_ts, "monitor parado", notify=False)
        self.db.commit()


# --------------------------------------------------------------------------
# estatísticas para painel e relatório

def subtract(intervals, holes):
    out = []
    for a, b in intervals:
        segs = [(a, b)]
        for h1, h2 in holes:
            nxt = []
            for s1, s2 in segs:
                if h2 <= s1 or h1 >= s2:
                    nxt.append((s1, s2))
                    continue
                if h1 > s1:
                    nxt.append((s1, h1))
                if h2 < s2:
                    nxt.append((h2, s2))
            segs = nxt
        out.extend(segs)
    return out


def clip(intervals, t0, t1):
    return [(max(a, t0), min(b, t1)) + tuple(rest)
            for a, b, *rest in intervals if b > t0 and a < t1 and min(b, t1) > max(a, t0)]


def overlap(intervals, t0, t1):
    return sum(min(b, t1) - max(a, t0) for a, b, *_ in intervals if b > t0 and a < t1)


def latency_stats(db, col, t0, t1):
    where = "FROM samples WHERE ts >= ? AND ts < ? AND state = 'ok' AND %s IS NOT NULL" % col
    n, avg, mx = db.execute("SELECT COUNT(*), AVG(%s), MAX(%s) %s" % (col, col, where), (t0, t1)).fetchone()
    if not n:
        return None

    def pct(p):
        return db.execute("SELECT %s %s ORDER BY %s LIMIT 1 OFFSET ?" % (col, where, col),
                          (t0, t1, int((n - 1) * p))).fetchone()[0]

    slow = db.execute("SELECT COUNT(*) %s AND %s > 200" % (where, col), (t0, t1)).fetchone()[0]
    return {"n": n, "avg": avg, "p50": pct(0.5), "p95": pct(0.95), "max": mx, "slow_pct": slow / n}


def summarize(t0, t1):
    now = time.time()
    db = connect()
    try:
        first = db.execute("SELECT MIN(start_ts) FROM sessions").fetchone()[0] or now
        sessions = db.execute("SELECT start_ts, end_ts FROM sessions WHERE end_ts > ? AND start_ts < ?",
                              (t0, t1)).fetchall()
        gaps = db.execute("SELECT start_ts, end_ts FROM gaps WHERE end_ts > ? AND start_ts < ?",
                          (t0, t1)).fetchall()
        mon = sorted(clip(subtract(sessions, gaps), t0, t1))
        rows = db.execute("SELECT start_ts, end_ts, cause, ended_by, network FROM outages "
                          "WHERE COALESCE(end_ts, ?) > ? AND start_ts < ? ORDER BY start_ts",
                          (now, t0, t1)).fetchall()
        outages = []
        for s, e, c, how, net in rows:
            e_ = e if e is not None else now
            rssi = db.execute("SELECT AVG(rssi) FROM samples WHERE ts >= ? AND ts <= ? AND rssi IS NOT NULL",
                              (s - 60, e_)).fetchone()[0]
            outages.append({"start": s, "end": e_, "dur": e_ - s, "cause": c or "unknown", "ended_by": how,
                            "ongoing": e is None, "network": net, "rssi": rssi})
        clipped = clip([(o["start"], o["end"], o["cause"]) for o in outages], t0, t1)

        mon_s = sum(b - a for a, b in mon)
        down_s = sum(b - a for a, b, _ in clipped)
        durs = sorted(o["dur"] for o in outages)
        longest = max(outages, key=lambda o: o["dur"]) if outages else None

        causes = {}
        for a, b, c in clipped:
            x = causes.setdefault(c, {"count": 0, "down_s": 0})
            x["count"] += 1
            x["down_s"] += b - a

        # dias (meia-noite local a meia-noite local)
        days = []
        d = datetime.fromtimestamp(t0).replace(hour=0, minute=0, second=0, microsecond=0)
        while d.timestamp() < t1:
            ds, de = d.timestamp(), (d + timedelta(days=1)).timestamp()
            dm = overlap(mon, ds, de)
            dd = overlap(clipped, ds, de)
            days.append({"start": ds, "end": de, "mon_s": dm, "down_s": dd,
                         "count": sum(1 for o in outages if ds <= o["start"] < de),
                         "isp": sum(1 for o in outages if ds <= o["start"] < de and o["cause"] == "isp"),
                         "avail": (dm - dd) / dm if dm else None,
                         "mon": clip(mon, ds, de), "out": clip(clipped, ds, de)})
            d += timedelta(days=1)

        # hora do dia
        hours = [{"h": h, "count": 0, "down_s": 0} for h in range(24)]
        for o in outages:
            if t0 <= o["start"] < t1:
                hours[datetime.fromtimestamp(o["start"]).hour]["count"] += 1
        for a, b, _ in clipped:
            while a < b:
                dt = datetime.fromtimestamp(a)
                nxt = (dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp()
                hours[dt.hour]["down_s"] += min(b, nxt) - a
                a = min(b, nxt)

        # períodos não monitorados (só depois do primeiro uso e até agora)
        e0, e1 = max(t0, first), min(t1, now)
        unmon = [g for g in subtract([(e0, e1)], mon) if g[1] - g[0] >= 60] if e1 > e0 else []

        n_samples, n_fail = db.execute("SELECT COUNT(*), SUM(state != 'ok') FROM samples WHERE ts >= ? AND ts < ?",
                                       (t0, t1)).fetchone()
        return {
            "from": t0, "to": t1, "now": now,
            "mon_s": mon_s, "unmon_s": sum(b - a for a, b in unmon), "down_s": down_s,
            "avail": (mon_s - down_s) / mon_s if mon_s else None,
            "count": len(outages), "short": sum(1 for x in durs if x < 60),
            "avg": sum(durs) / len(durs) if durs else None,
            "median": durs[len(durs) // 2] if durs else None,
            "longest": longest,
            "mtbf": mon_s / len(outages) if outages else None,
            "causes": causes, "days": days, "hours": hours, "outages": outages,
            "unmonitored": unmon,
            "latency": latency_stats(db, "net_ms", t0, t1),
            "gw_latency": latency_stats(db, "gw_ms", t0, t1),
            "samples": n_samples, "fail_pct": (n_fail or 0) / n_samples if n_samples else None,
        }
    finally:
        db.close()


def glance():
    """Respostas rápidas para o topo do painel: últimas 24h corridas; 7 e 30 dias contados da
    meia-noite, iguais aos botões de período do resumo (o número bate ao tocar no quadradinho)."""
    now = time.time()
    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    start_7d = (today - timedelta(days=6)).timestamp()
    start_30d = (today - timedelta(days=29)).timestamp()
    db = connect()
    try:
        rows = db.execute("SELECT start_ts, COALESCE(end_ts, ?), cause FROM outages WHERE COALESCE(end_ts, ?) > ?",
                          (now, now, min(start_30d, now - 86400))).fetchall()
        last = db.execute("SELECT start_ts, end_ts, cause FROM outages ORDER BY start_ts DESC LIMIT 1").fetchone()
        first = db.execute("SELECT MIN(start_ts) FROM sessions").fetchone()[0]
    finally:
        db.close()

    def window(t0):
        hit = [(max(s, t0), e, c) for s, e, c in rows if e > t0]
        return {"count": len(hit), "down_s": sum(e - s for s, e, _ in hit),
                "isp": sum(1 for _, _, c in hit if c == "isp")}

    return {"now": now, "since": first, "h24": window(now - 86400), "d7": window(start_7d), "d30": window(start_30d),
            "last": {"start": last[0], "end": last[1] if last[1] is not None else now, "cause": last[2] or "unknown",
                     "ongoing": last[1] is None} if last else None}


def timeseries(hours):
    """Latência/falhas/sinal agregados em ~360 pontos para o gráfico ao vivo."""
    now = time.time()
    step = max(60, int(hours * 3600 / 360))
    db = connect()
    try:
        rows = db.execute(
            "SELECT CAST(ts / ? AS INTEGER) * ? AS b, AVG(CASE WHEN state='ok' THEN net_ms END), "
            "MAX(CASE WHEN state='ok' THEN net_ms END), AVG(gw_ms), SUM(state != 'ok'), COUNT(*), AVG(rssi) "
            "FROM samples WHERE ts >= ? GROUP BY b ORDER BY b", (step, step, now - hours * 3600)).fetchall()
    finally:
        db.close()
    return {"now": now, "step": step, "from": now - hours * 3600,
            "points": [{"t": b, "avg": a, "max": m, "gw": g, "fail": f, "n": n, "rssi": r}
                       for b, a, m, g, f, n, r in rows]}


def outages_csv(s):
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")    # aspas automáticas: um ';' no nome do Wi-Fi não quebra as colunas
    w.writerow(["Início", "Fim", "Duração (segundos)", "Duração", "Causa provável", "Rede", "Observação"])
    for o in s["outages"]:
        note = "em andamento" if o["ongoing"] else ("" if o["ended_by"] == "voltou" else o["ended_by"] or "")
        w.writerow([fmt_ts(o["start"]), fmt_ts(o["end"]), "%d" % round(o["dur"]),
                    fmt_dur(o["dur"]), CAUSES.get(o["cause"], o["cause"]), o["network"] or "", note])
    return "﻿" + out.getvalue()   # BOM + ';' para o Excel em português


def parse_range(q):
    def day(name):
        v = q.get(name, [""])[0]
        return datetime.strptime(v, "%Y-%m-%d") if v else None

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    a = day("from") or today
    b = day("to") or a
    if b < a:
        a, b = b, a
    if (b - a).days > MAX_RANGE_DAYS:
        raise ValueError("período longo demais")
    return a.timestamp(), (b + timedelta(days=1)).timestamp()


# --------------------------------------------------------------------------
# servidor web

MAX_RANGE_DAYS = 400
# Só estes arquivos são servidos — nada de montar caminho a partir da URL.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/relatorio": ("relatorio.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/common.js": ("common.js", "application/javascript; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/report.js": ("report.js", "application/javascript; charset=utf-8"),
}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def host_allowed(host_header, extra):
    """Bloqueia DNS rebinding: só aceita IP, localhost, *.local, o nome desta máquina e allowed_hosts."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):                       # [::1]:8000
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    host = host.rstrip(".")
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return host == "localhost" or host.endswith(".local") or host in [h.lower() for h in extra]


class Handler(BaseHTTPRequestHandler):
    monitor = None
    notifier = None
    cfg = None
    info = {}
    own_names = set()            # nome desta máquina (preenchido em cmd_run)
    timeout = 30                 # derruba conexões paradas
    server_version = "down-again"
    sys_version = ""
    last_test = 0
    test_lock = threading.Lock()

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in list(SECURITY_HEADERS.items()) + list((extra or {}).items()):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def check_host(self):
        if host_allowed(self.headers.get("Host"), list(self.cfg.get("allowed_hosts") or []) + list(self.own_names)):
            return True
        self.send(403, "Host não permitido. Para usar outro nome, inclua-o em allowed_hosts no "
                       "dados/config.json.", "text/plain; charset=utf-8")
        return False

    def do_GET(self):
        if not self.check_host():
            return
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/status":
                st = self.monitor.get_status()
                st["now"] = time.time()
                st["interval"] = self.cfg["interval"]
                return self.json(st)
            if u.path == "/api/summary":
                return self.json(summarize(*parse_range(q)))
            if u.path == "/api/glance":
                return self.json(glance())
            if u.path == "/api/timeseries":
                return self.json(timeseries(min(168.0, max(0.25, float(q.get("hours", ["6"])[0])))))
            if u.path == "/api/outages.csv":
                t0, t1 = parse_range(q)
                name = "quedas_%s_a_%s.csv" % (fmt_ts(t0, "%Y-%m-%d"), fmt_ts(t1 - 1, "%Y-%m-%d"))
                return self.send(200, outages_csv(summarize(t0, t1)), "text/csv; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="%s"' % name})
            if u.path == "/api/config":
                return self.json({
                    "interval": self.cfg["interval"], "timeout": self.cfg["timeout"],
                    "fail_threshold": self.cfg["fail_threshold"],
                    "tcp_targets": ["%s:%d" % t for t in TCP_TARGETS], "http_url": HTTP_URL,
                    "ntfy_server": self.cfg["ntfy_server"], "ntfy_topic": self.cfg["ntfy_topic"],
                    "host": self.info.get("host"), "ip": self.info.get("ip"), "port": self.cfg["port"],
                    "causes": CAUSES, "platform": PLATFORM,
                })
        except (ValueError, OverflowError, OSError):
            return self.json({"error": "período inválido (use AAAA-MM-DD, até %d dias)" % MAX_RANGE_DAYS}, 400)
        self.static(u.path)

    def do_POST(self):
        if not self.check_host():
            return
        if urlparse(self.path).path != "/api/test-notify":
            return self.send(404, "não encontrado", "text/plain; charset=utf-8")
        # Cabeçalho próprio força preflight de CORS (que não respondemos): outro site não consegue disparar.
        if self.headers.get("X-Down-Again") != "1":
            return self.json({"ok": False, "error": "requisição recusada"}, 403)
        with Handler.test_lock:
            wait = 30 - (time.time() - Handler.last_test)
            if wait > 0:
                return self.json({"ok": False, "error": "aguarde %ds para testar de novo" % wait}, 429)
            Handler.last_test = time.time()
        if not self.notifier.enabled:
            return self.json({"ok": False, "error": "ntfy_topic vazio em dados/config.json"})
        ok, err = self.notifier.send("Teste do monitor de internet",
                                     "Se você está lendo isto, os avisos estão funcionando.", ["white_check_mark"])
        return self.json({"ok": ok, "error": err})

    def static(self, path):
        if path not in STATIC_FILES:
            return self.send(404, "não encontrado", "text/plain; charset=utf-8")
        name, ctype = STATIC_FILES[path]
        with open(os.path.join(STATIC, name), "rb") as f:
            self.send(200, f.read(), ctype)


# --------------------------------------------------------------------------
# comandos

def cmd_run(cfg):
    if sys.stdout is None or sys.stderr is None:   # pythonw (início automático no Windows): log em arquivo
        sys.stdout = sys.stderr = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    notifier = Notifier(cfg)
    monitor = Monitor(cfg, notifier)
    host, ip = local_addresses()
    Handler.monitor, Handler.notifier, Handler.cfg = monitor, notifier, cfg
    Handler.info = {"host": host, "ip": ip}
    # o próprio nome da máquina também vale como Host (no Windows não há .local)
    name = socket.gethostname().lower()
    Handler.own_names = {name, name.split(".")[0]}
    server = ThreadingHTTPServer((cfg["bind"], cfg["port"]), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=notifier.run, daemon=True).start()

    log("monitor iniciado no %s (teste a cada %ss)" % (PLATFORM, cfg["interval"]))
    if not IS_MAC:
        log("aviso: suporte a %s é experimental e ainda não foi testado em máquina real" % PLATFORM)
    log("painel: http://localhost:%d" % cfg["port"])
    for addr in (host, ip):
        if addr:
            log("        http://%s:%d" % (addr, cfg["port"]))
    if notifier.enabled:
        log("avisos: assine o tópico '%s' no app ntfy" % cfg["ntfy_topic"])

    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    try:
        monitor.run()
    except (KeyboardInterrupt, SystemExit):
        monitor.stop()
        log("monitor parado")


def cmd_check(cfg):
    p = probe(cfg["timeout"])
    state = classify(p, p["gw_ms"] is not None)
    ms = lambda v: "%.0f ms" % v if v is not None else "sem resposta"
    net = network_info()
    print("Sistema            : %s%s" % (PLATFORM, "" if IS_MAC else " (experimental, não testado em máquina real)"))
    print("Rede               : %s" % network_label(net))
    if net.get("rssi") is not None:
        print("  sinal            : %.0f dBm  (canal %s, link %s Mbps)" % (net["rssi"], net["channel"], net["tx_rate"]))
    print("Roteador (gateway) : %s" % (p["gw"] or "nenhum — computador sem rede"))
    print("  ping             : %s" % (ms(p["gw_ms"]) if p["gw"] else "—"))
    print("Internet por IP    : %s  (%s)" % (ms(p["net_ms"]), ", ".join(h for h, _ in TCP_TARGETS)))
    print("Site por nome      : %s  (%s)" % ("ok" if p["http_ok"] else "falhou", HTTP_URL))
    print("Diagnóstico        : %s" % ("conexão OK" if state == "ok" else "SEM INTERNET — " + CAUSES[state]))
    if p["gw"] and p["gw_ms"] is None and state == "ok":
        print("\nObs.: seu roteador não responde a ping. Nesse caso o monitor não consegue separar\n"
              "      'provedor' de 'rede local' e as quedas aparecem como 'Indeterminada'.")


def print_installed(cfg, how, logs):
    host, ip = local_addresses()
    print("Instalado. O monitor já está rodando e vai iniciar sozinho %s." % how)
    print("Painel: http://%s:%d" % (host or ip or "localhost", cfg["port"]))
    print("Log:    %s" % logs)


# --- macOS: LaunchAgent + caffeinate (não deixa o Mac dormir) ---

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-ims</string>
    <string>{python}</string><string>{script}</string>
  </array>
  <key>WorkingDirectory</key><string>{base}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def install_mac(cfg):
    home = os.path.expanduser("~")
    for protected in ("Desktop", "Documents", "Downloads", "Mesa", "Documentos"):
        if BASE.startswith(os.path.join(home, protected) + os.sep):
            print("A pasta está em ~/%s, que o macOS bloqueia para programas em segundo plano.\n"
                  "Mova a pasta down-again para a sua pasta pessoal (ex.: ~/down-again) e rode de novo." % protected)
            return
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    for path in (OLD_PLIST_PATH, PLIST_PATH):     # para o antigo (netmon) e a versão anterior antes de subir
        if os.path.exists(path):
            run_cmd(["launchctl", "unload", "-w", path])
    if os.path.exists(OLD_PLIST_PATH):
        os.remove(OLD_PLIST_PATH)
        print("Removido o início automático antigo (netmon).")
    with open(PLIST_PATH, "w", encoding="utf-8") as f:
        f.write(PLIST.format(label=PLIST_LABEL, python=xml_escape(sys.executable),
                             script=xml_escape(os.path.abspath(__file__)), base=xml_escape(BASE),
                             log=xml_escape(LOG_PATH)))
    code, _ = run_cmd(["launchctl", "load", "-w", PLIST_PATH])
    if code != 0:
        print("Falha ao carregar o LaunchAgent. Veja: launchctl load -w %s" % PLIST_PATH)
        return
    print_installed(cfg, "sempre que você entrar no Mac", LOG_PATH)


def uninstall_mac():
    if not os.path.exists(PLIST_PATH):
        return False
    run_cmd(["launchctl", "unload", "-w", PLIST_PATH])
    os.remove(PLIST_PATH)
    return True


# --- Linux (experimental): serviço de usuário do systemd ---

SYSTEMD_UNIT = "down-again.service"
SYSTEMD_PATH = os.path.expanduser("~/.config/systemd/user/" + SYSTEMD_UNIT)
UNIT = """[Unit]
Description=down-again - monitor de quedas de internet
After=network-online.target

[Service]
ExecStart={python} {script}
WorkingDirectory={base}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def systemd_quote(s):
    # aspas para espaços; '%' é especificador no systemd e precisa virar '%%'
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def install_linux(cfg):
    if not shutil.which("systemctl"):
        print("systemd não encontrado. Rode em segundo plano por outro meio, por exemplo no crontab:\n"
              "  @reboot %s %s" % (sys.executable, os.path.abspath(__file__)))
        return
    os.makedirs(os.path.dirname(SYSTEMD_PATH), exist_ok=True)
    with open(SYSTEMD_PATH, "w", encoding="utf-8") as f:
        f.write(UNIT.format(python=systemd_quote(sys.executable), script=systemd_quote(os.path.abspath(__file__)),
                            base=BASE.replace("%", "%%")))
    for args in (["daemon-reload"], ["enable", SYSTEMD_UNIT], ["restart", SYSTEMD_UNIT]):
        code, _ = run_cmd(["systemctl", "--user"] + args, timeout=30)
        if code != 0:
            print("Falha em: systemctl --user %s" % " ".join(args))
            return
    print_installed(cfg, "quando você entrar no sistema", "journalctl --user -u %s -f" % SYSTEMD_UNIT)
    print("Para rodar mesmo sem ninguém logado (ex.: Raspberry Pi depois de uma falta de luz):\n"
          "  sudo loginctl enable-linger %s" % os.environ.get("USER", "$USER"))


def uninstall_linux():
    if not os.path.exists(SYSTEMD_PATH):
        return False
    run_cmd(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT], timeout=30)
    os.remove(SYSTEMD_PATH)
    run_cmd(["systemctl", "--user", "daemon-reload"], timeout=30)
    return True


# --- Windows (experimental): Agendador de Tarefas, ao entrar no Windows, sem janela (pythonw) ---

TASK_NAME = "down-again"


def install_windows(cfg):
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    command = '"%s" "%s"' % (pyw if os.path.exists(pyw) else sys.executable, os.path.abspath(__file__))
    if len(command) > 261:
        print("Caminho longo demais para o Agendador de Tarefas. Mova a pasta para algo como C:\\down-again.")
        return
    run_cmd(["schtasks", "/End", "/TN", TASK_NAME])
    code, _ = run_cmd(["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON", "/TR", command,
                       "/RL", "LIMITED", "/F"], timeout=30)
    if code != 0:
        print("Falha ao criar a tarefa. Tente de novo num terminal aberto como administrador.")
        return
    run_cmd(["schtasks", "/Run", "/TN", TASK_NAME])
    print_installed(cfg, "quando você entrar no Windows", LOG_PATH)


def uninstall_windows():
    code, _ = run_cmd(["schtasks", "/Query", "/TN", TASK_NAME])
    if code != 0:
        return False
    run_cmd(["schtasks", "/End", "/TN", TASK_NAME])
    run_cmd(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    return True


def cmd_install(cfg):
    if not IS_MAC:
        print("Aviso: o suporte a %s é experimental e ainda não foi testado em máquina real." % PLATFORM)
    if IS_MAC:
        install_mac(cfg)
    elif IS_LINUX:
        install_linux(cfg)
    elif IS_WIN:
        install_windows(cfg)
    else:
        print("Início automático não suportado em %s. Rode: python3 down_again.py" % PLATFORM)


def cmd_uninstall(cfg):
    removed = {"macOS": uninstall_mac, "Linux": uninstall_linux, "Windows": uninstall_windows}.get(PLATFORM, lambda: False)()
    print("Início automático removido (os dados em %s continuam lá)." % DATA if removed else "Não estava instalado.")


def main():
    ap = argparse.ArgumentParser(description="Monitor de quedas de internet com painel web.")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "check", "install", "uninstall"])
    ap.add_argument("--port", type=int, help="porta do painel (padrão: config.json)")
    args = ap.parse_args()
    cfg = load_config()
    if args.port:
        cfg["port"] = args.port
    {"run": cmd_run, "check": cmd_check, "install": cmd_install, "uninstall": cmd_uninstall}[args.cmd](cfg)


if __name__ == "__main__":
    main()
