import { afterEach, describe, expect, test, vi } from 'vitest';
import { parseSSE, parseSse, streamEvents, type SseHandlers } from './sse.js';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// --- a ReadableStream of string chunks, like a fetch() body ----------------
function streamRes(chunks: string[], init: { ok?: boolean; status?: number } = {}) {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    body: new ReadableStream<string>({
      start(controller) {
        for (const c of chunks) controller.enqueue(c);
        controller.close();
      },
    }),
  };
}

const frame = (id: number, event: string, data: unknown): string =>
  `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function collector(): SseHandlers & {
  events: Array<[number, string, Record<string, unknown>]>;
  onClose: ReturnType<typeof vi.fn>;
  onReconnecting: ReturnType<typeof vi.fn>;
  onReconnected: ReturnType<typeof vi.fn>;
} {
  const events: Array<[number, string, Record<string, unknown>]> = [];
  return {
    events,
    onEvent: (id, event, data) => events.push([id, event, data]),
    onClose: vi.fn(),
    onReconnecting: vi.fn(),
    onReconnected: vi.fn(),
  };
}

// -------------------------------------------------------------------- parser
describe('parseSSE (re-exported pure parser)', () => {
  test('parseSSE is the same function as parseSse', () => {
    expect(parseSSE).toBe(parseSse);
  });

  test('decodes complete frames with incremental ids, keeps the partial tail', () => {
    const raw =
      frame(1, 'chat.delta', { text: 'a' }) +
      frame(2, 'chat.delta', { text: 'b' }) +
      'id: 3\nevent: chat.delta\ndata: {"text":"c';
    const { events, rest } = parseSSE(raw);
    expect(events).toEqual([
      { id: 1, event: 'chat.delta', data: { text: 'a' } },
      { id: 2, event: 'chat.delta', data: { text: 'b' } },
    ]);
    expect(rest).toBe('id: 3\nevent: chat.delta\ndata: {"text":"c');
  });

  test('a partial frame parses once its terminator arrives', () => {
    const first = parseSSE('id: 7\nevent: chat.delta\ndata: {"text":"hi"}');
    expect(first.events).toEqual([]);
    expect(first.rest).toContain('hi');
    const { events } = parseSSE(first.rest + '\n\n');
    expect(events).toEqual([{ id: 7, event: 'chat.delta', data: { text: 'hi' } }]);
  });

  test('joins multiple data: lines with \\n before parsing', () => {
    const raw = 'id: 9\nevent: chat.delta\ndata: {"text":\ndata: "split"}\n\n';
    const { events } = parseSSE(raw);
    expect(events).toEqual([
      { id: 9, event: 'chat.delta', data: { text: 'split' } },
    ]);
  });
});

// ---------------------------------------------------------------- reconnect
describe('streamEvents reconnect', () => {
  test('chat.done in the first stream → onClose, no reconnect', async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(
        streamRes([frame(1, 'chat.delta', { text: 'pong' }), frame(2, 'chat.done', {})]),
      );
    vi.stubGlobal('fetch', fetchFn);
    const h = collector();

    await streamEvents('sid', 0, h, new AbortController().signal);

    expect(fetchFn).toHaveBeenCalledOnce();
    expect(h.events.map((e) => e[1])).toEqual(['chat.delta', 'chat.done']);
    expect(h.onClose).toHaveBeenCalledOnce();
    expect(h.onReconnecting).not.toHaveBeenCalled();
  });

  test('server closes without a terminal frame → reconnects from lastEventId', async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(
        streamRes([frame(1, 'chat.delta', { text: 'a' }), frame(2, 'chat.delta', { text: 'b' })]),
      )
      .mockResolvedValueOnce(streamRes([frame(3, 'chat.done', {})]));
    vi.stubGlobal('fetch', fetchFn);
    const h = collector();

    await streamEvents('sid', 0, h, new AbortController().signal, {
      backoffMs: [1, 1, 1],
    });

    expect(fetchFn).toHaveBeenCalledTimes(2);
    expect(String(fetchFn.mock.calls[0][0])).toContain('cursor=0');
    // second connection resumes past the last delivered id
    expect(String(fetchFn.mock.calls[1][0])).toContain('cursor=2');
    expect(h.events.map((e) => e[0])).toEqual([1, 2, 3]);
    expect(h.onReconnecting).toHaveBeenCalled();
    expect(h.onReconnected).toHaveBeenCalled();
    expect(h.onClose).toHaveBeenCalledOnce();
  });

  test('backoff is 500ms → 1s → 2s and gives up (onClose) after 3 attempts', async () => {
    vi.useFakeTimers();
    const fetchFn = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    vi.stubGlobal('fetch', fetchFn);
    const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    const h = collector();

    const p = streamEvents('sid', 0, h, new AbortController().signal);

    await vi.advanceTimersByTimeAsync(0); // initial fetch rejects, schedules retry 1
    await vi.advanceTimersByTimeAsync(500); // retry 1 rejects, schedules retry 2
    await vi.advanceTimersByTimeAsync(1000); // retry 2 rejects, schedules retry 3
    await vi.advanceTimersByTimeAsync(2000); // retry 3 rejects, budget spent
    await p;

    const delays = setTimeoutSpy.mock.calls
      .map((c) => c[1])
      .filter((d): d is number => d === 500 || d === 1000 || d === 2000);
    expect(delays).toEqual([500, 1000, 2000]);
    expect(fetchFn).toHaveBeenCalledTimes(4); // 1 initial + 3 retries
    expect(h.onClose).toHaveBeenCalledOnce();
    expect(h.onReconnecting).toHaveBeenCalledOnce();
    expect(h.events).toEqual([]);
  });

  test('an aborted signal stops the reader without calling onClose', async () => {
    const ac = new AbortController();
    ac.abort();
    const fetchFn = vi.fn();
    vi.stubGlobal('fetch', fetchFn);
    const h = collector();

    await streamEvents('sid', 0, h, ac.signal);

    expect(fetchFn).not.toHaveBeenCalled();
    expect(h.onClose).not.toHaveBeenCalled();
  });
});
