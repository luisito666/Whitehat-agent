# Flujo completo whitehat-agent — referencia visual

Un mapa de todos los pasos, artefactos y llaves del flujo ofensivo completo.
Los gate 🔒 son fail-closed: sin ellos, nada se ejecuta.

## 1) Vista general: quién corre dónde

```
TÚ (operador)                      MÁQUINA (procesos separados a propósito)
──────────────                     ─────────────────────────────────────────
                                   ┌──────────────────────────────────┐
                                   │ LABS (targets vulnerables)        │
                                   │  lab.py       → 127.0.0.1:PUERTO  │
                                   │  lab_vsftpd   → :2121 ftp / :6200 │
                                   └──────────────────────────────────┘
                                   ┌──────────────────────────────────┐
                                   │ STACK A2A (un proceso por rol)    │
                                   │  recon    :9101  (defensivo)      │
                                   │  vuln     :9102  (defensivo)      │
                                   │  reporter :9103  (defensivo)      │
                                   │  exploit  :9104  🔒 llave 2 aquí   │
                                   └──────────────────────────────────┘
                                   ┌──────────────────────────────────┐
                                   │ SUPERVISOR (LangGraph)            │
                                   │  rutea con Command + tool calls   │
                                   │  conoce exploit SOLO si exportas  │
                                   │  A2A_EXPLOIT_URL (registro)       │
                                   └──────────────────────────────────┘
```

**Por qué procesos separados:** si todo viviera en un solo proceso, el propio
LLM podría auto-aprobarse. La aprobación (env var) vive en el proceso del
SERVIDOR exploit; el supervisor solo puede *pedirle*, nunca *otorgarla*.

## 2) Las tres llaves (todas deben abrir, en orden)

```
LLAVE 1 — CONTRATO            LLAVE 2 — HUMANO               LLAVE 3 — TÉCNICA
engagement.yaml (disco)       PENTEST_EXPLOIT_APPROVED       rules_of_engagement
├─ engagement_id              == engagement_id                ├─ allowed_techniques
├─ cliente + contacto           (env del PROCESO exploit,      │   (metasploit → msf.allowed_modules: allowlist EXACTA)
├─ authorization               solo TÚ lo exportas            └─ prohibited  ← se evalúa PRIMERO
│   ├─ reference (RoE firmado)   tras 'y' en approve)             (un typo en allowed NO habilita lo vetado)
│   ├─ valid_from / valid_until
│   └─ scope: allowed_targets (CIDRs)
└─ FAIL-CLOSED: falta/expira/malformado → NADA se ejecuta

   └─────────────── las 3 sí ────────────────────────────────┐
                                                             ▼
                                     ┌──────────────────────────────────┐
                                     │ ejecución mínima + no destructiva │
                                     │ (leer 1 canary / 1 módulo / 1     │
                                     │ snippet contenido)                │
                                     └───────────────┬──────────────────┘
                                                     ▼
                                     reports/evidence.jsonl  (LEDGER)
                                     ts + technique + target + sha256
                                     + auth_reference + proven
```

## 3) End-to-end con el script de un comando

`bash scripts/run_lab_full.sh` orquesta estos pasos (el prompt de aprobación
sigue siendo tuyo — el script no puede aprobar por ti):

```
[1] validar engagement ──fail──► ABORT (nada se levanta)
[2] mostrar resumen + 'y' humano ──'n'──► ABORT (fail-closed)
[3] levantar labs (web traversal + vsftpd backdoor)
[4] levantar recon:9101 vuln:9102 reporter:9103 (defensivos, sin gates ofensivos)
[5] levantar exploit:9104 con PENTEST_EXPLOIT_APPROVED en SU proceso 🔒
[6] exportar A2A_EXPLOIT_URL → supervisor registra handoff ofensivo
[7] run_audit E2E:
      supervisor ──A2A──► recon (scan_host: puertos + fingerprints)
              │                 │
              ▼                 ▼
      supervisor ◄──hallazgo CRITICO/KEV── vuln (find_cves: NVD+KEV)
              │
              ▼ (solo entonces, y con las 3 llaves)
      supervisor ──A2A──► exploit 🔒 (PoC canary / módulo msf allowlist /
              │            snippet contenido; todo al ledger)
              ▼
      supervisor ──A2A──► reporter (save_report: markdown citado + ledger)
              ▼
          FIN
[8] tail del ledger + limpieza del stack (trap EXIT)
```

## 4) Qué queda dónde (artefactos)

- `engagement.yaml` — el contrato (gitignored, se crea del example por cliente)
- `reports/evidence.jsonl` — ledger append-only: la cadena de custodia (deliverable)
- `reports/audit-*.md` — reportes de auditoría con hallazgos citados por fuente
- `.cache/*.log` — logs de workers/labs (diagnóstico)
- `scope.yaml` — frontera defensiva de recon/vuln (allowlist de targets, code-level)

## 5) Atajos

- Solo defensivo (sin llaves): `bash scripts/start_a2a_stack.sh` + `scripts/e2e_a2a.py`
- Aprobar sin script: `python -m pentest_agent.approve` → exporta lo que imprime
- Todo-ofensivo en un comando: `bash scripts/run_lab_full.sh`
- Determinista sin LLM: `python -m pentest_agent --target 127.0.0.1 --no-llm`
