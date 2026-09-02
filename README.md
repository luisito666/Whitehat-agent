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

## Modo ofensivo (whitehat PoC) — fail-closed por diseño

El flujo de venta: demostrarle al cliente que el hueco es real ("leímos el
canary, aquí está el hash"). Para eso existe `exploit_agent` (:9104), pero con
**triple llave** — todas deben abrirse o no se ejecuta nada:

1. **Engagement** (`engagement.yaml`, NO se commitea): cliente, referencia de
   autorización escrita, ventana de vigencia, scope y técnicas permitidas.
   Las tools ofensivas **no tienen default**: sin archivo válido, fallan.
2. **Aprobación humana** (`python -m pentest_agent.approve` → exporta
   `PENTEST_EXPLOIT_APPROVED=<engagement_id>` en el proceso del SERVIDOR
   exploit). El LLM/supervisor/cliente no pueden inyectarla.
3. **Técnica autorizada y no prohibida** — `prohibited` se evalúa primero
   (un typo en `allowed` no puede habilitar algo vetado).

Reglas del PoC: **no destructivo** (leer UN canary, hash sha256, cero
exfiltración real, cero persistencia/DoS/lateral). Todo queda en el ledger
append-only `reports/evidence.jsonl` — cadena de custodia con timestamp,
técnica, URL, hash y referencia de autorización. Ese ledger es parte del
deliverable para el cliente.

Lab para desarrollar/demos: `python -m pentest_agent.lab` (app vulnerable
estilo CVE-2021-41773 con canary, SOLO loopback).

```bash
# Flujo ofensivo completo (lab)
cp engagement.example.yaml engagement.yaml     # adaptar por cliente real
python -m pentest_agent.lab                    # target vulnerable (lab)
python -m pentest_agent.approve                # TU apruebas -> export var
PENTEST_EXPLOIT_APPROVED=... python -m pentest_agent.a2a_server --role exploit --port 9104
export A2A_EXPLOIT_URL=http://127.0.0.1:9104   # habilita handoff en supervisor
python scripts/e2e_a2a.py                      # auditoria con demo de impacto
```

**Línea honesta:** lo que hay aquí es un *verificador de impacto* (canary
proof), no exploits weaponizados. Cadenas de explotación reales se agregan
por-engagement, bajo contrato, como tools específicas con su técnica
declarada en el engagement.

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
