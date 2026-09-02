import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pentest_agent.config import OutOfScopeError, Scope
from pentest_agent.tools.scanner import _expand_ports, banner_query, parse_nmap_xml, python_scan, run_scan
from pentest_agent.tools.vuln import parse_nvd_response


class TestScope:
    def test_localhost_permitido(self):
        s = Scope(["127.0.0.1/32"])
        assert s.is_allowed("127.0.0.1")

    def test_ip_externa_rechazada(self):
        s = Scope(["127.0.0.1/32"])
        with pytest.raises(OutOfScopeError):
            s.assert_allowed("8.8.8.8")

    def test_rango_lan(self):
        s = Scope(["192.168.17.0/24"])
        assert s.is_allowed("192.168.17.230")
        assert not s.is_allowed("192.168.18.1")

    def test_scope_vacio_invalido(self):
        with pytest.raises(ValueError):
            Scope([])

    def test_basura_no_pasa(self):
        s = Scope(["127.0.0.1/32"])
        assert not s.is_allowed("no-es-una-ip")


class TestPorts:
    def test_lista(self):
        assert _expand_ports("22,80,443") == [22, 80, 443]

    def test_rango(self):
        assert _expand_ports("8000-8002") == [8000, 8001, 8002]

    def test_rango_gigante_rechazado(self):
        with pytest.raises(ValueError):
            _expand_ports("1-99999")


class TestNmapXml:
    def test_parse_minimo(self):
        xml = """<nmaprun><host>
        <address addr="10.0.0.5" addrtype="ipv4"/>
        <ports><port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="9.6p1">
        <cpe>cpe:/a:openbsd:openssh:9.6p1</cpe></service>
        </port></ports></host></nmaprun>"""
        r = parse_nmap_xml(xml)
        assert r["host"] == "10.0.0.5"
        assert r["services"][0]["product"] == "OpenSSH"
        assert r["services"][0]["version"] == "9.6p1"
        assert "openssh" in r["services"][0]["cpe"][0]

    def test_sin_host(self):
        assert parse_nmap_xml("<nmaprun></nmaprun>")["host"] is None


class TestNvdParse:
    def test_parse(self):
        data = {"vulnerabilities": [{"cve": {
            "id": "CVE-2024-1234",
            "descriptions": [{"lang": "en", "value": "RCE critico en demo"}],
            "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}]},
            "references": [{"url": "https://nvd.nist.gov/vuln/detail/CVE-2024-1234"}],
            "published": "2024-01-01T00:00:00.000",
        }}]}
        out = parse_nvd_response(data)
        assert out[0]["cve"] == "CVE-2024-1234"
        assert out[0]["cvss_score"] == 9.8
        assert out[0]["severity"] == "CRITICAL"

    def test_vacio(self):
        assert parse_nvd_response({}) == []


class TestBannerQuery:
    def test_http_server_header(self):
        assert banner_query("HTTP/1.1 200 OK\r\nServer: Apache/2.4.49 (Unix)") == "Apache 2.4.49"

    def test_ssh_banner(self):
        assert banner_query("SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.18") == "OpenSSH 9.6p1"

    def test_sin_version(self):
        assert banner_query("HTTP/1.1 200 OK") is None
        assert banner_query(None) is None


class TestScanIntegrado:
    def test_python_scan_encuentra_socket(self):
        srv = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            found = python_scan("127.0.0.1", [port, port + 1])
            ports = [f["port"] for f in found]
            assert port in ports and (port + 1) not in ports
        finally:
            srv.shutdown()

    def test_run_scan_fuera_de_scope_rechazado(self):
        with pytest.raises(OutOfScopeError):
            run_scan("8.8.8.8", "80", Scope(["127.0.0.1/32"]))

    def test_tool_scan_host_degraded_json(self):
        from pentest_agent.tools.scanner import scan_host
        out = json.loads(scan_host.invoke({"target": "203.0.113.9", "ports": "80"}))
        assert out["error"] == "OutOfScopeError"
