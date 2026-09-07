import { render } from 'ink';
import { App } from './App.js';
import { BusProvider } from './bus.js';

render(
  <BusProvider>
    <App />
  </BusProvider>,
  { exitOnCtrlC: true },
);
