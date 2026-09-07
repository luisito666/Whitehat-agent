/**
 * E2E for the ledger view + overview (Task 11), fully self-contained: it writes
 * a real-format evidence.jsonl into a throwaway cwd, spawns its own
 * deterministic sidecar there and drives GET /ledger and GET /status through
 * src/api.ts. The sidecar's A2A_*_URL envs are pointed at a dead port so every
 * worker reports down regardless of what else is running on this host.
 *
 *   pnpm exec tsx scripts/e2e-ledger-overview.ts
 *
 * Prints the rows LedgerView would render (short ts · technique · target ·
 * sha256[:8] · auth) and the OverviewView data (workers ●/○, engagement,
 * protocol, base url). Exit 0 on success, 1 otherwise.
 */
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const REPO_ROOT = resolve(import.meta.dirname, '../..');
const PY = resolve(REPO_ROOT, '.venv/bin/python');
const PORT = Number(process.env.PENTEST_CHAT_PORT ?? 9141);
// Must be set BEFORE api.ts is imported — it reads BASE_URL from the env once.
process.env.PENTEST_TUI_URL = `http://127.0.0.1:${PORT}`;
const { BASE_URL, getLedger, getStatus } = await import('../src/api.js');

// Three entries in the exact shape reports/evidence.jsonl uses: two Metasploit
// runs (carry `msf` + `exploit_method`, no hash) and one HTTP PoC (carries
// `body_sha256` + `url`, proven).
const ENTRIES = [
  {
    ts: '2026-09-07T01:10:24+00:00',
    exploit_method: 'metasploit',
    engagement_id: 'mcp-test-001',
    technique: 'metasploit-module',
    target: '127.0.0.1',
    msf: {
      backend: 'sim',
      module: 'auxiliary/scanner/ssh/ssh_version',
      options: {},
      job_id: null,
      session_opened: false,
    },
    auth_reference: 'REF-1',
    proven: false,
  },
  {
    ts: '2026-09-07T01:44:20+00:00',
    exploit_method: 'metasploit',
    engagement_id: 'mcp-test-001',
    technique: 'metasploit-module',
    target: '127.0.0.1',
    msf: {
      backend: 'sim',
      module: 'exploit/multi/http/some_rce',
      options: { RHOSTS: '127.0.0.1' },
      job_id: 3,
      session_opened: true,
      output_tail: '[*] Started reverse TCP handler\n[+] Session 1 opened',
    },
    auth_reference: 'REF-1',
    proven: true,
  },
  {
    ts: '2026-09-07T02:15:00+00:00',
    engagement_id: 'mcp-test-001',
    technique: 'http-path-traversal',
    target: '10.0.0.5',
    url: 'http://10.0.0.5/files/../canary/canary.txt',
    http_status: 200,
    proven: true,
    body_sha256:
      '9f2c4e1b7a3d5f6088c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f60718293a4b5c6d7',
    evidence_snippet: 'WH-CANARY-abc123',
    auth_reference: 'REF-1',
  },
];

function str(v: unknown): string | null {
  return typeof v === 'string' && v.trim() !== '' ? v : null;
}
function shortTs(v: unknown): string {
  const s = str(v);
  const m = s ? /^\d{4}-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(s) : null;
  return m ? `${m[1]}-${m[2]} ${m[3]}:${m[4]}` : (s ?? '?');
}

// A port nothing listens on: forces every worker card poll to fail -> up:false.
const DEAD = 'http://127.0.0.1:9099';

function startSidecar(cwd: string): ChildProcess {
  const child = spawn(PY, ['-m', 'pentest_agent.chat_server'], {
    cwd,
    env: {
      ...process.env,
      PENTEST_CHAT_DETERMINISTIC: '1',
      PENTEST_CHAT_PORT: String(PORT),
      A2A_RECON_URL: DEAD,
      A2A_VULN_URL: DEAD,
      A2A_REPORTER_URL: DEAD,
    },
    stdio: ['ignore', 'ignore', 'inherit'],
  });
  child.unref();
  return child;
}

async function waitForStatus(attempts: number): Promise<void> {
  for (let i = 0; i < attempts; i++) {
    try {
      await getStatus();
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
  const dir = mkdtempSync(join(tmpdir(), 'pentest-ledger-'));
  mkdirSync(join(dir, 'reports'));
  writeFileSync(
    join(dir, 'reports', 'evidence.jsonl'),
    ENTRIES.map((e) => JSON.stringify(e)).join('\n') + '\n',
  );
  console.log(`[e2e] base url: ${BASE_URL}`);
  console.log(`[e2e] fixture cwd: ${dir} (3 entries)`);

  const sidecar = startSidecar(dir);
  try {
    await waitForStatus(40);

    // --- LedgerView data ---------------------------------------------------
    const ledger = await getLedger(20);
    console.log(`\n[ledger] total=${ledger.total}`);
    if (ledger.entries.length === 0) {
      console.log('  ledger vacío — sin evidencia registrada');
    }
    for (const e of ledger.entries as Record<string, unknown>[]) {
      const technique = str(e.technique) ?? str(e.exploit_method) ?? '—';
      const target = str(e.target) ?? '?';
      const hash = str(e.body_sha256);
      const auth = str(e.auth_reference);
      const proven = e.proven === true ? ' ✓' : '';
      console.log(
        `  ${shortTs(e.ts)}  ${technique} · ${target}` +
          `${hash ? ` · ${hash.slice(0, 8)}` : ''}` +
          `${auth ? ` · auth ${auth}` : ''}${proven}`,
      );
    }
    if (ledger.total !== ENTRIES.length) {
      throw new Error(`expected ${ENTRIES.length} entries, got ${ledger.total}`);
    }
    const hashRow = (ledger.entries as Record<string, unknown>[]).find(
      (e) => typeof e.body_sha256 === 'string',
    );
    if (!hashRow) throw new Error('the http PoC row with body_sha256 was dropped');

    // --- OverviewView data ----------------------------------------------------
    const status = await getStatus();
    console.log(`\n[overview] protocolo ${status.protocol} · base ${BASE_URL}`);
    console.log('[overview] workers');
    for (const w of status.workers) {
      console.log(`  ${w.up ? '●' : '○'} ${w.role}  ${w.url}`);
    }
    const eng = status.engagement;
    console.log(
      `[overview] engagement: ${eng.id ? `${eng.id} · ${eng.client}` : 'sin engagement'}`,
    );

    if (status.workers.length === 0) throw new Error('no workers in /status');
    if (status.workers.some((w) => w.up)) {
      throw new Error('no A2A servers are running — every worker must be down');
    }

    console.log('\n[e2e] OK');
  } finally {
    await killAndWait(sidecar);
    rmSync(dir, { recursive: true, force: true });
  }
}

main().catch((err: unknown) => {
  console.error('[e2e] FAIL:', err instanceof Error ? err.message : err);
  process.exitCode = 1;
});
