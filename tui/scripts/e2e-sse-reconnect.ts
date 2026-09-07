/**
 * E2E for live SSE mode + reconnect (Task 10), fully self-contained: it spawns
 * and kills its own deterministic sidecars (no LLM, no network).
 *
 *   pnpm exec tsx scripts/e2e-sse-reconnect.ts
 *
 * Flow:
 *   1. start a deterministic sidecar, GET /status, POST /chat
 *   2. open streamEvents(); on the first frame, SIGKILL the sidecar mid-turn
 *      -> the reader must NOT crash: reconnect fails, onClose fires after the
 *         3-attempt budget (or, if chat.done was already buffered, it closes
 *         cleanly — either way the process stays alive)
 *   3. start a fresh sidecar, POST /chat again, stream to chat.done -> OK
 *
 * Exit 0 on success, 1 otherwise.
 */
import { spawn, type ChildProcess } from 'node:child_process';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const REPO_ROOT = resolve(import.meta.dirname, '../..');
const PY = resolve(REPO_ROOT, '.venv/bin/python');
const PORT = Number(process.env.PENTEST_CHAT_PORT ?? 9137);
// Must be set BEFORE api.ts is imported — it reads BASE_URL from the env once.
process.env.PENTEST_TUI_URL = `http://127.0.0.1:${PORT}`;
const { getStatus, postChat } = await import('../src/api.js');
const { streamEvents } = await import('../src/sse.js');

function startSidecar(): ChildProcess {
  const child = spawn(PY, ['-m', 'pentest_agent.chat_server'], {
    cwd: REPO_ROOT,
    env: {
      ...process.env,
      PENTEST_CHAT_DETERMINISTIC: '1',
      PENTEST_CHAT_PORT: String(PORT),
    },
    stdio: ['ignore', 'ignore', 'inherit'],
  });
  child.unref();
  return child;
}

async function waitForStatus(attempts: number): Promise<void> {
  for (let i = 0; i < attempts; i++) {
    try {
      const s = await getStatus();
      console.log(`[status] protocol=${s.protocol} stack=${s.stack}`);
      return;
    } catch {
      await sleep(250);
    }
  }
  throw new Error('sidecar never became ready');
}

async function killAndWait(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const dead = new Promise<void>((r) => child.once('exit', () => r()));
  child.kill('SIGKILL');
  await Promise.race([dead, sleep(2000)]);
}

async function main(): Promise<void> {
  console.log(`[e2e] base url: ${process.env.PENTEST_TUI_URL}`);

  // --- 1) turn cut off mid-flight: the reader must not crash --------------
  // The deterministic turn buffers pong/echo/chat.done almost instantly, so to
  // deterministically exercise the reconnect path we kill the sidecar the
  // moment the frame arrives AND before the first stream even opens on a second
  // pass. Here: open the stream, kill on the first frame, and require that
  // whatever happens next (clean terminal close, or reconnect budget spent)
  // ends in onClose without an unhandled crash.
  let sidecar = startSidecar();
  await waitForStatus(40);

  const first = await postChat('hola sidecar');
  console.log(`[chat] session=${first.session_id} cursor=${first.cursor}`);

  let killed = false;
  let reconnecting = 0;
  let closedA = false;
  const seen: string[] = [];

  await streamEvents(
    first.session_id,
    Number(first.cursor) || 0,
    {
      onEvent: (_id, event) => {
        seen.push(event);
        if (!killed) {
          killed = true;
          console.log(`[e2e] first frame (${event}) -> SIGKILL the sidecar`);
          void killAndWait(sidecar);
        }
      },
      onReconnecting: () => {
        reconnecting += 1;
        console.log(`[e2e] reconnecting… (${reconnecting})`);
      },
      onClose: () => {
        closedA = true;
      },
    },
    new AbortController().signal,
    { backoffMs: [100, 200, 400] },
  );
  await killAndWait(sidecar);
  if (!closedA) throw new Error('streamEvents did not call onClose after the kill');
  console.log(
    `[e2e] survived mid-stream kill: frames=${JSON.stringify(seen)} ` +
      `reconnect-attempts=${reconnecting} (process alive ✔)`,
  );

  // --- 1b) sidecar already gone before the stream opens -> pure reconnect --
  // First fetch fails outright: reconnect must back off 3× then onClose, never
  // throw. `killAndWait` above already dropped the process; the port is dead.
  let closedB = false;
  let reconnectingB = 0;
  await streamEvents(
    first.session_id,
    0,
    {
      onEvent: () => undefined,
      onReconnecting: () => {
        reconnectingB += 1;
      },
      onClose: () => {
        closedB = true;
      },
    },
    new AbortController().signal,
    { backoffMs: [100, 200, 400] },
  );
  if (!closedB) throw new Error('reconnect-exhausted path did not call onClose');
  console.log(
    `[e2e] dead-sidecar stream: reconnect-attempts=${reconnectingB} -> onClose ✔`,
  );

  // --- 2) fresh sidecar, clean turn -----------------------------------------
  sidecar = startSidecar();
  await waitForStatus(40);

  const second = await postChat('otra vez');
  const parts: string[] = [];
  let done = false;
  await streamEvents(
    second.session_id,
    Number(second.cursor) || 0,
    {
      onEvent: (_id, event, data) => {
        if (event === 'chat.delta') parts.push(String(data.text ?? ''));
        if (event === 'chat.done') done = true;
        if (event === 'error') throw new Error(`stream error: ${JSON.stringify(data)}`);
      },
      onClose: () => {},
    },
    new AbortController().signal,
  );
  await killAndWait(sidecar);

  const text = parts.join('');
  console.log(`[e2e] second turn text: ${JSON.stringify(text)} done=${done}`);
  if (!done || !text) throw new Error('second turn did not complete over SSE');

  console.log('[e2e] OK');
}

main().catch(async (err: unknown) => {
  console.error('[e2e] FAIL:', err instanceof Error ? err.message : err);
  process.exitCode = 1;
});
