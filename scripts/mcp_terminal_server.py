"""Servidor MCP terminal COMPLETO con politica dual (stdio).

Dos modos, elegidos por el operador al spawnear (MCP_TERMINAL_POLICY):

  investigative (default — recon/vuln)
      - Allowlist EXACTA de binarios de reconocimiento (sin shell, argv directo)
      - Toda IP literal (IPv4/IPv6, incluidas dentro de args) se valida
        contra scope.yaml ANTES de ejecutar
      - Sin operadores de red ofensivos (nmap NSE exploit, hydra, sqlmap...)
      - DNS: los hostnames se resuelven y TODAS sus IPs se validan contra scope

  full (SOLO exploit bajo triple llave — no es el default)
      - Comando arbitrario con shell (bash -c), timeout y limite de output
      - Se asume que el proceso ya paso engagement + aprobacion humana

Tools:
    run_command(cmd, args, timeout)   -> ejecuta y devuelve salida+exit code
    list_allowed()                    -> binarios permitidos (investigative)
    policy()                          -> modo activo y reglas

Env:
    MCP_TERMINAL_POLICY = investigative | full
    PENTEST_SCOPE_FILE  = scope.yaml del operador
"""
from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

POLICY = os.environ.get("MCP_TERMINAL_POLICY", "investigative")
SCOPE_FILE = os.environ.get("PENTEST_SCOPE_FILE", "scope.yaml")

# Binarios de reconocimiento permitidos en modo investigative.
ALLOWED_BINARIES = {
    "nmap": ["-sV", "-Pn", "-p", "-T4", "--version-light", "-O", "-A", "-v",
             "-sn", "-sU", "-F", "--top-ports", "-oN", "-oG"],
    "curl": ["-sS", "-I", "-k", "-L", "--max-time", "-A", "-H", "-o", "-w",
             "-X", "-d", "--resolve"],
    "dig": ["+short", "+noall", "+answer", "ANY", "A", "AAAA", "MX", "TXT",
            "NS", "CNAME", "SOA", "@8.8.8.8", "@1.1.1.1"],
    "host": [],
    "whois": [],
    "traceroute": ["-n", "-m", "-I", "-T", "-U"],
    "ping": ["-c", "-W", "-4", "-6"],
    "openssl": ["s_client", "-connect", "-showcerts", "x509", "-noout", "-text",
                "-in", "-startdate", "-enddate", "-subject", "-issuer"],
    "amass": ["enum", "-passive", "-d", "-o"],
    "nuclei": [],  # off por default: templates ofensivos; habilitar deliberadamente
}

m = FastMCP("terminal-gated")


# ------------------------------------------------------------------ scope
def _load_scope_networks() -> list:
    import ipaddress

    import yaml

    p = Path(SCOPE_FILE)
    if not p.exists():
        # fail-closed razonable: sin scope file, solo loopback
        return [ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("::1/128")]
    data = yaml.safe_load(p.read_text()) or {}
    nets = []
    for t in data.get("allowed_targets") or ["127.0.0.1/32", "::1/128"]:
        try:
            nets.append(ipaddress.ip_network(t, strict=False))
        except ValueError:
            continue
    return nets


def _ips_in_text(text: str) -> list[str]:
    """IPs literales en un texto (args de comando), sin falsos positivos
    obvios (versiones tipo 1.2 no matchean por exigir 4 octetos)."""
    import ipaddress
    import re

    pat = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
    candidates = pat.findall(text)
    out = []
    for c in candidates:
        try:
            ipaddress.ip_address(c)
            out.append(c)
        except ValueError:
            pass
    # IPv6 literal entre corchetes o tokens con ':'
    for tok in re.findall(r"[0-9a-fA-F:]+:[0-9a-fA-F:]+", text):
        try:
            ipaddress.ip_address(tok)
            out.append(tok)
        except ValueError:
            pass
    return out


def _validate_target(token: str) -> str | None:
    """None si el token es un target valido; razon del bloqueo si no."""
    import ipaddress

    nets = _load_scope_networks()
    try:
        addr = ipaddress.ip_address(token.strip("[]"))
    except ValueError:
        # hostname -> resolver y validar TODAS sus IPs
        try:
            infos = socket.getaddrinfo(token, None)
        except socket.gaierror:
            return f"hostname irresoluble: {token}"
        ips = {i[4][0] for i in infos}
        bad = [ip for ip in ips if not _ip_allowed(ip, nets)]
        if bad:
            return f"hostname {token} resuelve fuera de scope: {sorted(bad)}"
        return None
    return None if _ip_allowed(str(addr), nets) else f"IP fuera de scope: {token}"


def _ip_allowed(ip: str, nets) -> bool:
    import ipaddress

    addr = ipaddress.ip_address(ip)
    return any(addr in n for n in nets)


def validation_infos(infos):  # pragma: no cover - helper legibility
    return infos


# ------------------------------------------------------------------ gate
def _gate_investigative(cmd: str, args: list[str]) -> str | None:
    """Razon de bloqueo o None si pasa. Allowlist + scope sobre targets."""
    if cmd not in ALLOWED_BINARIES:
        return (f"binario {cmd!r} no permitido en modo investigative. "
                f"Permitidos: {sorted(ALLOWED_BINARIES)}")
    bad_flags = []
    allowed_flags = ALLOWED_BINARIES[cmd]
    for a in args:
        if a.startswith("-") and a not in allowed_flags:
            bad_flags.append(a)
    if bad_flags:
        return f"flags no permitidos para {cmd}: {bad_flags}. Permitidos: {allowed_flags}"
    # scope: toda IP literal o hostname en args
    joined = " ".join(args)
    for ip in _ips_in_text(joined):
        r = _validate_target(ip)
        if r:
            return r
    for tok in args:
        if _looks_like_host(tok):
            r = _validate_target(tok)
            if r:
                return r
    return None


def _looks_like_host(tok: str) -> bool:
    """Heuristica: token con punto, sin slash ni flag — hostname o IP."""
    if tok.startswith("-") or "/" in tok or "." not in tok:
        return False
    return True


# ------------------------------------------------------------------ tools
@m.tool()
def run_command(cmd: str, args_json: str = "[]", timeout: int = 120) -> str:
    """Ejecuta un comando bajo la politica activa.

    investigative: binario en allowlist + flags permitidos + targets dentro
    de scope.yaml (IPs literales y hostnames resueltos). Sin shell.
    full: comando arbitrario con shell (solo exploit, triple llave).
    args_json: JSON array de argumentos.
    """
    try:
        args = json.loads(args_json) if args_json else []
    except json.JSONDecodeError as e:
        return json.dumps({"error": "args_json invalido", "detail": str(e)})

    if POLICY == "investigative":
        reason = _gate_investigative(cmd, args)
        if reason:
            return json.dumps({"blocked": True, "reason": reason})
        argv = [cmd, *args]
    else:  # full
        argv = ["bash", "-c", " ".join([cmd, *args])]

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return json.dumps({
            "cmd": cmd,
            "args": args,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-2000:],
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"cmd": cmd, "error": f"timeout tras {timeout}s"})
    except FileNotFoundError:
        return json.dumps({"cmd": cmd, "error": "binario no encontrado"})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"cmd": cmd, "error": type(e).__name__, "detail": str(e)[:300]})


@m.tool()
def list_allowed() -> str:
    """Binarios y flags permitidos en modo investigative."""
    return json.dumps({"policy": POLICY, "allowed": ALLOWED_BINARIES}, indent=2)


@m.tool()
def policy() -> str:
    """Politica activa del terminal MCP y sus reglas."""
    return json.dumps({
        "policy": POLICY,
        "rules": (
            "allowlist de binarios+flags, targets validados contra scope.yaml "
            "(IPs literales y hostnames resueltos), sin shell"
            if POLICY == "investigative"
            else "comando arbitrero con shell (bash -c): solo bajo triple llave "
                 "del exploit_agent (engagement + aprobacion humana en proceso)"
        ),
    })


if __name__ == "__main__":
    m.run(transport="stdio")
