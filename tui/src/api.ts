/**
 * Minimal HTTP client for the chat sidecar (`src/pentest_agent/chat_server.py`).
 *
 * Contract v1 (protocol 1), all endpoints on loopback:
 *   GET  /status                       -> Status
 *   POST /chat {session_id?, message}  -> PostChatResult
 *   GET  /engagement                   -> Engagement (404 when there is none)
 *   GET  /ledger?tail=N                -> Ledger
 *   GET  /chat/{sid}/events?cursor=N   -> SSE (text/event-stream), incremental ids
 *
 * Node 22 ships a global `fetch` and `AbortSignal.timeout`, so there is no
 * dependency here beyond the platform.
 */

export const BASE_URL: string =
  process.env.PENTEST_TUI_URL?.replace(/\/$/, '') ?? 'http://127.0.0.1:9000';

/** Short timeout: `/status` and friends must never hang the TUI. */
export const DEFAULT_TIMEOUT_MS = 2000;

/** A turn blocks POST /chat until it finishes; give it more room than a poll. */
export const CHAT_TIMEOUT_MS = 120_000;

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

// --- contract types -------------------------------------------------------

export interface Worker {
  role: string;
  url: string;
  up: boolean;
}

/** Engagement summary as embedded in GET /status (no secrets). */
export interface EngagementSummary {
  id: string | null;
  client: string | null;
  valid: boolean;
  approved: boolean;
}

export interface Status {
  stack: string;
  workers: Worker[];
  engagement: EngagementSummary;
  protocol: number;
}

export interface PostChatResult {
  session_id: string;
  cursor: string;
}

export interface EngagementWindow {
  valid_from: string | null;
  valid_until: string | null;
}

/** Full public engagement view from GET /engagement (still no secrets). */
export interface Engagement {
  id: string | null;
  client: string | null;
  valid: boolean;
  approved: boolean;
  window: EngagementWindow;
  auth_reference: string | null;
}

export type LedgerEntry = Record<string, unknown>;

export interface Ledger {
  entries: LedgerEntry[];
  total: number;
}

/** One decoded SSE frame from GET /chat/{sid}/events. */
export interface ChatEvent {
  id: number;
  event: string;
  data: Record<string, unknown>;
}

// --- transport ----------------------------------------------------------

async function request(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    throw new ApiError(0, `${init.method ?? 'GET'} ${path} failed: ${reason}`);
  }
  return res;
}

async function json<T>(res: Response, path: string): Promise<T> {
  if (!res.ok) {
    throw new ApiError(res.status, `${path} -> HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

// --- endpoints --------------------------------------------------------

export async function getStatus(): Promise<Status> {
  const res = await request('/status');
  return json<Status>(res, 'GET /status');
}

export async function postChat(
  message: string,
  sessionId?: string,
): Promise<PostChatResult> {
  const body: { message: string; session_id?: string } = { message };
  if (sessionId !== undefined) body.session_id = sessionId;
  const res = await request(
    '/chat',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    },
    CHAT_TIMEOUT_MS,
  );
  return json<PostChatResult>(res, 'POST /chat');
}

/** GET /engagement; a 404 (no engagement.yaml) is not an error here -> null. */
export async function getEngagement(): Promise<Engagement | null> {
  const res = await request('/engagement');
  if (res.status === 404) return null;
  return json<Engagement>(res, 'GET /engagement');
}

export async function getLedger(tail: number): Promise<Ledger> {
  const res = await request(`/ledger?tail=${encodeURIComponent(tail)}`);
  return json<Ledger>(res, 'GET /ledger');
}

// --- SSE (interim: Task 10 replaces this with a live EventSource) -----------

/**
 * Parse a `text/event-stream` payload into frames. Frames are separated by a
 * blank line; within a frame we read `id:`, `event:` and `data:` lines. A
 * trailing partial frame (no blank-line terminator) is returned so the caller
 * can prepend it to the next chunk.
 */
export function parseSse(text: string): { events: ChatEvent[]; rest: string } {
  const events: ChatEvent[] = [];
  const parts = text.split('\n\n');
  const rest = parts.pop() ?? '';
  for (const frame of parts) {
    let id = 0;
    let event = '';
    let data = '';
    for (const line of frame.split('\n')) {
      if (line.startsWith('id:')) id = Number(line.slice(3).trim()) || 0;
      else if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data = line.slice(5).trim();
    }
    if (!event) continue;
    let parsed: Record<string, unknown> = {};
    if (data) {
      try {
        parsed = JSON.parse(data) as Record<string, unknown>;
      } catch {
        parsed = {};
      }
    }
    events.push({ id, event, data: parsed });
  }
  return { events, rest };
}

/**
 * Fetch the buffered/streamed events for a session with id > `cursor` and
 * return them once the connection closes (the sidecar closes on the terminal
 * `chat.done`/`error` frame). Interim replacement for the real SSE reader.
 */
export async function fetchEvents(
  sessionId: string,
  cursor: number,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<ChatEvent[]> {
  const res = await request(
    `/chat/${encodeURIComponent(sessionId)}/events?cursor=${cursor}`,
    { headers: { accept: 'text/event-stream' } },
    timeoutMs,
  );
  if (!res.ok) {
    throw new ApiError(res.status, `GET /chat/${sessionId}/events -> HTTP ${res.status}`);
  }
  const body = await res.text();
  return parseSse(body).events;
}
