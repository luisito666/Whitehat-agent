/**
 * Read-only approve gate (Ctrl+P opens it, Esc closes it — see App.tsx).
 *
 * This screen is the heart of D5 ("UI fail-closed"): the TUI *never* approves an
 * engagement. It only reports state:
 *
 *   - engagement in force  -> GREEN banner: id, client, validity window,
 *     auth_reference and whether operator approval is present.
 *   - no engagement (404 / sidecar unreachable) -> RED banner spelling out the
 *     fail-closed procedure: run `python -m pentest_agent.approve`, and the
 *     approval is confirmed ONLY in person, in the exploit server process.
 *
 * The engagement is fetched on mount (spinner while it loads).
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Box, Text, useInput } from 'ink';
import { getEngagement, type Engagement } from '../api.js';

interface Props {
  /** Back to the chat view (bound to Esc by App). */
  onClose: () => void;
}

const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

function Spinner(): ReactNode {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const id = setInterval(
      () => setFrame((f) => (f + 1) % SPINNER_FRAMES.length),
      80,
    );
    return () => clearInterval(id);
  }, []);
  return <Text>{SPINNER_FRAMES[frame]}</Text>;
}

type Load =
  | { phase: 'loading' }
  | { phase: 'ok'; engagement: Engagement }
  | { phase: 'none' };

function GreenBanner({ e }: { e: Engagement }): ReactNode {
  const from = e.window.valid_from ?? '?';
  const until = e.window.valid_until ?? '?';
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" paddingX={1}>
      <Text color="green">✓ engagement vigente</Text>
      <Text>
        id <Text color="green">{e.id ?? '?'}</Text> · cliente{' '}
        <Text color="green">{e.client ?? '?'}</Text>
      </Text>
      <Text>
        vigencia {from} → {until}
      </Text>
      <Text>auth_reference: {e.auth_reference ?? '(sin referencia)'}</Text>
      <Text>
        approved:{' '}
        <Text color={e.approved ? 'green' : 'yellow'}>
          {e.approved ? 'sí' : 'no'}
        </Text>
        {e.approved ? null : (
          <Text dimColor> — la aproba el proceso del servidor exploit, no la TUI</Text>
        )}
      </Text>
    </Box>
  );
}

function RedBanner(): ReactNode {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="red" paddingX={1}>
      <Text color="red">✗ sin engagement.yaml vigente</Text>
      <Text>La explotación falla cerrado: no hay autorización por defecto.</Text>
      <Box marginTop={1} flexDirection="column">
        <Text>Para autorizar una auditoría real:</Text>
        <Text>
          1. crea/renueva <Text bold>engagement.yaml</Text> (ver
          engagement.example.yaml).
        </Text>
        <Text>
          2. corre <Text bold>python -m pentest_agent.approve</Text> y exporta la
          variable que imprime.
        </Text>
      </Box>
      <Box marginTop={1} flexDirection="column">
        <Text color="yellow">
          La aprobación es SOLO presencial, en el proceso del servidor exploit.
        </Text>
        <Text dimColor>
          Esta TUI jamás aprueba nada: solo muestra el estado del engagement.
        </Text>
      </Box>
    </Box>
  );
}

export function ApproveGate({ onClose }: Props): ReactNode {
  const [load, setLoad] = useState<Load>({ phase: 'loading' });

  useInput((_input, key) => {
    if (key.escape) onClose();
  });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const engagement = await getEngagement();
        if (cancelled) return;
        setLoad(
          engagement
            ? { phase: 'ok', engagement }
            : { phase: 'none' },
        );
      } catch {
        // 404 already maps to null in the client; any other failure (sidecar
        // down) is treated the same here — fail closed, show the procedure.
        if (!cancelled) setLoad({ phase: 'none' });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Box flexDirection="column">
      <Text>
        Puerta de aprobación — engagement <Text dimColor>· Esc vuelve al chat</Text>
      </Text>
      {load.phase === 'loading' ? (
        <Text>
          <Spinner /> cargando engagement…
        </Text>
      ) : load.phase === 'ok' ? (
        <GreenBanner e={load.engagement} />
      ) : (
        <RedBanner />
      )}
    </Box>
  );
}
