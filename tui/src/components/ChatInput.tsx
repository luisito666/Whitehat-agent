/**
 * One-line text input driven by Ink's useInput.
 *   - Enter  : submit (only while `ready`; blank input ignored)
 *   - Ctrl+P : approve-gate toggle — handled in App; swallowed here so it never
 *     lands in the buffer
 *   - Ctrl+C : exit, restoring raw mode via useApp().exit()
 *   - Backspace/Delete edit the buffer
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Box, Text, useApp, useInput } from 'ink';

interface Props {
  ready: boolean;
  onSubmit: (text: string) => void;
}

const HINT = 'Enter envía · Ctrl+P aprobación · l ledger · s status';

export function ChatInput({ ready, onSubmit }: Props): ReactNode {
  const { exit } = useApp();
  const [value, setValue] = useState('');

  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      exit();
      return;
    }
    if (key.ctrl && input === 'p') {
      // App owns the approve-gate toggle; just don't type a "p".
      return;
    }
    if (key.return) {
      const text = value.trim();
      if (ready && text) {
        onSubmit(text);
        setValue('');
      }
      return;
    }
    if (key.backspace || key.delete) {
      setValue((v) => v.slice(0, -1));
      return;
    }
    if (input && !key.ctrl && !key.meta && !key.escape) {
      setValue((v) => v + input);
    }
  });

  return (
    <Box flexDirection="column">
      <Box>
        <Text color="cyan">{'> '}</Text>
        <Text>{value}</Text>
      </Box>
      <Text dimColor>{HINT}</Text>
    </Box>
  );
}
