"""Tests del cargador de tools MCP por rol (fail-closed para exploit)."""
import asyncio
import sys
from pathlib import Path

import yaml

FIXTURE = Path(__file__).parent / "fixtures" / "mini_mcp_server.py"


def _write_config(tmp_path: Path, data: dict, monkeypatch) -> None:
    p = tmp_path / "mcp_servers.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr("pentest_agent.mcp_config.MCP_CONFIG_PATH", p)


def test_no_config_returns_empty(tmp_path, monkeypatch):
    _write_config(tmp_path, {"recon": []}, monkeypatch)
    from pentest_agent.mcp import load_mcp_tools

    assert load_mcp_tools("recon") == []


def test_loads_real_tool_from_stdio_server(tmp_path, monkeypatch):
    _write_config(tmp_path, {"recon": [{
        "name": "mini",
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(FIXTURE)],
    }]}, monkeypatch)
    from pentest_agent.mcp import load_mcp_tools

    tools = load_mcp_tools("recon")
    assert len(tools) == 1
    assert tools[0].name == "echo"
    out = asyncio.run(tools[0].ainvoke({"text": "hola"}))
    blocks = out if isinstance(out, list) else [out]
    assert any("hola" in b.get("text", "") for b in blocks if isinstance(b, dict))


def test_exploit_fail_closed_without_env(tmp_path, monkeypatch):
    _write_config(tmp_path, {"exploit": [{
        "name": "mini",
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(FIXTURE)],
    }]}, monkeypatch)
    monkeypatch.delenv("PENTEST_EXPLOIT_APPROVED", raising=False)
    monkeypatch.delenv("PENTEST_ENGAGEMENT_FILE", raising=False)
    from pentest_agent.mcp import load_mcp_tools

    # gates cerrados -> ni intenta cargar: [] sin spawn de subprocess
    assert load_mcp_tools("exploit") == []


def test_exploit_fail_closed_without_engagement(tmp_path, monkeypatch):
    _write_config(tmp_path, {"exploit": [{
        "name": "mini",
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(FIXTURE)],
    }]}, monkeypatch)
    monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "1")
    monkeypatch.delenv("PENTEST_ENGAGEMENT_FILE", raising=False)
    from pentest_agent.mcp import load_mcp_tools

    assert load_mcp_tools("exploit") == []


def test_gates_open_non_exploit_roles():
    from pentest_agent.mcp import gates_open

    assert gates_open("recon") is True
    assert gates_open("vuln") is True
    assert gates_open("reporter") is True
