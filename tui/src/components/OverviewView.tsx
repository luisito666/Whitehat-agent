/**
 * Overview view (`s` from the chat view, Esc returns).
 *
 * A compact read-only dashboard: A2A workers (●up / ○down + url), the engagement
 * summary (like the approve gate but on one screen), the wire protocol version,
 * the full session id and the sidecar base URL (PENTEST_TUI_URL). Both
 * GET /status and GET /engagement are re-fetched on open.
 */
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Box, Text, useInput } from 'ink';
import {
  BASE_URL,
  getEngagement,
  getStatus,
  type Engagement,
  type Status,
} from '../api.js';
import { Spinner } from './Spinner.js';

interface Props {
  onClose: () => void;
  /** Full session id of the last turn, or null before the first one. */
  sessionId: string | null;
}

type Load =
  | { phase: 'loading' }
  | { phase: 'ok'; status: Status; engagement: Engagement | null }
  | { phase: 'error'; detail: string };

function WorkerRow({
  role,
  url,
  up,
}: {
  role: string;
  url: string;
  up: boolean;
}): ReactNode {
  return (
    <Text>
      <Text color={up ? 'green' : 'red'}>{up ? '●' : '○'}</Text> {role}
      <Text dimColor> {url}</Text>
    </Text>
  );
}

function EngagementLine({
  status,
  full,
}: {
  status: Status;
  full: Engagement | null;
}): ReactNode {
  const s = status.engagement;
  if (!s.id) {
    return <Text color="red">sin engagement</Text>;
  }
  const from = full?.window.valid_from ?? '?';
  const until = full?.window.valid_until ?? '?';
  return (
    <Box flexDirection="column">
      <Text>
        <Text color="green">{s.id}</Text>
        {s.client ? ` · ${s.client}` : ''} · vigente {s.valid ? 'sí' : 'no'} ·
        approved{' '}
        <Text color={s.approved ? 'green' : 'yellow'}>
          {s.approved ? 'sí' : 'no'}
        </Text>
      </Text>
      {full ? (
        <Text dimColor>
          vigencia {from} → {until} · auth{' '}
          {full.auth_reference ?? '(sin referencia)'}
        </Text>
      ) : null}
    </Box>
  );
}

export function OverviewView({ onClose, sessionId }: Props): ReactNode {
  const [load, setLoad] = useState<Load>({ phase: 'loading' });
  const aliveRef = useRef(true);

  useInput((_input, key) => {
    if (key.escape) onClose();
  });

  useEffect(() => {
    aliveRef.current = true;
    void (async () => {
      try {
        const [status, engagement] = await Promise.all([
          getStatus(),
          getEngagement().catch(() => null),
        ]);
        if (aliveRef.current) setLoad({ phase: 'ok', status, engagement });
      } catch (err) {
        if (aliveRef.current) {
          setLoad({
            phase: 'error',
            detail: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      aliveRef.current = false;
    };
  }, []);

  return (
    <Box flexDirection="column">
      <Text>
        Overview — stack &amp; engagement <Text dimColor>· Esc vuelve</Text>
      </Text>

      {load.phase === 'loading' ? (
        <Text>
          <Spinner /> cargando estado…
        </Text>
      ) : load.phase === 'error' ? (
        <Text color="red">! {load.detail}</Text>
      ) : (
        <Box flexDirection="column">
          <Box marginTop={1} flexDirection="column">
            <Text dimColor>workers</Text>
            {load.status.workers.map((w) => (
              <WorkerRow key={w.role} role={w.role} url={w.url} up={w.up} />
            ))}
          </Box>

          <Box marginTop={1} flexDirection="column">
            <Text dimColor>engagement</Text>
            <EngagementLine status={load.status} full={load.engagement} />
          </Box>

          <Box marginTop={1} flexDirection="column">
            <Text>
              <Text dimColor>protocolo </Text>
              {load.status.protocol}
            </Text>
          </Box>
        </Box>
      )}

      <Box marginTop={1} flexDirection="column">
        <Text>
          <Text dimColor>sesión </Text>
          {sessionId ?? '(sin sesión aún)'}
        </Text>
        <Text>
          <Text dimColor>base </Text>
          {BASE_URL}
        </Text>
      </Box>
    </Box>
  );
}
