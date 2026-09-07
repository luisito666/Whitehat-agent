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
