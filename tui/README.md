# pentest-chat — TUI

Terminal chat UI (Ink + React 19) for the Whitehat pentest supervisor. Talks to the
FastAPI sidecar (`chat_server.py`, default `:9000`): `/status`, `/chat`,
SSE `/chat/{sid}/events`, `/engagement`, `/ledger`.

This is the Task 7 scaffold: a minimal "hello chat" boot placeholder. The chat loop,
approve-gate, SSE live mode and ledger view land in Tasks 8–11.

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

## Note on the Ink version

The plan calls this "Ink v5 + React 19". Ink 5 ships `react-reconciler@0.29`, which
targets React 18 internals (`ReactCurrentOwner`, `resolveUpdatePriority`) and crashes
under React 19. Ink 6 is the first release to officially support React 19
(`peerDependencies: react >=19.0.0`), so this scaffold uses `ink@^6`. React stays on
19 as the plan requires.
