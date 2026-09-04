"""Tests de los servers MCP de fase 2 contra el protocolo real (stdio).

Usa mcp.client.session directamente: verifica handshake + tool call sin
pasar por el LLM. Los gates se testean con el server vivo.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent
MSF_SERVER = REPO / "scripts" / "mcp_msf_server.py"
OSINT_SERVER = REPO / "scripts" / "mcp_osint_server.py"


def _server_params(script: Path, env: dict | None = None) -> StdioServerParameters:
    import os

    e = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    e.update(env or {})
    return StdioServerParameters(command=sys.executable, args=[str(script)], env=e)


async def _call_tool(script: Path, name: str, args: dict, env: dict | None = None):
    async with stdio_client(_server_params(script, env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            out = await s.call_tool(name, args)
            texts = [c.text for c in out.content if hasattr(c, "text")]
            return json.loads(texts[0]) if texts else {}


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ msf gates
def test_msf_blocked_without_engagement():
    out = _run(_call_tool(MSF_SERVER, "run_metasploit_module",
                          {"host_target": "127.0.0.1", "module": "auxiliary/scanner/ssh/ssh_version"},
                          env={"PENTEST_ENGAGEMENT_FILE": "", "PENTEST_EXPLOIT_APPROVED": ""}))
    assert out.get("blocked") is True
    assert "engagement" in out.get("reason", "").lower()


def test_msf_engagement_status_reports_gates():
    out = _run(_call_tool(MSF_SERVER, "engagement_status", {},
                          env={"PENTEST_ENGAGEMENT_FILE": "", "PENTEST_EXPLOIT_APPROVED": ""}))
    assert out.get("blocked") or out.get("engagement")


def test_msf_sim_run_with_full_gates(tmp_path):
    """Gates abiertos + backend sim: la tool corre y escribe ledger."""
    import yaml

    eng = tmp_path / "engagement.yaml"
    eng.write_text(yaml.safe_dump({
        "engagement_id": "mcp-test-001",
        "client": {"name": "Test"},
        "authorization": {"reference": "REF-1", "valid_from": "2026-01-01",
                          "valid_until": "2026-12-31"},
        "scope": {"allowed_targets": ["127.0.0.1/32"]},
        "rules_of_engagement": {"allowed_techniques": ["metasploit-module"]},
        "msf": {"allowed_modules": ["auxiliary/scanner/ssh/ssh_version"]},
    }))
    ledger = tmp_path / "ledger.jsonl"
    out = _run(_call_tool(
        MSF_SERVER, "run_metasploit_module",
        {"host_target": "127.0.0.1", "module": "auxiliary/scanner/ssh/ssh_version"},
        env={
            "PENTEST_ENGAGEMENT_FILE": str(eng),
            "PENTEST_EXPLOIT_APPROVED": "mcp-test-001",
            "MSF_BACKEND": "sim",
            "PENTEST_LEDGER": str(ledger),
        },
    ))
    assert out.get("blocked") is not True
    assert out.get("proven") is False  # sim no abre sesion
    assert out.get("auth_reference") == "REF-1"


def test_msf_module_not_in_allowlist_blocked(tmp_path):
    import yaml

    eng = tmp_path / "engagement.yaml"
    eng.write_text(yaml.safe_dump({
        "engagement_id": "mcp-test-002",
        "client": {"name": "Test"},
        "authorization": {"reference": "REF-2", "valid_from": "2026-01-01",
                          "valid_until": "2026-12-31"},
        "scope": {"allowed_targets": ["127.0.0.1/32"]},
        "rules_of_engagement": {"allowed_techniques": ["metasploit-module"]},
        "msf": {"allowed_modules": ["auxiliary/scanner/ssh/ssh_version"]},
    }))
    out = _run(_call_tool(
        MSF_SERVER, "run_metasploit_module",
        {"host_target": "127.0.0.1", "module": "exploit/unix/ftp/vsftpd_234backdoor"},
        env={
            "PENTEST_ENGAGEMENT_FILE": str(eng),
            "PENTEST_EXPLOIT_APPROVED": "mcp-test-002",
            "MSF_BACKEND": "sim",
        },
    ))
    assert out.get("blocked") is True
    assert "NO autorizado" in out.get("reason", "")


# ------------------------------------------------------------------ osint gates
def test_osint_blocked_without_authorization():
    out = _run(_call_tool(OSINT_SERVER, "ct_subdomains", {"domain": "example.com"},
                          env={"PENTEST_OSINT_CONFIRM_DOMAIN": "", "PENTEST_ENGAGEMENT_FILE": ""}))
    assert out.get("blocked") is True


def test_osint_engagement_domain_gate(tmp_path):
    import yaml

    eng = tmp_path / "engagement.yaml"
    eng.write_text(yaml.safe_dump({
        "engagement_id": "osint-001",
        "client": {"name": "Test"},
        "authorization": {"reference": "REF", "valid_from": "2026-01-01",
                          "valid_until": "2026-12-31"},
        "scope": {"allowed_targets": ["127.0.0.1/32"]},
        "rules_of_engagement": {"allowed_techniques": []},
        "osint": {"allowed_domains": ["midominio.co"]},
    }))
    # dominio fuera de la allowlist -> blocked (sin llegar a crt.sh)
    out = _run(_call_tool(OSINT_SERVER, "ct_subdomains", {"domain": "otro.com"},
                          env={"PENTEST_ENGAGEMENT_FILE": str(eng)}))
    assert out.get("blocked") is True
    assert "allowed_domains" in out.get("reason", "")
