"""Smoke E2E fase 2: servers MCP nuevos contra servicios reales.

1. OSINT: ct_subdomains contra luisito.dev (dominio propio del operador)
   via protocolo MCP stdio real. Verifica subdominios conocidos.
2. MSF (sim): engagement de lab + gates abiertos -> run_metasploit_module
   via MCP escribe ledger con auth_reference.

Uso:
    .venv/bin/python scripts/mcp_smoke_phase2.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent
DOMAIN = os.environ.get("SMOKE_DOMAIN", "luisito.dev")


def _params(script: Path, env: dict | None = None) -> StdioServerParameters:
    e = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    e.update(env or {})
    return StdioServerParameters(command=sys.executable, args=[str(script)], env=e)


async def _call(script: Path, tool: str, args: dict, env: dict | None = None) -> dict:
    async with stdio_client(_params(script, env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            out = await s.call_tool(tool, args)
            texts = [c.text for c in out.content if hasattr(c, "text")]
            return json.loads(texts[0]) if texts else {}


async def smoke_osint() -> bool:
    print(f"== OSINT: ct_subdomains({DOMAIN}) via MCP real ==")
    out = await _call(
        REPO / "scripts" / "mcp_osint_server.py", "ct_subdomains", {"domain": DOMAIN},
        # lab/demo: aislamos el engagement del operador si hubiera en el env
        env={"PENTEST_OSINT_CONFIRM_DOMAIN": DOMAIN, "PENTEST_ENGAGEMENT_FILE": ""},
    )
    if out.get("error") or out.get("blocked"):
        print("FAIL:", json.dumps(out, ensure_ascii=False)[:300])
        return False
    names = out.get("names") or []
    print(f"count={out.get('count')} muestra={names[:8]}")
    # subdominios conocidos del dominio (registro CT publico)
    expected = {"luisito.dev", "www.luisito.dev"}
    hits = expected & set(names)
    print("hits esperados:", sorted(hits) or "(ninguno)")
    return bool(names)  # el dominio tiene certificados => al menos el base


async def smoke_msf() -> bool:
    print("== MSF sim: gates abiertos -> ledger via MCP real ==")
    tmp = Path(tempfile.mkdtemp(prefix="smoke2-msf-"))
    eng = tmp / "engagement.yaml"
    eng.write_text(yaml.safe_dump({
        "engagement_id": "smoke2-msf-001",
        "client": {"name": "Smoke Lab"},
        "authorization": {"reference": "REF-SMOKE2", "valid_from": "2026-01-01",
                          "valid_until": "2026-12-31"},
        "scope": {"allowed_targets": ["127.0.0.1/32"]},
        "rules_of_engagement": {"allowed_techniques": ["metasploit-module"]},
        "msf": {"allowed_modules": ["auxiliary/scanner/ftp/ftp_version"]},
    }))
    out = await _call(
        REPO / "scripts" / "mcp_msf_server.py", "run_metasploit_module",
        {"host_target": "127.0.0.1", "module": "auxiliary/scanner/ftp/ftp_version"},
        env={
            "PENTEST_ENGAGEMENT_FILE": str(eng),
            "PENTEST_EXPLOIT_APPROVED": "smoke2-msf-001",
            "MSF_BACKEND": "sim",
        },
    )
    ok = (
        out.get("blocked") is not True
        and out.get("auth_reference") == "REF-SMOKE2"
        and out.get("engagement_id") == "smoke2-msf-001"
        and out.get("msf", {}).get("backend") == "sim"
    )
    print("ledger record:", json.dumps(out, ensure_ascii=False)[:300])
    return bool(ok)


async def main() -> int:
    ok1 = await smoke_osint()
    ok2 = await smoke_msf()
    print("== RESULTADO:", "OK" if ok1 and ok2 else "FAIL", "==")
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
