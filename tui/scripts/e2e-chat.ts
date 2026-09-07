/**
 * Throwaway-ish E2E: drive the real sidecar through src/api.ts.
 *
 * Assumes a sidecar is already listening (see the command in tui/README.md):
 *   PENTEST_CHAT_DETERMINISTIC=1 PENTEST_CHAT_PORT=9111 \
 *     .venv/bin/python -m pentest_agent.chat_server &
 *   PENTEST_TUI_URL=http://127.0.0.1:9111 pnpm exec tsx scripts/e2e-chat.ts
 *
 * Does: getStatus -> postChat -> read events until chat.done, prints the text.
 * Exit code 0 on a clean turn, 1 otherwise.
 */
import {
  BASE_URL,
  fetchEvents,
  getStatus,
  postChat,
  type ChatEvent,
} from '../src/api.js';

const sleep = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

async function waitForStatus(attempts: number): Promise<void> {
  for (let i = 0; i < attempts; i++) {
    try {
      const status = await getStatus();
      console.log(
        `[status] protocol=${status.protocol} stack=${status.stack} ` +
          `workers=${status.workers.map((w) => `${w.role}:${w.up ? 'up' : 'down'}`).join(',')}`,
      );
      return;
    } catch (err) {
      await sleep(250);
      if (i === attempts - 1) throw err;
    }
  }
}

async function main(): Promise<void> {
  console.log(`[e2e] base url: ${BASE_URL}`);
  await waitForStatus(40);

  const first = await postChat('hola sidecar');
  console.log(`[chat] session=${first.session_id} cursor=${first.cursor}`);

  let seen = Number(first.cursor) || 0;
  const collected: ChatEvent[] = [];
  let done = false;
  for (let i = 0; i < 40 && !done; i++) {
    const events = await fetchEvents(first.session_id, seen);
    for (const ev of events) {
      if (ev.id > seen) seen = ev.id;
      collected.push(ev);
      if (ev.event === 'chat.done') done = true;
      if (ev.event === 'error') {
        throw new Error(`stream error: ${JSON.stringify(ev.data)}`);
      }
    }
    if (!done) await sleep(500);
  }

  if (!done) throw new Error('never saw chat.done');

  const text = collected
    .filter((e) => e.event === 'chat.delta')
    .map((e) => String(e.data.text ?? ''))
    .join('');
  const activity = collected.filter((e) => e.event === 'agent.activity');

  console.log(`[e2e] agent.activity events: ${activity.length}`);
  console.log(`[e2e] final assistant text: ${JSON.stringify(text)}`);

  if (!text) throw new Error('empty assistant text');
  console.log('[e2e] OK');
}

main().catch((err: unknown) => {
  console.error('[e2e] FAIL:', err instanceof Error ? err.message : err);
  process.exit(1);
});
