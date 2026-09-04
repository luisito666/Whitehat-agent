"""Servidor MCP filesystem COMPLETO con jail (stdio).

Todas las rutas resuelven dentro de un directorio base (jail); ningún
operador puede salir de él (se rechazan '..' y absolutos fuera).

Base dir (primero que aplique):
    argv[1]                       (spawn del operador)
    PENTEST_FS_ROOT               (env)

Tools:
    list(path)                    -> entradas con tipo/tamano
    read_text(path, max_bytes)    -> contenido (rechaza binarios)
    write_text(path, content)     -> crear/sobrescribir (mkdir -p implicito)
    append_text(path, content)    -> anexar
    move(src, dst)                -> mover/renombrar dentro del jail
    remove(path)                  -> borrar archivo O directorio vacio
    mkdir(path)                   -> crear directorio
    tree(path, max_entries)       -> arbol recursivo
    search(pattern, subdirs)      -> grep recursivo de contenido
    sha256(path)                  -> hash de archivo
    info(path)                    -> tipo, tamano, mtimes, permisos

Uso (stdio):
    python scripts/mcp_fs_server.py /ruta/base
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_BASE = Path(
    sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PENTEST_FS_ROOT", "/tmp/pentest-reports")
).resolve()
_BASE.mkdir(parents=True, exist_ok=True)

m = FastMCP("filesystem-jail")


def _resolve(path: str) -> Path:
    """Resuelve dentro del jail o lanza PermissionError."""
    p = (_BASE / path).resolve() if path else _BASE
    if p != _BASE and _BASE not in p.parents:
        raise PermissionError(f"fuera del jail {p} (base={_BASE})")
    return p


def _is_binary(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            chunk = f.read(8192)
    except OSError:
        return False
    return b"\x00" in chunk


def _ok(msg: str) -> str:
    return f"OK {msg}"


@m.tool()
def list(path: str = "") -> str:
    """Lista entradas de un dir del jail: nombre, tipo, tamano."""
    try:
        p = _resolve(path)
        if not p.is_dir():
            return f"ERROR: no es directorio: {path}"
        lines = []
        for e in sorted(p.iterdir(), key=lambda x: x.name):
            kind = "dir" if e.is_dir() else "file"
            size = e.stat().st_size if e.is_file() else ""
            lines.append(f"{kind}\t{size}\t{e.name}")
        return "\n".join(lines) or "(vacio)"
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def read_text(path: str, max_bytes: int = 65536) -> str:
    """Lee un archivo de texto (binarios rechazados)."""
    try:
        p = _resolve(path)
        if not p.is_file():
            return f"ERROR: no es archivo: {path}"
        if _is_binary(p):
            return f"ERROR: binario (usa sha256/info): {path}"
        data = p.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def write_text(path: str, content: str) -> str:
    """Crea/sobrescribe un archivo de texto (mkdir -p implicito)."""
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return _ok(f"{p.relative_to(_BASE)} ({len(content)} chars)")
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def append_text(path: str, content: str) -> str:
    """Anexa texto a un archivo (lo crea si no existe)."""
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return _ok(f"append {len(content)} chars a {p.relative_to(_BASE)}")
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def move(src: str, dst: str) -> str:
    """Mueve/renomina dentro del jail (dst puede sobrescribir)."""
    try:
        s, d = _resolve(src), _resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        s.rename(d)
        return _ok(f"{src} -> {dst}")
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def remove(path: str) -> str:
    """Borra un archivo O un directorio VACIO."""
    try:
        p = _resolve(path)
        if p == _BASE:
            return "ERROR: no se borra la raiz del jail"
        if p.is_dir():
            if any(p.iterdir()):
                return f"ERROR: directorio no vacio: {path}"
            p.rmdir()
        elif p.exists():
            p.unlink()
        else:
            return f"ERROR: no existe: {path}"
        return _ok(f"removed {path}")
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def mkdir(path: str) -> str:
    """Crea un directorio (mkdir -p)."""
    try:
        p = _resolve(path)
        p.mkdir(parents=True, exist_ok=True)
        return _ok(str(p.relative_to(_BASE) if p != _BASE else "."))
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def tree(path: str = "", max_entries: int = 500) -> str:
    """Arbol recursivo del jail (recorta en max_entries)."""
    try:
        root = _resolve(path)
        lines, n = [], 0

        def walk(d: Path, prefix: str) -> None:
            nonlocal n
            for e in sorted(d.iterdir(), key=lambda x: x.name):
                n += 1
                if n > max_entries:
                    lines.append(prefix + "... (recortado)")
                    return
                lines.append(prefix + e.name + ("/" if e.is_dir() else ""))
                if e.is_dir():
                    walk(e, prefix + "  ")

        walk(root, "")
        return "\n".join(lines) or "(vacio)"
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def search(pattern: str, subdirs: str = "") -> str:
    """Busca pattern (texto literal) en contenido de archivos bajo subdirs."""
    import fnmatch

    try:
        base = _resolve(subdirs)
        hits = []
        for p in sorted(base.rglob("*")):
            if not p.is_file() or _is_binary(p):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern in text:
                rel = p.relative_to(_BASE)
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern in line:
                        hits.append(f"{rel}:{i}: {line.strip()[:150]}")
                        break  # primera linea por archivo
            if len(hits) >= 100:
                hits.append("... (recortado a 100)")
                break
        _ = fnmatch  # disponible para futuras mejoras de glob
        return "\n".join(hits) or f"sin resultados para {pattern!r}"
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def sha256(path: str) -> str:
    """SHA-256 de un archivo (cadena de custodia de evidencia)."""
    try:
        p = _resolve(path)
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(131072), b""):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


@m.tool()
def info(path: str) -> str:
    """Tipo, tamano, mtime y permisos de una ruta."""
    try:
        p = _resolve(path)
        if not p.exists() and p != _BASE:
            return f"ERROR: no existe: {path}"
        st = p.stat()
        import datetime

        mtime = datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        kind = "dir" if p.is_dir() else ("file" if p.is_file() else "otro")
        return (f"{kind} size={st.st_size} mtime={mtime} "
                f"mode={oct(st.st_mode & 0o777)} path={p.relative_to(_BASE) if p != _BASE else '.'}")
    except (PermissionError, OSError) as e:
        return f"ERROR: {e}"


if __name__ == "__main__":
    m.run(transport="stdio")
