import { render } from 'ink-testing-library';
import { afterEach, expect, test, vi } from 'vitest';
import type { Engagement, Status } from '../api.js';
import { getEngagement, getStatus } from '../api.js';
import { OverviewView } from './OverviewView.js';

vi.mock('../api.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api.js')>();
  return { ...actual, getStatus: vi.fn(), getEngagement: vi.fn() };
});

const mockStatus = vi.mocked(getStatus);
const mockEngagement = vi.mocked(getEngagement);

const STATUS = (over: Partial<Status> = {}): Status => ({
  stack: 'up',
  workers: [
    { role: 'recon', url: 'http://127.0.0.1:9101', up: true },
    { role: 'vuln', url: 'http://127.0.0.1:9102', up: false },
    { role: 'reporter', url: 'http://127.0.0.1:9103', up: false },
  ],
  engagement: { id: 'ENG-1', client: 'ACME', valid: true, approved: false },
  protocol: 1,
  ...over,
});

const FULL_ENG: Engagement = {
  id: 'ENG-1',
  client: 'ACME',
  valid: true,
  approved: false,
  window: { valid_from: '2026-01-01', valid_until: '2026-12-31' },
  auth_reference: 'PO-42',
};

afterEach(() => {
  vi.clearAllMocks();
});

test('workers render up/down with role, url and marker; protocol + session shown', async () => {
  mockStatus.mockResolvedValue(STATUS());
  mockEngagement.mockResolvedValue(FULL_ENG);
  const { lastFrame, unmount } = render(
    <OverviewView onClose={vi.fn()} sessionId="sess-abcdef-123456" />,
  );

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('recon');
  });
  const frame = lastFrame() ?? '';
  expect(frame).toContain('vuln');
  expect(frame).toContain('reporter');
  expect(frame).toContain('http://127.0.0.1:9101');
  expect(frame).toContain('●'); // recon is up
  expect(frame).toContain('○'); // vuln / reporter are down
  expect(frame).toContain('protocolo 1');
  expect(frame).toContain('sess-abcdef-123456'); // full session id
  expect(frame).toContain('2026-01-01'); // engagement window from GET /engagement
  expect(frame).toContain('PO-42');
  unmount();
});

test('engagement present -> id and client shown', async () => {
  mockStatus.mockResolvedValue(STATUS());
  mockEngagement.mockResolvedValue(null);
  const { lastFrame, unmount } = render(
    <OverviewView onClose={vi.fn()} sessionId={null} />,
  );

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('ENG-1');
  });
  expect(lastFrame() ?? '').toContain('ACME');
  expect(lastFrame() ?? '').toContain('(sin sesión aún)');
  unmount();
});

test('engagement absent -> "sin engagement"', async () => {
  mockStatus.mockResolvedValue(
    STATUS({
      engagement: { id: null, client: null, valid: false, approved: false },
    }),
  );
  mockEngagement.mockResolvedValue(null);
  const { lastFrame, unmount } = render(
    <OverviewView onClose={vi.fn()} sessionId={null} />,
  );

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('sin engagement');
  });
  unmount();
});

test('Esc calls onClose', async () => {
  mockStatus.mockReturnValue(new Promise(() => {}));
  mockEngagement.mockReturnValue(new Promise(() => {}));
  const onClose = vi.fn();
  const { stdin, unmount } = render(
    <OverviewView onClose={onClose} sessionId={null} />,
  );

  await new Promise((r) => setTimeout(r, 20));
  stdin.write('\x1B'); // Esc
  await new Promise((r) => setTimeout(r, 20));
  expect(onClose).toHaveBeenCalledOnce();
  unmount();
});
