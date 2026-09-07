# pentest-chat — TUI

Terminal chat UI (Ink + React 19) for the Whitehat pentest supervisor. Talks to the
FastAPI sidecar (`chat_server.py`, default `:9000`): `/status`, `/chat`,
SSE `/chat/{sid}/events`, `/engagement`, `/ledger`.

Task 8 adds the basic chat loop: `src/api.ts` (HTTP client), `src/bus.tsx` (UI
state machine + context), and the `ChatLog` / `ChatInput` components wired up in
`src/App.tsx`. The approve-gate, live SSE mode and ledger view land in Tasks 9–11.

### Chat loop state machine (`src/bus.tsx`)

```
boot ─DISCOVER_OK→ ready              ready ─SUBMIT→ thinking
boot ─DISCOVER_FAIL→ discovering      thinking ─DELTA→ streaming (accumulates)
discovering ─DISCOVER_OK→ ready       streaming ─DELTA→ streaming (accumulates)
discovering ─DISCOVER_FAIL ×3→ down   (thinking|streaming) ─DONE→ ready
down ─DISCOVER_OK→ ready              (thinking|streaming) ─ERROR→ ready (+visible)
```

Ctrl+C exits (raw-mode cleanup via `useApp().exit()`); it is a component concern,
not a reducer action.

Until Task 10 wires a live `EventSource`, `App.tsx` reads the turn's events by
polling `GET /chat/{sid}/events?cursor=` every 500ms and parsing the
`text/event-stream` frames by hand (`parseSse` in `src/api.ts`).

## Requirements

- Node 22 (`v22.22.3` used here)
- pnpm 12 (`corepack enable`; if `pnpm` is missing add `~/.hermes/node/bin` to `PATH`)

## Install

```sh
cd tui
pnpm install
```

`esbuild` (pulled in by `tsx`/`vitest`) needs a post-install build step. It is
pre-approved in `pnpm-workspace.yaml` (`allowBuilds: esbuild: true`), so a clean
`pnpm install` runs it without an interactive prompt.

## Scripts

| Command           | What it does                                  |
|-------------------|-----------------------------------------------|
| `pnpm dev`        | `tsx src/main.tsx` — runs the TUI (needs a TTY)|
| `pnpm test`       | `vitest run` — headless render tests           |
| `pnpm typecheck`  | `tsc --noEmit` — strict typecheck              |

## Verifying the render without a TTY

`pnpm dev` needs an interactive terminal (raw mode) and will not run in CI or a
non-interactive shell. The render is instead verified headlessly with
`ink-testing-library` in `src/App.test.tsx`, which mounts the component and asserts
on the rendered frame. Run:

```sh
pnpm test
pnpm typecheck
```

Both must be green. That is the authoritative check for this scaffold — do **not**
rely on `pnpm dev` in an environment without a TTY.

## E2E against the real sidecar (deterministic)

`scripts/e2e-chat.ts` drives the real sidecar through `src/api.ts`
(`getStatus` → `postChat` → read events until `chat.done`). Run it against a
throwaway deterministic sidecar (no LLM, no network):

```sh
# from the repo root
PENTEST_CHAT_DETERMINISTIC=1 PENTEST_CHAT_PORT=9111 \
  .venv/bin/python -m pentest_agent.chat_server > /tmp/sidecar.log 2>&1 &
SIDECAR=$!
( cd tui && PENTEST_TUI_URL=http://127.0.0.1:9111 pnpm exec tsx scripts/e2e-chat.ts )
kill $SIDECAR
```

Expected tail: `final assistant text: "pong: hola sidecar"` then `[e2e] OK`.

## Note on the Ink version

The plan calls this "Ink v5 + React 19". Ink 5 ships `react-reconciler@0.29`, which
targets React 18 internals (`ReactCurrentOwner`, `resolveUpdatePriority`) and crashes
under React 19. Ink 6 is the first release to officially support React 19
(`peerDependencies: react >=19.0.0`), so this scaffold uses `ink@^6`. React stays on
19 as the plan requires.
