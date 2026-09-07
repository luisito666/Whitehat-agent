import { describe, expect, test } from 'vitest';
import type { Status } from './api.js';
import {
  DISCOVER_MAX_FAILS,
  activityText,
  initialState,
  reducer,
  type Action,
  type UiState,
} from './bus.js';

const STATUS: Status = {
  stack: 'up',
  workers: [
    { role: 'recon', url: 'http://127.0.0.1:9101', up: true },
    { role: 'vuln', url: 'http://127.0.0.1:9102', up: false },
  ],
  engagement: { id: 'ENG-1', client: 'ACME', valid: true, approved: false },
  protocol: 1,
};

const run = (state: UiState, ...actions: Action[]): UiState =>
  actions.reduce(reducer, state);

describe('bus reducer edges', () => {
  test('DISCOVER_OK: boot -> ready and stores status', () => {
    const next = reducer(initialState, { type: 'DISCOVER_OK', status: STATUS });
    expect(next.phase).toBe('ready');
    expect(next.status).toBe(STATUS);
    expect(next.discoverFails).toBe(0);
  });

  test('DISCOVER_FAIL in boot -> keeps discovering', () => {
    const next = reducer(initialState, { type: 'DISCOVER_FAIL' });
    expect(next.phase).toBe('discovering');
    expect(next.discoverFails).toBe(1);
  });

  test('DISCOVER_FAIL repeated -> falls to down after the threshold', () => {
    let state = initialState;
    for (let i = 0; i < DISCOVER_MAX_FAILS; i++) {
      state = reducer(state, { type: 'DISCOVER_FAIL' });
    }
    expect(state.phase).toBe('down');
    // recovers on a good poll
    expect(reducer(state, { type: 'DISCOVER_OK', status: STATUS }).phase).toBe(
      'ready',
    );
  });

  test('SUBMIT in ready -> thinking and pushes the user line', () => {
    const ready = reducer(initialState, { type: 'DISCOVER_OK', status: STATUS });
    const next = reducer(ready, { type: 'SUBMIT', text: 'scan target' });
    expect(next.phase).toBe('thinking');
    expect(next.history).toEqual([{ kind: 'user', text: 'scan target' }]);
  });

  test('SUBMIT is ignored unless ready', () => {
    expect(reducer(initialState, { type: 'SUBMIT', text: 'x' })).toBe(
      initialState,
    );
  });

  test('DELTA in thinking -> streaming and accumulates', () => {
    const state = run(
      initialState,
      { type: 'DISCOVER_OK', status: STATUS },
      { type: 'SUBMIT', text: 'hi' },
      { type: 'DELTA', text: 'pong' },
      { type: 'DELTA', text: ': hi' },
    );
    expect(state.phase).toBe('streaming');
    expect(state.assistantBuf).toBe('pong: hi');
  });

  test('DONE -> ready and flushes the buffer into history', () => {
    const state = run(
      initialState,
      { type: 'DISCOVER_OK', status: STATUS },
      { type: 'SUBMIT', text: 'hi' },
      { type: 'DELTA', text: 'pong: hi' },
      { type: 'DONE' },
    );
    expect(state.phase).toBe('ready');
    expect(state.assistantBuf).toBe('');
    expect(state.history).toEqual([
      { kind: 'user', text: 'hi' },
      { kind: 'assistant', text: 'pong: hi' },
    ]);
  });

  test('ERROR -> ready with the error visible', () => {
    const state = run(
      initialState,
      { type: 'DISCOVER_OK', status: STATUS },
      { type: 'SUBMIT', text: 'hi' },
      { type: 'DELTA', text: 'half' },
      { type: 'ERROR', detail: 'boom' },
    );
    expect(state.phase).toBe('ready');
    expect(state.error).toBe('boom');
    expect(state.assistantBuf).toBe('');
    expect(state.history.at(-1)).toEqual({ kind: 'error', text: 'boom' });
  });

  test('ACTIVITY during a turn -> dim handoff line, phase unchanged', () => {
    const state = run(
      initialState,
      { type: 'DISCOVER_OK', status: STATUS },
      { type: 'SUBMIT', text: 'hi' },
      { type: 'ACTIVITY', role: 'recon', action: 'handoff', detail: 'enumerate' },
    );
    expect(state.phase).toBe('thinking');
    expect(state.history.at(-1)).toEqual({
      kind: 'activity',
      text: '‹recon handoff: enumerate›',
    });
  });

  test('DELTA outside a turn is ignored', () => {
    const ready = reducer(initialState, { type: 'DISCOVER_OK', status: STATUS });
    expect(reducer(ready, { type: 'DELTA', text: 'x' })).toBe(ready);
  });

  test('activityText formats with and without detail', () => {
    expect(activityText('vuln', 'done')).toBe('‹vuln done›');
    expect(activityText('vuln', 'handoff', '  cve match  ')).toBe(
      '‹vuln handoff: cve match›',
    );
  });
});

describe('bus reducer — view axis (approve gate)', () => {
  test('starts on the chat view', () => {
    expect(initialState.view).toBe('chat');
  });

  test('TOGGLE_VIEW flips chat <-> approve', () => {
    const open = reducer(initialState, { type: 'TOGGLE_VIEW' });
    expect(open.view).toBe('approve');
    expect(reducer(open, { type: 'TOGGLE_VIEW' }).view).toBe('chat');
  });

  test('CLOSE_VIEW returns to chat from approve, no-ops on chat', () => {
    const open = reducer(initialState, { type: 'TOGGLE_VIEW' });
    expect(reducer(open, { type: 'CLOSE_VIEW' }).view).toBe('chat');
    // already on chat -> same reference (nothing to re-render)
    expect(reducer(initialState, { type: 'CLOSE_VIEW' })).toBe(initialState);
  });

  test('toggling the view never disturbs an in-flight turn', () => {
    const mid = run(
      initialState,
      { type: 'DISCOVER_OK', status: STATUS },
      { type: 'SUBMIT', text: 'hi' },
      { type: 'DELTA', text: 'half' },
      { type: 'TOGGLE_VIEW' },
    );
    expect(mid.view).toBe('approve');
    expect(mid.phase).toBe('streaming');
    expect(mid.assistantBuf).toBe('half');
    expect(mid.history).toEqual([{ kind: 'user', text: 'hi' }]);
  });
});
