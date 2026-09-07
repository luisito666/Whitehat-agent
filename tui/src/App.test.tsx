import { render } from 'ink-testing-library';
import { expect, test } from 'vitest';
import { App } from './App.js';

test('App renders the boot placeholder', () => {
  const { lastFrame } = render(<App />);
  expect(lastFrame()).toContain('pentest-chat');
  expect(lastFrame()).toContain('protocol 1');
});
