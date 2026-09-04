"""Smoke E2E: reporter worker carga y USA una tool MCP real (filesystem).

Levanta el A2A server reporter con mcp_servers.yaml apuntando al server
MCP filesystem propio, manda un mensaje por A2A pidiendo guardar un
mini-report, y verifica el archivo en disco.

Uso:
    .venv/bin/python scripts/mcp_smoke.py
"""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    outdir = Path(tempfile.mkdtemp(prefix="mcp-smoke-"))
    cfg = REPO / "mcp_servers.yaml"
    cfg.write_text(yaml.safe_dump({
        "reporter": [{
            "name": "artifacts-fs",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(REPO / "scripts" / "mcp_fs_server.py"), str(outdir)],
        }],
    }), encoding="utf-8")

    # arrancar el worker A2A reporter
    port = 9103
    proc = subprocess.Popen(
        [str(REPO / ".venv/bin/python"), "-m", "pentest_agent.a2a_server",
         "--role", "reporter", "--port", str(port)],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        import time
        import httpx

        for _ in range(30):
            time.sleep(0.5)
            try:
                httpx.get(f"http://127.0.0.1:{port}/.well-known/agent.json", timeout=1)
                break
            except Exception:
                if proc.poll() is not None:
                    print("worker murio:", proc.stdout.read() if proc.stdout else "")
                    return 1
        else:
            print("worker no respondio")
            return 1

        from pentest_agent.a2a_client import safe_call_agent

        reply = safe_call_agent(f"http://127.0.0.1:{port}/", (
            "Guarda un mini reporte de prueba usando la tool MCP write_report "
            "con filename 'smoke.md' y contenido '# Smoke MCP\\n\\nE2E OK'. "
            "Responde el resultado de la tool tal cual."
        ))
        print("reply:", reply[:400])
        f = outdir / "smoke.md"
        if f.exists() and "E2E OK" in f.read_text(encoding="utf-8"):
            print(f"SMOKE OK: {f}")
            return 0
        print(f"FAIL: {f} no existe o sin contenido")
        return 1
    finally:
        proc.terminate()
        cfg.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
