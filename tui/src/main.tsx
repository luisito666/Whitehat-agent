/**
 * Entry point. Before touching Ink we handle the non-interactive flags so
 * `--version` / `--help` work without a TTY (CI, `node dist/pentest-chat.js`);
 * see src/cli.ts. With no flag and a real terminal we render the TUI.
 */
import { render } from 'ink';
import { App } from './App.js';
import { BusProvider } from './bus.js';
import { handleCliFlags } from './cli.js';

const output = handleCliFlags(process.argv.slice(2));
if (output !== null) {
  process.stdout.write(output);
  process.exit(0);
}

render(
  <BusProvider>
    <App />
  </BusProvider>,
  { exitOnCtrlC: true },
);
