/**
 * Renders the chat transcript:
 *   - user messages as `> msg` (cyan)
 *   - assistant text: the accumulated deltas of the turn
 *   - agent.activity lines, dim: "‹recon handoff: ...›"
 *   - errors in red
 *
 * `assistantBuf` is the not-yet-finished turn; it renders below the finished
 * history as a live assistant line.
 */
import { Box, Text } from 'ink';
import type { ReactNode } from 'react';
import type { Line } from '../bus.js';

interface Props {
  history: Line[];
  assistantBuf: string;
}

function LogLine({ line }: { line: Line }): ReactNode {
  switch (line.kind) {
    case 'user':
      return <Text color="cyan">{`> ${line.text}`}</Text>;
    case 'assistant':
      return <Text>{line.text}</Text>;
    case 'activity':
      return <Text dimColor>{line.text}</Text>;
    case 'error':
      return <Text color="red">{line.text}</Text>;
  }
}

export function ChatLog({ history, assistantBuf }: Props): ReactNode {
  return (
    <Box flexDirection="column">
      {history.map((line, i) => (
        <LogLine key={i} line={line} />
      ))}
      {assistantBuf ? <Text>{assistantBuf}</Text> : null}
    </Box>
  );
}
