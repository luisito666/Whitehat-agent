import { render } from 'ink-testing-library';
import { afterEach, expect, test, vi } from 'vitest';

// A turn is driven entirely through the mocked SSE reader: postChat resolves,
// then streamEvents replays a delta + chat.done and closes. The turn must land
// back on `ready`.
vi.mock('./api.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api.js')>();
  return {
    ...actual,
    getStatus: vi.fn().mockResolvedValue({
      stack: 'up',
      workers: [],
      engagement: { id: 'ENG-1', client: 'ACME', valid: true, approved: false },
      protocol: 1,
    }),
    postChat: vi.fn().mockResolvedValue({ session_id: 's1', cursor: '0' }),
  };
});

vi.mock('./sse.js', () => ({
  streamEvents: vi.fn(
    async (
      _sid: string,
      _cursor: number,
      handlers: {
        onEvent: (id: number, event: string, data: Record<string, unknown>) => void;
        onClose: () => void;
      },
    ) => {
      handlers.onEvent(1, 'chat.delta', { text: 'pong' });
      handlers.onEvent(2, 'chat.done', {});
      handlers.onClose();
    },
  ),
}));

const { App } = await import('./App.js');
const { BusProvider } = await import('./bus.js');

const delay = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

afterEach(() => {
  vi.clearAllMocks();
});

test('a turn finished over SSE returns the phase to ready', async () => {
  const { lastFrame, stdin, unmount } = render(
    <BusProvider>
      <App />
    </BusProvider>,
  );

  // GET /status resolves -> DISCOVER_OK -> ready
  await delay(30);
  expect(lastFrame() ?? '').toContain('ready');

  stdin.write('hola');
  await delay(10);
  stdin.write('\r'); // Enter -> SUBMIT -> runTurn -> streamEvents (mocked)
  await delay(50);

  const frame = lastFrame() ?? '';
  expect(frame).toContain('> hola'); // user line
  expect(frame).toContain('pong'); // assistant text flushed to history
  expect(frame).toContain('ready'); // phase is back to ready
  expect(frame).not.toContain('thinking');
  expect(frame).not.toContain('reconectando');
  unmount();
});
