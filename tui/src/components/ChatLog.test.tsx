import { render } from 'ink-testing-library';
import { expect, test } from 'vitest';
import type { Line } from '../bus.js';
import { ChatLog } from './ChatLog.js';

test('renders user messages, accumulated assistant deltas and activity lines', () => {
  const history: Line[] = [
    { kind: 'user', text: 'scan the box' },
    { kind: 'activity', text: '‹recon handoff: enumerate ports›' },
    { kind: 'assistant', text: 'found ssh and http' },
  ];
  const { lastFrame } = render(
    <ChatLog history={history} assistantBuf="streaming tail..." />,
  );
  const frame = lastFrame() ?? '';

  expect(frame).toContain('> scan the box');
  expect(frame).toContain('found ssh and http');
  expect(frame).toContain('‹recon handoff: enumerate ports›');
  // the in-flight buffer renders below the finished history
  expect(frame).toContain('streaming tail...');
});

test('accumulated deltas render as one assistant line', () => {
  const { lastFrame } = render(
    <ChatLog
      history={[{ kind: 'user', text: 'hi' }]}
      assistantBuf={'pong' + ': hi'}
    />,
  );
  expect(lastFrame()).toContain('pong: hi');
});

test('activity line renders its handoff text without the user "> " prefix', () => {
  // ink-testing-library runs with color disabled, so dimColor is not observable
  // in the frame; assert the structural rendering instead.
  const { lastFrame } = render(
    <ChatLog
      history={[{ kind: 'activity', text: '‹vuln done›' }]}
      assistantBuf=""
    />,
  );
  expect(lastFrame()).toBe('‹vuln done›');
});
