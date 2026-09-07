/**
 * The always-on status line, extracted from App (Task 11).
 *
 * One line: run phase · workers up (n/m) · engagement · session id (6 chars).
 * Every field comes from the bus state — phase / reconnecting / sessionId from
 * the UI state machine, workers + engagement from the last GET /status poll.
 * No fetching here; it is a pure function of `state`.
 */
import type { ReactNode } from 'react';
import { Text } from 'ink';
import type { Status } from '../api.js';
import type { Phase, UiState } from '../bus.js';

/** Short word for the run phase; reconnect wins while it is in flight. */
function phaseWord(phase: Phase, reconnecting: boolean): string {
  if (reconnecting) return 'reconectando';
  switch (phase) {
    case 'boot':
    case 'discovering':
      return 'connecting';
    default:
      return phase; // ready | thinking | streaming | down
  }
}

function workersLabel(status: Status | null): string | null {
  if (!status || status.workers.length === 0) return null;
  const up = status.workers.filter((w) => w.up).length;
  return `${up}/${status.workers.length}`;
}

export function StatusBar({ state }: { state: UiState }): ReactNode {
  const workers = workersLabel(state.status);
  const eng = state.status?.engagement;
  const sid = state.sessionId ? state.sessionId.slice(0, 6) : null;
  return (
    <Text>
      <Text dimColor>estado </Text>
      <Text color={state.reconnecting ? 'yellow' : undefined}>
        {phaseWord(state.phase, state.reconnecting)}
      </Text>
      {workers ? (
        <>
          <Text dimColor> · workers </Text>
          {workers}
        </>
      ) : null}
      <Text dimColor> · engagement </Text>
      {eng?.id ? (
        <Text color="green">
          {eng.id}
          {eng.client ? ` · ${eng.client}` : ''}
        </Text>
      ) : (
        <Text color="red">sin engagement</Text>
      )}
      {sid ? (
        <>
          <Text dimColor> · sesión </Text>
          {sid}
        </>
      ) : null}
    </Text>
  );
}
