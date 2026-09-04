"""Integración: el worker A2A usa tools nativas + MCP del rol."""
from pathlib import Path

import yaml


def test_worker_uses_native_plus_mcp_tools(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp_servers.yaml"
    cfg.write_text(yaml.safe_dump({"reporter": [{
        "name": "mini",
        "transport": "stdio",
        "command": "python-unused",
        "args": [],
    }]}), encoding="utf-8")
    monkeypatch.setattr("pentest_agent.mcp_config.MCP_CONFIG_PATH", cfg)

    from langchain_core.tools import StructuredTool

    async def note(text: str) -> str:
        return text

    fake_mcp = [StructuredTool(
        name="mcp_note", description="x", coroutine=note,
        args_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )]
    monkeypatch.setattr("pentest_agent.mcp.load_mcp_tools", lambda role: fake_mcp)

    captured = {}

    def fake_react_agent(llm, tools, prompt_txt):
        captured["tools"] = list(tools)
        return object()

    monkeypatch.setattr("pentest_agent.a2a_server._react_agent", fake_react_agent)
    import pentest_agent.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda: None)

    from pentest_agent.a2a_server import ReactAgentExecutor

    ReactAgentExecutor("reporter")._get_agent()
    names = [t.name for t in captured["tools"]]
    assert "save_report" in names      # nativa
    assert "mcp_note" in names         # MCP


def test_worker_without_mcp_uses_native_only(tmp_path, monkeypatch):
    monkeypatch.setattr("pentest_agent.mcp.load_mcp_tools", lambda role: [])

    captured = {}

    def fake_react_agent(llm, tools, prompt_txt):
        captured["tools"] = list(tools)
        return object()

    monkeypatch.setattr("pentest_agent.a2a_server._react_agent", fake_react_agent)
    import pentest_agent.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda: None)

    from pentest_agent.a2a_server import ReactAgentExecutor

    ReactAgentExecutor("vuln")._get_agent()
    assert [t.name for t in captured["tools"]] == ["find_cves"]


def test_exploit_mcp_never_loaded_when_gates_closed(tmp_path, monkeypatch):
    """El gate vive en load_mcp_tools (tests del loader); aqui verificamos que
    el worker no lo bypassa: sin config MCP el exploit solo tiene las nativas."""
    monkeypatch.delenv("PENTEST_EXPLOIT_APPROVED", raising=False)
    monkeypatch.setattr("pentest_agent.mcp_config.MCP_CONFIG_PATH", tmp_path / "nope.yaml")

    captured = {}

    def fake_react_agent(llm, tools, prompt_txt):
        captured["tools"] = list(tools)
        return object()

    monkeypatch.setattr("pentest_agent.a2a_server._react_agent", fake_react_agent)
    import pentest_agent.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda: None)

    from pentest_agent.a2a_server import ReactAgentExecutor

    ReactAgentExecutor("exploit")._get_agent()
    names = [t.name for t in captured["tools"]]
    assert names == ["prove_vulnerability", "run_metasploit_module", "run_python_snippet"]
