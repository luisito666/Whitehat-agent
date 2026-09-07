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
 * Two distinct budgets, because the two failure shapes are not the same:
 *
 *   - **Real failures** (fetch rejects, non-OK HTTP, a drain that throws
 *     mid-stream): `maxAttempts` consecutive ones with a 500ms → 1s → 2s
 *     backoff, then we give up with a plain `onClose()`.
 *   - **Benign long-poll recycles** (fetch + drain completed cleanly, just no
 *     terminal frame): NOT a failure. A real audit has multi-minute silent
 *     stretches — recon/nmap, NVD correlation, report generation — where the
 *     sidecar streams nothing for a whole 55s window. Counting those against
 *     the failure budget killed the connection after ~3×55s while the turn was
 *     still running server-side. They now reconnect from the cursor without
 *     spending the failure budget; only `maxIdleCycles` (a very high absolute
 *     ceiling, ~hours) bounds them so a truly wedged stream still ends.
 *
 * A reconnect that delivers fresh events resets both budgets.
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
  /** Consecutive *real* failed reconnects tolerated before giving up. Default 3. */
  maxAttempts?: number;
  /** Delay before reconnecting after a benign long-poll recycle. Default 1000. */
  idleReconnectMs?: number;
  /**
   * Absolute ceiling on consecutive benign long-poll recycles that delivered
   * nothing — a safety net for a wedged-but-clean stream, not a real limit.
   * Default 250 (~4h at one 55s window per cycle).
   */
  maxIdleCycles?: number;
}

export const DEFAULT_BACKOFF_MS: readonly number[] = [500, 1000, 2000];
export const DEFAULT_MAX_ATTEMPTS = 3;
export const DEFAULT_IDLE_RECONNECT_MS = 1000;
export const DEFAULT_MAX_IDLE_CYCLES = 250;

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
  const idleReconnectMs = opts.idleReconnectMs ?? DEFAULT_IDLE_RECONNECT_MS;
  const maxIdleCycles = opts.maxIdleCycles ?? DEFAULT_MAX_IDLE_CYCLES;
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
  let failAttempt = 0; // consecutive real failures (fetch reject / non-OK / drain throw)
  let idleCycles = 0; // consecutive benign long-poll recycles that delivered nothing
  let reconnecting = false;

  try {
    for (;;) {
      if (signal.aborted) return;

      const before = lastEventId;
      let clean = false;
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
        // fetch + drain returned without throwing: the server closed the stream
        // on its own terms (long-poll deadline or a terminal frame), not a drop.
        clean = true;
      } catch {
        // Network / HTTP / mid-stream failure — a real error, distinct from the
        // server's benign ~55s long-poll close handled by the `clean` branch.
      }

      if (signal.aborted) return;

      if (TERMINAL.has(lastEventName)) {
        handlers.onClose();
        return;
      }

      const gotEvents = lastEventId > before;

      if (clean) {
        // Benign long-poll recycle. Not a failure: reconnect from the cursor
        // without touching the failure budget so a multi-minute quiet turn
        // survives. Only the absolute idle ceiling can end it.
        failAttempt = 0;
        idleCycles = gotEvents ? 0 : idleCycles + 1;
        if (idleCycles >= maxIdleCycles) {
          handlers.onClose();
          return;
        }
      } else {
        // Real failure: bounded retries with the backoff ladder. Fresh events
        // before the drop still earn a clean slate.
        if (gotEvents) failAttempt = 0;
        if (failAttempt >= maxAttempts) {
          handlers.onClose();
          return;
        }
      }

      if (!reconnecting) {
        reconnecting = true;
        handlers.onReconnecting?.();
      }

      let wait: number;
      if (clean) {
        wait = gotEvents ? 0 : idleReconnectMs;
      } else {
        wait = backoff[Math.min(failAttempt, backoff.length - 1)];
        failAttempt += 1;
      }
      await sleep(wait, signal);
    }
  } finally {
    internal.abort();
  }
}
