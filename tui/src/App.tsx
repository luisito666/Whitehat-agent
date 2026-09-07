/**
 * Chat loop: input → POST /chat → render.
 *
 *   - polls GET /status every 2s (DISCOVER_OK / DISCOVER_FAIL)
 *   - on submit: dispatch SUBMIT, POST /chat, then — INTERIM, Task 10 swaps this
 *     for a live SSE reader — poll GET /chat/{sid}/events?cursor= every 500ms,
 *     translating frames into DELTA / ACTIVITY / DONE / ERROR until the terminal
 *     chat.done (the POST response is NOT the end of the turn).
 */
import { useCallback, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Box, Text, useInput } from 'ink';
import {
  fetchEvents,
  getStatus,
  postChat,
  type Status,
} from './api.js';
import { useBus, type UiState } from './bus.js';
import { ApproveGate } from './components/ApproveGate.js';
import { ChatLog } from './components/ChatLog.js';
import { ChatInput } from './components/ChatInput.js';

const STATUS_POLL_MS = 2000;
const EVENT_POLL_MS = 500;
/** Safety bound on the interim event poll (Task 10 removes the loop). */
const MAX_EVENT_POLLS = 600;

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

function workersUp(status: Status | null): string {
  if (!status) return '';
  const up = status.workers.filter((w) => w.up).length;
  return ` (${up}/${status.workers.length} workers)`;
}

function phaseLabel(state: UiState): string {
  switch (state.phase) {
    case 'boot':
    case 'discovering':
      return 'connecting to sidecar…';
    case 'down':
      return 'sidecar down — retrying';
    case 'ready':
      return `ready${workersUp(state.status)}`;
    case 'thinking':
      return 'thinking…';
    case 'streaming':
      return 'streaming…';
  }
}

/** Short status word for the always-on status bar. */
function stateWord(phase: UiState['phase']): string {
  switch (phase) {
    case 'boot':
    case 'discovering':
      return 'connecting';
    case 'down':
      return 'down';
    default:
      return phase; // ready | thinking | streaming
  }
}

/**
 * One always-visible line: run state + engagement from the last /status poll
 * (green id/client, or red "sin engagement"). Task 11 promotes this to its own
 * StatusBar component with the worker overview.
 */
function StatusLine({ state }: { state: UiState }): ReactNode {
  const eng = state.status?.engagement;
  return (
    <Text>
      <Text dimColor>estado </Text>
      {stateWord(state.phase)}
      <Text dimColor> · engagement </Text>
      {eng?.id ? (
        <Text color="green">
          {eng.id}
          {eng.client ? ` · ${eng.client}` : ''}
        </Text>
      ) : (
        <Text color="red">sin engagement</Text>
      )}
    </Text>
  );
}

export function App(): ReactNode {
  const { state, dispatch } = useBus();
  const sessionRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // GET /status poll.
  useEffect(() => {
    let cancelled = false;
    const poll = async (): Promise<void> => {
      try {
        const status = await getStatus();
        if (!cancelled) dispatch({ type: 'DISCOVER_OK', status });
      } catch {
        if (!cancelled) dispatch({ type: 'DISCOVER_FAIL' });
      }
    };
    void poll();
    const id = setInterval(() => void poll(), STATUS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [dispatch]);

  const runTurn = useCallback(
    async (text: string): Promise<void> => {
      try {
        const { session_id, cursor } = await postChat(
          text,
          sessionRef.current ?? undefined,
        );
        sessionRef.current = session_id;
        let seen = Number(cursor) || 0;

        for (let i = 0; i < MAX_EVENT_POLLS; i++) {
          if (!mountedRef.current) return;
          const events = await fetchEvents(session_id, seen);
          let terminal = false;
          for (const ev of events) {
            if (ev.id > seen) seen = ev.id;
            if (ev.event === 'chat.delta') {
              dispatch({ type: 'DELTA', text: String(ev.data.text ?? '') });
            } else if (ev.event === 'agent.activity') {
              dispatch({
                type: 'ACTIVITY',
                role: String(ev.data.role ?? '?'),
                action: String(ev.data.action ?? ''),
                detail:
                  ev.data.detail != null ? String(ev.data.detail) : undefined,
              });
            } else if (ev.event === 'chat.done') {
              dispatch({ type: 'DONE' });
              terminal = true;
            } else if (ev.event === 'error') {
              dispatch({
                type: 'ERROR',
                detail: String(ev.data.detail ?? 'stream error'),
              });
              terminal = true;
            }
          }
          if (terminal) return;
          await sleep(EVENT_POLL_MS);
        }
        dispatch({ type: 'ERROR', detail: 'turn timed out waiting for chat.done' });
      } catch (err) {
        dispatch({
          type: 'ERROR',
          detail: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [dispatch],
  );

  const handleSubmit = useCallback(
    (text: string): void => {
      dispatch({ type: 'SUBMIT', text });
      void runTurn(text);
    },
    [dispatch, runTurn],
  );

  // Ctrl+P toggles the approve gate from anywhere; Esc-to-close lives in
  // ApproveGate. While the gate is open ChatInput is unmounted (input disabled).
  useInput((input, key) => {
    if (key.ctrl && input === 'p') dispatch({ type: 'TOGGLE_VIEW' });
  });

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text>
        pentest-chat — protocol 1 <Text dimColor>· {phaseLabel(state)}</Text>
      </Text>
      <StatusLine state={state} />
      {state.error ? <Text color="red">! {state.error}</Text> : null}
      {state.view === 'approve' ? (
        <ApproveGate onClose={() => dispatch({ type: 'CLOSE_VIEW' })} />
      ) : (
        <>
          <ChatLog history={state.history} assistantBuf={state.assistantBuf} />
          <ChatInput ready={state.phase === 'ready'} onSubmit={handleSubmit} />
        </>
      )}
    </Box>
  );
}
