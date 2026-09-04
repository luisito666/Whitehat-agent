"""Tests fase 3: fs MCP completo, terminal MCP (politicas) y defaults."""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent
FS_SERVER = REPO / "scripts" / "mcp_fs_server.py"
TERM_SERVER = REPO / "scripts" / "mcp_terminal_server.py"


def _params(script: Path, env: dict | None = None, arg: str | None = None) -> StdioServerParameters:
    import os

    e = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    e.update(env or {})
    args = [str(script)] + ([arg] if arg else [])
    return StdioServerParameters(command=sys.executable, args=args, env=e)


def _run(coro):
    return asyncio.run(coro)


async def _call(script, tool, args, env=None, arg=None):
    async with stdio_client(_params(script, env, arg)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            out = await s.call_tool(tool, args)
            texts = [c.text for c in out.content if hasattr(c, "text")]
            return texts[0] if texts else ""


# ------------------------------------------------------------------ fs
def test_fs_crud_roundtrip(tmp_path):
    jail = tmp_path / "jail"
    call = lambda t, a: _run(_call(FS_SERVER, t, a, arg=str(jail)))  # noqa: E731

    assert call("write_text", {"path": "audits/2026/nota.md", "content": "hola INICIAL"}) .startswith("OK")
    assert "hola INICIAL" in call("read_text", {"path": "audits/2026/nota.md"})
    assert "nota.md" in call("list", {"path": "audits/2026"})
    assert "nota.md" in call("tree", {})
    assert call("append_text", {"path": "audits/2026/nota.md", "content": " + mas"}).startswith("OK")
    assert "hola INICIAL + mas" in call("read_text", {"path": "audits/2026/nota.md"})
    assert "audits/2026/nota.md" in call("search", {"pattern": "INICIAL"})
    assert len(call("sha256", {"path": "audits/2026/nota.md"})) == 64
    assert "file" in call("info", {"path": "audits/2026/nota.md"})
    assert call("move", {"src": "audits/2026/nota.md", "dst": "audits/final.md"}).startswith("OK")
    assert call("remove", {"path": "audits/final.md"}).startswith("OK")


def test_fs_jail_escape_blocked(tmp_path):
    jail = tmp_path / "jail"
    jail.mkdir()
    outside = tmp_path / "fuera.txt"
    outside.write_text("secreto", encoding="utf-8")
    call = lambda t, a: _run(_call(FS_SERVER, t, a, arg=str(jail)))  # noqa: E731

    r = call("read_text", {"path": "../fuera.txt"})
    assert r.startswith("ERROR")
    r = call("write_text", {"path": "/etc/passwd", "content": "x"})
    assert r.startswith("ERROR")
    r = call("read_text", {"path": "../../etc/passwd"})
    assert r.startswith("ERROR")


def test_fs_binary_rejected_for_read(tmp_path):
    jail = tmp_path / "jail"
    binf = jail / "blob.bin"
    jail.mkdir()
    binf.write_bytes(b"\x00\x01\x02binary")
    r = _run(_call(FS_SERVER, "read_text", {"path": "blob.bin"}, arg=str(jail)))
    assert r.startswith("ERROR") and "binario" in r
    # pero sha256 funciona
    assert len(_run(_call(FS_SERVER, "sha256", {"path": "blob.bin"}, arg=str(jail)))) == 64


# ------------------------------------------------------------------ terminal
def test_terminal_investigative_blocks_disallowed_binary(tmp_path):
    r = _run(_call(TERM_SERVER, "run_command",
                   {"cmd": "nc", "args_json": '["-zv","127.0.0.1","22"]'},
                   env={"MCP_TERMINAL_POLICY": "investigative"}))
    out = json.loads(r)
    assert out.get("blocked") is True
    assert "no permitido" in out["reason"]


def test_terminal_investigative_blocks_bad_flag(tmp_path):
    r = _run(_call(TERM_SERVER, "run_command",
                   {"cmd": "nmap", "args_json": '["--script","exploit","127.0.0.1"]'},
                   env={"MCP_TERMINAL_POLICY": "investigative"}))
    out = json.loads(r)
    assert out.get("blocked") is True
    assert "flags no permitidos" in out["reason"]


def test_terminal_investigative_blocks_out_of_scope_ip(tmp_path):
    scope = tmp_path / "scope.yaml"
    scope.write_text("allowed_targets:\n  - 127.0.0.1/32\n", encoding="utf-8")
    r = _run(_call(TERM_SERVER, "run_command",
                   {"cmd": "ping", "args_json": '["-c","1","8.8.8.8"]'},
                   env={"MCP_TERMINAL_POLICY": "investigative",
                        "PENTEST_SCOPE_FILE": str(scope)}))
    out = json.loads(r)
    assert out.get("blocked") is True
    assert "fuera de scope" in out["reason"]


def test_terminal_investigative_allows_in_scope(tmp_path):
    scope = tmp_path / "scope.yaml"
    scope.write_text("allowed_targets:\n  - 127.0.0.1/32\n", encoding="utf-8")
    r = _run(_call(TERM_SERVER, "run_command",
                   {"cmd": "curl", "args_json": '["-sS","--max-time","5","http://127.0.0.1:9101"]'},
                   env={"MCP_TERMINAL_POLICY": "investigative",
                        "PENTEST_SCOPE_FILE": str(scope)}))
    out = json.loads(r)
    # curl corre (exit code cualquiera: el puerto puede estar cerrado);
    # lo importante es que NO fue blocked por el gate
    assert out.get("blocked") is not True
    assert "exit_code" in out


def test_terminal_full_runs_arbitrary(tmp_path):
    r = _run(_call(TERM_SERVER, "run_command",
                   {"cmd": "echo", "args_json": '["hola$((1+1))mundo"]'},
                   env={"MCP_TERMINAL_POLICY": "full"}))
    out = json.loads(r)
    assert out.get("exit_code") == 0
    assert "hola2mundo" in out.get("stdout", "")  # shell activo: evalua $((1+1))


def test_terminal_policy_tool_reports_mode():
    r = _run(_call(TERM_SERVER, "policy", {}, env={"MCP_TERMINAL_POLICY": "investigative"}))
    out = json.loads(r)
    assert out["policy"] == "investigative"
    assert "scope.yaml" in out["rules"]


# ------------------------------------------------------------------ defaults
def test_defaults_without_config_file(tmp_path, monkeypatch):
    import pentest_agent.mcp_config as mc

    monkeypatch.setattr(mc, "MCP_CONFIG_PATH", tmp_path / "nope.yaml")
    for role in ("recon", "vuln", "exploit"):
        servers = mc.load_mcp_config(role)
        names = [s["name"] for s in servers]
        assert names == ["filesystem", "terminal"], role
    # reporter no tiene defaults
    assert mc.load_mcp_config("reporter") == []


def test_yaml_entry_overrides_defaults(tmp_path, monkeypatch):
    import yaml as y

    import pentest_agent.mcp_config as mc

    p = tmp_path / "mcp_servers.yaml"
    p.write_text(y.safe_dump({"recon": []}), encoding="utf-8")
    monkeypatch.setattr(mc, "MCP_CONFIG_PATH", p)
    assert mc.load_mcp_config("recon") == []      # opt-out explicito
    servers = mc.load_mcp_config("vuln")           # rol sin entrada -> defaults
    assert [s["name"] for s in servers] == ["filesystem", "terminal"]


def test_default_policies_by_role(tmp_path, monkeypatch):
    import pentest_agent.mcp_config as mc

    monkeypatch.setattr(mc, "MCP_CONFIG_PATH", tmp_path / "nope.yaml")
    pol = {r: {s["name"]: (s.get("env") or {}).get("MCP_TERMINAL_POLICY")
               for s in mc.load_mcp_config(r)} for r in ("recon", "vuln", "exploit")}
    assert pol["recon"]["terminal"] == "investigative"
    assert pol["vuln"]["terminal"] == "investigative"
    assert pol["exploit"]["terminal"] == "full"
