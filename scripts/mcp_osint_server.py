"""Servidor MCP OSINT pasivo y keyless (stdio).

Tools de inteligencia pasiva sobre dominios propios del cliente, SIN API
keys de pago: certificate transparency (crt.sh) para descubrir subdominios.

Seguridad:
- Pasivo: solo consulta fuentes publicas; cero contacto con la infra del
  cliente (no scan, no exploit).
- Scope: en modo ofensivo (PENTEST_ENGAGEMENT_FILE presente) exige que el
  dominio este en engagement.osint.allowed_domains. Sin engagement, la
  tool exige confirmacion explicita de propiedad via env
  PENTEST_OSINT_CONFIRM_DOMAIN (para demos/labs con dominio propio).

Uso (stdio):
    PYTHONPATH=src python scripts/mcp_osint_server.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import httpx  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

m = FastMCP("osint-passive")

CRT_SH = "https://crt.sh/?output=json&q={q}"


def _crt_sh_query(domain: str) -> list[dict]:
    """Consulta crt.sh con wildcard + reintentos. crt.sh es inestable (502
    intermitentes incluso para dominios validos): reintenta con backoff."""
    import time

    q = urllib.parse.quote(f"%.{domain}", safe="")
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            with httpx.Client(timeout=45) as http:
                resp = http.get(
                    CRT_SH.format(q=q),
                    headers={"User-Agent": "pentest-agent-osint/0.1"},
                )
                if resp.status_code in (502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"crt.sh {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:  # noqa: BLE001 - reintenta y reporta el ultimo
            last_exc = e
            time.sleep(2 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _domain_allowed(domain: str) -> tuple[bool, str]:
    """Gate: dominio en engagement.osint.allowed_domains o confirmacion env."""
    eng_path = os.environ.get("PENTEST_ENGAGEMENT_FILE")
    if eng_path and Path(eng_path).exists():
        import yaml

        try:
            data = yaml.safe_load(Path(eng_path).read_text()) or {}
            allowed = ((data.get("osint") or {}).get("allowed_domains")) or []
            if domain.lower() in [str(a).lower() for a in allowed]:
                return True, "engagement"
            return False, (
                f"dominio {domain!r} fuera de engagement.osint.allowed_domains"
            )
        except Exception as e:  # yaml roto = fail-closed
            return False, f"engagement ilegible: {e}"
    # sin engagement (modo demo/lab): confirmacion explicita por env
    confirmed = os.environ.get("PENTEST_OSINT_CONFIRM_DOMAIN", "")
    if domain.lower() == confirmed.lower():
        return True, "env-confirm"
    return False, (
        f"sin engagement: exporta PENTEST_OSINT_CONFIRM_DOMAIN={domain} "
        "para autorizar este dominio (demo/lab con dominio propio)"
    )


@m.tool()
def ct_subdomains(domain: str, limit: int = 100) -> str:
    """Subdominios historicos via certificate transparency (crt.sh, keyless).

    Pasivo: consulta logs publicos de CT, sin tocar la infra del dominio.
    El dominio debe estar autorizado (engagement.osint.allowed_domains o
    PENTEST_OSINT_CONFIRM_DOMAIN en labs).
    """
    ok, why = _domain_allowed(domain)
    if not ok:
        return json.dumps({"blocked": True, "reason": why})

    try:
        rows = _crt_sh_query(domain)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": type(e).__name__, "detail": str(e)[:300]})

    names: set[str] = set()
    for row in rows:
        for name_field in (row.get("common_name"), row.get("name_value")):
            if not name_field:
                continue
            for n in str(name_field).split("\n"):
                n = n.strip().lstrip("*.").lower()
                if n and n.endswith(domain.lower()):
                    names.add(n)
    return json.dumps(
        {"domain": domain, "source": "crt.sh", "count": len(names),
         "names": sorted(names)[:limit]},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    m.run(transport="stdio")
