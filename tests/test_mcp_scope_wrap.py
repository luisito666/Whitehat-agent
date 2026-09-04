"""Tests del wrapper de scope para tools MCP que reciben targets de red."""
import asyncio

import pytest
from langchain_core.tools import StructuredTool


def _make_net_tool() -> StructuredTool:
    async def probe(host: str, port: int = 80) -> str:
        return f"connected {host}:{port}"

    return StructuredTool(
        name="probe",
        description="probe a host",
        coroutine=probe,
        args_schema={"type": "object", "properties": {
            "host": {"type": "string"}, "port": {"type": "integer"},
        }, "required": ["host"]},
    )


def _write_scope(tmp_path, allowed):
    (tmp_path / "scope.yaml").write_text(
        f"allowed_targets:\n" + "".join(f"  - {a}\n" for a in allowed), encoding="utf-8"
    )
    return tmp_path / "scope.yaml"


def test_out_of_scope_blocked(tmp_path, monkeypatch):
    from pentest_agent.mcp import wrap_scope

    monkeypatch.setenv("PENTEST_SCOPE_FILE", str(_write_scope(tmp_path, ["127.0.0.1"])))
    tool = wrap_scope(_make_net_tool())
    with pytest.raises(Exception) as ei:
        asyncio.run(tool.ainvoke({"host": "8.8.8.8", "port": 53}))
    assert "FUERA DE SCOPE" in str(ei.value)


def test_in_scope_passes(tmp_path, monkeypatch):
    from pentest_agent.mcp import wrap_scope

    monkeypatch.setenv("PENTEST_SCOPE_FILE", str(_write_scope(tmp_path, ["127.0.0.1"])))
    tool = wrap_scope(_make_net_tool())
    out = asyncio.run(tool.ainvoke({"host": "127.0.0.1", "port": 9101}))
    assert "connected 127.0.0.1:9101" in str(out)


def test_no_target_fields_unwrapped_unchanged():
    """Tools sin host/target/url no se envuelven (devuelve la misma)."""
    from pentest_agent.mcp import maybe_wrap_scope

    async def echo(text: str) -> str:
        return text

    t = StructuredTool(name="echo", description="d", coroutine=echo,
                       args_schema={"type": "object", "properties": {"text": {"type": "string"}}})
    assert maybe_wrap_scope(t) is t


def test_host_field_triggers_wrap():
    from pentest_agent.mcp import maybe_wrap_scope

    t = _make_net_tool()
    wrapped = maybe_wrap_scope(t)
    assert wrapped is not t
    assert wrapped.name == "probe"  # identidad preservada para el LLM
