/**
 * Ledger view (`l` from the chat view, Esc returns, `r` re-fetches).
 *
 * Reads the append-only chain of custody through GET /ledger?tail=20 and renders
 * one row per entry. The ledger schema is heterogeneous (Metasploit runs carry
 * an `msf` block, HTTP PoCs carry `body_sha256` + `url`, etc. — see
 * reports/evidence.jsonl), so every field is optional and a row only shows what
 * the entry actually carries: short timestamp, technique, target, the first 8
 * chars of the body sha256 (when present) and the auth reference.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Box, Text, useInput } from 'ink';
import { getLedger, type Ledger, type LedgerEntry } from '../api.js';
import { Spinner } from './Spinner.js';

interface Props {
  /** Back to the chat view (bound to Esc by App). */
  onClose: () => void;
}

const TAIL = 20;

type Load =
  | { phase: 'loading' }
  | { phase: 'ok'; ledger: Ledger }
  | { phase: 'error'; detail: string };

/** A non-empty string field, or null. */
function str(v: unknown): string | null {
  return typeof v === 'string' && v.trim() !== '' ? v : null;
}

/** "2026-09-07T01:10:24+00:00" -> "09-07 01:10"; anything else passes through. */
function shortTs(v: unknown): string {
  const s = str(v);
  if (!s) return '?';
  const m = /^\d{4}-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(s);
  return m ? `${m[1]}-${m[2]} ${m[3]}:${m[4]}` : s;
}

/** First 8 chars of the entry's body sha256, when it carries one. */
function shortHash(e: LedgerEntry): string | null {
  const h = str(e['body_sha256']) ?? str(e['sha256']);
  return h ? h.slice(0, 8) : null;
}

function LedgerRow({ e }: { e: LedgerEntry }): ReactNode {
  const technique = str(e['technique']) ?? str(e['exploit_method']) ?? '—';
  const target = str(e['target']);
  const hash = shortHash(e);
  const auth = str(e['auth_reference']);
  const proven = e['proven'] === true;
  return (
    <Text>
      <Text dimColor>{shortTs(e['ts'])}</Text>
      {'  '}
      <Text color={proven ? 'green' : undefined}>{technique}</Text>
      {target ? <Text> · {target}</Text> : null}
      {hash ? <Text dimColor> · {hash}</Text> : null}
      {auth ? <Text dimColor> · auth {auth}</Text> : null}
      {proven ? <Text color="green"> ✓</Text> : null}
    </Text>
  );
}

export function LedgerView({ onClose }: Props): ReactNode {
  const [load, setLoad] = useState<Load>({ phase: 'loading' });
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const fetchLedger = useCallback((): void => {
    setLoad({ phase: 'loading' });
    void (async () => {
      try {
        const ledger = await getLedger(TAIL);
        if (aliveRef.current) setLoad({ phase: 'ok', ledger });
      } catch (err) {
        if (aliveRef.current) {
          setLoad({
            phase: 'error',
            detail: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
  }, []);

  useEffect(() => {
    fetchLedger();
  }, [fetchLedger]);

  useInput((input, key) => {
    if (key.escape) onClose();
    else if (input === 'r') fetchLedger();
  });

  return (
    <Box flexDirection="column">
      <Text>
        Ledger — cadena de custodia{' '}
        <Text dimColor>· reports/evidence.jsonl</Text>
      </Text>
      {load.phase === 'loading' ? (
        <Text>
          <Spinner /> cargando ledger…
        </Text>
      ) : load.phase === 'error' ? (
        <Text color="red">! {load.detail}</Text>
      ) : load.ledger.entries.length === 0 ? (
        <Text dimColor>ledger vacío — sin evidencia registrada</Text>
      ) : (
        <Box flexDirection="column">
          {load.ledger.entries.map((e, i) => (
            <LedgerRow key={i} e={e} />
          ))}
        </Box>
      )}
      <Text dimColor>
        {load.phase === 'ok' ? `${load.ledger.total} entradas · ` : ''}r
        refrescar · Esc volver
      </Text>
    </Box>
  );
}
