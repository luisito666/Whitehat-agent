/**
 * Braille dot spinner — one animated Text cell. Used while a view's first fetch
 * (engagement / ledger / status) is in flight.
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Text } from 'ink';

export const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

export function Spinner(): ReactNode {
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
