import { render } from 'ink-testing-library';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { App } from './App.js';
import { BusProvider } from './bus.js';

beforeEach(() => {
  // No sidecar in the test env: every poll rejects -> DISCOVER_FAIL.
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

test('App renders the header and a connecting status on boot', () => {
  const { lastFrame, unmount } = render(
    <BusProvider>
      <App />
    </BusProvider>,
  );
  const frame = lastFrame() ?? '';
  expect(frame).toContain('pentest-chat');
  expect(frame).toContain('protocol 1');
  expect(frame).toContain('connecting to sidecar');
  // input hint is always visible
  expect(frame).toContain('Enter envía');
  unmount();
});

test('status bar is always visible with the run state and engagement', () => {
  const { lastFrame, unmount } = render(
    <BusProvider>
      <App />
    </BusProvider>,
  );
  const frame = lastFrame() ?? '';
  expect(frame).toContain('estado');
  // no /status yet in the test env -> engagement shows the red fallback
  expect(frame).toContain('sin engagement');
  unmount();
});

test('Ctrl+P opens the approve gate; Esc returns to the chat', async () => {
  const { lastFrame, stdin, unmount } = render(
    <BusProvider>
      <App />
    </BusProvider>,
  );

  expect(lastFrame() ?? '').toContain('Enter envía');

  stdin.write(''); // Ctrl+P
  await delay(20);
  const open = lastFrame() ?? '';
  expect(open).toContain('engagement');
  expect(open).toContain('Puerta de aprobación');
  // chat input is gone while the gate is open
  expect(open).not.toContain('Enter envía');

  stdin.write(''); // Esc
  await delay(20);
  const back = lastFrame() ?? '';
  expect(back).toContain('Enter envía');
  expect(back).not.toContain('Puerta de aprobación');
  unmount();
});
