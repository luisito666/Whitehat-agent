/**
 * UI state machine for the chat TUI: a plain reducer plus a React context so
 * components can read state / dispatch without prop drilling.
 *
 *   boot ─DISCOVER_OK→ ready            ready ─SUBMIT→ thinking
 *   boot ─DISCOVER_FAIL→ discovering    thinking ─DELTA→ streaming (accumulates)
 *   discovering ─DISCOVER_OK→ ready     streaming ─DELTA→ streaming (accumulates)
 *   discovering ─DISCOVER_FAIL(xN)→ down (thinking|streaming) ─DONE→ ready
 *   down ─DISCOVER_OK→ ready            (thinking|streaming) ─ERROR→ ready (+visible)
 *
 * The visible view is a separate axis from `phase`, carried on the same state so
 * it is testable in isolation (Task 9):
 *
 *   chat ─TOGGLE_VIEW (Ctrl+P)→ approve      approve ─TOGGLE_VIEW (Ctrl+P)→ chat
 *   <any> ─CLOSE_VIEW (Esc)→ chat            chat ─CLOSE_VIEW→ chat (no-op)
 *   chat+ready ─OPEN_VIEW 'ledger'→ ledger   chat+ready ─OPEN_VIEW 'overview'→ overview
 *
 * OPEN_VIEW (the `l` / `s` hotkeys) only fires from the chat view while `ready`
 * — it never hijacks keys mid-turn. TOGGLE_VIEW (Ctrl+P, the read-only approve
 * gate) is exempt: it is a safety screen and works even while a turn streams.
 *
 * A third flag, `reconnecting`, tracks a live-SSE reconnect in progress (the
 * sidecar buffer + cursor guarantee no chat is lost). It rides on the same
 * state so the status bar can show "reconectando…"; RECONNECTING / RECONNECTED
 * toggle it and it is force-cleared whenever a turn starts or ends.
 *
 * The approve view is read-only (it never approves anything — D5). A turn can
 * keep streaming underneath while it is open; toggling the view never touches
 * `phase`, `history` or `assistantBuf`.
 *
 * Ctrl+C (exit) is a component concern (raw-mode cleanup via useApp().exit()),
 * not a reducer action.
 */
import {
  createContext,
  useContext,
  useReducer,
  type Dispatch,
  type ReactNode,
} from 'react';
import type { Status } from './api.js';

export type Phase =
  | 'boot'
  | 'discovering'
  | 'ready'
  | 'thinking'
  | 'streaming'
  | 'down';

export type View = 'chat' | 'approve' | 'ledger' | 'overview';

export type LineKind = 'user' | 'assistant' | 'activity' | 'error';

export interface Line {
  kind: LineKind;
  text: string;
}

export interface UiState {
  phase: Phase;
  /** Which screen is on top: chat log, approve gate, ledger or overview. */
  view: View;
  status: Status | null;
  /** Session id of the last turn (from POST /chat); shown in the status bar. */
  sessionId: string | null;
  /** Completed chat lines, in order. */
  history: Line[];
  /** Deltas of the turn in flight, accumulated; flushed to history on DONE. */
  assistantBuf: string;
  /** Last error text, kept visible until the next SUBMIT. */
  error: string | null;
  /** Consecutive failed /status polls; drives the fall to `down`. */
  discoverFails: number;
  /** A live-SSE reconnect is in flight (transparent to history/assistantBuf). */
  reconnecting: boolean;
}

/** Failed polls tolerated while `discovering`/`boot` before declaring `down`. */
export const DISCOVER_MAX_FAILS = 3;

export const initialState: UiState = {
  phase: 'boot',
  view: 'chat',
  status: null,
  sessionId: null,
  history: [],
  assistantBuf: '',
  error: null,
  discoverFails: 0,
  reconnecting: false,
};

export type Action =
  | { type: 'DISCOVER_OK'; status: Status }
  | { type: 'DISCOVER_FAIL' }
  | { type: 'SUBMIT'; text: string }
  | { type: 'DELTA'; text: string }
  | { type: 'ACTIVITY'; role: string; action: string; detail?: string }
  | { type: 'DONE' }
  | { type: 'ERROR'; detail: string }
  | { type: 'RECONNECTING' }
  | { type: 'RECONNECTED' }
  | { type: 'SESSION'; sessionId: string }
  | { type: 'TOGGLE_VIEW' }
  | { type: 'OPEN_VIEW'; target: 'ledger' | 'overview' }
  | { type: 'CLOSE_VIEW' };

const IN_TURN: ReadonlySet<Phase> = new Set<Phase>(['thinking', 'streaming']);

/** "‹recon handoff: enumerate ...›" / "‹recon done›" */
export function activityText(role: string, action: string, detail?: string): string {
  const tail = detail && detail.trim() ? `: ${detail.trim()}` : '';
  return `‹${role} ${action}${tail}›`;
}

export function reducer(state: UiState, action: Action): UiState {
  switch (action.type) {
    case 'DISCOVER_OK': {
      // A successful poll never disturbs a turn already in flight.
      const phase: Phase = IN_TURN.has(state.phase) ? state.phase : 'ready';
      return { ...state, phase, status: action.status, discoverFails: 0 };
    }

    case 'DISCOVER_FAIL': {
      if (state.phase === 'ready' || IN_TURN.has(state.phase)) {
        // Transient blip during/after a good discovery: stay put.
        return state;
      }
      const discoverFails = state.discoverFails + 1;
      const phase: Phase =
        discoverFails >= DISCOVER_MAX_FAILS ? 'down' : 'discovering';
      return { ...state, phase, discoverFails };
    }

    case 'SUBMIT': {
      if (state.phase !== 'ready') return state;
      return {
        ...state,
        phase: 'thinking',
        error: null,
        assistantBuf: '',
        reconnecting: false,
        history: [...state.history, { kind: 'user', text: action.text }],
      };
    }

    case 'DELTA': {
      if (!IN_TURN.has(state.phase)) return state;
      return {
        ...state,
        phase: 'streaming',
        assistantBuf: state.assistantBuf + action.text,
      };
    }

    case 'ACTIVITY': {
      if (!IN_TURN.has(state.phase)) return state;
      const text = activityText(action.role, action.action, action.detail);
      return { ...state, history: [...state.history, { kind: 'activity', text }] };
    }

    case 'DONE': {
      if (!IN_TURN.has(state.phase)) return state;
      const history = state.assistantBuf
        ? [...state.history, { kind: 'assistant' as const, text: state.assistantBuf }]
        : state.history;
      return {
        ...state,
        phase: 'ready',
        assistantBuf: '',
        reconnecting: false,
        history,
      };
    }

    case 'ERROR': {
      const history: Line[] = [
        ...state.history,
        { kind: 'error', text: action.detail },
      ];
      const phase: Phase =
        state.phase === 'ready' || IN_TURN.has(state.phase) ? 'ready' : state.phase;
      return {
        ...state,
        phase,
        error: action.detail,
        assistantBuf: '',
        reconnecting: false,
        history,
      };
    }

    case 'RECONNECTING': {
      // Only meaningful mid-turn; never disturbs phase/history/assistantBuf.
      if (!IN_TURN.has(state.phase) || state.reconnecting) return state;
      return { ...state, reconnecting: true };
    }

    case 'RECONNECTED': {
      if (!state.reconnecting) return state;
      return { ...state, reconnecting: false };
    }

    case 'SESSION': {
      return state.sessionId === action.sessionId
        ? state
        : { ...state, sessionId: action.sessionId };
    }

    case 'TOGGLE_VIEW': {
      // Only flips the view; a turn in flight keeps running underneath.
      return { ...state, view: state.view === 'approve' ? 'chat' : 'approve' };
    }

    case 'OPEN_VIEW': {
      // Ledger / overview hotkeys: only from the chat view, only while ready —
      // never steal a keystroke from an in-flight turn.
      if (state.view !== 'chat' || state.phase !== 'ready') return state;
      return { ...state, view: action.target };
    }

    case 'CLOSE_VIEW': {
      return state.view === 'chat' ? state : { ...state, view: 'chat' };
    }

    default:
      return state;
  }
}

// --- context -----------------------------------------------------------

interface Bus {
  state: UiState;
  dispatch: Dispatch<Action>;
}

const BusContext = createContext<Bus | null>(null);

export function BusProvider({ children }: { children: ReactNode }): ReactNode {
  const [state, dispatch] = useReducer(reducer, initialState);
  return <BusContext.Provider value={{ state, dispatch }}>{children}</BusContext.Provider>;
}

export function useBus(): Bus {
  const ctx = useContext(BusContext);
  if (!ctx) throw new Error('useBus must be used within <BusProvider>');
  return ctx;
}
