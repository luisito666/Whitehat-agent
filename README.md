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
                                        │ hallazgo CRITICO/KEV
                                        ▼ (opcional, triple llave)
                        ┌───────────────────────────────┐
                        │ exploit_agent  :9104 (A2A)    │
                        │ prove_vulnerability (canary)  │
                        │ run_metasploit_module         │
                        │ run_python_snippet            │
                        └───────────────────────────────┘
```

El supervisor es un grafo LangGraph manual (`Command`) cuyas tools de handoff
(`transfer_to_recon_agent`, etc.) rutean el grafo; cada worker es un **servicio
A2A independiente** (Agent Card en `/.well-known/agent.json`, JSON-RPC
`message/send`) que internamente es un `create_react_agent` con SUS herramientas.
Todos los system prompts de los agentes están centralizados en
`src/pentest_agent/agents.py` (`EXPLOIT_PROMPT` incluido).

Hay además dos modos extra:

- **in-process** (`agents.py::build_team`): supervisor `langgraph-supervisor`
  clásico, todo en un proceso (útil para comparar).
- **determinista** (`--no-llm`): scan → NVD → reporte sin LLM (CI/tests).

## Modo ofensivo (whitehat) — fail-closed por diseño

El flujo de venta: demostrarle al cliente que el hueco es **real y explotable**
("leímos el canary, obtuvimos shell de root; aquí está el hash y la referencia
de autorización"). Para eso existe `exploit_agent` (:9104), que solo se registra
en el supervisor si el operador exporta `A2A_EXPLOIT_URL`, y cuyas tools tienen
**triple llave** — todas deben abrirse o no se ejecuta nada:

1. **Engagement** (`engagement.yaml`, NO se commitea): cliente, referencia de
   autorización escrita, ventana de vigencia, scope y técnicas permitidas.
   Las tools ofensivas **no tienen default**: sin archivo válido, fallan.
2. **Aprobación humana** (`python -m pentest_agent.approve` → exporta
   `PENTEST_EXPLOIT_APPROVED=<engagement_id>` en el proceso del SERVIDOR
   exploit). El LLM/supervisor/cliente no pueden inyectarla.
3. **Técnica autorizada y no prohibida** — `prohibited` se evalúa primero
   (un typo en `allowed` no puede habilitar algo vetado).

### Las 3 tools del exploit_agent

| tool | qué hace | contención |
|---|---|---|
| `prove_vulnerability` | PoC path-traversal: leer UN canary, sha256, cero exfiltración | scope + triple llave |
| `run_metasploit_module` | Ejecuta UN módulo de la **allowlist exacta** del engagement (`msf.allowed_modules`) vía msfrpcd; detecta sesión y la prueba (`id`) | allowlist por módulo + triple llave |
| `run_python_snippet` | Python ad-hoc del operador (POCs, parsers, cálculos) | subproceso aislado; audit hook: `socket.connect` solo a IPs del scope, subprocesos/forks bloqueados; RLIMIT CPU/mem + timeout; sha256 al ledger |

Todo queda en el ledger append-only `reports/evidence.jsonl` — cadena de
custodia con timestamp, técnica, hash y `auth_reference`. Ese ledger es parte
del deliverable para el cliente.

**E2E verificado en lab** (Metasploit 6.5.4 real, userspace, todo loopback):
`exploit/unix/ftp/vsftpd_234_backdoor` contra `lab_vsftpd.py` → AutoCheck
`[+] The target appears to be vulnerable` → `[+] Backdoor has been spawned` →
payload `cmd/unix/reverse_bash` → **sesión Command shell** → `id` responde
`uid=0(root)` → ledger con `proven: true, session_opened: true`.

### Labs (loopback únicamente)

- `python -m pentest_agent.lab` — web vulnerable estilo CVE-2021-41773 con
  canary (para `prove_vulnerability`).
- `python -m pentest_agent.lab_vsftpd` — vsftpd 2.3.4 simulado con backdoor
  CVE-2011-2523 (FTP 2121, shell 6200; para `run_metasploit_module`).

### Flujo ofensivo completo (lab)

```bash
cp engagement.example.yaml engagement.yaml     # adaptar por cliente real
python -m pentest_agent.lab_vsftpd             # target vulnerable (lab)
python -m pentest_agent.approve                # TÚ apruebas -> export var
PENTEST_EXPLOIT_APPROVED=... python -m pentest_agent.a2a_server --role exploit --port 9104
export A2A_EXPLOIT_URL=http://127.0.0.1:9104   # habilita handoff en supervisor
python scripts/e2e_a2a.py                      # auditoria con demo de impacto
```

Para el backend Metasploit real: instalar Metasploit + msfrpcd (ver
`scripts/msf_e2e.sh`) y exportar `MSF_BACKEND=real`, `MSFRPCD_PASSWORD`,
`MSFRPCD_SSL=1`. Sin daemon, la tool corre en backend `sim` (dev/tests).

**Línea honesta:** sin engagement vigente + aprobación humana no hay
explotación, punto. Lo weaponizado es **por módulo de allowlist** declarado en
el contrato; los snippets Python corren contenidos (audit hook + rlimits) pero
con los privilegios del operador — la barrera primaria es contractual y
auditada; sandbox fuerte (contenedor dedicado) está en el roadmap.

## Seguridad (innegociable)

1. **Scope allowlist** (`scope.yaml`): las tools rechazan targets fuera de la
   lista; la frontera es código, no prompt. Por defecto solo `127.0.0.1`.
2. **Defensivo por defecto**: descubrimiento + correlación + reporte. Lo
   ofensivo es opt-in por el operador y falla cerrado sin las tres llaves.
3. **CVEs solo de tool calls**: prohibido citar CVEs que no devuelva `find_cves`.
4. **Escaneo no privilegiado**: connect-scan puro si no hay nmap; con nmap,
   `-sV -oX -` y parseo XML determinista.
5. **Evidencia no destructiva**: leer UN canary / escribir UN marcador o
   ejecutar UN módulo allowlisted. Cero exfiltración real, persistencia, DoS
   o movimiento lateral — prohibidos en el engagement y auditados en el ledger.

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
- **Exploit (opcional)**: `A2A_EXPLOIT_URL` (registra al exploit_agent en el
  supervisor), `PENTEST_ENGAGEMENT_FILE`, `PENTEST_EXPLOIT_APPROVED`,
  `MSF_BACKEND` (`sim|real`), `MSFRPCD_PASSWORD`, `MSFRPCD_USER`,
  `MSFRPCD_SSL`, `MSFRPCD_HOST/PORT`, `PENTEST_SNIPPET_TIMEOUT`.

## Tests

```bash
pytest -q    # 81 tests: scope, parsing nmap/NVD, A2A (4 roles), gates
             # fail-closed (engagement/msf/pysnippet), skills, MCP loader,
             # scope wrapper MCP y contencion real
```

## Skills (conocimiento por rol)

Cada subagente carga **skills**: markdown versionado en el repo, concatenado
en orden alfabético bajo una sección fija del system prompt. El repo es el
distribuidor — sin curador, sin runtime, sin descargas.

```
skills/
├── recon/scanning-methodology.md     # orden de scan, banners, fingerprint
├── vuln/cve-correlation.md           # NVD, KEV, reglas de escalada
├── reporter/report-standards.md      # estructura, evidencia citada
└── exploit/msf-runbook.md            # check→exploit→sesión, triple llave
```

Para añadir conocimiento a un rol: crea `skills/<rol>/*.md` y reinicia el
worker. Regla de tamaño: <2KB por archivo (el prompt viaja en cada request).

**Skills por cliente (fase 2)**: un engagement vigente puede declarar
`skills_dirs: [<dirs>]`; los packs `<dir>/<rol>/*.md` se añaden DESPUÉS de
las del repo (aislados por rol). Engagement inválido/expirado degrada a
solo-skills-de-repo — nunca rompe el arranque del worker.

## MCP (Model Context Protocol)

Los workers pueden usar tools de servidores MCP externos además de las
nativas. Config declarativa por rol en `mcp_servers.yaml` (gitignored;
`mcp_servers.example.yaml` es la plantilla):

```yaml
reporter:
  - name: artifacts-fs
    transport: stdio
    command: python
    args: ["scripts/mcp_fs_server.py", "/tmp/pentest-reports"]
```

- **Sin archivo o sin rol → []**: ese rol no carga MCP (todo sigue igual).
- **Trust boundary**: `mcp_servers.yaml` solo lo escribe el operador.
  Credenciales por env vars, jamás en el yaml.
- **Fail-closed para exploit**: las tools MCP del rol ofensivo no se cargan
  (ni se exponen sus schemas al LLM) sin las tres llaves abiertas en el
  proceso del worker: scope + `engagement.yaml` + `PENTEST_EXPLOIT_APPROVED`.
  Los servidores stdio heredan el env del proceso aprobado.
- **Scope para tools de red**: cualquier tool MCP cuyo schema acepte
  `host`/`target`/`url` se envuelve con la misma frontera `Scope.assert_allowed`
  que las tools nativas (roles no ofensivos).

Smoke E2E (reporter escribe un reporte vía MCP real):

```bash
.venv/bin/python scripts/mcp_smoke.py
```

Los workers **recon, vuln y exploit** cargan por defecto dos servidores MCP
(sin configuración del operador; una entrada explícita en `mcp_servers.yaml`
— incluso `[]` — la desactiva):

| Server | Tools | Nota |
|---|---|---|
| `scripts/mcp_fs_server.py` | list, read_text, write_text, append_text, move, remove, mkdir, tree, search, sha256, info | jail a un dir base; sin escape con `..`/absolutos |
| `scripts/mcp_terminal_server.py` | run_command, list_allowed, policy | política dual (abajo) |

### Políticas del terminal MCP

- **investigative** (default recon/vuln): allowlist exacta de binarios
  (nmap, curl, dig, host, whois, traceroute, ping, openssl, amass) +
  allowlist de flags por binario + **sin shell** (argv directo) + toda IP
  literal y todo hostname (resuelto por DNS) se valida contra `scope.yaml`
  ANTES de ejecutar. Binario/flag/target fuera → `blocked`.
- **full** (default exploit): `bash -c` arbitrario con timeout y salida
  acotada — solo se carga bajo la triple llave del rol exploit
  (`load_mcp_tools` no registra nada del rol sin gates abiertos).

Smoke fase 3 (agents reales + defaults + fail-closed):

```bash
.venv/bin/python scripts/mcp_smoke_fase3.py
```

### Servers MCP de fase 2

| Server | Rol | Qué da | Gates |
|---|---|---|---|
| `scripts/mcp_osint_server.py` | recon (opt-in) | `ct_subdomains`: subdominios vía certificate transparency (crt.sh, keyless, pasivo) | dominio en `engagement.osint.allowed_domains` o `PENTEST_OSINT_CONFIRM_DOMAIN` (labs) |
| `scripts/mcp_msf_server.py` | exploit | `run_metasploit_module` + `engagement_status` (canal MCP del mismo core nativo) | triple llave completa dentro del proceso del server |
| `scripts/mcp_fs_server.py` | reporter | `write_report`/`list_reports` confinados a un dir | ninguno (no ofensivo) |

El OSINT es **pasivo**: consulta logs públicos de CT, cero contacto con la
infra del cliente. crt.sh es inestable (502 intermitentes) → reintentos con
backoff + query wildcard `%.dominio`.

Smoke fase 2 (OSINT real contra tu dominio + msf sim con ledger):

```bash
.venv/bin/python scripts/mcp_smoke_phase2.py   # SMOKE_DOMAIN=tudominio.co opcional
```

## Limitaciones honestas (roadmap)

- Matching versión→CVE por keyword NVD; el camino robusto es CPE exacto
  (`cpeMatch`), y nmap ya emite CPE.
- Sin NVD API key: rate limit estricto (~5 req/30s).
- Sin auth en los servidores A2A (PoC local). Producción: API key/bearer.
- Sandbox de snippets Python: el audit hook no es barrera contra
  ctypes/C-ext; para sandbox fuerte, contenedor dedicado por engagement.
- Faltan: `searchsploit` como tool, subagente host-audit (SSH config) y K8s
  (`trivy`, `kube-bench`), aprobación humana vía Telegram (interrupt de
  LangGraph) y reporte ejecutivo a partir del ledger.
