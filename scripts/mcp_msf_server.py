"""Servidor MCP Metasploit (opt-in, stdio).

Expone run_msf_module — el CORE sin @tool — de pentest_agent.tools.msf.
Todos los gates viven DENTRO del core y corren en ESTE proceso:
engagement vigente + tecnica autorizada + allowlist de modulos +
PENTEST_EXPLOIT_APPROVED == engagement_id. Sin ellos, la tool devuelve
blocked SIN ejecutar nada (fail-closed).

Es un alternative delivery channel del mismo core nativo: si ya usas la
tool nativa run_metasploit_module, no necesitas este server. Valor real:
desacoplar el ciclo de release de msf.py del runtime de agents que
consumen metasploit (clients MCP estandar, no LangChain).

Uso (stdio):
    PYTHONPATH=src python scripts/mcp_msf_server.py
El proceso que lo spawnea (worker exploit) hereda el env aprobado.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# runnable como script: resolver el paquete si no esta instalado
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mcp.server.fastmcp import FastMCP  # noqa: E402

m = FastMCP("metasploit-gated")


@m.tool()
def run_metasploit_module(host_target: str, module: str, options_json: str = "{}") -> str:
    """Ejecuta un modulo Metasploit AUTORIZADO por el engagement (fail-closed).

    Requiere en ESTE proceso: PENTEST_ENGAGEMENT_FILE valido + modulo en la
    allowlist del engagement + PENTEST_EXPLOIT_APPROVED == engagement_id.
    Devuelve JSON del ledger (proven, session_opened, auth_reference) o
    {"blocked": reason} SIN ejecutar nada si algun gate falla.
    options_json: JSON string con opciones del modulo (RHOSTS, LHOST...).
    """
    import json

    from pentest_agent.tools.msf import run_msf_module
    from pentest_agent.engagement import EngagementError

    try:
        opts = json.loads(options_json) if options_json else {}
        return json.dumps(run_msf_module(host_target, module, opts))
    except EngagementError as e:
        return json.dumps({"blocked": True, "reason": str(e)})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": type(e).__name__, "detail": str(e)})


@m.tool()
def engagement_status() -> str:
    """Estado de los gates ofensivos en este proceso (sin exponer secretos)."""
    import json

    from pentest_agent.engagement import EngagementError, load_engagement

    env_file = os.environ.get("PENTEST_ENGAGEMENT_FILE")
    approved = os.environ.get("PENTEST_EXPLOIT_APPROVED", "")
    try:
        eng = load_engagement()
        eng.assert_valid()
        return json.dumps({
            "engagement": eng.id,
            "approved": approved == eng.id,
            "allowed_modules": (eng.data.get("msf") or {}).get("allowed_modules") or [],
            "env_file": bool(env_file),
        })
    except EngagementError as e:
        return json.dumps({"blocked": str(e), "env_file": bool(env_file)})


if __name__ == "__main__":
    m.run(transport="stdio")
