"""Tests del loader de config MCP por rol."""
from pathlib import Path

import pytest

import yaml


def _write_config(tmp_path: Path, data: dict) -> None:
    (tmp_path / "mcp_servers.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_no_config_file_means_no_servers(tmp_path, monkeypatch):
    monkeypatch.setattr("pentest_agent.mcp_config.MCP_CONFIG_PATH", tmp_path / "mcp_servers.yaml")
    from pentest_agent.mcp_config import load_mcp_config

    assert load_mcp_config("recon") == []


def test_missing_role_means_no_servers(tmp_path, monkeypatch):
    _write_config(tmp_path, {"reporter": [{"name": "fs", "transport": "stdio"}]})
    monkeypatch.setattr("pentest_agent.mcp_config.MCP_CONFIG_PATH", tmp_path / "mcp_servers.yaml")
    from pentest_agent.mcp_config import load_mcp_config

    assert load_mcp_config("recon") == []
    assert load_mcp_config("reporter") == [{"name": "fs", "transport": "stdio"}]


def test_returns_servers_for_role(tmp_path, monkeypatch):
    _write_config(tmp_path, {
        "recon": [
            {"name": "osint", "transport": "stdio", "command": "python", "args": ["-m", "x"]},
            {"name": "geo", "transport": "http", "url": "http://127.0.0.1:9999/mcp"},
        ],
    })
    monkeypatch.setattr("pentest_agent.mcp_config.MCP_CONFIG_PATH", tmp_path / "mcp_servers.yaml")
    from pentest_agent.mcp_config import load_mcp_config

    servers = load_mcp_config("recon")
    assert [s["name"] for s in servers] == ["osint", "geo"]


def test_invalid_yaml_raises(tmp_path, monkeypatch):
    (tmp_path / "mcp_servers.yaml").write_text("a: [1, 2", encoding="utf-8")
    monkeypatch.setattr("pentest_agent.mcp_config.MCP_CONFIG_PATH", tmp_path / "mcp_servers.yaml")
    from pentest_agent.mcp_config import load_mcp_config

    # fail-closed pero RUIDOSO: mejor tronar al arrancar que correr sin tools
    # en silencio (el operador configuro algo y no se cargo).
    with pytest.raises(Exception):
        load_mcp_config("recon")


def test_non_list_role_raises(tmp_path, monkeypatch):
    _write_config(tmp_path, {"recon": {"name": "oops"}})
    monkeypatch.setattr("pentest_agent.mcp_config.MCP_CONFIG_PATH", tmp_path / "mcp_servers.yaml")
    from pentest_agent.mcp_config import load_mcp_config

    with pytest.raises(AssertionError):
        load_mcp_config("recon")
