# pentest-chat — TUI

Terminal chat UI (Ink + React 19) for the Whitehat pentest supervisor. Talks to the
FastAPI sidecar (`chat_server.py`, default `:9000`): `/status`, `/chat`,
SSE `/chat/{sid}/events`, `/engagement`, `/ledger`.

Task 8 adds the basic chat loop: `src/api.ts` (HTTP client), `src/bus.tsx` (UI
state machine + context), and the `ChatLog` / `ChatInput` components wired up in
`src/App.tsx`. Task 10 adds live SSE mode with reconnect (`src/sse.ts`); the
ledger view lands in Task 11.

### Live SSE mode (Task 10)

`src/sse.ts` `streamEvents()` reads `GET /chat/{sid}/events?cursor=` as a live
`fetch` stream (not `EventSource` — Node's has no custom headers and no clean
abort). It parses the `text/event-stream` incrementally (`parseSse`, re-exported
here as `parseSSE`), tracking `lastEventId`. The sidecar long-polls ~55s then
closes; on any non-terminal close it reconnects from `lastEventId` (the sidecar
replays its per-session buffer, so a network blip loses no chat) with a
500ms → 1s → 2s backoff, up to 3 consecutive failed attempts, then gives up with
`onClose()`. A close whose last frame was `chat.done` / `error` is the real end
of the turn.

`App.tsx` swaps the old 500ms poll for `streamEvents`; the reducer gains
`RECONNECTING` / `RECONNECTED` (flag `reconnecting`, force-cleared on
`SUBMIT` / `DONE` / `ERROR`) and the status bar shows `reconectando…` while a
reconnect is in flight.

### Approve gate (Task 9)

`src/components/ApproveGate.tsx` is a **read-only** screen (D5, "UI fail-closed"):
the TUI never approves anything. Ctrl+P toggles it from any view (handler in
`App.tsx`), Esc closes it back to the chat. On mount it fetches `GET /engagement`
(spinner while loading), then shows:

- **green banner** if an engagement is in force — id, client, validity window,
  `auth_reference`, and whether operator approval (`PENTEST_EXPLOIT_APPROVED`) is
  present;
- **red banner** on 404 (or an unreachable sidecar) — the fail-closed procedure:
  create `engagement.yaml`, run `python -m pentest_agent.approve`, and note that
  approval is confirmed **only in person, in the exploit server process**.

The view axis lives on the reducer (`view: 'chat' | 'approve'`, actions
`TOGGLE_VIEW` / `CLOSE_VIEW`) so it is unit-testable without a render. While the
gate is open `ChatInput` is unmounted, so input is disabled.

`App.tsx` also renders a one-line **status bar** (always visible): the run state
(`ready` / `thinking` / `streaming` / `down` / `connecting`) plus the engagement
from the last `/status` poll — green `id · client`, or red `sin engagement`.

### Chat loop state machine (`src/bus.tsx`)

```
boot ─DISCOVER_OK→ ready              ready ─SUBMIT→ thinking
boot ─DISCOVER_FAIL→ discovering      thinking ─DELTA→ streaming (accumulates)
discovering ─DISCOVER_OK→ ready       streaming ─DELTA→ streaming (accumulates)
discovering ─DISCOVER_FAIL ×3→ down   (thinking|streaming) ─DONE→ ready
down ─DISCOVER_OK→ ready              (thinking|streaming) ─ERROR→ ready (+visible)
```

The view is a separate axis on the same state (a turn keeps running underneath):

```
chat ─TOGGLE_VIEW (Ctrl+P)→ approve    approve ─TOGGLE_VIEW / CLOSE_VIEW (Esc)→ chat
```

Ctrl+C exits (raw-mode cleanup via `useApp().exit()`); it is a component concern,
not a reducer action.

`App.tsx` reads the turn's events with `streamEvents` (`src/sse.ts`); the pure
frame parser is `parseSse` in `src/api.ts`.

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

### E2E for the approve gate

`scripts/e2e-engagement.ts` drives `GET /engagement` and prints what the banner
would render. Run it twice against a deterministic sidecar:

```sh
# from the repo root — WITH an engagement in force
cp tests/fixtures/engagement.valid.yaml /tmp/eng.yaml
PENTEST_CHAT_DETERMINISTIC=1 PENTEST_CHAT_PORT=9112 PENTEST_ENGAGEMENT_FILE=/tmp/eng.yaml \
  .venv/bin/python -m pentest_agent.chat_server > /tmp/sidecar.log 2>&1 &
( cd tui && PENTEST_TUI_URL=http://127.0.0.1:9112 pnpm exec tsx scripts/e2e-engagement.ts )

# WITHOUT one (no PENTEST_ENGAGEMENT_FILE, no engagement.yaml in cwd) -> null (404)
PENTEST_CHAT_DETERMINISTIC=1 PENTEST_CHAT_PORT=9113 \
  .venv/bin/python -m pentest_agent.chat_server > /tmp/sidecar.log 2>&1 &
( cd tui && PENTEST_TUI_URL=http://127.0.0.1:9113 pnpm exec tsx scripts/e2e-engagement.ts )

pkill -f pentest_agent.chat_server
```

Expected: the first run prints `id=ENG-FIXTURE-2026-009 … auth_reference=roE-fixture-tui-v1`,
the second prints `null (404) -> fail-closed banner: run approve.py`. Both end `[e2e] OK`.

### E2E for live SSE + reconnect

`scripts/e2e-sse-reconnect.ts` is self-contained — it spawns and SIGKILLs its own
deterministic sidecars. It streams a turn, kills the sidecar mid-flight (the
reader must not crash — reconnect backs off then `onClose`s), then brings a fresh
sidecar up and runs a clean turn to `chat.done`.

```sh
cd tui && pnpm exec tsx scripts/e2e-sse-reconnect.ts
```

Expected tail: `second turn text: "pong: otra vez" done=true` then `[e2e] OK`.

## Note on the Ink version

The plan calls this "Ink v5 + React 19". Ink 5 ships `react-reconciler@0.29`, which
targets React 18 internals (`ReactCurrentOwner`, `resolveUpdatePriority`) and crashes
under React 19. Ink 6 is the first release to officially support React 19
(`peerDependencies: react >=19.0.0`), so this scaffold uses `ink@^6`. React stays on
19 as the plan requires.
