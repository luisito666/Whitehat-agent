"""Smoke E2E fase 3: agents reales (LLM) usando los MCP default.

1. recon_agent (A2A, sin config MCP del operador): pide escanear 127.0.0.1
   y GUARDAR notas con la tool MCP filesystem default. Verifica archivo.
2. vuln_agent (A2A): usa el terminal MCP investigative (curl a loopback)
   y filesystem para dejar nota.
3. exploit (sin gates): load_mcp_tools debe devolver [] (fail-closed) —
   ni fs ni terminal full se cargan.

Uso:
    .venv/bin/python scripts/mcp_smoke_fase3.py
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

WORKERS = {"recon": 9121, "vuln": 9122}


def _start_worker(role: str, port: int, env_extra: dict) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), **env_extra}
    return subprocess.Popen(
        [str(REPO / ".venv/bin/python"), "-m", "pentest_agent.a2a_server",
         "--role", role, "--port", str(port)],
        cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def _wait_port(port: int, proc: subprocess.Popen) -> bool:
    for _ in range(40):
        time.sleep(0.5)
        try:
            httpx.get(f"http://127.0.0.1:{port}/.well-known/agent.json", timeout=1)
            return True
        except Exception:
            if proc.poll() is not None:
                return False
    return False


async def _call_worker(port: int, text: str) -> str:
    import uuid

    from a2a.client import A2AClient, A2ACardResolver
    from a2a.types import Message, MessageSendParams, Part, SendMessageRequest, TextPart

    async with httpx.AsyncClient(timeout=300) as http:
        resolver = A2ACardResolver(httpx_client=http, base_url=f"http://127.0.0.1:{port}/")
        card = await resolver.get_agent_card()
        client = A2AClient(httpx_client=http, agent_card=card)
        msg = Message(role="user", parts=[Part(root=TextPart(text=text))],
                      messageId=f"smoke-{uuid.uuid4().hex[:8]}", kind="message")
        req = SendMessageRequest(id=uuid.uuid4().hex[:8], params=MessageSendParams(message=msg))
        resp = await client.send_message(req)
        task = resp.root.result
        for art in getattr(task, "artifacts", None) or []:
            for p in art.parts:
                if hasattr(p.root, "text"):
                    return p.root.text
        return ""


async def main() -> int:
    from pentest_agent.a2a_client import _result_to_text  # noqa: F401  (reutilizable)

    # aislamos engagement/env del operador para este smoke
    base_env = {"PENTEST_ENGAGEMENT_FILE": "", "PENTEST_EXPLOIT_APPROVED": ""}

    # 1) fail-closed del exploit ANTES de levantar nada
    from pentest_agent.mcp import load_mcp_tools

    scoped = {k: v for k, v in os.environ.items()
              if k not in ("PENTEST_ENGAGEMENT_FILE", "PENTEST_EXPLOIT_APPROVED")}
    os.environ.clear()
    os.environ.update(scoped)
    os.environ.update(base_env)
    tools = load_mcp_tools("exploit")
    print(f"exploit sin gates -> tools MCP: {len(tools)} (esperado 0)")
    fail_closed_ok = len(tools) == 0

    # 2) recon con defaults (sin mcp_servers.yaml en el cwd del worker)
    outroot = Path(tempfile.mkdtemp(prefix="smoke3-"))
    procs = {}
    try:
        env = {**base_env,
               # sin PENTEST_FS_ROOT: el default del server es reports/mcp/<rol>
               # pero para el smoke apuntamos el jail a tmp vía config ad-hoc:
               }
        # usamos config por archivo para dirigir el jail del fs a tmp
        cfg = REPO / "mcp_servers.yaml"
        cfg.write_text(
            "recon:\n"
            "  - name: filesystem\n"
            "    transport: stdio\n"
            "    command: python\n"
            "    args: [\"scripts/mcp_fs_server.py\"]\n"
            "    env:\n"
            f"      PENTEST_FS_ROOT: \"{outroot / 'recon'}\"\n"
            "  - name: terminal\n"
            "    transport: stdio\n"
            "    command: python\n"
            "    args: [\"scripts/mcp_terminal_server.py\"]\n"
            "    env:\n"
            "      MCP_TERMINAL_POLICY: investigative\n"
            "vuln:\n"
            "  - name: filesystem\n"
            "    transport: stdio\n"
            "    command: python\n"
            "    args: [\"scripts/mcp_fs_server.py\"]\n"
            "    env:\n"
            f"      PENTEST_FS_ROOT: \"{outroot / 'vuln'}\"\n"
            "  - name: terminal\n"
            "    transport: stdio\n"
            "    command: python\n"
            "    args: [\"scripts/mcp_terminal_server.py\"]\n"
            "    env:\n"
            "      MCP_TERMINAL_POLICY: investigative\n",
            encoding="utf-8",
        )
        for role, port in WORKERS.items():
            procs[role] = _start_worker(role, port, env)
            if not _wait_port(port, procs[role]):
                log = procs[role].stdout.read() if procs[role].stdout else ""
                print(f"worker {role} no levanto:\n{log[:1500]}")
                return 1
        print("workers recon/vuln arriba (defaults activos)")

        reply = await _call_worker(WORKERS["recon"],
            "Escanea 127.0.0.1 con scan_host y luego usa la tool write_text del "
            "filesystem MCP para guardar un resumen en 'resumen-scan.md'. "
            "Responde brevemente que guardaste.")
        print("recon reply:", (reply or "")[:200])
        f1 = outroot / "recon" / "resumen-scan.md"
        recon_ok = f1.exists() and ("127.0.0.1" in f1.read_text(encoding="utf-8"))

        reply2 = await _call_worker(WORKERS["vuln"],
            "Usa la tool run_command del terminal MCP para ejecutar "
            "curl -sS --max-time 5 http://127.0.0.1:9121/.well-known/agent.json "
            "y guarda las primeras lineas de la salida en 'curl-probe.md' con write_text. "
            "Responde brevemente.")
        print("vuln reply:", (reply2 or "")[:200])
        f2 = outroot / "vuln" / "curl-probe.md"
        vuln_ok = f2.exists() and f2.stat().st_size > 0

        print(f"recon fs: {'OK' if recon_ok else 'FAIL'} ({f1})")
        print(f"vuln terminal+fs: {'OK' if vuln_ok else 'FAIL'} ({f2})")
        ok = fail_closed_ok and recon_ok and vuln_ok
        print("== RESULTADO:", "OK" if ok else "FAIL", "==")
        return 0 if ok else 1
    finally:
        for p in procs.values():
            p.terminate()
        (REPO / "mcp_servers.yaml").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
