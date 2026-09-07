import { Box, Text } from 'ink';

/**
 * Minimal "hello chat" placeholder for the boot state.
 * Real chat loop (input -> POST /chat -> render) lands in Task 8.
 */
export function App() {
  return (
    <Box borderStyle="round" paddingX={1}>
      <Text>pentest-chat — TUI (protocol 1)</Text>
    </Box>
  );
}
