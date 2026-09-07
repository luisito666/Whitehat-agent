import { render } from 'ink-testing-library';
import { afterEach, expect, test, vi } from 'vitest';
import type { Engagement } from '../api.js';
import { getEngagement } from '../api.js';
import { ApproveGate } from './ApproveGate.js';

vi.mock('../api.js', () => ({ getEngagement: vi.fn() }));

const mockEngagement = vi.mocked(getEngagement);

const VALID: Engagement = {
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

test('valid engagement -> green banner with id, client, window, auth_reference, approved', async () => {
  mockEngagement.mockResolvedValue(VALID);
  const { lastFrame, unmount } = render(<ApproveGate onClose={vi.fn()} />);

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('ENG-1');
  });
  const frame = lastFrame() ?? '';
  expect(frame).toContain('ACME');
  expect(frame).toContain('2026-01-01');
  expect(frame).toContain('2026-12-31');
  expect(frame).toContain('PO-42');
  expect(frame).toContain('approved');
  expect(frame).toContain('engagement vigente');
  unmount();
});

test('no engagement (null) -> fail-closed instructions: approve module + "presencial"', async () => {
  mockEngagement.mockResolvedValue(null);
  const { lastFrame, unmount } = render(<ApproveGate onClose={vi.fn()} />);

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('sin engagement.yaml vigente');
  });
  const frame = lastFrame() ?? '';
  expect(frame).toContain('python -m pentest_agent.approve');
  expect(frame).toContain('presencial');
  expect(frame).toContain('jamás aprueba');
  unmount();
});

test('sidecar unreachable (fetch rejects) -> also shows the fail-closed procedure', async () => {
  mockEngagement.mockRejectedValue(new Error('ECONNREFUSED'));
  const { lastFrame, unmount } = render(<ApproveGate onClose={vi.fn()} />);

  await vi.waitFor(() => {
    expect(lastFrame() ?? '').toContain('python -m pentest_agent.approve');
  });
  unmount();
});

test('loading state -> spinner while the engagement is in flight', () => {
  mockEngagement.mockReturnValue(new Promise<never>(() => {}));
  const { lastFrame, unmount } = render(<ApproveGate onClose={vi.fn()} />);

  const frame = lastFrame() ?? '';
  expect(frame).toContain('cargando engagement');
  expect(frame).toMatch(/[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]/);
  unmount();
});

test('Esc calls onClose', async () => {
  mockEngagement.mockReturnValue(new Promise<never>(() => {}));
  const onClose = vi.fn();
  const { stdin, unmount } = render(<ApproveGate onClose={onClose} />);

  await new Promise((r) => setTimeout(r, 20));

  stdin.write(''); // Esc
  await new Promise((r) => setTimeout(r, 20));
  expect(onClose).toHaveBeenCalledOnce();
  unmount();
});
