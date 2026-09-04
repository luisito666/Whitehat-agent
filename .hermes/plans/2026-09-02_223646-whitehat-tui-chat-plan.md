# Chat TUI para pentest-agent (Python + Ink/React) — Plan de Implementación

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Que el operador pueda chatear con el equipo de auditoría desde una TUI React (Ink) que consume el stack A2A existente — sin reescribir el backend Python.

**Architecture:** El stack LangGraph+A2A queda intacto. Se añade un sidecar FastAPI (`chat_server.py`, :9000, solo 127.0.0.1) con endpoints de chat y streaming SSE, y una TUI Ink que renderiza conversación, actividad de agentes, estado del engagement y la puerta de aprobación (solo lectura).

**Tech Stack:** Python 3.11 (FastAPI, sse-starlette, a2a-sdk 0.2.11 ya presente) · React 19 + Ink 5 · Node 22 · pnpm (corepack) · Vitest + Testing Library (ink-testing-library) · pytest + httpx MockTransport

---

## 1. Decisión de arquitectura: ¿agente Python + CLI en React/Ink? — Pros y contras

**Recomendación: SÍ, híbrido.** Es el patrón Claude Code, Gemini CLI y opencode: la CLI es presentación/transporte; el runtime del agente vive donde viven las tools (Python: nmap, pymetasploit3, audit hooks).

### Pros
- **Separación limpia:** la TUI puede fallar o cambiarse sin tocar el fail-closed del backend.
- **Ink = React:** componentes, hooks, composición. Curva mínima para ti (ya vienes de Angular con modelo React).
- **Ecosistema maduro:** ink-text-input, ink-spinner, ink-table, pastel (empaquetado a binario).
- **Streaming natural:** SSE → render incremental; chateas mientras el agente trabaja.
- **Contrato explícito:** la TUI es reemplazable (web, Telegram, otra TUI) sin tocar el backend.
- **Chatear ≠ delegar:** el operador conversa con el supervisor; los workers A2A no cambian.

### Contras
- **Dos toolchains:** Node+pnpm+Vitest junto a pytest. CI doble (mitigar: un job extra en GH Actions).
- **Distribución:** 2 runtimes. Mitigar con `pastel bake` → binario self-contained `pentest-chat`.
- **Versionado del contrato:** la TUI debe respetar la versión del protocolo `/chat` (header `X-Chat-Protocol: 1`).
- **Sin servidor no hay TUI:** mitigar con pantalla "stack no detectado" + comando a correr (la TUI NO spawnea el stack; el operador usa `scripts/start_master_stack.sh`).
- **Consumo:** Node añade ~50-80 MB RSS vs. solución Python pura.
- **Sin Redis/colas (YAGNI):** buffer de eventos en memoria del sidecar por session_id.

### Alternativas descartadas
- **Textual (Python puro):** excelente librería, pero te obliga a un paradigma UI nuevo y el nicho "agent chat TUI" hoy vive en Ink (Claude Code, Gemini CLI, opencode).
- **Bubble Tea (Go):** buen performance y binario único, pero un tercer lenguaje en el repo.
- **prompt_toolkit:** viable pero sin ecosistema de componentes comparable a Ink.
- **Web UI local (Angular):** reuso máximo de tu experiencia, pero no es "aplicación de consola" (requisito) y no vive en el terminal donde ya corren msfrpcd/labs. Queda habilitada gratis en el futuro por el contrato `/chat`.

---

## 2. Contexto actual (verificado en el repo)

- Supervisor: `src/pentest_agent/a2a_team.py::build_a2a_supervisor` — grafo LangGraph con handoffs a workers A2A (:9101-9103; exploit :9104 solo con `A2A_EXPLOIT_URL`).
- Workers: `src/pentest_agent/a2a_server.py` — un servidor A2A por rol; Agent Card en `/.well-known/agent.json`; `message/send` sin streaming.
- CLI actual: `src/pentest_agent/cli.py` — un solo turno (`team.invoke(...)`, luego FIN). **No hay loop de conversación** ← esto es lo que añade el chat.
- Aprobación: `src/pentest_agent/approve.py` — interactivo, imprime `export PENTEST_EXPLOIT_APPROVED=...` para el proceso SERVIDOR exploit. La TUI solo muestra estado, nunca aprueba.
- Ledger: `reports/evidence.jsonl` append-only (cadena de custodia). La TUI lo lee por API.
- `engagement.yaml` NO se commitea; la TUI lo lee vía endpoint de estado.
- Entorno: Node v22.22.3 y npm 10.9.8 presentes; pnpm falta (instalar via corepack). venv del repo en `.venv` (Python 3.11).

---

## 3. Contrato API v1 (fuente de verdad)

```
GET  /status    → 200 {"stack":"up","workers":[{"role":"recon","url":...}],
                    "engagement":{"id","client","valid","approved"},
                    "protocol":1}

POST /chat      {"session_id":"opt","message":"texto"}
               → 200 {"session_id":"...","cursor":"..."}

GET  /chat/{sid}/events?cursor=...   → SSE (text/event-stream)
     eventos: chat.delta | agent.activity | chat.done | error
     ids incrementales → reconexión con Last-Event-ID sin perder eventos

GET  /engagement           → resumen público (id, cliente, ventana, approved) — sin secretos; 404 si no hay
POST /engagement/approve   → 501 SIEMPRE (fail-closed: la aprobación es solo presencial vía approve.py)
GET  /ledger?tail=N        → últimas N entradas del evidence.jsonl
```

Reglas duras:
- Bind **solo 127.0.0.1** (:9000). Nunca LAN.
- Streaming del supervisor vía `astream_events` de LangGraph con `thread_id = session_id` (memoria de conversación multi-turno).
- Artifacts/actividad de workers A2A → eventos `agent.activity` (traducción en el sidecar, reusando `a2a_client`).
- Fallback si `astream_events` es ruidoso: chunking del mensaje final en `chat.delta` (v1 aceptable).
- Buffer por sesión en memoria; replay desde cursor.

---

## 4. Decisiones (Fase 0)

| # | Decisión | Elección |
|---|---|---|
| D1 | Dónde vive `/chat` | Sidecar FastAPI nuevo `chat_server.py` — no tocar `a2a_server.py` |
| D2 | Dónde vive la TUI | `tui/` en el mismo repo (pnpm workspace simple) |
| D3 | ¿La TUI spawnea el stack? | NO — solo descubre vía `GET /status` (poll 2s) o `PENTEST_TUI_URL` |
| D4 | Estado del chat | En memoria en el sidecar (dict por session_id). Sin Redis (YAGNI) |
| D5 | Aprobación en TUI | Solo lectura: explica approve.py, nunca aprueba (UI fail-closed) |
| D6 | Packaging | `pastel bake` → binario `pentest-chat` (fase final) |
| D7 | Versionado | Header `X-Chat-Protocol: 1` |

---

## 5. Plan paso a paso

### Fase 1 — Backend: sidecar de chat (Python, TDD)

**Task 1: Scaffold del sidecar FastAPI + GET /status**
- Create: `src/pentest_agent/chat_server.py`, `tests/test_chat_server.py`
- `GET /status` → protocol:1, workers (poll de agent cards), resumen engagement. Bind 127.0.0.1:9000.
- Test: `test_status_ok` con httpx MockTransport.
- Run: `pytest tests/test_chat_server.py -v` → PASS
- Commit: `feat(chat): add sidecar /status endpoint`

**Task 2: POST /chat — un turno sin streaming (happy path)**
- Test: `test_chat_single_turn` con supervisor stub (monkeypatch `build_a2a_supervisor` → agente echo).
- El endpoint invoca `supervisor.astream_events(..., config={"configurable": {"thread_id": sid}})`, acumula `chat.delta` y cierra con `chat.done`.
- Run: pytest → PASS
- Commit: `feat(chat): POST /chat single turn`

**Task 3: SSE de eventos con cursor**
- Test: media_type `text/event-stream`; eventos con id incremental; `Last-Event-ID` re-emite lo pendiente.
- Run: pytest → PASS
- Commit: `feat(chat): SSE events with cursor replay`

**Task 4: GET /engagement + POST /engagement/approve → 501 + GET /ledger**
- Test: `test_engagement_fail_closed` — approve SIEMPRE 501 con mensaje "aprobación solo presencial vía approve.py"; GET /engagement sin secretos, 404 si no hay; /ledger devuelve tail del evidence.jsonl.
- Reusar `load_engagement()` del dominio — no duplicar lógica.
- Run: pytest → PASS
- Commit: `feat(chat): engagement and ledger endpoints fail-closed`

**Task 5: Correlación A2A → eventos agent.activity**
- Test: `test_worker_activity_surfaced` — workers A2A stub que emiten artifacts → sidecar los traduce a `agent.activity`.
- Reusar `a2a_client` existente.
- Run: pytest → PASS
- Commit: `feat(chat): surface A2A worker activity as agent.activity events`

**Task 6: E2E del sidecar en modo determinista (sin LLM)**
- Test: sidecar como subprocess (fixture) + pipeline `--no-llm` stubbeado; verifica /status → POST /chat → SSE completo.
- Run: `pytest tests/test_chat_server.py -v` → PASS (timeouts generosos, pytest-asyncio)
- Commit: `test(chat): sidecar E2E determinista`

### Fase 2 — TUI Ink (React)

**Task 7: Scaffold Ink + pnpm**
- Create: `tui/package.json`, `tui/src/main.tsx`, `tui/src/App.tsx`, `tui/tsconfig.json`, `tui/vitest.config.ts`
- `corepack enable && pnpm install`; "hello chat" minimal.
- Verify: `pnpm dev` renderiza la TUI.
- Commit: `feat(tui): scaffold Ink v5 + React 19`

**Task 8: Chat loop básico (input → POST /chat → render)**
- Create: `tui/src/api.ts`, `tui/src/bus.tsx` (reducer + context), `tui/src/components/ChatLog.tsx`, `tui/src/components/ChatInput.tsx`
- Máquina de estados de la UI (testear edges del reducer con vitest):
  ```
  boot → discovering (GET /status poll 2s) → ready
  ready + Enter  → thinking → streaming → ready
  ready + Ctrl+P → approve-gate
  any   + Ctrl+C → exit (limpiar raw mode)
  ```
- Verify: `pnpm dev` + sidecar real (`python -m pentest_agent.chat_server`), conversación multi-turno real.
- Commit: `feat(tui): chat loop with real sidecar`

**Task 9: Approve-gate + engagement banner**
- Create: `tui/src/components/ApproveGate.tsx`
- Muestra engagement vigente (banner verde) o instrucciones de approve.py (fail-closed UI); Esc vuelve.
- Verify: con y sin `engagement.yaml`.
- Commit: `feat(tui): approve-gate + engagement banner`

**Task 10: SSE live con reconnect**
- Create: `tui/src/sse.ts` (EventSource con Last-Event-ID), integración en bus.
- `chat.delta` renderiza en vivo; si el SSE se corta → "reconectando..." + retry con cursor (fail-safe: no se pierde el chat, buffer por sesión en sidecar).
- Verify: matar el sidecar mid-stream, reanudar, verificar que el flujo continúa desde el cursor.
- Commit: `feat(tui): SSE live mode with reconnect`

**Task 11: Ledger view + status bar**
- Create: `tui/src/components/LedgerView.tsx`, `tui/src/components/StatusBar.tsx`
- Teclas: `l` = ledger (tail evidence.jsonl), `s` = overview (workers up/down, engagement, session_id).
- Verify: ledger real visible; overview con workers reales.
- Commit: `feat(tui): ledger view + status bar`

**Task 12: Packaging pastel + docs**
- Create: `tui/README.md`; `pastel bake` → `dist/pentest-chat`.
- Verify: `./dist/pentest-chat --version` + E2E manual con stack real.
- Commit: `chore(tui): pastel packaging + docs`

### Fase 3 — CI y entrega

**Task 13: CI doble en GH Actions**
- Job existente + job `tui` (pnpm install, vitest, typecheck). El job Python no cambia.
- Commit: `ci: add tui job (pnpm vitest)`

---

## 6. Files likely to change

- Create: `src/pentest_agent/chat_server.py`, `tests/test_chat_server.py`, `tui/**` (12+ archivos), workflow job.
- Modify: `pyproject.toml` (deps: fastapi, sse-starlette; script `pentest-chat-server`), `README.md` (sección chat).
- NUNCA modificar: `tools/exploit.py` (triple llave), `approve.py`, `engagement.py` — el fail-closed queda intacto.

## 7. Verificación final

1. `pytest` verde (suite completa del repo + tests nuevos del sidecar).
2. `pnpm vitest` verde en `tui/`.
3. E2E manual: stack real arriba → `pentest-chat` → chatear multi-turno con el supervisor, ver `agent.activity` de recon/vuln/reporter, Ctrl+P gate, reconexión SSE, ledger view.
4. Confirmar fail-closed: `POST /engagement/approve` → 501; sin engagement.yaml el banner lo dice; la TUI no puede aprobar nada.

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| `astream_events` ruidoso (eventos internos LangGraph) | Fallback: chunking del mensaje final en `chat.delta`; filtrar por `name="Supervisor"` |
| A2A workers sin streaming (streaming=False) | El sidecar emite `agent.activity` al inicio/fin de cada handoff (granularidad por task, no por token) |
| 2 runtimes al distribuir | `pastel bake` → binario único; el backend ya es `pip install` |
| Deriva del contrato | Header `X-Chat-Protocol: 1` + tests de contrato en ambos lados |
| Superficie de ataque HTTP | Solo 127.0.0.1; sin tools expuestas; engagement sin secretos; approve siempre 501 |

## 9. Open questions

- ¿El chat multi-turno necesita checkpointing persistente de LangGraph (SqliteSaver) o basta memoria en-proceso del sidecar? Recomendación v1: en-proceso (YAGNI); migrar a SqliteSaver si se reinicia el sidecar a mitad de auditoría con frecuencia.
- ¿Granularidad de `agent.activity`: por handoff o por tool-call del worker? Recomendación v1: por handoff (más simple, menos ruido).
