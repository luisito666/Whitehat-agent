# pentest-chat — TUI

Terminal chat UI (Ink 6 + React 19) to talk to the Whitehat pentest **supervisor**
while it works. You converse with the supervisor; the A2A workers
(recon/vuln/reporter/exploit) are unchanged. The TUI is **presentation only** — it
renders the conversation, live agent activity, engagement state and a **read-only**
approve gate. It never runs a tool and never approves anything.

## Architecture

```
  ┌────────────┐   HTTP + SSE    ┌─────────────────────┐   LangGraph / A2A   ┌──────────┐
  │  this TUI  │ ──────────────► │  chat sidecar :9000 │ ──────────────────► │ supervisor│
  │  (Ink)     │ ◄────────────── │  chat_server.py     │ ◄───────────────── │ + workers │
  └────────────┘                 └─────────────────────┘                     └──────────┘
```

- The **sidecar** (`src/pentest_agent/chat_server.py`, loopback `127.0.0.1:9000`)
  is a small FastAPI app that owns conversation state (in-memory, per `session_id`)
  and speaks contract v1 (`X-Chat-Protocol: 1`):
  - `GET  /status` — stack up?, workers up/down, engagement summary, `protocol`
  - `POST /chat` `{session_id?, message}` → `{session_id, cursor}`
  - `GET  /chat/{sid}/events?cursor=N` — SSE stream (`chat.delta`, `agent.activity`,
    `chat.done`, `error`), incremental ids, replay from `cursor`
  - `GET  /engagement` — public engagement view (no secrets); `404` when none
  - `GET  /ledger?tail=N` — last N `reports/evidence.jsonl` entries
  - `POST /engagement/approve` — **always `501`** (approval is in-person only)
- The TUI **does not spawn the stack**. It discovers the sidecar by polling
  `GET /status` every 2s; point it elsewhere with `PENTEST_TUI_URL`.

Client code: `src/api.ts` (HTTP), `src/sse.ts` (live SSE reader with reconnect),
`src/bus.tsx` (reducer + context — the UI state machine), `src/cli.ts`
(`--version` / `--help`), components under `src/components/`.

## Requirements

- Node 22 (`v22.22.3` used here)
- pnpm (`corepack enable`; if `pnpm` is missing add `~/.hermes/node/bin` to `PATH`)

## Install

```sh
cd tui
pnpm install
```

`esbuild` (used by `tsx`, `vitest` and the packaging script) has a post-install
build step; it is pre-approved in `pnpm-workspace.yaml` (`allowBuilds`), so a
clean `pnpm install` runs it without a prompt.

## Run (dev)

Two terminals, from the **repo root**:

```sh
# 1) the chat sidecar (loopback :9000). Add the exploit worker etc. as usual.
.venv/bin/python -m pentest_agent.chat_server

# 2) the TUI (needs an interactive terminal / raw mode)
cd tui && pnpm dev
```

`pnpm dev` is `tsx src/main.tsx`. To talk to a sidecar on another port/host:

```sh
PENTEST_TUI_URL=http://127.0.0.1:9131 pnpm dev
```

## Keys

| Key      | Action                                                              |
|----------|--------------------------------------------------------------------|
| `Enter`  | send the message (only while `ready`; blank input ignored)          |
| `Ctrl+P` | toggle the **approve gate** (read-only) from any view               |
| `l`      | ledger view — tail of `reports/evidence.jsonl` (empty prompt only)  |
| `s`      | status / overview — workers up·down, engagement, `session_id`       |
| `r`      | reload the ledger (inside the ledger view)                          |
| `Esc`    | close the current view, back to chat                                |
| `Ctrl+C` | quit (restores raw mode)                                            |

`l` / `s` only act on an **empty** prompt while `ready`, so a message can still
start with those letters.

## Environment

| Var              | Default                  | Meaning                          |
|------------------|--------------------------|----------------------------------|
| `PENTEST_TUI_URL`| `http://127.0.0.1:9000`  | base URL of the chat sidecar     |

## Scripts

| Command          | What it does                                        |
|------------------|------------------------------------------------------|
| `pnpm dev`       | `tsx src/main.tsx` — run the TUI (needs a TTY)      |
| `pnpm build`     | `node scripts/build.mjs` — bundle → `dist/pentest-chat.js` |
| `pnpm build:bin` | `node scripts/build-bin.mjs` — standalone binary (Node ≥ 26) → `dist/bin/` |
| `pnpm test`      | `vitest run` — headless render / reducer tests      |
| `pnpm typecheck` | `tsc --noEmit` — strict typecheck                   |

## Build / packaging

```sh
pnpm build          # -> dist/pentest-chat.js  (executable, #!/usr/bin/env node)
node dist/pentest-chat.js --version   # -> "pentest-chat 0.1.0", exit 0
node dist/pentest-chat.js --help      # -> usage: keys + PENTEST_TUI_URL
```

`scripts/build.mjs` is a single **esbuild** bundle (`platform: node`,
`format: esm`, `target: node22`, no minify): Ink, React and the fetch client are
inlined, a `#!/usr/bin/env node` shebang is prepended and the file is `chmod +x`.
`package.json` wires it as `bin.pentest-chat`. The version is baked in at build
time (`--define:PKG_VERSION=…`, see `src/cli.ts`) so `--version` also works
inside the standalone binary below, where no `package.json` exists.

> The plan said "`pastel bake` → `dist/pentest-chat`". **pastel
> (vadimdemedes/pastel) has no `bake` / standalone-binary command** — it is a
> file-routing framework whose `pastel build` only emits a `build/` directory of
> JS that still needs `node`. The esbuild bundle above is the pragmatic
> equivalent: one file, no `node_modules`, still needs `node` on `PATH` (the
> Python backend is already a `pip install`).

`dist/` is git-ignored (build artifact).

## Standalone binary (no Node.js required)

```sh
pnpm build:bin      # -> dist/bin/pentest-chat-linux-x64 (~150 MB)
./dist/bin/pentest-chat-linux-x64 --version   # -> "pentest-chat 0.1.0"
```

`scripts/build-bin.mjs` chains `build.mjs` → `node --build-sea` (Node ≥ 26).
The bundle is embedded as the SEA main script with `"mainFormat": "module"` —
Ink 6 / yoga-layout use top-level await, so the main must be ESM; no CJS
wrapper is needed. The script smoke-tests the binary with a scrubbed `PATH`
(no node) before declaring success, and refuses non-linux platforms (untested).

Notes:

- The binary is ~150 MB because it embeds the full Node runtime. That is the
  price of a true standalone; the 1.8 MB `dist/pentest-chat.js` bundle is the
  alternative when `node` is already on the machine.
- **Build requires Node ≥ 26** (`--build-sea`); the produced binary needs
  nothing on the target machine. `nvs add 26 && nvs use 26` gets you a build
  Node side-by-side.
- SEA is the injection path that replaced `postject` (unmaintained, removed
  from the npm registry) — `--build-sea` is Node core, no external tools.
- SEA is still flagged *experimental* upstream and Node security updates
  require rebuilding the binary.

Smoke test with the built binary (no TTY needed):

```sh
pnpm build:bin && env -i PATH=/usr/bin:/bin ./dist/bin/pentest-chat-linux-x64 --version
```

### Verifying the render without a TTY

`pnpm dev` / `node dist/pentest-chat.js` (no args) need an interactive terminal
(raw mode) and will not render usefully in CI or a non-interactive shell. The
**interactive render cannot be verified without a TTY.** What *is* verified
headlessly:

- `pnpm test` — `ink-testing-library` mounts the components and asserts on frames;
  `src/cli.test.ts` covers `--version` / `--help`.
- `pnpm typecheck` — strict.
- `node dist/pentest-chat.js --version` → `pentest-chat 0.1.0`, exit 0 (no TTY,
  no render). This is the packaging smoke test.

Both `pnpm test` and `pnpm typecheck` must be green.

## E2E against a real sidecar (deterministic, no LLM)

All four scripts drive the real client code (`src/api.ts` / `src/sse.ts`) against
a throwaway deterministic sidecar (`PENTEST_CHAT_DETERMINISTIC=1`, no LLM, no
network). Run with `pnpm exec tsx scripts/<name>.ts`.

| Script                        | What it exercises                                             |
|-------------------------------|-------------------------------------------------------------|
| `scripts/e2e-chat.ts`         | `getStatus` → `postChat` → read SSE until `chat.done`         |
| `scripts/e2e-engagement.ts`   | `GET /engagement` — prints what the approve banner would show |
| `scripts/e2e-sse-reconnect.ts`| live SSE, SIGKILL the sidecar mid-stream, resume from cursor  |
| `scripts/e2e-ledger-overview.ts` | `GET /ledger` + `GET /status` — ledger rows + overview data |

Example (`e2e-chat`, from the repo root):

```sh
PENTEST_CHAT_DETERMINISTIC=1 PENTEST_CHAT_PORT=9131 \
  .venv/bin/python -m pentest_agent.chat_server > /tmp/sidecar.log 2>&1 &
( cd tui && PENTEST_TUI_URL=http://127.0.0.1:9131 pnpm exec tsx scripts/e2e-chat.ts )
pkill -f pentest_agent.chat_server
```

Expected tail: `final assistant text: "pong: hola sidecar"` then `[e2e] OK`.
`e2e-sse-reconnect.ts` and `e2e-ledger-overview.ts` are self-contained (they
spawn and kill their own sidecars) — just `pnpm exec tsx scripts/<name>.ts`.

Packaging smoke with the built binary:

```sh
pnpm build && node dist/pentest-chat.js --version   # -> pentest-chat 0.1.0, exit 0
```

## Fail-closed (non-negotiable)

**This TUI never approves anything.** `POST /engagement/approve` is always `501`;
the approve gate (`Ctrl+P`, `src/components/ApproveGate.tsx`) is read-only. It
shows either the engagement in force (green banner) or the fail-closed procedure
(red banner): create `engagement.yaml`, run `python -m pentest_agent.approve`,
and note that approval is confirmed **only in person, in the exploit server
process** (`PENTEST_EXPLOIT_APPROVED`). The LLM, the supervisor, the sidecar and
this UI cannot inject it.

## Note on the Ink version

The plan calls this "Ink v5 + React 19". Ink 5 ships `react-reconciler@0.29`,
which targets React 18 internals and crashes under React 19. Ink 6 is the first
release to officially support React 19 (`peerDependencies: react >=19.0.0`), so
this uses `ink@^6`. React stays on 19 as the plan requires.
