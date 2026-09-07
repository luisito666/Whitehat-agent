import { render } from 'ink-testing-library';
import { expect, test } from 'vitest';
import type { Status } from '../api.js';
import { initialState, type UiState } from '../bus.js';
import { StatusBar } from './StatusBar.js';

const STATUS: Status = {
  stack: 'up',
  workers: [
    { role: 'recon', url: 'http://127.0.0.1:9101', up: true },
    { role: 'vuln', url: 'http://127.0.0.1:9102', up: false },
  ],
  engagement: { id: 'ENG-1', client: 'ACME', valid: true, approved: false },
  protocol: 1,
};

const withState = (over: Partial<UiState>): UiState => ({ ...initialState, ...over });

test('ready phase: run word, workers up/total, engagement and short session id', () => {
  const { lastFrame } = render(
    <StatusBar
      state={withState({
        phase: 'ready',
        status: STATUS,
        sessionId: 'abcdef0123456789',
      })}
    />,
  );
  const frame = lastFrame() ?? '';
  expect(frame).toContain('estado');
  expect(frame).toContain('ready');
  expect(frame).toContain('1/2'); // one of two workers up
  expect(frame).toContain('ENG-1');
  expect(frame).toContain('ACME');
  expect(frame).toContain('abcdef'); // session trimmed to 6 chars
  expect(frame).not.toContain('abcdef0123456789');
});

test('reconnecting wins over the phase word', () => {
  const { lastFrame } = render(
    <StatusBar state={withState({ phase: 'streaming', reconnecting: true })} />,
  );
  expect(lastFrame() ?? '').toContain('reconectando');
});

test('down phase is shown verbatim', () => {
  const { lastFrame } = render(
    <StatusBar state={withState({ phase: 'down' })} />,
  );
  expect(lastFrame() ?? '').toContain('down');
});

test('no /status yet: engagement falls back to the red "sin engagement"', () => {
  const { lastFrame } = render(<StatusBar state={initialState} />);
  const frame = lastFrame() ?? '';
  expect(frame).toContain('sin engagement');
  expect(frame).not.toContain('workers'); // no worker segment without a poll
});

test('boot/discovering render as "connecting"', () => {
  const { lastFrame } = render(
    <StatusBar state={withState({ phase: 'discovering' })} />,
  );
  expect(lastFrame() ?? '').toContain('connecting');
});
