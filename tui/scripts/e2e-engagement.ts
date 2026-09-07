/**
 * Throwaway-ish E2E for the approve-gate: drive the real sidecar's
 * GET /engagement through src/api.ts and print what the banner would show.
 *
 * Assumes a sidecar is already listening. Two runs:
 *
 *   # with an engagement in force -> prints id / client / window / auth_reference
 *   cp tests/fixtures/engagement.valid.yaml /tmp/eng.yaml
 *   PENTEST_CHAT_DETERMINISTIC=1 PENTEST_CHAT_PORT=9112 \
 *     PENTEST_ENGAGEMENT_FILE=/tmp/eng.yaml \
 *     .venv/bin/python -m pentest_agent.chat_server > /tmp/sidecar.log 2>&1 &
 *   ( cd tui && PENTEST_TUI_URL=http://127.0.0.1:9112 pnpm exec tsx scripts/e2e-engagement.ts )
 *
 *   # without one -> prints "null (404)" (fail-closed banner)
 *   PENTEST_CHAT_DETERMINISTIC=1 PENTEST_CHAT_PORT=9113 \
 *     .venv/bin/python -m pentest_agent.chat_server > /tmp/sidecar.log 2>&1 &
 *   ( cd tui && PENTEST_TUI_URL=http://127.0.0.1:9113 pnpm exec tsx scripts/e2e-engagement.ts )
 *
 * Exit code 0 on a clean fetch (either outcome), 1 on transport failure.
 */
import { BASE_URL, getEngagement } from '../src/api.js';

async function main(): Promise<void> {
  console.log(`[e2e] base url: ${BASE_URL}`);
  const eng = await getEngagement();

  if (eng === null) {
    console.log('[engagement] null (404) -> fail-closed banner: run approve.py');
    console.log('[e2e] OK');
    return;
  }

  console.log(
    `[engagement] id=${eng.id} client=${eng.client} ` +
      `valid=${eng.valid} approved=${eng.approved}`,
  );
  console.log(
    `[engagement] window=${eng.window.valid_from}..${eng.window.valid_until} ` +
      `auth_reference=${eng.auth_reference}`,
  );
  if (!eng.id || !eng.auth_reference) throw new Error('engagement missing id/auth_reference');
  console.log('[e2e] OK');
}

main().catch((err: unknown) => {
  console.error('[e2e] FAIL:', err instanceof Error ? err.message : err);
  process.exit(1);
});
