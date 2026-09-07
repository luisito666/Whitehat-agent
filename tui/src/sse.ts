/**
 * Live SSE reader for GET /chat/{sid}/events with transparent reconnect.
 *
 * Why not `EventSource`: the WHATWG/undici EventSource in Node 22 cannot send
 * custom headers and has no clean abort story. The Node-native pattern is a
 * `fetch` whose `Response.body` is a `ReadableStream` we drain frame by frame.
 *
 * The sidecar long-polls for up to ~55s and then closes the stream; it also
 * closes right after the terminal `chat.delta`… `chat.done` / `error` frame.
 * So a *clean* close is normal and we simply reconnect from `lastEventId`
 * (the sidecar replays anything buffered past that cursor — no chat is lost).
 * A close whose last frame was `chat.done` / `error` is the real end of the
 * turn: `onClose()` fires and we stop.
 *
 * Reconnect budget: MAX_ATTEMPTS consecutive failed/empty reconnects with a
 * 500ms → 1s → 2s backoff. A reconnect that actually delivers new events resets
 * the budget (a slow multi-minute turn keeps streaming). Once the budget is
 * spent we give up with a plain `onClose()`.
 */
import { BASE_URL, ApiError, parseSse, type ChatEvent } from './api.js';

/** Re-exported so tests can hit the pure parser without importing api.ts. */
export { parseSse, parseSse as parseSSE } from './api.js';

export interface SseHandlers {
  /** One decoded frame. `data` is the parsed JSON payload (`{}` if not JSON). */
  onEvent: (id: number, event: string, data: Record<string, unknown>) => void;
  /** The stream is finished: terminal frame seen, or the reconnect budget spent. */
  onClose: () => void;
  /** A non-terminal close led to a scheduled retry (status bar: "reconnecting…"). */
  onReconnecting?: () => void;
  /** A retry re-established the stream and delivered fresh events. */
  onReconnected?: () => void;
}

export interface StreamOptions {
  /** Backoff ladder in ms; the last value repeats. Default 500 / 1000 / 2000. */
  backoffMs?: number[];
  /** Consecutive failed reconnects tolerated before giving up. Default 3. */
  maxAttempts?: number;
}

export const DEFAULT_BACKOFF_MS: readonly number[] = [500, 1000, 2000];
export const DEFAULT_MAX_ATTEMPTS = 3;

const TERMINAL = new Set(['chat.done', 'error']);

/** `setTimeout` that also resolves early if `signal` aborts. */
function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve) => {
    const done = (): void => {
      clearTimeout(timer);
      signal.removeEventListener('abort', done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    if (signal.aborted) done();
    else signal.addEventListener('abort', done, { once: true });
  });
}

/**
 * Drain one `Response` body, feeding decoded frames to `onFrame`. Keeps a
 * running buffer so a frame split across chunk boundaries is not lost; the
 * trailing partial frame stays buffered until the next chunk (or is dropped
 * when the stream ends, as the spec allows for an unterminated frame).
 */
async function drain(
  res: Response,
  onFrame: (ev: ChatEvent) => void,
): Promise<void> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf +=
        typeof value === 'string' ? value : decoder.decode(value, { stream: true });
      const { events, rest } = parseSse(buf);
      buf = rest;
      for (const ev of events) onFrame(ev);
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Stream events for `sessionId` starting past `cursor`, reconnecting across
 * benign stream closes until a terminal frame or the reconnect budget runs out.
 * Resolves once `onClose()` has fired (or the caller aborted `signal`).
 */
export async function streamEvents(
  sessionId: string,
  cursor: number,
  handlers: SseHandlers,
  signal: AbortSignal,
  opts: StreamOptions = {},
): Promise<void> {
  const backoff = opts.backoffMs ?? [...DEFAULT_BACKOFF_MS];
  const maxAttempts = opts.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  const path = `/chat/${encodeURIComponent(sessionId)}/events`;

  // Internal controller: aborted in `finally` so a lingering fetch/stream is
  // always torn down when we return. Timeout is intentionally 0 (disabled) —
  // the server owns the long-poll deadline, the client never times out a read.
  const internal = new AbortController();
  const combined =
    typeof AbortSignal.any === 'function'
      ? AbortSignal.any([signal, internal.signal])
      : signal;

  let lastEventId = cursor;
  let lastEventName = '';
  let attempt = 0;
  let reconnecting = false;

  try {
    for (;;) {
      if (signal.aborted) return;

      const before = lastEventId;
      try {
        const res = await fetch(`${BASE_URL}${path}?cursor=${lastEventId}`, {
          headers: { accept: 'text/event-stream' },
          signal: combined,
        });
        if (!res.ok) {
          throw new ApiError(res.status, `GET ${path} -> HTTP ${res.status}`);
        }
        await drain(res, (ev) => {
          if (ev.id > lastEventId) lastEventId = ev.id;
          lastEventName = ev.event;
          if (reconnecting) {
            reconnecting = false;
            handlers.onReconnected?.();
          }
          handlers.onEvent(ev.id, ev.event, ev.data);
        });
      } catch {
        // Network/HTTP failure: treated the same as a non-terminal close.
      }

      if (signal.aborted) return;

      if (TERMINAL.has(lastEventName)) {
        handlers.onClose();
        return;
      }

      // A reconnect that delivered fresh events earns a clean slate.
      if (lastEventId > before) attempt = 0;

      if (attempt >= maxAttempts) {
        handlers.onClose();
        return;
      }

      if (!reconnecting) {
        reconnecting = true;
        handlers.onReconnecting?.();
      }
      const wait = backoff[Math.min(attempt, backoff.length - 1)];
      attempt += 1;
      await sleep(wait, signal);
    }
  } finally {
    internal.abort();
  }
}
