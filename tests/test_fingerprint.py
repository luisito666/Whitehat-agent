"""Tests del fingerprinting TLS/HTTP del scanner (PR B).

Fixtures locales: servidores TLS (cert autofirmado con CN/SANs k8s) y HTTP
(JSON estilo kube-apiserver /version) en puertos efimeros. Todo determinista,
sin red externa: 127.0.0.1 unicamente.
"""
from __future__ import annotations

import datetime
import json
import ssl
import socket
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from pentest_agent.tools.scanner import (
    _enrich_with_probes,
    _parse_http_response,
    http_version_probe,
    python_scan,
)


def _make_cert(cn: str, sans: list[str]) -> tuple[bytes, bytes]:
    """Genera cert+key autofirmado (fixture, no producción)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    san = x509.SubjectAlternativeName([x509.DNSName(s) for s in sans])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )


class _Stop:
    def __init__(self) -> None:
        self.stop = False


def _serve_tls(certfile: str, keyfile: str) -> tuple[int, _Stop]:
    """Servidor TLS en puerto efimero; responde basura tras el handshake."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    st = _Stop()

    def run() -> None:
        listener.settimeout(0.2)
        while not st.stop:
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                with ctx.wrap_socket(conn, server_side=True) as tls:
                    tls.sendall(b"hello-secure\r\n")
            except (OSError, ssl.SSLError):
                pass
        listener.close()

    threading.Thread(target=run, daemon=True).start()
    return port, st


def _serve_http(payload: bytes, status: str = "200 OK") -> tuple[int, _Stop]:
    """Servidor HTTP plano en puerto efimero."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    st = _Stop()

    def run() -> None:
        listener.settimeout(0.2)
        while not st.stop:
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.recv(4096)
                conn.sendall(
                    f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                    + payload
                )
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        listener.close()

    threading.Thread(target=run, daemon=True).start()
    return port, st


KUBE_VERSION = json.dumps(
    {"major": "1", "minor": "31", "gitVersion": "v1.31.0", "gitCommit": "ffd6b", "platform": "linux/amd64"}
).encode()


class TestParseHttpResponse:
    def test_json_kube_style(self):
        raw = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + KUBE_VERSION
        out = _parse_http_response(raw)
        assert out is not None
        assert out["status"] == 200
        assert out["json"]["gitVersion"] == "v1.31.0"

    def test_status_401_sin_body(self):
        raw = b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"
        out = _parse_http_response(raw)
        assert out is not None and out["status"] == 401 and "json" not in out

    def test_basura_no_http(self):
        assert _parse_http_response(b"SSH-2.0-OpenSSH_9.6\r\n") is None


class TestHTTPProbe:
    def test_http_json_version(self):
        port, st = _serve_http(KUBE_VERSION)
        try:
            out = http_version_probe("127.0.0.1", port, timeout=2.0)
            assert out is not None
            assert out["status"] == 200
            assert out["json"]["gitVersion"] == "v1.31.0"
            assert out["https"] is False
        finally:
            st.stop = True

    def test_puerto_cerrado_devuelve_none(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        assert http_version_probe("127.0.0.1", dead_port, timeout=0.5) is None


class TestTLSEnrich:
    def test_tls_probe_cert_kube_apiserver(self, tmp_path):
        cert, key = _make_cert(
            "kube-apiserver",
            ["kubernetes.default.svc", "kubernetes.default", "10.96.0.1"],
        )
        cf = tmp_path / "cert.pem"
        kf = tmp_path / "key.pem"
        cf.write_bytes(cert)
        kf.write_bytes(key)
        port, st = _serve_tls(str(cf), str(kf))
        try:
            svc = {"port": port, "protocol": "tcp", "state": "open", "service": None,
                   "product": None, "version": None, "extrainfo": None, "cpe": [], "banner": None}
            out = _enrich_with_probes("127.0.0.1", svc, timeout=2.0)
            tls = out.get("tls") or {}
            assert tls.get("tls_cn") == "kube-apiserver"
            assert "kubernetes.default.svc" in (tls.get("tls_sans") or [])
            assert out["service"] == "kube-apiserver"
        finally:
            st.stop = True

    def test_enriquece_version_desde_http(self):
        port, st = _serve_http(KUBE_VERSION)
        try:
            svc = {"port": port, "protocol": "tcp", "state": "open", "service": None,
                   "product": None, "version": None, "extrainfo": None, "cpe": [], "banner": None}
            out = _enrich_with_probes("127.0.0.1", svc, timeout=2.0)
            assert out["version"] == "v1.31.0"
            assert out["product"] == "kubernetes"
        finally:
            st.stop = True

    def test_nmap_data_no_se_sobreescribe(self):
        svc = {"port": 6443, "protocol": "tcp", "state": "open", "service": "https",
               "product": "Kubernetes API server", "version": "1.30.1",
               "extrainfo": None, "cpe": [], "banner": None}
        out = _enrich_with_probes("127.0.0.1", svc, timeout=0.2)
        assert out["version"] == "1.30.1"  # intacto, no gastó probes
        assert "tls" not in out and "http" not in out


class TestPythonScanEnrich:
    def test_python_scan_captura_version(self):
        port, st = _serve_http(KUBE_VERSION)
        try:
            found = python_scan("127.0.0.1", [port], timeout=1.0)
            assert len(found) == 1
            assert found[0]["version"] == "v1.31.0"
            assert found[0]["product"] == "kubernetes"
        finally:
            st.stop = True
