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

export type LineKind = 'user' | 'assistant' | 'activity' | 'error';

export interface Line {
  kind: LineKind;
  text: string;
}

export interface UiState {
  phase: Phase;
  status: Status | null;
  /** Completed chat lines, in order. */
  history: Line[];
  /** Deltas of the turn in flight, accumulated; flushed to history on DONE. */
  assistantBuf: string;
  /** Last error text, kept visible until the next SUBMIT. */
  error: string | null;
  /** Consecutive failed /status polls; drives the fall to `down`. */
  discoverFails: number;
}

/** Failed polls tolerated while `discovering`/`boot` before declaring `down`. */
export const DISCOVER_MAX_FAILS = 3;

export const initialState: UiState = {
  phase: 'boot',
  status: null,
  history: [],
  assistantBuf: '',
  error: null,
  discoverFails: 0,
};

export type Action =
  | { type: 'DISCOVER_OK'; status: Status }
  | { type: 'DISCOVER_FAIL' }
  | { type: 'SUBMIT'; text: string }
  | { type: 'DELTA'; text: string }
  | { type: 'ACTIVITY'; role: string; action: string; detail?: string }
  | { type: 'DONE' }
  | { type: 'ERROR'; detail: string };

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
      return { ...state, phase: 'ready', assistantBuf: '', history };
    }

    case 'ERROR': {
      const history: Line[] = [
        ...state.history,
        { kind: 'error', text: action.detail },
      ];
      const phase: Phase =
        state.phase === 'ready' || IN_TURN.has(state.phase) ? 'ready' : state.phase;
      return { ...state, phase, error: action.detail, assistantBuf: '', history };
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
