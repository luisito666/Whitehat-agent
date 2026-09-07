/**
 * Chat loop: input → POST /chat → live SSE render.
 *
 *   - polls GET /status every 2s (DISCOVER_OK / DISCOVER_FAIL)
 *   - on submit: dispatch SUBMIT, POST /chat, then open a live SSE reader
 *     (src/sse.ts) on GET /chat/{sid}/events?cursor=, translating frames into
 *     DELTA / ACTIVITY / DONE / ERROR until the terminal chat.done (the POST
 *     response is NOT the end of the turn). Reconnects across benign stream
 *     closes are transparent to the bus — cursor + sidecar buffer mean no chat
 *     is lost; the status bar just shows "reconectando…" while one is in flight.
 */
import { useCallback, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Box, Text, useInput } from 'ink';
import { getStatus, postChat, type Status } from './api.js';
import { streamEvents } from './sse.js';
import { useBus, type UiState } from './bus.js';
import { ApproveGate } from './components/ApproveGate.js';
import { ChatLog } from './components/ChatLog.js';
import { ChatInput } from './components/ChatInput.js';

const STATUS_POLL_MS = 2000;

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
      return state.reconnecting ? 'reconectando…' : 'thinking…';
    case 'streaming':
      return state.reconnecting ? 'reconectando…' : 'streaming…';
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
      {state.reconnecting ? (
        <Text color="yellow">reconectando…</Text>
      ) : (
        stateWord(state.phase)
      )}
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
  /** Aborts the live SSE reader of the turn in flight (unmount / new turn). */
  const turnAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      turnAbortRef.current?.abort();
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
      turnAbortRef.current?.abort();
      const ac = new AbortController();
      turnAbortRef.current = ac;
      try {
        const { session_id, cursor } = await postChat(
          text,
          sessionRef.current ?? undefined,
        );
        sessionRef.current = session_id;

        let sawTerminal = false;
        await streamEvents(
          session_id,
          Number(cursor) || 0,
          {
            onEvent: (_id, event, data) => {
              if (!mountedRef.current) return;
              if (event === 'chat.delta') {
                dispatch({ type: 'DELTA', text: String(data.text ?? '') });
              } else if (event === 'agent.activity') {
                dispatch({
                  type: 'ACTIVITY',
                  role: String(data.role ?? '?'),
                  action: String(data.action ?? ''),
                  detail: data.detail != null ? String(data.detail) : undefined,
                });
              } else if (event === 'chat.done') {
                sawTerminal = true;
                dispatch({ type: 'DONE' });
              } else if (event === 'error') {
                sawTerminal = true;
                dispatch({
                  type: 'ERROR',
                  detail: String(data.detail ?? 'stream error'),
                });
              }
            },
            // Terminal frame seen → the turn already ended via DONE/ERROR.
            // No terminal frame → the reconnect budget ran out: surface it so
            // the UI leaves the in-turn phase instead of hanging.
            onClose: () => {
              if (!mountedRef.current) return;
              dispatch({ type: 'RECONNECTED' });
              if (!sawTerminal) {
                dispatch({
                  type: 'ERROR',
                  detail: 'conexión perdida con el sidecar — reintento agotado',
                });
              }
            },
            onReconnecting: () => {
              if (mountedRef.current) dispatch({ type: 'RECONNECTING' });
            },
            onReconnected: () => {
              if (mountedRef.current) dispatch({ type: 'RECONNECTED' });
            },
          },
          ac.signal,
        );
      } catch (err) {
        if (!mountedRef.current) return;
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
