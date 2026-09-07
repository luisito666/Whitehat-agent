import { afterEach, describe, expect, test, vi } from 'vitest';
import {
  fetchEvents,
  getEngagement,
  getLedger,
  getStatus,
  parseSse,
  postChat,
} from './api.js';

interface FakeResponse {
  ok: boolean;
  status: number;
  json?: () => Promise<unknown>;
  text?: () => Promise<string>;
}

const ok = (body: unknown): FakeResponse => ({
  ok: true,
  status: 200,
  json: async () => body,
  text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
});

function stubFetch(...responses: FakeResponse[]): ReturnType<typeof vi.fn> {
  const fn = vi.fn();
  for (const r of responses) fn.mockResolvedValueOnce(r);
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api client', () => {
  test('getStatus parses workers', async () => {
    const fetchFn = stubFetch(
      ok({
        stack: 'up',
        workers: [
          { role: 'recon', url: 'http://127.0.0.1:9101', up: true },
          { role: 'vuln', url: 'http://127.0.0.1:9102', up: false },
        ],
        engagement: { id: null, client: null, valid: false, approved: false },
        protocol: 1,
      }),
    );

    const status = await getStatus();

    expect(fetchFn).toHaveBeenCalledOnce();
    expect(String(fetchFn.mock.calls[0][0])).toContain('/status');
    expect(status.protocol).toBe(1);
    expect(status.workers).toHaveLength(2);
    expect(status.workers[0]).toEqual({
      role: 'recon',
      url: 'http://127.0.0.1:9101',
      up: true,
    });
    expect(status.workers.filter((w) => w.up)).toHaveLength(1);
  });

  test('postChat returns session_id and cursor', async () => {
    const fetchFn = stubFetch(ok({ session_id: 'abc123', cursor: '0' }));

    const res = await postChat('scan target', 'abc123');

    const [, init] = fetchFn.mock.calls[0];
    expect((init as RequestInit).method).toBe('POST');
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      message: 'scan target',
      session_id: 'abc123',
    });
    expect(res.session_id).toBe('abc123');
    expect(res.cursor).toBe('0');
  });

  test('postChat omits session_id when not given', async () => {
    const fetchFn = stubFetch(ok({ session_id: 'fresh', cursor: '0' }));

    await postChat('hello');

    const [, init] = fetchFn.mock.calls[0];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      message: 'hello',
    });
  });

  test('getEngagement: 404 -> null', async () => {
    stubFetch({ ok: false, status: 404, json: async () => ({}) });
    expect(await getEngagement()).toBeNull();
  });

  test('getEngagement: 200 -> parsed engagement', async () => {
    stubFetch(
      ok({
        id: 'ENG-1',
        client: 'ACME',
        valid: true,
        approved: false,
        window: { valid_from: '2026-01-01', valid_until: '2026-12-31' },
        auth_reference: 'PO-42',
      }),
    );
    const eng = await getEngagement();
    expect(eng?.id).toBe('ENG-1');
    expect(eng?.window.valid_until).toBe('2026-12-31');
  });

  test('getLedger passes tail and parses entries', async () => {
    const fetchFn = stubFetch(ok({ entries: [{ id: 1 }, { id: 2 }], total: 2 }));
    const ledger = await getLedger(5);
    expect(String(fetchFn.mock.calls[0][0])).toContain('tail=5');
    expect(ledger.total).toBe(2);
  });

  test('non-ok status raises ApiError', async () => {
    stubFetch({ ok: false, status: 500, json: async () => ({}) });
    await expect(getStatus()).rejects.toThrow(/HTTP 500/);
  });

  test('parseSse decodes id/event/data frames and keeps the partial tail', () => {
    const raw =
      'id: 1\nevent: chat.delta\ndata: {"text":"pong"}\n\n' +
      'id: 2\nevent: agent.activity\ndata: {"role":"recon","action":"handoff"}\n\n' +
      'id: 3\nevent: chat.done\ndata: {}\n\n' +
      'id: 4\nevent: chat.delta\ndata: {"text":"par';
    const { events, rest } = parseSse(raw);
    expect(events).toEqual([
      { id: 1, event: 'chat.delta', data: { text: 'pong' } },
      { id: 2, event: 'agent.activity', data: { role: 'recon', action: 'handoff' } },
      { id: 3, event: 'chat.done', data: {} },
    ]);
    expect(rest).toContain('par');
  });

  test('fetchEvents reads the stream body and returns decoded frames', async () => {
    stubFetch({
      ok: true,
      status: 200,
      text: async () =>
        'id: 1\nevent: chat.delta\ndata: {"text":"hi"}\n\n' +
        'id: 2\nevent: chat.done\ndata: {}\n\n',
    });
    const events = await fetchEvents('sid', 0);
    expect(events.map((e) => e.event)).toEqual(['chat.delta', 'chat.done']);
  });
});
