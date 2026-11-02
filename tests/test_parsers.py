# -*- coding: utf-8 -*-
"""
Testes dos leitores de saída de comandos de cada sistema (macOS, Linux, Windows).

As amostras abaixo reproduzem a saída real dos comandos. É assim que o suporte a Linux e
Windows é verificado sem máquinas reais; ao encontrar uma saída diferente num sistema de
verdade, adicione-a aqui como novo caso.

    python3 -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import down_again as da  # noqa: E402

MAC_ROUTE = """   route to: default
destination: default
       mask: default
    gateway: 192.168.0.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING>
"""

LINUX_ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
wlan0\t00000000\t0100A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0
eth0\t00000000\tFE01A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0
eth0\t0001A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0
"""

WIN_ROUTE_EN = """===========================================================================
Interface List
 12...a4 bb 6d 11 22 33 ......Intel(R) Wi-Fi 6 AX201 160MHz
  1...........................Software Loopback Interface 1
===========================================================================

IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.0.1    192.168.0.56     35
          0.0.0.0          0.0.0.0     192.168.50.1   192.168.50.10     50
===========================================================================
Persistent Routes:
  Network Address          Netmask  Gateway Address  Metric
          0.0.0.0          0.0.0.0    192.168.0.254  Default
===========================================================================
"""

WIN_ROUTE_PT = """Tabela de rotas IPv4
===========================================================================
Rotas ativas:
Destino de rede        Máscara          Gateway       Interface  Métrica
          0.0.0.0          0.0.0.0     192.168.15.1   192.168.15.20     25
===========================================================================
Rotas persistentes:
  Nenhum
"""

WIN_ROUTE_NO_GATEWAY = """Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
"""

MAC_PING = """PING 192.168.0.1 (192.168.0.1): 56 data bytes
64 bytes from 192.168.0.1: icmp_seq=0 ttl=64 time=3.412 ms

--- 192.168.0.1 ping statistics ---
1 packets transmitted, 1 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 3.412/3.412/3.412/0.000 ms
"""

LINUX_PING = """PING 192.168.0.1 (192.168.0.1) 56(84) bytes of data.
64 bytes from 192.168.0.1: icmp_seq=1 ttl=64 time=2.81 ms

--- 192.168.0.1 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 2.810/2.810/2.810/0.000 ms
"""

LINUX_PING_LOST = """PING 192.168.0.1 (192.168.0.1) 56(84) bytes of data.

--- 192.168.0.1 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms
"""

WIN_PING_EN = """Pinging 192.168.0.1 with 32 bytes of data:
Reply from 192.168.0.1: bytes=32 time=4ms TTL=64

Ping statistics for 192.168.0.1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 4ms, Maximum = 4ms, Average = 4ms
"""

WIN_PING_PT_FAST = """Disparando 192.168.0.1 com 32 bytes de dados:
Resposta de 192.168.0.1: bytes=32 tempo<1ms TTL=64
"""

# Windows: "host inacessível" responde com código 0, mas não é resposta do roteador
WIN_PING_UNREACHABLE = """Pinging 192.168.0.1 with 32 bytes of data:
Reply from 192.168.0.56: Destination host unreachable.

Ping statistics for 192.168.0.1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""

WIN_PING_TIMEOUT_PT = """Disparando 192.168.0.1 com 32 bytes de dados:
Esgotado o tempo limite do pedido.

Estatísticas do Ping para 192.168.0.1:
    Pacotes: Enviados = 1, Recebidos = 0, Perdidos = 1 (100% de perda),
"""

IW_LINK = """Connected to aa:bb:cc:dd:ee:ff (on wlan0)
\tSSID: Casa_5G
\tfreq: 5745
\tRX: 1234 bytes (10 packets)
\tTX: 567 bytes (5 packets)
\tsignal: -61 dBm
\trx bitrate: 433.3 MBit/s VHT-MCS 9 80MHz short GI VHT-NSS 1
\ttx bitrate: 390.0 MBit/s VHT-MCS 8 80MHz short GI VHT-NSS 1
"""

NMCLI = """no:Vizinho:40:6:130 Mbit/s
yes:Casa\\:5G:72:149:270 Mbit/s
"""

NETSH_EN = """There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 0b6f2c3a-1111-2222-3333-444455556666
    Physical address       : a4:bb:6d:11:22:33
    Interface type         : Primary
    State                  : connected
    SSID                   : Casa 5G
    AP BSSID               : aa:bb:cc:dd:ee:ff
    Band                   : 5 GHz
    Channel                : 149
    Network type           : Infrastructure
    Radio type             : 802.11ac
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Connection mode        : Auto Connect
    Receive rate (Mbps)    : 866.7
    Transmit rate (Mbps)   : 866.7
    Signal                 : 92%
    Profile                : Casa 5G

    Hosted network status  : Not available
"""

NETSH_PT = """Há 1 interface no sistema:

    Nome                   : Wi-Fi
    Descrição              : Intel(R) Wi-Fi 6 AX201 160MHz
    Estado                 : conectado
    SSID                   : Casa_5G
    BSSID                  : aa:bb:cc:dd:ee:ff
    Tipo de rede           : Infraestrutura
    Canal                  : 36
    Taxa de recepção (Mbps)  : 433,3
    Taxa de transmissão (Mbps) : 433,3
    Sinal                  : 80%
    Perfil                 : Casa_5G
"""

NETSH_DISCONNECTED = """There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : disconnected
    Radio status           : Hardware On
                             Software On
"""


class RouteTests(unittest.TestCase):
    def test_macos(self):
        self.assertEqual(da.parse_route_macos(MAC_ROUTE), ("192.168.0.1", "en0"))
        self.assertEqual(da.parse_route_macos("route: writing to routing socket: not in table"), (None, None))

    def test_linux_picks_lowest_metric(self):
        self.assertEqual(da.parse_route_linux(LINUX_ROUTE), ("192.168.1.254", "eth0"))

    def test_linux_no_default(self):
        self.assertEqual(da.parse_route_linux(LINUX_ROUTE.splitlines()[0] + "\n"), (None, None))

    def test_windows_english_ignores_persistent(self):
        self.assertEqual(da.parse_route_windows(WIN_ROUTE_EN), ("192.168.0.1", "192.168.0.56"))

    def test_windows_portuguese(self):
        self.assertEqual(da.parse_route_windows(WIN_ROUTE_PT), ("192.168.15.1", "192.168.15.20"))

    def test_windows_on_link_only(self):
        self.assertEqual(da.parse_route_windows(WIN_ROUTE_NO_GATEWAY), (None, None))


class PingTests(unittest.TestCase):
    def test_replies(self):
        self.assertEqual(da.parse_ping_ms(MAC_PING), 3.412)
        self.assertEqual(da.parse_ping_ms(LINUX_PING), 2.81)
        self.assertEqual(da.parse_ping_ms(WIN_PING_EN), 4.0)
        self.assertEqual(da.parse_ping_ms(WIN_PING_PT_FAST), 1.0)

    def test_no_reply(self):
        for text in (LINUX_PING_LOST, WIN_PING_UNREACHABLE, WIN_PING_TIMEOUT_PT, ""):
            self.assertIsNone(da.parse_ping_ms(text), text)

    def test_commands(self):
        da_flags = (da.IS_MAC, da.IS_LINUX, da.IS_WIN)
        try:
            da.IS_MAC, da.IS_LINUX, da.IS_WIN = False, False, True
            self.assertEqual(da.ping_cmd("10.0.0.1", 2), ["ping", "-n", "1", "-w", "2000", "10.0.0.1"])
            da.IS_WIN, da.IS_LINUX = False, True
            self.assertEqual(da.ping_cmd("10.0.0.1", 2), ["ping", "-n", "-c", "1", "-W", "2", "10.0.0.1"])
            da.IS_LINUX, da.IS_MAC = False, True
            self.assertEqual(da.ping_cmd("10.0.0.1", 2), ["/sbin/ping", "-n", "-c", "1", "-t", "2", "10.0.0.1"])
        finally:
            da.IS_MAC, da.IS_LINUX, da.IS_WIN = da_flags


class WifiTests(unittest.TestCase):
    def test_iw(self):
        self.assertEqual(da.parse_iw_link(IW_LINK), {"ssid": "Casa_5G", "rssi": -61.0, "tx_rate": 390.0, "channel": "149"})
        self.assertEqual(da.parse_iw_link("Not connected."), {})

    def test_nmcli_active_with_escaped_colon(self):
        self.assertEqual(da.parse_nmcli(NMCLI), {"ssid": "Casa:5G", "rssi": -64.0, "channel": "149", "tx_rate": 270.0})
        self.assertEqual(da.parse_nmcli("no:Vizinho:40:6:130 Mbit/s\n"), {})

    def test_netsh_english(self):
        self.assertEqual(da.parse_netsh_wlan(NETSH_EN), {"ssid": "Casa 5G", "rssi": -54.0, "channel": "149", "tx_rate": 866.7})

    def test_netsh_portuguese(self):
        self.assertEqual(da.parse_netsh_wlan(NETSH_PT), {"ssid": "Casa_5G", "rssi": -60.0, "channel": "36", "tx_rate": 433.3})

    def test_netsh_disconnected(self):
        self.assertEqual(da.parse_netsh_wlan(NETSH_DISCONNECTED), {})

    def test_channels(self):
        for mhz, ch in ((2412, "1"), (2437, "6"), (2484, "14"), (5180, "36"), (5745, "149"), (5955, "1"), (6115, "33")):
            self.assertEqual(da.wifi_channel(mhz), ch, mhz)
        self.assertIsNone(da.wifi_channel("x"))


class SecurityTests(unittest.TestCase):
    def test_host_allowlist(self):
        own = ["balboa"]
        for ok in ("balboa.local:8000", "192.168.0.56:8000", "localhost", "[::1]:8000", "balboa:8000", "BALBOA"):
            self.assertTrue(da.host_allowed(ok, own), ok)
        for bad in ("evil.com", "balboa.evil.com:8000", "rebind.attacker.net", "", None):
            self.assertFalse(da.host_allowed(bad, own), bad)


class ClassifyTests(unittest.TestCase):
    def test_causes(self):
        ok = {"gw": "192.168.0.1", "gw_ms": 3.0, "net_ms": 20.0, "http_ok": True}
        self.assertEqual(da.classify(ok, True), "ok")
        self.assertEqual(da.classify(dict(ok, http_ok=False), True), "dns")
        self.assertEqual(da.classify(dict(ok, net_ms=None, http_ok=False), True), "isp")
        self.assertEqual(da.classify(dict(ok, gw_ms=None, net_ms=None, http_ok=False), True), "local")
        self.assertEqual(da.classify(dict(ok, gw_ms=None, net_ms=None, http_ok=False), False), "unknown")
        self.assertEqual(da.classify(dict(ok, gw=None, gw_ms=None, net_ms=None, http_ok=False), False), "local")


if __name__ == "__main__":
    unittest.main()
