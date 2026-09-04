"""Servidor MCP filesystem minimo para artifacts del pentest-agent.

Solo expone write_file (crear markdown en un dir de salida) y list_files.
El directorio base se fija al arrancar: toda escritura queda confinada ahi.

Uso (stdio):
    python scripts/mcp_fs_server.py /ruta/de/salida
"""
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

BASE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("/tmp/pentest-reports")
BASE.mkdir(parents=True, exist_ok=True)

m = FastMCP("artifacts-fs")


@m.tool()
def write_report(filename: str, content: str) -> str:
    """Escribe un reporte markdown. filename sin rutas (solo nombre plano)."""
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        return f"ERROR: filename invalido {filename!r}"
    p = BASE / filename
    p.write_text(content, encoding="utf-8")
    return f"OK {p}"


@m.tool()
def list_reports() -> str:
    """Lista los reportes guardados."""
    return "\n".join(sorted(p.name for p in BASE.glob("*.md"))) or "(vacio)"


if __name__ == "__main__":
    m.run(transport="stdio")
