import { describe, expect, test } from 'vitest';
import { handleCliFlags, pkgVersion, HELP } from './cli.js';

describe('handleCliFlags', () => {
  test('--version returns "pentest-chat <version>\\n"', () => {
    expect(handleCliFlags(['--version'])).toBe(`pentest-chat ${pkgVersion()}\n`);
  });

  test('pkgVersion matches package.json (0.1.0)', () => {
    expect(pkgVersion()).toBe('0.1.0');
  });

  test('--help returns the key map with PENTEST_TUI_URL', () => {
    expect(handleCliFlags(['--help'])).toBe(HELP);
    expect(HELP).toContain('Ctrl+P');
    expect(HELP).toContain('PENTEST_TUI_URL');
  });

  test('no flag → null (render the TUI)', () => {
    expect(handleCliFlags([])).toBeNull();
    expect(handleCliFlags(['hola', 'mundo'])).toBeNull();
  });
});
