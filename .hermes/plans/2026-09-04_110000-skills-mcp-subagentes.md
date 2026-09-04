# Skills + MCP para los subagentes del pentest-agent — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Agregar (1) un sistema de skills por rol (markdown inyectado en el system prompt de cada subagente) y (2) tools MCP (Model Context Protocol) cargables por rol, manteniendo el diseño fail-closed: las tools MCP del exploit_agent solo se registran si la triple llave (scope + engagement + aprobación en proceso) está abierta.

**Architecture:** Los workers A2A ya se construyen como `create_react_agent(llm, spec["tools"], spec["prompt"])` en `ReactAgentExecutor._get_agent()` (lazy, al primer request). El plan extiende ese punto único de construcción: (a) el prompt pasa a ser `PROMPT + skills_md(role)` leído de `skills/<role>/*.md`; (b) la lista de tools pasa a ser `native + load_mcp_tools(role)`, donde `load_mcp_tools` usa `MultiServerMCPClient` de `langchain-mcp-adapters` con config declarativa por rol y **no registra nada** para el rol exploit sin gates abiertos.

**Tech Stack:** Python 3.11, LangGraph/LangChain (existentes), `langchain-mcp-adapters>=0.1` (nuevo), pytest.

---

## Contexto actual (verificado en el repo)

- Repo: `/home/luisito/workdir/pentest-agent`, rama main, suite 56/56 verde.
- Workers A2A: `src/pentest_agent/a2a_server.py` — dict `ROLES` (name/description/port/tools/prompt por rol: recon :9101, vuln :9102, reporter :9103, exploit :9104) + `ReactAgentExecutor` que construye el ReAct agent lazy.
- Modo in-process: `src/pentest_agent/agents.py::build_team` (mismos ROLES/prompt centralizados).
- Tools nativas: `src/pentest_agent/tools/{scanner,vuln,exploit,msf,pysnippet}.py`.
- Safety: `scope.yaml` allowlist + `engagement.yaml` + `PENTEST_EXPLOIT_APPROVED` en el proceso del server exploit (ver `engagement.py`).
- Patrón existente a reusar: `_react_agent()` tolera drift de versiones de LangGraph inspeccionando la firma — hacer lo mismo con la API de `langchain-mcp-adapters` (ha cambiado entre versiones: `async with client:` + `get_tools()` vs `client.get_tools()` directo).

## Decisiones de diseño

1. **Skills = markdown plano por rol, versionado en el repo** (`skills/<role>/*.md`), concatenado en orden alfabético. Sin frontmatter estilo Hermes: los workers no son agentes conversacionales con curador; la simplicidad gana. El repo es el distribuidor.
2. **MCP config declarativa**: `mcp_servers.yaml` (gitignored, con `mcp_servers.example.yaml` commiteado). Estructura: por rol → lista de servidores stdio/http. Credenciales solo por env vars, nunca en el yaml.
3. **Fail-closed para MCP del exploit**: la carga de servidores MCP del rol exploit ocurre SOLO si `engagement` válido + `PENTEST_EXPLOIT_APPROVED` en el proceso. Sin gates → ni siquiera se exponen los schemas de tools MCP al LLM (superficie mínima). Los servidores stdio spawn como hijos del proceso server A2A → heredan el env del proceso aprobado, un cliente A2A malicioso no puede inyectarlos.
4. **Roles no ofensivos** (recon/vuln/reporter): MCP se carga libre PERO las tools MCP pasan por un wrapper de scope (misma validación de target que las nativas) cuando aplican a targets de red.
5. **YAGNI fase 1**: infraestructura + 1 servidor MCP real de prueba (reporter/filesystem). Metasploit-MCP y OSINT-MCP quedan en fase 2 (ver "Out of scope").

---

### Task 1: Módulo loader de skills

**Objective:** Función pura que lee y concatena `skills/<role>/*.md`.

**Files:**
- Create: `src/pentest_agent/skills.py`
- Test: `tests/test_skills_loader.py`

**Step 1: Write failing test**

```python
# tests/test_skills_loader.py
from pathlib import Path
from pentest_agent.skills import load_skills

def test_load_skills_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    assert load_skills("recon") == ""

def test_load_skills_concatenates_alphabetical(tmp_path, monkeypatch):
    root = tmp_path / "skills" / "recon"
    root.mkdir(parents=True)
    (root / "b-method.md").write_text("## Metodo B")
    (root / "a-method.md").write_text("## Metodo A")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    out = load_skills("recon")
    assert out.index("Metodo A") < out.index("Metodo B")
    assert out.startswith("## Metodo A")

def test_load_skills_ignores_non_md(tmp_path, monkeypatch):
    root = tmp_path / "skills" / "recon"
    root.mkdir(parents=True)
    (root / "note.txt").write_text("x")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    assert load_skills("recon") == ""
```

**Step 2:** Run `pytest tests/test_skills_loader.py -v` → FAIL (no module).

**Step 3: Implementación mínima**

```python
# src/pentest_agent/skills.py
"""Skills por rol: markdown del repo inyectado en el system prompt del worker."""
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent / "skills"

def load_skills(role: str) -> str:
    """Concatena skills/<role>/*.md en orden alfabético. '' si no hay nada."""
    d = SKILLS_ROOT / role
    if not d.is_dir():
        return ""
    parts = [p.read_text(encoding="utf-8").rstrip() for p in sorted(d.glob("*.md"))]
    return "\n\n---\n\n".join(parts)
```

**Step 4:** Run → PASS (3 tests).
**Step 5:** `git add -A && git commit -m "feat(skills): role-scoped markdown loader"`

### Task 2: Contenido inicial de skills (migración desde prompts)

**Objective:** Crear `skills/` con contenido real extraído de lo que ya sabe cada agente.

**Files:**
- Create: `skills/recon/scanning-methodology.md`, `skills/vuln/cve-correlation.md`, `skills/reporter/report-standards.md`, `skills/exploit/msf-runbook.md`

Contenido inicial (2-4 secciones cada uno, conocimiento ya implícito en los prompts/tools actuales):
- recon: orden de scan (ports → services → fingerprint TLS/HTTP), interpretación de banners, cuándo usar nmap vs fallback Python.
- vuln: cómo correlacionar producto+versión con NVD, qué es KEV y cuándo escala a exploit (CRITICO/KEV), formato de un hallazgo.
- reporter: estructura del informe (resumen ejecutivo → hallazgos con evidencia hasheada → remediación), regla: todo hallazgo cita su fuente (scan/CVE/proof).
- exploit: runbook de msfrpcd (módulo → check → exploit con payload → sesión), reglas de evidencia no destructiva (canary read-only, un marcador), triple llave.

**Step 1:** Escribir los 4 archivos.
**Step 2:** `pytest tests/test_skills_loader.py -v` sigue PASS (loader real ahora encuentra contenido — no hay test de contenido).
**Step 3:** Commit: `feat(skills): initial per-role skill content`

### Task 3: Inyectar skills en el prompt del worker A2A

**Objective:** El ReAct agent del worker A2A recibe `prompt + skills`.

**Files:**
- Modify: `src/pentest_agent/a2a_server.py` (en `ReactAgentExecutor._get_agent`, ~línea 92)

```python
def _get_agent(self):
    from .llm import get_llm
    from .skills import load_skills
    if self._agent is None:
        spec = ROLES[self.role]
        skills_md = load_skills(self.role)
        prompt = spec["prompt"] if not skills_md else (
            f"{spec['prompt']}\n\n# Guia de procedimiento (skills)\n\n{skills_md}"
        )
        self._agent = _react_agent(get_llm(), spec["tools"], prompt)
    return self._agent
```

**Step 1: Write failing test** — `tests/test_a2a_server_skills.py`: monkeypatch `SKILLS_ROOT` a tmp con `skills/recon/x.md` = "RECONSKILL123", construir `ReactAgentExecutor("recon")`, llamar `_get_agent()` con LLM stub (reusar el patrón de tests existentes: fake llm), assert "RECONSKILL123" aparece en el prompt del agent construido (inspeccionar `agent.nodes` / prompt attr según versión — si es opaco, extraer la construcción a una función pura `_build_prompt(role)` y testear esa: **preferir esto**, más robusto).

Mejor: refactor mínimo a `def _build_prompt(role: str) -> str` en `a2a_server.py` y testearla directa.

**Step 2:** FAIL → **Step 3:** implementar → **Step 4:** PASS.
**Step 5:** Commit: `feat(skills): inject role skills into A2A worker prompts`

### Task 4: Inyectar skills en modo in-process

**Objective:** `build_team()` (agents.py) usa el mismo `_build_prompt`.

**Files:**
- Modify: `src/pentest_agent/agents.py` (`build_team`, donde pasa `spec["prompt"]`)

**Step 1:** Test `tests/test_agents_skills.py`: mismo patrón del Task 3 contra `build_team` con fake llm (o contra `_build_prompt` importado — ya cubierto; aquí basta smoke test de que `build_team` no rompe).
**Step 2-4:** FAIL → implement → PASS (suite completa: `pytest -q`, 56+tests verde).
**Step 5:** Commit: `feat(skills): skills in in-process team mode`

### Task 5: Dependencia MCP + config loader

**Objective:** Parsear `mcp_servers.yaml` por rol sin cargar servidores todavía.

**Files:**
- Modify: `pyproject.toml` (optional group `[project.optional-dependencies] mcp = ["langchain-mcp-adapters>=0.1"]`)
- Create: `src/pentest_agent/mcp_config.py`
- Create: `mcp_servers.example.yaml`

```yaml
# mcp_servers.example.yaml — copiar a mcp_servers.yaml (gitignored). Credenciales SOLO por env.
reporter:
  - name: artifacts-fs
    transport: stdio
    command: python
    args: ["-m", "mcp_server_filesystem", "/tmp/pentest-reports"]
vuln: []          # fase 2: NVD/OSV MCP
recon: []         # fase 2: OSINT
exploit: []       # fase 2: metasploit MCP (BAJO TRIPLE LLAVE)
```

```python
# src/pentest_agent/mcp_config.py
"""Config MCP por rol. Sin archivo o sin entrada para el rol -> []."""
from pathlib import Path
import yaml

MCP_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "mcp_servers.yaml"

def load_mcp_config(role: str) -> list[dict]:
    if not MCP_CONFIG_PATH.is_file():
        return []
    data = yaml.safe_load(MCP_CONFIG_PATH.read_text()) or {}
    servers = data.get(role) or []
    assert isinstance(servers, list)
    return servers
```

**Step 1:** Tests `tests/test_mcp_config.py`: sin archivo → []; rol ausente → []; rol con 2 servidores → lista de 2 dicts; yaml inválido → raise (dejar tronar, fail-closed por omisión de tools… no: tronar al arrancar es mejor que correr sin tools silenciosamente — documentar).
**Step 2-4:** TDD cycle.
**Step 5:** `git add pyproject.toml mcp_servers.example.yaml src/pentest_agent/mcp_config.py tests/ && git commit -m "feat(mcp): per-role server config loader"`
**Step 6:** `.venv/bin/pip install -e '.[mcp,dev,msf]'` y verificar `import langchain_mcp_adapters`.

### Task 6: Cargador de tools MCP (con fake server)

**Objective:** `load_mcp_tools(role)` devuelve `list[BaseTool]` reales de `MultiServerMCPClient`.

**Files:**
- Create: `src/pentest_agent/mcp.py`
- Create: `tests/fixtures/mini_mcp_server.py` (server MCP stdio mínimo con 1 tool `echo`)

```python
# src/pentest_agent/mcp.py
"""Carga tools MCP por rol como LangChain BaseTools. Fail-closed para exploit."""
import asyncio, inspect
from .mcp_config import load_mcp_config

def _gates_open(role: str) -> bool:
    if role != "exploit":
        return True
    import os
    if not os.environ.get("PENTEST_EXPLOIT_APPROVED"):
        return False
    from .engagement import load_engagement  # valida engagement.yaml real
    try:
        load_engagement(); return True
    except Exception:
        return False

async def _load(role: str) -> list:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    servers = load_mcp_config(role)
    if not servers:
        return []
    # normaliza el nombre de campo command/args/transport según versión
    client = MultiServerMCPClient({s["name"]: {k: v for k, v in s.items() if k != "name"} for s in servers})
    if inspect.iscoroutinefunction(getattr(client, "get_tools", None)):
        return await client.get_tools()
    async with client:  # API vieja
        return client.get_tools()

def load_mcp_tools(role: str) -> list:
    if not _gates_open(role):
        return []  # fail-closed: ni schemas expuestos
    return asyncio.run(_load(role))
```

`tests/fixtures/mini_mcp_server.py`: implementar con `mcp` SDK (FastMCP) una tool `echo(text) -> text`. Es la misma dependencia que trae langchain-mcp-adapters.

**Step 1:** Test `tests/test_mcp_loader.py`:
- `load_mcp_tools("recon")` con config vacía → `[]`.
- Con config apuntando al fake server (transport stdio, command = sys.executable, args = [fixture path]) → lista con tool cuyo name contiene "echo", y `tool.invoke({"text": "hi"})` == "hi".
- `load_mcp_tools("exploit")` sin env/approval → `[]` aunque haya config (monkeypatch config con servidor).
**Step 2-4:** TDD (ajustar llamada a la versión real instalada de langchain-mcp-adapters: la normalización por firma como en `_react_agent`).
**Step 5:** Commit: `feat(mcp): load MCP tools per role, fail-closed for exploit`

### Task 7: Wrapper de scope para tools MCP de red (roles no ofensivos)

**Objective:** Las tools MCP que reciben un host/target (recon) validan contra `scope.assert_allowed` como las nativas.

**Files:**
- Modify: `src/pentest_agent/mcp.py` — añadir `wrap_scope(tool)` que envuelve `arun`/`_run` validando campos `host`/`target`/`url` del input si existen.
- Test: `tests/test_mcp_scope_wrap.py` — fake BaseTool con campo host; host fuera de scope → excepción de scope, dentro → pasa.

**Step 1-4:** TDD. **Step 5:** Commit: `feat(mcp): scope-gate MCP tools that take network targets`

### Task 8: Integración en el worker A2A

**Objective:** El agente del worker usa tools nativas + MCP.

**Files:**
- Modify: `src/pentest_agent/a2a_server.py` — en `_get_agent`:

```python
from .mcp import load_mcp_tools
tools = list(spec["tools"]) + load_mcp_tools(self.role)
self._agent = _react_agent(get_llm(), tools, _build_prompt(self.role))
```

Nota: `_get_agent` corre en `asyncio.to_thread` → `asyncio.run` dentro de `load_mcp_tools` es seguro (hilo propio sin loop).

**Step 1:** Test de integración: monkeypatch `load_mcp_tools` para devolver una tool fake; construir executor reporter; assert la tool está en las tools del agent (extraer `_build_tools(role)` como función pura y testearla, mismo refactor que `_build_prompt`).
**Step 2-4:** TDD; correr **suite completa** `pytest -q` → todo verde.
**Step 5:** Commit: `feat(mcp): workers load native + MCP tools`

### Task 9: Un servidor MCP real (reporter/filesystem) — smoke E2E

**Objective:** Demo real de la vía MCP: reporter escribe el informe a disco vía tool MCP filesystem (no vía Python directo).

**Steps:**
1. `pip install mcp-server-filesystem` (o `npx @modelcontextprotocol/server-filesystem` si prefieres Node — decisión del implementador, documentar en README).
2. `cp mcp_servers.example.yaml mcp_servers.yaml`, configurar dir de salida `reports-out/` (gitignored).
3. Arrancar `a2a-server --role reporter`, mandarle un mensaje de prueba con `safe_call_agent` (script `scripts/mcp_smoke.py`) pidiendo guardar un mini-report.
4. Verificar `reports-out/*.md` existe con el contenido.
5. Commit script: `feat(mcp): E2E smoke — reporter writes report via filesystem MCP`

### Task 10: Docs + PR

1. README: sección "Skills" (cómo añadir `skills/<rol>/*.md`) y "MCP" (yaml, fail-closed del exploit, qué corre en fase 2).
2. `pytest -q` completo verde; `git push` a rama `feat/skills-mcp`; `gh pr create` con resumen de safety properties. **No mergear sin review de Luis.**

---

## Validación global

- `pytest -q` → suite crecida (~65+ tests) verde.
- Smoke in-process: `pentest-audit` determinista sigue funcionando (skills no rompen modo `--no-llm`).
- Fail-closed demo: quitar env `PENTEST_EXPLOIT_APPROVED` → exploit worker arranca SIN tools MCP aunque haya config.
- E2E reporter/filesystem del Task 9.

## Riesgos / tradeoffs

- **Drift de API de langchain-mcp-adapters**: mitigado con normalización por firma (patrón `_react_agent` ya probado en el repo).
- **Subprocesos stdio MCP**: hijos del proceso worker → en exploit heredan env de aprobación (propiedad, no bug). Documentar que `mcp_servers.yaml` es trust boundary: solo el operador lo escribe (gitignored).
- **Contexto de prompt**: skills muy largas inflan tokens de cada request. Regla: <2KB por archivo de skill por ahora; reevaluar si crece.
- **mcp-server-filesystem** da acceso de escritura a un dir: acotar al dir de reports, no al home.

## Out of scope (fase 2 — no construir ahora)

- metasploit MCP server (envolver msfrpcd como MCP) → reemplazaría la integración nativa `tools/msf.py`; solo si aporta valor sobre lo nativo.
- OSINT MCP (Shodan/Censys) para recon — requiere API keys de pago.
- Skills dinámicas por cliente (p.ej. `engagement.yaml` referencia skills extra).
