# pentest-agent

PoC de **auditoría de seguridad multi-agente** con LangGraph + **protocolo A2A**:

```
                         ┌────────────────────────┐
                         │  supervisor (LangGraph)│
                         │  rutea con Command     │
                         └───────┬────────┬───────┘
              A2A (JSON-RPC)     │        │     A2A (JSON-RPC)
        ┌────────────────────────┘        └────────────────────────┐
        ▼                                 ▼                        ▼
┌───────────────┐              ┌────────────────┐        ┌────────────────┐
│ recon_agent   │              │ vuln_agent     │        │ reporter_agent │
│ :9101 (A2A)   │              │ :9102 (A2A)    │        │ :9103 (A2A)    │
│ scan_host     │              │ find_cves      │        │ save_report    │
│ (nmap/py)     │              │ (NVD+KEV)      │        │ (markdown)     │
└───────────────┘              └────────────────┘        └────────────────┘
```

El supervisor es un grafo LangGraph manual (`Command`) cuyas tools de handoff
(`transfer_to_recon_agent`, etc.) rutean el grafo; cada worker es un **servicio
A2A independiente** (Agent Card en `/.well-known/agent.json`, JSON-RPC
`message/send`) que internamente es un `create_react_agent` con SUS herramientas.

Hay además dos modos extra:

- **in-process** (`agents.py::build_team`): supervisor `langgraph-supervisor`
  clásico, todo en un proceso (útil para comparar).
- **determinista** (`--no-llm`): scan → NVD → reporte sin LLM (CI/tests).

## Seguridad (innegociable)

1. **Scope allowlist** (`scope.yaml`): las tools rechazan targets fuera de la
   lista; la frontera es código, no prompt. Por defecto solo `127.0.0.1`.
2. **Cero explotación**: descubrimiento + correlación + reporte. Nada ofensivo.
3. **CVEs solo de tool calls**: prohibido citar CVEs que no devuelva `find_cves`.
4. **Escaneo no privilegiado**: connect-scan puro si no hay nmap; con nmap,
   `-sV -oX -` y parseo XML determinista.

## Arranque

```bash
cd pentest-agent
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 1) Subagentes A2A (terminales separadas o el script)
bash scripts/start_a2a_stack.sh        # recon 9101, vuln 9102, reporter 9103

# 2) Supervisor coordinando via A2A (requiere GLM_API_KEY en env o ~/.hermes/.env)
.venv/bin/python scripts/e2e_a2a.py    # audita 127.0.0.1 (demo)

# Alternativas
python -m pentest_agent --target 127.0.0.1 --no-llm     # determinista
python -m pentest_agent --target 127.0.0.1              # in-process
```

## Configuración

- **LLM**: GLM (z.ai) vía `GLM_API_KEY` (env o `~/.hermes/.env`, nunca se
  imprime). Otro provider OpenAI-compatible: `PENTEST_BASE_URL`, `PENTEST_API_KEY`,
  `PENTEST_MODEL`.
- **URLs A2A**: `A2A_RECON_URL`, `A2A_VULN_URL`, `A2A_REPORTER_URL` (defaults
  `127.0.0.1:9101/9102/9103`) — así puedes desparramar subagentes en máquinas
  distintas (ej: recon en la Raspberry Pi).

## Tests

```bash
pytest -q    # scope, parsing nmap/NVD, banner->query, A2A build/fail-safe
```

## Limitaciones honestas (roadmap)

- Matching versión→CVE por keyword NVD; el camino robusto es CPE exacto
  (`cpeMatch`), y nmap ya emite CPE.
- Sin NVD API key: rate limit estricto (~5 req/30s).
- Sin auth en los servidores A2A (PoC local). Producción: API key/bearer.
- Faltan: `searchsploit` como tool, subagente host-audit (SSH config) y K8s
  (`trivy`, `kube-bench`).
