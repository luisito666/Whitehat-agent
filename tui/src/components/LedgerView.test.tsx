import { render } from 'ink-testing-library';
import { afterEach, expect, test, vi } from 'vitest';
import type { LedgerEntry } from '../api.js';
import { getLedger } from '../api.js';
import { LedgerView } from './LedgerView.js';

vi.mock('../api.js', () => ({ getLedger: vi.fn() }));

const mockLedger = vi.mocked(getLedger);

// Real-shape rows from reports/evidence.jsonl: a Metasploit run (carries `msf`,
// `exploit_method`, no hash) and an HTTP PoC (carries `body_sha256`, `url`).
const ENTRIES: LedgerEntry[] = [
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
    ts: '2026-09-07T02:15:00+00:00',
    engagement_id: 'mcp-test-001',
    technique: 'http-path-traversal',
    target: '10.0.0.5',
    url: 'http://10.0.0.5/files/../canary/canary.txt',
    http_status: 200,
    proven: true,
    body_sha256: 'deadbeefcafef00d1234567890abcdef00112233',
    evidence_snippet: 'WH-CANARY-xyz',
    auth_reference: 'REF-1',
  },
];

afterEach(() => {
  vi.clearAllMocks();
});

test('one row per entry: short ts, technique, target, truncated hash, auth', async () => {
  mockLedger.mockResolvedValue({ entries: ENTRIES, total: ENTRIES.length });
  const { lastFrame, unmount } = render(<LedgerView onClose={vi.fn()} />);

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('metasploit-module');
  });
  const frame = lastFrame() ?? '';
  expect(frame).toContain('http-path-traversal');
  expect(frame).toContain('127.0.0.1');
  expect(frame).toContain('10.0.0.5');
  // hash truncated to 8 chars, never the full digest
  expect(frame).toContain('deadbeef');
  expect(frame).not.toContain('deadbeefcafef00d');
  // the metasploit row carries no hash -> nothing invented for it
  expect(frame).toContain('REF-1');
  expect(frame).toContain('01:10'); // short timestamp
  expect(frame).toContain('2 entradas');
  expect(getLedger).toHaveBeenCalledWith(20);
  unmount();
});

test('empty ledger -> explicit message', async () => {
  mockLedger.mockResolvedValue({ entries: [], total: 0 });
  const { lastFrame, unmount } = render(<LedgerView onClose={vi.fn()} />);

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('ledger vacío');
  });
  expect(lastFrame() ?? '').toContain('sin evidencia registrada');
  unmount();
});

test('"r" re-fetches the ledger', async () => {
  mockLedger.mockResolvedValue({ entries: [], total: 0 });
  const { lastFrame, stdin, unmount } = render(<LedgerView onClose={vi.fn()} />);

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('ledger vacío');
  });
  expect(mockLedger).toHaveBeenCalledTimes(1);

  stdin.write('r');
  await vi.waitFor(() => {
    expect(mockLedger).toHaveBeenCalledTimes(2);
  });
  unmount();
});

test('Esc calls onClose', async () => {
  mockLedger.mockReturnValue(new Promise(() => {}));
  const onClose = vi.fn();
  const { stdin, unmount } = render(<LedgerView onClose={onClose} />);

  await new Promise((r) => setTimeout(r, 20));
  stdin.write('\x1B'); // Esc
  await new Promise((r) => setTimeout(r, 20));
  expect(onClose).toHaveBeenCalledOnce();
  unmount();
});
