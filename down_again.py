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
import collections
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
    "language": "auto",            # "en", "pt", "zh" ou "auto" (idioma do sistema): avisos, CSV, terminal
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
    "daily_summary_hour": 9,       # resumo do dia anterior no celular a esta hora (-1 desliga)
    "speedtest_minutes": 240,      # teste de velocidade a cada N minutos (240 = 6 por dia); 0 desliga
    "speedtest_seconds": 5,        # duração de cada sentido (download e upload)
    "plan_down_mbps": 0,           # plano contratado, para comparar (0 = não informado)
    "plan_up_mbps": 0,
}

# IPs fixos (sem depender de DNS) e uma URL por nome (exercita DNS + HTTP).
TCP_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443), ("208.67.222.222", 443)]
HTTP_URL = "http://captive.apple.com/hotspot-detect.html"

# Textos do servidor (avisos no celular, CSV, terminal) em todos os idiomas da interface.
# O idioma vem de "language" no config.json ("auto" = idioma do sistema). tests/test_i18n.py
# confere que todos os idiomas têm as mesmas chaves e os mesmos {marcadores}.
TEXTS = {
    "en": {
        "unit.d": "d", "unit.h": "h", "unit.min": "min", "unit.s": "s",
        "cause.isp": "ISP", "cause.local": "Local network / Wi-Fi", "cause.dns": "DNS / websites not loading",
        "cause.unknown": "Unknown",
        "net.none": "no network", "net.cable": "Cable ({port})",
        "notify.back.title": "Internet is back",
        "notify.back.body": "Went down at {start} and came back at {end} ({dur}).\nLikely cause: {cause}.\nOutages today: {today}.",
        "notify.gap.title": "The monitor stopped running",
        "notify.gap.body": "From {a} to {b} ({dur}). Computer off, asleep or a power cut — this period shows as 'not monitored'.",
        "notify.many.title": "{n} alerts from the monitor",
        "notify.test.title": "down-again test", "notify.test.body": "If you can read this, alerts are working.",
        "log.notify_failed": "alert not sent, retrying in 30s: {err}", "log.db_error": "database error: {err}",
        "log.outage": "OUTAGE since {since} — likely cause: {cause}", "log.back": "back after {dur} ({cause})",
        "log.gap": "the monitor was stopped for {dur} (computer asleep or frozen)",
        "log.started": "monitor started on {os} (checking every {n}s)",
        "log.experimental": "warning: {os} support is experimental and has not been tested on a real machine",
        "log.panel": "dashboard: {url}", "log.subscribe": "alerts: subscribe to the topic '{topic}' in the ntfy app",
        "log.stopped": "monitor stopped",
        "log.speed": "speed test: {down} Mbps down, {up} Mbps up, ping {ping} ms", "log.speed_failed": "speed test failed: {err}",
        "http.host": "Host not allowed. To use another name, add it to allowed_hosts in dados/config.json.",
        "check.system": "System", "check.experimental": "experimental, not tested on a real machine",
        "check.network": "Network", "check.signal": "signal", "check.router": "Router (gateway)",
        "check.no_gateway": "none — computer has no network", "check.ping": "ping", "check.internet": "Internet by IP",
        "check.site": "Website by name", "check.ok": "ok", "check.failed": "failed", "check.no_reply": "no reply",
        "check.diagnosis": "Diagnosis", "check.conn_ok": "connection OK", "check.no_internet": "NO INTERNET — {cause}",
        "check.channel": "channel {channel}, link {rate} Mbps",
        "check.no_ping_note": "Note: your router doesn't answer ping. The monitor can't tell 'ISP' from 'local network', so outages show as 'Unknown'.",
        "install.done": "Installed. The monitor is running now and will start by itself {how}.",
        "install.panel": "Dashboard: {url}", "install.log": "Log:       {log}",
        "install.how_mac": "whenever you log in to the Mac", "install.how_linux": "when you log in",
        "install.how_win": "when you sign in to Windows",
        "install.protected": "The folder is in ~/{folder}, which macOS blocks for background programs.\nMove the down-again folder to your home folder (e.g. ~/down-again) and run this again.",
        "install.old_removed": "Removed the old automatic start (netmon).",
        "install.launchd_failed": "Could not load the LaunchAgent. See: launchctl load -w {path}",
        "install.no_systemd": "systemd not found. Run it in the background another way, e.g. in crontab:\n  @reboot {cmd}",
        "install.systemctl_failed": "Failed: systemctl --user {cmd}",
        "install.linger": "To run even when nobody is logged in (e.g. a Raspberry Pi after a power cut):\n  sudo loginctl enable-linger {user}",
        "install.path_too_long": "The path is too long for Task Scheduler. Move the folder to something like C:\\down-again.",
        "install.task_failed": "Could not create the task. Try again from a terminal opened as administrator.",
        "install.experimental": "Warning: {os} support is experimental and has not been tested on a real machine.",
        "install.unsupported": "Automatic start is not supported on {os}. Run: python3 down_again.py",
        "uninstall.done": "Automatic start removed (your data in {data} is still there).", "uninstall.none": "It wasn't installed.",
        "csv.start": "Start", "csv.end": "End", "csv.dur_s": "Duration (seconds)", "csv.dur": "Duration",
        "csv.cause": "Likely cause", "csv.network": "Network", "csv.note": "Note", "csv.ongoing": "ongoing",
        "csv.stopped": "monitor stopped", "csv.file": "outages",
        "hint.router_restart": "router restarted (new public IP)",
        "hint.reconnect": "ISP renewed the connection (new public IP)",
        "log.unstable": "unstable connection since {since} (packet loss or high latency)",
        "log.unstable_end": "stable again after {dur} ({loss} failed and {slow} slow checks)",
        "log.ip_change": "public IP changed: {old} -> {new}",
        "daily.title.none": "Yesterday: no outages", "daily.title.one": "Yesterday: 1 outage ({d} offline)",
        "daily.title": "Yesterday: {n} outages ({d} offline)",
        "daily.avail": "Availability {p} · monitored {mon}", "daily.outages": "ISP's fault: {isp} · longest {d}",
        "daily.unstable": "Unstable: {n}× ({d})", "daily.speed": "Average speed: {down} ↓ / {up} ↑ Mbps",
        "daily.speed_plan": " ({p} of the plan)", "daily.ip": "Public IP changed {n}×",
        "daily.footer": "Daily summary — if it stops arriving, check the monitor.",
    },
    "pt": {
        "unit.d": "d", "unit.h": "h", "unit.min": "min", "unit.s": "s",
        "cause.isp": "Provedor", "cause.local": "Rede local / Wi-Fi", "cause.dns": "DNS / sites não abrem",
        "cause.unknown": "Indeterminada",
        "net.none": "sem rede", "net.cable": "Cabo ({port})",
        "notify.back.title": "Internet voltou",
        "notify.back.body": "Caiu às {start} e voltou às {end} ({dur}).\nCausa provável: {cause}.\nQuedas hoje: {today}.",
        "notify.gap.title": "Monitor ficou sem rodar",
        "notify.gap.body": "De {a} até {b} ({dur}). Computador desligado, dormindo ou falta de luz — esse período aparece como 'não monitorado'.",
        "notify.many.title": "{n} avisos do monitor",
        "notify.test.title": "Teste do down-again", "notify.test.body": "Se você está lendo isto, os avisos estão funcionando.",
        "log.notify_failed": "aviso não enviado, tento de novo em 30s: {err}", "log.db_error": "erro no banco: {err}",
        "log.outage": "QUEDA desde {since} — causa provável: {cause}", "log.back": "voltou após {dur} ({cause})",
        "log.gap": "monitor ficou parado {dur} (computador dormiu ou travou)",
        "log.started": "monitor iniciado no {os} (teste a cada {n}s)",
        "log.experimental": "aviso: o suporte a {os} é experimental e ainda não foi testado em máquina real",
        "log.panel": "painel: {url}", "log.subscribe": "avisos: assine o tópico '{topic}' no app ntfy",
        "log.stopped": "monitor parado",
        "log.speed": "teste de velocidade: {down} Mbps de download, {up} Mbps de upload, ping {ping} ms", "log.speed_failed": "teste de velocidade falhou: {err}",
        "http.host": "Host não permitido. Para usar outro nome, inclua-o em allowed_hosts no dados/config.json.",
        "check.system": "Sistema", "check.experimental": "experimental, não testado em máquina real",
        "check.network": "Rede", "check.signal": "sinal", "check.router": "Roteador (gateway)",
        "check.no_gateway": "nenhum — computador sem rede", "check.ping": "ping", "check.internet": "Internet por IP",
        "check.site": "Site por nome", "check.ok": "ok", "check.failed": "falhou", "check.no_reply": "sem resposta",
        "check.diagnosis": "Diagnóstico", "check.conn_ok": "conexão OK", "check.no_internet": "SEM INTERNET — {cause}",
        "check.channel": "canal {channel}, link {rate} Mbps",
        "check.no_ping_note": "Obs.: seu roteador não responde a ping. O monitor não consegue separar 'provedor' de 'rede local', e as quedas aparecem como 'Indeterminada'.",
        "install.done": "Instalado. O monitor já está rodando e vai iniciar sozinho {how}.",
        "install.panel": "Painel: {url}", "install.log": "Log:    {log}",
        "install.how_mac": "sempre que você entrar no Mac", "install.how_linux": "quando você entrar no sistema",
        "install.how_win": "quando você entrar no Windows",
        "install.protected": "A pasta está em ~/{folder}, que o macOS bloqueia para programas em segundo plano.\nMova a pasta down-again para a sua pasta pessoal (ex.: ~/down-again) e rode de novo.",
        "install.old_removed": "Removido o início automático antigo (netmon).",
        "install.launchd_failed": "Falha ao carregar o LaunchAgent. Veja: launchctl load -w {path}",
        "install.no_systemd": "systemd não encontrado. Rode em segundo plano por outro meio, por exemplo no crontab:\n  @reboot {cmd}",
        "install.systemctl_failed": "Falha em: systemctl --user {cmd}",
        "install.linger": "Para rodar mesmo sem ninguém logado (ex.: Raspberry Pi depois de uma falta de luz):\n  sudo loginctl enable-linger {user}",
        "install.path_too_long": "Caminho longo demais para o Agendador de Tarefas. Mova a pasta para algo como C:\\down-again.",
        "install.task_failed": "Falha ao criar a tarefa. Tente de novo num terminal aberto como administrador.",
        "install.experimental": "Aviso: o suporte a {os} é experimental e ainda não foi testado em máquina real.",
        "install.unsupported": "Início automático não suportado em {os}. Rode: python3 down_again.py",
        "uninstall.done": "Início automático removido (os dados em {data} continuam lá).", "uninstall.none": "Não estava instalado.",
        "csv.start": "Início", "csv.end": "Fim", "csv.dur_s": "Duração (segundos)", "csv.dur": "Duração",
        "csv.cause": "Causa provável", "csv.network": "Rede", "csv.note": "Observação", "csv.ongoing": "em andamento",
        "csv.stopped": "monitor parado", "csv.file": "quedas",
        "hint.router_restart": "roteador reiniciou (IP público novo)",
        "hint.reconnect": "provedor refez a conexão (IP público novo)",
        "log.unstable": "conexão instável desde {since} (perda de pacotes ou latência alta)",
        "log.unstable_end": "estável de novo após {dur} ({loss} testes falharam e {slow} ficaram lentos)",
        "log.ip_change": "IP público trocou: {old} -> {new}",
        "daily.title.none": "Ontem: nenhuma queda", "daily.title.one": "Ontem: 1 queda ({d} fora do ar)",
        "daily.title": "Ontem: {n} quedas ({d} fora do ar)",
        "daily.avail": "Disponibilidade {p} · monitorado {mon}", "daily.outages": "Do provedor: {isp} · maior {d}",
        "daily.unstable": "Instável: {n}× ({d})", "daily.speed": "Velocidade média: {down} ↓ / {up} ↑ Mbps",
        "daily.speed_plan": " ({p} do plano)", "daily.ip": "IP público trocou {n}×",
        "daily.footer": "Resumo diário — se um dia não chegar, confira o monitor.",
    },
    "zh": {
        "unit.d": "天", "unit.h": "小时", "unit.min": "分", "unit.s": "秒",
        "cause.isp": "运营商", "cause.local": "本地网络 / Wi-Fi", "cause.dns": "DNS / 网站打不开",
        "cause.unknown": "无法确定",
        "net.none": "无网络", "net.cable": "网线（{port}）",
        "notify.back.title": "网络已恢复",
        "notify.back.body": "{start} 断开，{end} 恢复（{dur}）。\n可能原因：{cause}。\n今日断线：{today} 次。",
        "notify.gap.title": "监控曾停止运行",
        "notify.gap.body": "从 {a} 到 {b}（{dur}）。电脑关机、睡眠或停电 — 该时段显示为“未监控”。",
        "notify.many.title": "监控的 {n} 条通知",
        "notify.test.title": "down-again 测试", "notify.test.body": "如果你看到这条消息，说明通知功能正常。",
        "log.notify_failed": "通知未发送，30 秒后重试：{err}", "log.db_error": "数据库错误：{err}",
        "log.outage": "断线，开始于 {since} — 可能原因：{cause}", "log.back": "已恢复，断开 {dur}（{cause}）",
        "log.gap": "监控停止了 {dur}（电脑睡眠或卡住）",
        "log.started": "监控已在 {os} 上启动（每 {n} 秒检测一次）",
        "log.experimental": "提示：{os} 支持仍为实验性，尚未在真机上测试",
        "log.panel": "面板：{url}", "log.subscribe": "通知：在 ntfy 应用中订阅主题“{topic}”",
        "log.stopped": "监控已停止",
        "log.speed": "测速：下载 {down} Mbps，上传 {up} Mbps，延迟 {ping} ms", "log.speed_failed": "测速失败：{err}",
        "http.host": "不允许的 Host。如需使用其他名称，请将其加入 dados/config.json 的 allowed_hosts。",
        "check.system": "系统", "check.experimental": "实验性，尚未在真机上测试",
        "check.network": "网络", "check.signal": "信号", "check.router": "路由器（网关）",
        "check.no_gateway": "无 — 电脑未联网", "check.ping": "ping", "check.internet": "按 IP 访问互联网",
        "check.site": "按域名访问网站", "check.ok": "正常", "check.failed": "失败", "check.no_reply": "无响应",
        "check.diagnosis": "诊断", "check.conn_ok": "连接正常", "check.no_internet": "断网 — {cause}",
        "check.channel": "信道 {channel}，速率 {rate} Mbps",
        "check.no_ping_note": "提示：你的路由器不响应 ping。监控无法区分“运营商”和“本地网络”，断线会显示为“无法确定”。",
        "install.done": "已安装。监控正在运行，并会{how}自动启动。",
        "install.panel": "面板：{url}", "install.log": "日志：{log}",
        "install.how_mac": "在每次登录 Mac 时", "install.how_linux": "在你登录系统时",
        "install.how_win": "在你登录 Windows 时",
        "install.protected": "文件夹位于 ~/{folder}，macOS 会阻止后台程序访问该位置。\n请把 down-again 文件夹移到个人目录（例如 ~/down-again）后重新运行。",
        "install.old_removed": "已移除旧的自动启动项（netmon）。",
        "install.launchd_failed": "无法加载 LaunchAgent。请查看：launchctl load -w {path}",
        "install.no_systemd": "未找到 systemd。请用其他方式后台运行，例如在 crontab 中：\n  @reboot {cmd}",
        "install.systemctl_failed": "执行失败：systemctl --user {cmd}",
        "install.linger": "如需在无人登录时也运行（例如 Raspberry Pi 停电重启后）：\n  sudo loginctl enable-linger {user}",
        "install.path_too_long": "路径过长，任务计划程序无法使用。请把文件夹移到类似 C:\\down-again 的位置。",
        "install.task_failed": "无法创建任务。请在以管理员身份打开的终端中重试。",
        "install.experimental": "提示：{os} 支持仍为实验性，尚未在真机上测试。",
        "install.unsupported": "{os} 不支持自动启动。请运行：python3 down_again.py",
        "uninstall.done": "已移除自动启动（{data} 中的数据仍保留）。", "uninstall.none": "尚未安装。",
        "csv.start": "开始", "csv.end": "结束", "csv.dur_s": "时长（秒）", "csv.dur": "时长",
        "csv.cause": "可能原因", "csv.network": "网络", "csv.note": "备注", "csv.ongoing": "进行中",
        "csv.stopped": "监控停止", "csv.file": "outages",
        "hint.router_restart": "路由器已重启（公网 IP 已变）",
        "hint.reconnect": "运营商重新建立了连接（公网 IP 已变）",
        "log.unstable": "连接不稳定，开始于 {since}（丢包或延迟高）",
        "log.unstable_end": "已恢复稳定，持续 {dur}（{loss} 次失败，{slow} 次过慢）",
        "log.ip_change": "公网 IP 已变更：{old} -> {new}",
        "daily.title.none": "昨天：没有断线", "daily.title.one": "昨天：1 次断线（离线 {d}）",
        "daily.title": "昨天：{n} 次断线（离线 {d}）",
        "daily.avail": "可用率 {p} · 监控 {mon}", "daily.outages": "运营商原因：{isp} 次 · 最长 {d}",
        "daily.unstable": "不稳定：{n} 次（{d}）", "daily.speed": "平均网速：下行 {down} / 上行 {up} Mbps",
        "daily.speed_plan": "（套餐的 {p}）", "daily.ip": "公网 IP 变更 {n} 次",
        "daily.footer": "每日摘要 — 如果某天没收到，请检查监控。",
    },
}
LANG = "en"   # definido em load_config


def tr(key, lang=None, **kw):
    s = TEXTS.get(lang or LANG, TEXTS["en"]).get(key) or TEXTS["en"].get(key, key)
    return s.format(**kw) if kw else s


def cause_label(code, lang=None):
    return tr("cause." + (code if code in ("isp", "local", "dns") else "unknown"), lang)


def detect_language():
    """Idioma do sistema: variáveis de ambiente; no macOS, AppleLocale; no Windows, o idioma da interface."""
    found = [os.environ.get(v) for v in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")]
    if IS_MAC:
        found.append(run_cmd(["defaults", "read", "-g", "AppleLocale"])[1])
    if IS_WIN:
        try:
            import ctypes
            found.append({0x16: "pt", 0x04: "zh", 0x09: "en"}.get(ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF))
        except Exception:
            pass
    for value in found:
        code = (value or "").strip().lower()[:2]
        if code in TEXTS:
            return code
    return "en"

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples(ts REAL, state TEXT, gw_ms REAL, net_ms REAL, http_ok INTEGER, rssi REAL);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS outages(id INTEGER PRIMARY KEY, start_ts REAL, end_ts REAL, cause TEXT, ended_by TEXT,
                                   network TEXT);
CREATE INDEX IF NOT EXISTS outages_start ON outages(start_ts);
CREATE TABLE IF NOT EXISTS gaps(start_ts REAL, end_ts REAL);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, start_ts REAL, end_ts REAL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, ts REAL, title TEXT, body TEXT, tag TEXT, sent_ts REAL);
CREATE TABLE IF NOT EXISTS speedtests(ts REAL, down_mbps REAL, up_mbps REAL, ping_ms REAL, jitter_ms REAL, error TEXT,
                                      manual INTEGER);
CREATE INDEX IF NOT EXISTS speedtests_ts ON speedtests(ts);
-- instabilidade (kind='unstable') e troca de IP público (kind='ip_change'); data = JSON com os detalhes
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, kind TEXT, start_ts REAL, end_ts REAL, data TEXT);
CREATE INDEX IF NOT EXISTS events_start ON events(start_ts);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def meta_get(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, str(value)))


# --------------------------------------------------------------------------
# utilidades

def log(msg):
    print("[%s] %s" % (time.strftime("%d/%m %H:%M:%S"), msg), flush=True)


def fmt_dur(sec, lang=None):
    u = {k: tr("unit." + k, lang) for k in ("d", "h", "min", "s")}
    sec = int(round(sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return "%d%s %02d%s%02d" % (d, u["d"], h, u["h"], m)
    if h:
        return "%d%s %02d%s" % (h, u["h"], m, u["min"])
    if m:
        return "%d%s %02d%s" % (m, u["min"], s, u["s"])
    return "%d%s" % (s, u["s"])


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
    set_language(cfg)
    db = connect()
    db.executescript(SCHEMA)
    # coluna nova em bancos de versões anteriores: pista da causa ("router_restart", "reconnect")
    if "hint" not in [r[1] for r in db.execute("PRAGMA table_info(outages)")]:
        db.execute("ALTER TABLE outages ADD COLUMN hint TEXT")
    db.commit()
    db.close()
    return cfg


def set_language(cfg):
    global LANG
    LANG = cfg["language"] if cfg.get("language") in TEXTS else detect_language()


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
        return tr("net.none")
    if net["kind"] == "cabo":
        return tr("net.cable", port=net.get("port") or net.get("iface"))
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
        self.last_error = None          # mostrado em Ajustes: ajuda a ver por que um aviso não chegou

    @property
    def enabled(self):
        return bool(self.cfg.get("ntfy_topic"))

    def queue(self, title, body, tag, db=None):
        """Guarda o aviso na fila. Quem já tem uma transação aberta (o monitor) passa a própria
        conexão: abrir outra e esperar o lock dela travava 15 s e perdia o aviso."""
        if not self.enabled:
            return
        own = db is None
        if own:
            db = connect()
        db.execute("INSERT INTO notifications(ts, title, body, tag) VALUES(?,?,?,?)",
                   (time.time(), title, body, tag))
        db.commit()
        if own:
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

    def daily(self, db):
        """Resumo do dia anterior a partir de daily_summary_hour. Também prova, todo dia,
        que o caminho dos avisos funciona: se ele não chegar, há algo errado."""
        hour = int(self.cfg.get("daily_summary_hour", -1))
        now = datetime.now()
        if not self.enabled or hour < 0 or now.hour < hour:
            return
        day = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        key = day.strftime("%Y-%m-%d")
        if meta_get(db, "daily_sent") == key:
            return
        meta_set(db, "daily_sent", key)
        msg = daily_summary(day, self.cfg)
        if msg:
            self.queue(msg[0], msg[1], "bar_chart", db=db)
        db.commit()

    def stats(self):
        db = connect()
        try:
            last = db.execute("SELECT MAX(sent_ts) FROM notifications").fetchone()[0]
            pending = db.execute("SELECT COUNT(*) FROM notifications WHERE sent_ts IS NULL").fetchone()[0]
        finally:
            db.close()
        return {"last_sent": last, "pending": pending, "error": self.last_error}

    def run(self):
        db = connect()
        while True:
            if self.wake.wait(30):
                self.wake.clear()
                time.sleep(3)   # dá um tempo para a conexão recém-voltada estabilizar
            if not self.enabled:
                continue
            try:
                self.daily(db)
            except Exception as e:      # resumo é extra: nunca derruba o envio dos avisos
                log(tr("log.db_error", err=repr(e)))
            rows = db.execute("SELECT id, title, body, tag FROM notifications WHERE sent_ts IS NULL "
                              "ORDER BY id LIMIT 20").fetchall()
            if not rows:
                continue
            if len(rows) == 1:
                title, body, tags = rows[0][1], rows[0][2], [rows[0][3]]
            else:
                title = tr("notify.many.title", n=len(rows))
                body = "\n\n".join("%s\n%s" % (r[1], r[2]) for r in rows)
                tags = [rows[-1][3]]
            ok, err = self.send(title, body, tags)
            self.last_error = None if ok else (err or "?")
            if ok:
                ids = [r[0] for r in rows]
                db.execute("UPDATE notifications SET sent_ts=? WHERE id IN (%s)" % ",".join("?" * len(ids)),
                           [time.time()] + ids)
                db.commit()
            else:
                log(tr("log.notify_failed", err=err))


# --------------------------------------------------------------------------
# teste de velocidade (servidores da Cloudflare, medido com o curl do sistema)
#
# O curl é escrito em C: alcança planos de 500+ Mbps num Mac antigo, onde o Python não chega,
# e usa os certificados do sistema. Várias conexões em paralelo, como os sites de teste fazem.

SPEED_HOST = "speed.cloudflare.com"
SPEED_DOWN_BYTES = 90000000      # a Cloudflare recusa pedidos de 100 MB ou mais
SPEED_STREAMS = 6


def curl_bin():
    if IS_WIN:
        return shutil.which("curl")       # curl.exe vem com o Windows 10+
    return "/usr/bin/curl" if os.path.exists("/usr/bin/curl") else shutil.which("curl")


def parse_curl_rate(text):
    """Saída de -w '%{size_*} %{time_total}' -> (bytes, segundos)."""
    parts = (text or "").strip().split()
    try:
        return int(float(parts[0])), float(parts[1].replace(",", "."))
    except (IndexError, ValueError):
        return 0, 0.0


def ping_stats(samples):
    """Latências (ms) -> (mediana, jitter = média das variações entre medições seguidas)."""
    if not samples:
        return None, None
    ordered = sorted(samples)
    median = ordered[len(ordered) // 2]
    jitter = sum(abs(a - b) for a, b in zip(samples, samples[1:])) / (len(samples) - 1) if len(samples) > 1 else 0.0
    return median, jitter


def measure_ping(count=10):
    addr = socket.getaddrinfo(SPEED_HOST, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4]
    samples = []
    for _ in range(count):
        t = time.time()
        try:
            socket.create_connection(addr, 3).close()
            samples.append((time.time() - t) * 1000)
        except OSError:
            pass
        time.sleep(0.05)
    return ping_stats(samples)


def measure_throughput(direction, seconds, streams=SPEED_STREAMS):
    """Mbps somando conexões paralelas; cada uma vale bytes/tempo dela (mesmo se terminar antes)."""
    curl = curl_bin()
    if not curl:
        raise RuntimeError("curl not found")
    kw = {"creationflags": 0x08000000} if IS_WIN else {}
    cmd = [curl, "-q", "-s", "-o", os.devnull, "--connect-timeout", "5", "--max-time", str(seconds)]
    if direction == "down":
        cmd += ["-w", "%{size_download} %{time_total}", "https://%s/__down?bytes=%d" % (SPEED_HOST, SPEED_DOWN_BYTES)]
        procs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **kw) for _ in range(streams)]
    else:
        # upload contínuo pelo stdin: nada de arquivo grande no disco
        cmd += ["-X", "POST", "-T", "-", "-H", "Content-Type: application/octet-stream",
                "-w", "%{size_upload} %{time_total}", "https://%s/__up" % SPEED_HOST]
        procs = [subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **kw)
                 for _ in range(streams)]

        def feed(proc):
            chunk = b"\0" * 65536
            try:
                while proc.poll() is None:
                    proc.stdin.write(chunk)
            except (OSError, ValueError):
                pass                           # o curl terminou (tempo esgotado): pipe fechado

        for proc in procs:
            threading.Thread(target=feed, args=(proc,), daemon=True).start()
    bits_per_second = 0.0
    for proc in procs:
        try:
            proc.wait(timeout=seconds + 15)
        except subprocess.TimeoutExpired:
            proc.kill()
        size, took = parse_curl_rate(proc.stdout.read().decode("ascii", "replace"))
        if took > 0:
            bits_per_second += size * 8 / took
    return bits_per_second / 1e6


def run_speedtest(cfg):
    result = {"ts": time.time(), "down": None, "up": None, "ping": None, "jitter": None, "error": None}
    try:
        result["ping"], result["jitter"] = measure_ping()
        seconds = max(2, int(cfg["speedtest_seconds"]))
        result["down"] = measure_throughput("down", seconds) or None
        result["up"] = measure_throughput("up", seconds) or None
        if result["down"] is None:
            result["error"] = "no data"
    except Exception as e:   # rede fora, curl ausente, DNS…: fica registrado como teste com falha
        result["error"] = str(e) or e.__class__.__name__
    return result


class SpeedTester:
    """Roda o teste a cada speedtest_minutes (e sob demanda), com a detecção de quedas pausada."""

    def __init__(self, cfg, monitor):
        self.cfg, self.monitor = cfg, monitor
        self.wake = threading.Event()
        self.running = False
        self.manual = False
        self.next_ts = None

    @property
    def period(self):
        return max(0, float(self.cfg.get("speedtest_minutes") or 0)) * 60

    def trigger(self):
        if self.running:
            return False
        self.manual = True
        self.wake.set()
        return True

    def reschedule(self):
        """Frequência mudou pelo painel: o próximo teste conta a partir do último."""
        db = connect()
        try:
            last = db.execute("SELECT MAX(ts) FROM speedtests").fetchone()[0] or 0
        finally:
            db.close()
        self.next_ts = max(time.time() + 60, last + self.period) if self.period else None
        self.wake.set()

    def status(self):
        db = connect()
        try:
            row = db.execute("SELECT ts, down_mbps, up_mbps, ping_ms, jitter_ms, error FROM speedtests "
                             "ORDER BY ts DESC LIMIT 1").fetchone()
        finally:
            db.close()
        last = dict(zip(("ts", "down", "up", "ping", "jitter", "error"), row)) if row else None
        return {"running": self.running, "next": self.next_ts, "enabled": self.period > 0, "last": last}

    def run(self):
        db = connect()
        last = db.execute("SELECT MAX(ts) FROM speedtests").fetchone()[0] or 0
        # primeiro teste uns minutos depois de ligar, para não competir com a inicialização
        self.next_ts = max(time.time() + 120, last + self.period) if self.period else None
        while True:
            self.wake.wait(max(1, self.next_ts - time.time()) if self.next_ts else None)
            self.wake.clear()
            manual, self.manual = self.manual, False
            if not manual and (not self.next_ts or time.time() < self.next_ts):
                continue
            st = self.monitor.get_status()
            if st["state"] != "up" or st["pending"]:
                # sem internet o teste não diz nada: tenta de novo daqui a 5 minutos
                if not manual:
                    self.next_ts = time.time() + 300
                continue
            self.running = True
            self.monitor.paused = True             # o teste satura a conexão: não é queda
            try:
                r = run_speedtest(self.cfg)
            finally:
                self.monitor.paused = False
                self.running = False
            db.execute("INSERT INTO speedtests(ts, down_mbps, up_mbps, ping_ms, jitter_ms, error, manual) "
                       "VALUES(?,?,?,?,?,?,?)", (r["ts"], r["down"], r["up"], r["ping"], r["jitter"], r["error"], int(manual)))
            db.commit()
            if r["error"]:
                log(tr("log.speed_failed", err=r["error"]))
            else:
                log(tr("log.speed", down="%.0f" % r["down"], up="%.0f" % (r["up"] or 0), ping="%.0f" % (r["ping"] or 0)))
            self.next_ts = time.time() + self.period if self.period else None


SPEED_CHOICES = (0, 60, 120, 240, 360, 720, 1440)     # minutos entre testes de velocidade


def parse_settings(body):
    """Ajustes enviados pelo painel. Só estas chaves, com valores conferidos; o resto do
    config.json (tópico e servidor do ntfy, rede) continua só no arquivo."""
    data = json.loads(body.decode("utf-8") or "{}")
    if not isinstance(data, dict) or not data:
        raise ValueError("empty")
    out = {}
    for key, value in data.items():
        if key in ("plan_down_mbps", "plan_up_mbps"):
            v = float(value or 0)
            if not 0 <= v <= 100000:
                raise ValueError(key)
            out[key] = round(v, 1)
        elif key in ("speedtest_minutes", "daily_summary_hour", "notify_min_seconds"):
            if isinstance(value, bool) or int(value) != value:
                raise ValueError(key)
            v = int(value)
            ok = {"speedtest_minutes": v in SPEED_CHOICES, "daily_summary_hour": -1 <= v <= 23,
                  "notify_min_seconds": 0 <= v <= 86400}[key]
            if not ok:
                raise ValueError(key)
            out[key] = v
        elif key == "language":
            if value not in ("auto",) + tuple(TEXTS):
                raise ValueError(key)
            out[key] = value
        else:
            raise ValueError("unknown setting")
    return out


def save_config(cfg):
    """Grava o config.json de forma atômica, mantendo só o dono com acesso."""
    tmp = CONFIG_PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


# --------------------------------------------------------------------------
# instabilidade: perda de pacotes ou latência alta sem a internet cair de vez

class Stability:
    """Janela deslizante dos últimos testes. Vídeo travando e chamada picotando aparecem aqui:
    testes que falham sozinhos (sem virar queda) ou bem mais lentos que o normal desta conexão."""
    WINDOW = 12          # ~1 min com testes a cada 5 s
    OPEN_AT = 4          # testes ruins na janela para começar
    CLOSE_AT = 1         # no máximo isso na janela para terminar
    MIN_SLOW_MS = 150    # abaixo disso nunca conta como lento

    def __init__(self):
        self.win = collections.deque(maxlen=self.WINDOW)
        self.normal = collections.deque(maxlen=720)      # latências normais da última ~1 h
        self.baseline = None
        self.episode = None
        self.fed = 0

    def limit(self):
        """Lento = 3x a mediana habitual (mínimo 150 ms). Sem histórico ainda: 300 ms."""
        return max(self.MIN_SLOW_MS, 3 * self.baseline) if self.baseline else 2 * self.MIN_SLOW_MS

    def reset(self):
        self.win.clear()

    def feed(self, ts, state, net_ms):
        """Registra um teste fora de queda. Devolve "open", "close" ou None."""
        lost = state != "ok"
        slow = not lost and net_ms is not None and net_ms > self.limit()
        if not (lost or slow) and net_ms is not None and not self.episode:
            self.normal.append(net_ms)
            self.fed += 1
            if self.fed % self.WINDOW == 0 and len(self.normal) >= 2 * self.WINDOW:
                ordered = sorted(self.normal)
                self.baseline = ordered[len(ordered) // 2]
        self.win.append((ts, lost, slow, None if lost else net_ms))
        bad = sum(1 for _, l, sl, _ in self.win if l or sl)
        ep = self.episode
        if ep:
            ep["n"] += 1
            ep["loss"] += lost
            ep["slow"] += slow
            if not lost and net_ms is not None:
                ep["max_ms"] = max(ep["max_ms"] or 0, net_ms)
            if lost or slow:
                ep["last_bad"] = ts
            return "close" if bad <= self.CLOSE_AT else None
        if bad < self.OPEN_AT:
            return None
        first = next(t for t, l, sl, _ in self.win if l or sl)
        part = [x for x in self.win if x[0] >= first]
        self.episode = {"start": first, "last_bad": ts, "n": len(part), "loss": sum(1 for x in part if x[1]),
                        "slow": sum(1 for x in part if x[2]),
                        "max_ms": max((x[3] for x in part if x[3] is not None), default=None),
                        "limit_ms": round(self.limit())}
        return "open"


PUBLIC_IP_URL = "https://1.1.1.1/cdn-cgi/trace"     # só IPv4; responde várias linhas, entre elas "ip=..."


def parse_trace(text):
    for line in (text or "").splitlines():
        if line.startswith("ip="):
            ip = line[3:].strip()
            return ip if is_ip(ip) else None
    return None


def fetch_public_ip(timeout=8):
    curl = curl_bin()
    if curl:
        code, out = run_cmd([curl, "-q", "-sS", "-m", str(timeout), PUBLIC_IP_URL], timeout=timeout + 2)
        return parse_trace(out) if code == 0 else None
    try:
        req = Request(PUBLIC_IP_URL, headers={"User-Agent": "down-again"})
        return parse_trace(urlopen(req, timeout=timeout).read(2048).decode("ascii", "replace"))
    except Exception:
        return None


class PublicIP:
    """IP público a cada 10 min e logo depois de cada queda. Trocar de IP quer dizer que a sessão
    com o provedor foi refeita: depois de uma queda local, o roteador provavelmente reiniciou;
    sem queda nenhuma, foi uma reconexão rápida demais para o monitor ver (menos de ~10 s)."""
    PERIOD = 600
    AFTER_OUTAGE = 20

    def __init__(self, monitor):
        self.monitor = monitor
        self.wake = threading.Event()
        self.soon = False
        self.ip = self.since = self.checked = None

    def poke(self):
        self.soon = True
        self.wake.set()

    def status(self):
        return {"ip": self.ip, "since": self.since, "checked": self.checked} if self.ip else None

    def check(self, db, ip, now):
        last_ok = float(meta_get(db, "public_ip_checked", 0) or 0)
        if self.ip and ip != self.ip:
            self.changed(db, self.ip, ip, last_ok, now)
            self.since = now
        elif not self.ip:
            self.since = now
        self.ip, self.checked = ip, now
        meta_set(db, "public_ip", ip)
        meta_set(db, "public_ip_since", self.since)
        meta_set(db, "public_ip_checked", now)
        db.commit()

    def changed(self, db, old, new, last_ok, now):
        data = {"old": old, "new": new}
        # queda que terminou depois da última leitura: a troca veio com ela
        row = db.execute("SELECT id, cause FROM outages WHERE end_ts >= ? ORDER BY end_ts DESC LIMIT 1",
                         (last_ok,)).fetchone() if last_ok else None
        if row:
            hint = "router_restart" if row[1] in ("local", "unknown") else "reconnect"
            db.execute("UPDATE outages SET hint=? WHERE id=?", (hint, row[0]))
            data.update(outage=row[0], hint=hint)
        elif not last_ok or now - last_ok > 2 * self.PERIOD:
            data["late"] = True          # muito tempo sem ler (monitor parado): não dá para saber quando
        else:
            data["silent"] = True
        db.execute("INSERT INTO events(kind, start_ts, end_ts, data) VALUES('ip_change', ?, ?, ?)",
                   (last_ok or now, now, json.dumps(data)))
        log(tr("log.ip_change", old=old, new=new))

    def run(self):
        db = connect()
        self.ip = meta_get(db, "public_ip")
        self.since = float(meta_get(db, "public_ip_since", 0) or 0) or None
        time.sleep(15)                      # deixa os primeiros testes de conexão acontecerem
        while True:
            if self.monitor.get_status()["state"] == "up" and not self.monitor.paused:
                ip = fetch_public_ip()
                if ip:
                    try:
                        self.check(db, ip, time.time())
                    except sqlite3.Error as e:
                        log(tr("log.db_error", err=repr(e)))
            if self.wake.wait(self.PERIOD):
                self.wake.clear()
                if self.soon:
                    self.soon = False
                    time.sleep(self.AFTER_OUTAGE)   # dá tempo do roteador refazer a sessão


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
        self.paused = False                       # True durante o teste de velocidade
        self.stab = Stability()
        self.last_unstable = None                 # último episódio fechado (junta os muito próximos)
        self.on_back = None                       # chamado quando uma queda termina (confere o IP público)
        self.db = connect()

        now = time.time()
        last = self.db.execute("SELECT MAX(end_ts) FROM sessions").fetchone()[0]
        # Queda que ficou aberta porque o processo morreu no meio dela.
        self.db.execute("UPDATE outages SET end_ts = COALESCE((SELECT MAX(ts) FROM samples "
                        "WHERE ts >= outages.start_ts), start_ts), ended_by = 'monitor parado' "
                        "WHERE end_ts IS NULL")
        self.db.execute("UPDATE events SET end_ts = COALESCE((SELECT MAX(ts) FROM samples "
                        "WHERE ts >= events.start_ts), start_ts) WHERE end_ts IS NULL")
        self.session_id = self.db.execute("INSERT INTO sessions(start_ts, end_ts) VALUES(?,?)",
                                          (now, now)).lastrowid
        self.db.commit()
        if last and now - last >= cfg["notify_monitor_gap_minutes"] * 60:
            self._notify_gap(last, now)
        # "sem quedas há X" continua contando da última queda registrada, mesmo após reiniciar
        last_out = self.db.execute("SELECT MAX(end_ts) FROM outages").fetchone()[0]
        self.status = {"state": "starting", "since": last_out or now, "since_start": not last_out, "started": now,
                       "last": None, "probe": None, "outage": None, "pending": 0, "unstable": None}

    def get_status(self):
        with self.lock:
            return json.loads(json.dumps(self.status))

    def run(self):
        while True:
            if self.paused:
                # teste de velocidade em andamento: a conexão está saturada de propósito.
                # Conta como monitorado (não vira "não monitorado" nem queda).
                if self.last_ts is not None:
                    self.last_ts = time.time()
                self.stab.reset()                 # latência durante o teste não é instabilidade
                time.sleep(1)
                continue
            t0 = time.time()
            try:
                self.step()
            except sqlite3.Error as e:
                log(tr("log.db_error", err=repr(e)))
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

        if self.outage is None:
            ev = self.stab.feed(ts, state, p["net_ms"])
            if ev == "open":
                self._unstable_open()
            elif ev == "close":
                self._unstable_close(self.stab.episode["last_bad"])

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
        if self.outage:
            # virou queda: a instabilidade termina onde a queda começa
            if self.stab.episode:
                self._unstable_close(min(self.stab.episode["last_bad"], self.outage["start"]))
            self.stab.reset()
            self.last_unstable = None

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
            ep = self.stab.episode
            st["unstable"] = {k: ep[k] for k in ("start", "n", "loss", "slow", "max_ms")} if ep else None
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
        log(tr("log.outage", since=fmt_ts(start, "%H:%M:%S"), cause=cause_label(state)))

    def _close(self, ts, ended_by, notify=True):
        o, self.outage = self.outage, None
        cause = max(o["counts"], key=o["counts"].get)
        dur = ts - o["start"]
        self.db.execute("UPDATE outages SET end_ts=?, cause=?, ended_by=? WHERE id=?",
                        (ts, cause, ended_by, o["id"]))
        with self.lock:
            self.status.update(since=ts, since_start=False)
        log(tr("log.back", dur=fmt_dur(dur), cause=cause_label(cause)))
        if self.on_back and ended_by == "voltou":
            self.on_back()
        if notify and dur >= self.cfg["notify_min_seconds"]:
            today = self.db.execute("SELECT COUNT(*) FROM outages WHERE start_ts >= ?",
                                    (midnight(ts),)).fetchone()[0]
            self.notifier.queue(
                tr("notify.back.title"),
                tr("notify.back.body", start=fmt_ts(o["start"], "%H:%M:%S"), end=fmt_ts(ts, "%H:%M:%S"),
                   dur=fmt_dur(dur), cause=cause_label(cause), today=today),
                "green_circle", db=self.db)

    def _unstable_open(self):
        ep, prev = self.stab.episode, self.last_unstable
        if prev and ep["start"] - prev["end"] < 120:
            # voltou a ficar instável logo depois: é o mesmo episódio
            ep["id"], ep["start"] = prev["id"], prev["start"]
            for k in ("n", "loss", "slow"):
                ep[k] += prev[k]
            ep["max_ms"] = max([v for v in (ep["max_ms"], prev["max_ms"]) if v is not None], default=None)
            self.db.execute("UPDATE events SET end_ts=NULL WHERE id=?", (ep["id"],))
            return
        ep["id"] = self.db.execute("INSERT INTO events(kind, start_ts) VALUES('unstable', ?)",
                                   (ep["start"],)).lastrowid
        log(tr("log.unstable", since=fmt_ts(ep["start"], "%H:%M:%S")))

    def _unstable_close(self, end):
        ep, self.stab.episode = self.stab.episode, None
        if end <= ep["start"]:
            # eram só as primeiras falhas da queda que veio em seguida
            self.db.execute("DELETE FROM events WHERE id=?", (ep["id"],))
            self.last_unstable = None
            return
        data = {k: ep[k] for k in ("n", "loss", "slow", "max_ms", "limit_ms")}
        self.db.execute("UPDATE events SET end_ts=?, data=? WHERE id=?", (end, json.dumps(data), ep["id"]))
        self.last_unstable = dict(ep, end=end)
        log(tr("log.unstable_end", dur=fmt_dur(end - ep["start"]), loss=ep["loss"], slow=ep["slow"]))

    def _end_unstable(self, at):
        if self.stab.episode:
            self._unstable_close(min(self.stab.episode["last_bad"], at))
        self.stab.reset()
        self.last_unstable = None

    def _gap(self, a, b):
        self.db.execute("INSERT INTO gaps VALUES(?,?)", (a, b))
        self.pending = []
        self._end_unstable(a)
        if self.outage:
            self._close(a, "monitor parado", notify=False)
        with self.lock:
            self.status.update(since=b, since_start=True)
        log(tr("log.gap", dur=fmt_dur(b - a)))
        if b - a >= self.cfg["notify_monitor_gap_minutes"] * 60:
            self._notify_gap(a, b)

    def _notify_gap(self, a, b):
        self.notifier.queue(
            tr("notify.gap.title"),
            tr("notify.gap.body", a=fmt_ts(a, "%d/%m %H:%M"), b=fmt_ts(b, "%d/%m %H:%M"), dur=fmt_dur(b - a)),
            "warning", db=self.db)

    def stop(self):
        if self.outage and self.last_ts:
            self._close(self.last_ts, "monitor parado", notify=False)
        if self.last_ts:
            self._end_unstable(self.last_ts)
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


def load_events(db, t0, t1, now, latest=None):
    """Eventos do período (ou os `latest` mais recentes), do mais antigo ao mais novo."""
    if latest:
        rows = db.execute("SELECT kind, start_ts, end_ts, data FROM events ORDER BY start_ts DESC LIMIT ?",
                          (latest,)).fetchall()[::-1]
    else:
        rows = db.execute("SELECT kind, start_ts, end_ts, data FROM events WHERE COALESCE(end_ts, ?) > ? AND start_ts < ? "
                          "ORDER BY start_ts", (now, t0, t1)).fetchall()
    out = []
    for kind, a, b, data in rows:
        end = b if b is not None else now
        out.append({"kind": kind, "start": a, "end": end, "dur": end - a, "ongoing": b is None,
                    "data": json.loads(data) if data else {}})
    return out


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
        rows = db.execute("SELECT start_ts, end_ts, cause, ended_by, network, hint FROM outages "
                          "WHERE COALESCE(end_ts, ?) > ? AND start_ts < ? ORDER BY start_ts",
                          (now, t0, t1)).fetchall()
        outages = []
        for s, e, c, how, net, hint in rows:
            e_ = e if e is not None else now
            rssi = db.execute("SELECT AVG(rssi) FROM samples WHERE ts >= ? AND ts <= ? AND rssi IS NOT NULL",
                              (s - 60, e_)).fetchone()[0]
            outages.append({"start": s, "end": e_, "dur": e_ - s, "cause": c or "unknown", "ended_by": how,
                            "ongoing": e is None, "network": net, "rssi": rssi, "hint": hint})
        events = load_events(db, t0, t1, now)
        uns = clip([(x["start"], x["end"]) for x in events if x["kind"] == "unstable"], t0, t1)
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
                         "unstable": sum(1 for x in events if x["kind"] == "unstable" and ds <= x["start"] < de),
                         "mon": clip(mon, ds, de), "out": clip(clipped, ds, de), "uns": clip(uns, ds, de)})
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
            "events": events,
            "unstable": {"count": sum(1 for x in events if x["kind"] == "unstable"), "dur_s": sum(b - a for a, b in uns)},
            "ip_changes": sum(1 for x in events if x["kind"] == "ip_change" and t0 <= x["end"] < t1),
        }
    finally:
        db.close()


def glance():
    """Topo da aba Agora: a faixa das últimas 24h corridas (monitorado, quedas e instabilidade)
    e os acontecimentos recentes."""
    now = time.time()
    t0 = now - 86400
    db = connect()
    try:
        sessions = db.execute("SELECT start_ts, end_ts FROM sessions WHERE end_ts > ?", (t0,)).fetchall()
        gaps = db.execute("SELECT start_ts, end_ts FROM gaps WHERE end_ts > ?", (t0,)).fetchall()
        rows = db.execute("SELECT start_ts, COALESCE(end_ts, ?), cause FROM outages WHERE COALESCE(end_ts, ?) > ?",
                          (now, now, t0)).fetchall()
        uns = db.execute("SELECT start_ts, COALESCE(end_ts, ?) FROM events WHERE kind='unstable' AND COALESCE(end_ts, ?) > ?",
                         (now, now, t0)).fetchall()
        last = db.execute("SELECT start_ts, end_ts, cause FROM outages ORDER BY start_ts DESC LIMIT 1").fetchone()
        first = db.execute("SELECT MIN(start_ts) FROM sessions").fetchone()[0]
        # acontecimentos recentes: quedas, instabilidade e trocas de IP (a troca ligada a uma queda
        # aparece como detalhe dela)
        recent = [{"kind": "outage", "start": s, "end": e if e is not None else now, "dur": (e if e is not None else now) - s,
                   "ongoing": e is None, "cause": c or "unknown", "hint": h}
                  for s, e, c, h in db.execute("SELECT start_ts, end_ts, cause, hint FROM outages "
                                               "ORDER BY start_ts DESC LIMIT 8")]
        recent += [x for x in load_events(db, 0, 0, now, latest=24)
                   if not (x["kind"] == "ip_change" and x["data"].get("outage"))]
        recent.sort(key=lambda x: x["end"] if x["kind"] == "ip_change" else x["start"], reverse=True)
    finally:
        db.close()
    out = clip([(a, b, c or "unknown") for a, b, c in rows], t0, now)
    return {"now": now, "since": first, "from": t0,
            "h24": {"count": len(rows), "down_s": sum(b - a for a, b, _ in out),
                    "isp": sum(1 for _, _, c in rows if c == "isp"), "unstable": len(uns)},
            "mon": clip(subtract(sessions, gaps), t0, now), "out": out, "uns": clip(uns, t0, now),
            "recent": recent[:8],
            "last": {"start": last[0], "end": last[1] if last[1] is not None else now, "cause": last[2] or "unknown",
                     "ongoing": last[1] is None} if last else None}


def speed_stats(t0, t1, cfg):
    """Testes de velocidade do período, médias e comparação com o plano contratado."""
    db = connect()
    try:
        rows = db.execute("SELECT ts, down_mbps, up_mbps, ping_ms, jitter_ms, error FROM speedtests "
                          "WHERE ts >= ? AND ts < ? ORDER BY ts", (t0, t1)).fetchall()
    finally:
        db.close()
    tests = [dict(zip(("ts", "down", "up", "ping", "jitter", "error"), r)) for r in rows]
    ok = [x for x in tests if not x["error"] and x["down"]]
    plan_down, plan_up = float(cfg.get("plan_down_mbps") or 0), float(cfg.get("plan_up_mbps") or 0)

    def agg(key):
        values = [x[key] for x in ok if x[key] is not None]
        return {"avg": sum(values) / len(values), "min": min(values), "max": max(values)} if values else None

    return {
        "tests": tests, "count": len(ok), "failed": len(tests) - len(ok),
        "down": agg("down"), "up": agg("up"), "ping": agg("ping"),
        "plan": {"down": plan_down, "up": plan_up},
        # referência usual: 40% do contratado no instantâneo, 80% na média
        "below40": sum(1 for x in ok if plan_down and x["down"] < 0.4 * plan_down),
        "minutes": cfg.get("speedtest_minutes"), "seconds": cfg.get("speedtest_seconds"),
        "streams": SPEED_STREAMS, "server": SPEED_HOST,
    }


def fmt_pct(x, lang=None, n=2):
    if x is None:
        return "—"
    text = "100" if x >= 0.99995 and n >= 2 else "%.*f" % (n, x * 100)
    return (text.replace(".", ",") if (lang or LANG) == "pt" else text) + "%"


def daily_summary(day, cfg, lang=None):
    """(título, texto) do aviso da manhã sobre o dia que começa em `day`; None se mal foi monitorado."""
    t0, t1 = day.timestamp(), (day + timedelta(days=1)).timestamp()
    s = summarize(t0, t1)
    if s["mon_s"] < 3600:
        return None
    sp = speed_stats(t0, t1, cfg)
    if not s["count"]:
        title = tr("daily.title.none", lang)
    elif s["count"] == 1:
        title = tr("daily.title.one", lang, d=fmt_dur(s["down_s"], lang))
    else:
        title = tr("daily.title", lang, n=s["count"], d=fmt_dur(s["down_s"], lang))
    lines = [tr("daily.avail", lang, p=fmt_pct(s["avail"], lang), mon=fmt_dur(s["mon_s"], lang))]
    if s["count"]:
        isp = s["causes"].get("isp", {"count": 0})["count"]
        lines.append(tr("daily.outages", lang, isp=isp, d=fmt_dur(s["longest"]["dur"], lang)))
    if s["unstable"]["count"]:
        lines.append(tr("daily.unstable", lang, n=s["unstable"]["count"], d=fmt_dur(s["unstable"]["dur_s"], lang)))
    if sp["count"]:
        line = tr("daily.speed", lang, down="%.0f" % sp["down"]["avg"], up="%.0f" % (sp["up"]["avg"] if sp["up"] else 0))
        if sp["plan"]["down"]:
            line += tr("daily.speed_plan", lang, p=fmt_pct(sp["down"]["avg"] / sp["plan"]["down"], lang, 0))
        lines.append(line)
    if s["ip_changes"]:
        lines.append(tr("daily.ip", lang, n=s["ip_changes"]))
    lines.append(tr("daily.footer", lang))
    return title, "\n".join(lines)


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


def outages_csv(s, lang=None):
    lang = lang or LANG
    out = io.StringIO()
    # Excel em português usa ';' e dia/mês; nos outros idiomas, ',' e data ISO. O csv.writer põe aspas
    # sozinho: um separador no nome do Wi-Fi não quebra as colunas.
    w = csv.writer(out, delimiter=";" if lang == "pt" else ",")
    stamp = "%d/%m/%Y %H:%M:%S" if lang == "pt" else "%Y-%m-%d %H:%M:%S"
    w.writerow([tr("csv." + k, lang) for k in ("start", "end", "dur_s", "dur", "cause", "network", "note")])
    for o in s["outages"]:
        if o["ongoing"]:
            note = tr("csv.ongoing", lang)
        elif o["ended_by"] == "monitor parado":
            note = tr("csv.stopped", lang)
        else:
            note = "" if o["ended_by"] in ("voltou", None) else o["ended_by"]
        if o.get("hint"):
            note = "; ".join(x for x in (note, tr("hint." + o["hint"], lang)) if x)
        w.writerow([fmt_ts(o["start"], stamp), fmt_ts(o["end"], stamp), "%d" % round(o["dur"]),
                    fmt_dur(o["dur"], lang), cause_label(o["cause"], lang), o["network"] or "", note])
    return "\ufeff" + out.getvalue()   # BOM: o Excel abre como UTF-8


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
    "/i18n.js": ("i18n.js", "application/javascript; charset=utf-8"),
    "/qr.js": ("qr.js", "application/javascript; charset=utf-8"),
    # app na tela de início do celular
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/icon-180.png": ("icon-180.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/icon-maskable-512.png": ("icon-maskable-512.png", "image/png"),
    # fonte do painel (licença OFL em static/fonts/OFL.txt), servida daqui: funciona com a internet fora
    "/fonts/plus-jakarta-sans.woff2": ("fonts/plus-jakarta-sans.woff2", "font/woff2"),
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
    last_speed = 0
    speed = None                 # SpeedTester (preenchido em cmd_run)
    pubip = None                 # PublicIP (preenchido em cmd_run)
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
        self.send(403, tr("http.host"), "text/plain; charset=utf-8")
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
                st["speed"] = self.speed.status() if self.speed else None
                st["public_ip"] = self.pubip.status() if self.pubip else None
                return self.json(st)
            if u.path == "/api/speedtests":
                return self.json(speed_stats(*(parse_range(q) + (self.cfg,))))
            if u.path == "/api/summary":
                return self.json(summarize(*parse_range(q)))
            if u.path == "/api/glance":
                return self.json(glance())
            if u.path == "/api/timeseries":
                return self.json(timeseries(min(168.0, max(0.25, float(q.get("hours", ["6"])[0])))))
            if u.path == "/api/outages.csv":
                t0, t1 = parse_range(q)
                lang = self.req_lang(q)
                name = "%s_%s_%s.csv" % (tr("csv.file", lang), fmt_ts(t0, "%Y-%m-%d"), fmt_ts(t1 - 1, "%Y-%m-%d"))
                return self.send(200, outages_csv(summarize(t0, t1), lang), "text/csv; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="%s"' % name})
            if u.path == "/api/config":
                return self.json({
                    "interval": self.cfg["interval"], "timeout": self.cfg["timeout"],
                    "fail_threshold": self.cfg["fail_threshold"],
                    "tcp_targets": ["%s:%d" % t for t in TCP_TARGETS], "http_url": HTTP_URL,
                    "ntfy_server": self.cfg["ntfy_server"], "ntfy_topic": self.cfg["ntfy_topic"],
                    "host": self.info.get("host"), "ip": self.info.get("ip"), "port": self.cfg["port"],
                    "platform": PLATFORM, "language": LANG,
                    "speedtest_minutes": self.cfg["speedtest_minutes"], "speedtest_seconds": self.cfg["speedtest_seconds"],
                    "plan_down_mbps": self.cfg["plan_down_mbps"], "plan_up_mbps": self.cfg["plan_up_mbps"],
                    "unstable": {"window": Stability.WINDOW, "open": Stability.OPEN_AT, "min_slow_ms": Stability.MIN_SLOW_MS},
                    "speed_choices": SPEED_CHOICES, "daily_summary_hour": self.cfg["daily_summary_hour"],
                    "notify_min_seconds": self.cfg["notify_min_seconds"], "language_setting": self.cfg["language"],
                    "notify": self.notifier.stats() if self.notifier.enabled else None,
                })
        except (ValueError, OverflowError, OSError):
            return self.json({"error": "invalid period (use YYYY-MM-DD, up to %d days)" % MAX_RANGE_DAYS}, 400)
        self.static(u.path)

    def do_POST(self):
        if not self.check_host():
            return
        u = urlparse(self.path)
        if u.path not in ("/api/test-notify", "/api/speedtest", "/api/settings"):
            return self.send(404, "not found", "text/plain; charset=utf-8")
        # Cabeçalho próprio força preflight de CORS (que não respondemos): outro site não consegue disparar.
        # As respostas trazem um código; o painel mostra a mensagem no idioma de quem está vendo.
        if self.headers.get("X-Down-Again") != "1":
            return self.json({"ok": False, "code": "refused"}, 403)
        if u.path == "/api/speedtest":
            return self.post_speedtest()
        if u.path == "/api/settings":
            return self.post_settings()
        with Handler.test_lock:
            wait = 30 - (time.time() - Handler.last_test)
            if wait > 0:
                return self.json({"ok": False, "code": "cooldown", "wait": int(wait) + 1}, 429)
            Handler.last_test = time.time()
        if not self.notifier.enabled:
            return self.json({"ok": False, "code": "disabled"})
        lang = self.req_lang(parse_qs(u.query))
        ok, err = self.notifier.send(tr("notify.test.title", lang), tr("notify.test.body", lang), ["white_check_mark"])
        return self.json({"ok": ok, "code": None if ok else "send_failed", "error": err})

    def post_speedtest(self):
        if not self.speed:
            return self.json({"ok": False, "code": "disabled"})
        with Handler.test_lock:
            wait = 60 - (time.time() - Handler.last_speed)
            if wait > 0:
                return self.json({"ok": False, "code": "cooldown", "wait": int(wait) + 1}, 429)
            if self.monitor.get_status()["state"] != "up":
                return self.json({"ok": False, "code": "offline"})
            if not self.speed.trigger():
                return self.json({"ok": False, "code": "running"})
            Handler.last_speed = time.time()
        return self.json({"ok": True})

    def post_settings(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 2048:
                raise ValueError("bad length")
            changes = parse_settings(self.rfile.read(length))
        except (ValueError, TypeError, AttributeError, OverflowError):
            return self.json({"ok": False, "code": "invalid"}, 400)
        with Handler.test_lock:
            self.cfg.update(changes)
            save_config(self.cfg)
        if "language" in changes:
            set_language(self.cfg)
        if "speedtest_minutes" in changes and self.speed:
            self.speed.reschedule()
        return self.json({"ok": True, "settings": changes})

    def req_lang(self, q):
        lang = q.get("lang", [""])[0]
        return lang if lang in TEXTS else LANG

    def static(self, path):
        if path not in STATIC_FILES:
            return self.send(404, "not found", "text/plain; charset=utf-8")
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
    Handler.speed = SpeedTester(cfg, monitor)
    threading.Thread(target=Handler.speed.run, daemon=True).start()
    Handler.pubip = PublicIP(monitor)
    monitor.on_back = Handler.pubip.poke
    threading.Thread(target=Handler.pubip.run, daemon=True).start()

    log(tr("log.started", os=PLATFORM, n=cfg["interval"]))
    if not IS_MAC:
        log(tr("log.experimental", os=PLATFORM))
    log(tr("log.panel", url="http://localhost:%d" % cfg["port"]))
    for addr in (host, ip):
        if addr:
            log(tr("log.panel", url="http://%s:%d" % (addr, cfg["port"])))
    if notifier.enabled:
        log(tr("log.subscribe", topic=cfg["ntfy_topic"]))

    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    try:
        monitor.run()
    except (KeyboardInterrupt, SystemExit):
        monitor.stop()
        log(tr("log.stopped"))


def cmd_check(cfg):
    p = probe(cfg["timeout"])
    state = classify(p, p["gw_ms"] is not None)
    ms = lambda v: "%.0f ms" % v if v is not None else tr("check.no_reply")
    net = network_info()
    rows = [(tr("check.system"), PLATFORM + ("" if IS_MAC else " (%s)" % tr("check.experimental"))),
            (tr("check.network"), network_label(net))]
    if net.get("rssi") is not None:
        rows.append(("  " + tr("check.signal"), "%.0f dBm  (%s)" % (net["rssi"], tr("check.channel", channel=net["channel"],
                                                                                   rate=net["tx_rate"]))))
    rows += [(tr("check.router"), p["gw"] or tr("check.no_gateway")),
             ("  " + tr("check.ping"), ms(p["gw_ms"]) if p["gw"] else "—"),
             (tr("check.internet"), "%s  (%s)" % (ms(p["net_ms"]), ", ".join(h for h, _ in TCP_TARGETS))),
             (tr("check.site"), "%s  (%s)" % (tr("check.ok") if p["http_ok"] else tr("check.failed"), HTTP_URL)),
             (tr("check.diagnosis"), tr("check.conn_ok") if state == "ok" else tr("check.no_internet", cause=cause_label(state)))]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print("%s : %s" % (label.ljust(width), value))
    if p["gw"] and p["gw_ms"] is None and state == "ok":
        print("\n" + tr("check.no_ping_note"))


def print_installed(cfg, how, logs):
    host, ip = local_addresses()
    print(tr("install.done", how=how))
    print(tr("install.panel", url="http://%s:%d" % (host or ip or "localhost", cfg["port"])))
    print(tr("install.log", log=logs))


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
            print(tr("install.protected", folder=protected))
            return
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    for path in (OLD_PLIST_PATH, PLIST_PATH):     # para o antigo (netmon) e a versão anterior antes de subir
        if os.path.exists(path):
            run_cmd(["launchctl", "unload", "-w", path])
    if os.path.exists(OLD_PLIST_PATH):
        os.remove(OLD_PLIST_PATH)
        print(tr("install.old_removed"))
    with open(PLIST_PATH, "w", encoding="utf-8") as f:
        f.write(PLIST.format(label=PLIST_LABEL, python=xml_escape(sys.executable),
                             script=xml_escape(os.path.abspath(__file__)), base=xml_escape(BASE),
                             log=xml_escape(LOG_PATH)))
    code, _ = run_cmd(["launchctl", "load", "-w", PLIST_PATH])
    if code != 0:
        print(tr("install.launchd_failed", path=PLIST_PATH))
        return
    print_installed(cfg, tr("install.how_mac"), LOG_PATH)


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
Description=down-again - internet outage monitor
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
        print(tr("install.no_systemd", cmd="%s %s" % (sys.executable, os.path.abspath(__file__))))
        return
    os.makedirs(os.path.dirname(SYSTEMD_PATH), exist_ok=True)
    with open(SYSTEMD_PATH, "w", encoding="utf-8") as f:
        f.write(UNIT.format(python=systemd_quote(sys.executable), script=systemd_quote(os.path.abspath(__file__)),
                            base=BASE.replace("%", "%%")))
    for args in (["daemon-reload"], ["enable", SYSTEMD_UNIT], ["restart", SYSTEMD_UNIT]):
        code, _ = run_cmd(["systemctl", "--user"] + args, timeout=30)
        if code != 0:
            print(tr("install.systemctl_failed", cmd=" ".join(args)))
            return
    print_installed(cfg, tr("install.how_linux"), "journalctl --user -u %s -f" % SYSTEMD_UNIT)
    print(tr("install.linger", user=os.environ.get("USER", "$USER")))


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
        print(tr("install.path_too_long"))
        return
    run_cmd(["schtasks", "/End", "/TN", TASK_NAME])
    code, _ = run_cmd(["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON", "/TR", command,
                       "/RL", "LIMITED", "/F"], timeout=30)
    if code != 0:
        print(tr("install.task_failed"))
        return
    run_cmd(["schtasks", "/Run", "/TN", TASK_NAME])
    print_installed(cfg, tr("install.how_win"), LOG_PATH)


def uninstall_windows():
    code, _ = run_cmd(["schtasks", "/Query", "/TN", TASK_NAME])
    if code != 0:
        return False
    run_cmd(["schtasks", "/End", "/TN", TASK_NAME])
    run_cmd(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    return True


def cmd_install(cfg):
    if not IS_MAC:
        print(tr("install.experimental", os=PLATFORM))
    if IS_MAC:
        install_mac(cfg)
    elif IS_LINUX:
        install_linux(cfg)
    elif IS_WIN:
        install_windows(cfg)
    else:
        print(tr("install.unsupported", os=PLATFORM))


def cmd_uninstall(cfg):
    removed = {"macOS": uninstall_mac, "Linux": uninstall_linux, "Windows": uninstall_windows}.get(PLATFORM, lambda: False)()
    print(tr("uninstall.done", data=DATA) if removed else tr("uninstall.none"))


def main():
    ap = argparse.ArgumentParser(description="down-again: internet outage monitor with a web dashboard.")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "check", "install", "uninstall"])
    ap.add_argument("--port", type=int, help="dashboard port (default: config.json)")
    args = ap.parse_args()
    # Terminal do Windows (cp1252/cp936…): caractere que não cabe vira '?' em vez de derrubar o programa
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    cfg = load_config()
    if args.port:
        cfg["port"] = args.port
    {"run": cmd_run, "check": cmd_check, "install": cmd_install, "uninstall": cmd_uninstall}[args.cmd](cfg)


if __name__ == "__main__":
    main()
