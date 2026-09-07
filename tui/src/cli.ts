/**
 * Non-interactive CLI flags, split out of main.tsx so they are unit-testable
 * without importing the entry (which would call render()).
 *
 *   --version  → "pentest-chat <version>" (from package.json)
 *   --help     → the key map + PENTEST_TUI_URL
 *
 * `handleCliFlags` is pure: it returns the text to print (caller writes it and
 * exits 0) or `null` when there is no flag and the TUI should render.
 */
import { readFileSync } from 'node:fs';

export const HELP = `pentest-chat — TUI de chat para el supervisor de pentest (Ink + React)

Uso:
  pentest-chat            abre la TUI (requiere un TTY interactivo)
  pentest-chat --version  imprime la versión y sale
  pentest-chat --help     imprime esta ayuda y sale

Teclas:
  Enter    envía el mensaje
  Ctrl+P   abra/cierra la puerta de aprobación (solo lectura)
  l        vista del ledger (con el prompt vacío)
  s        vista de estado / overview (con el prompt vacío)
  r        recarga la vista del ledger
  Esc      vuelve al chat
  Ctrl+C   salir

Entorno:
  PENTEST_TUI_URL  URL del sidecar de chat (por defecto http://127.0.0.1:9000)
`;

/**
 * Version injected at build time by esbuild `--define:PKG_VERSION=...`
 * (see scripts/build.mjs). Falls back to reading ../package.json for `tsx`
 * dev runs and plain-bundle runs that did not pass the define; in a Node SEA
 * binary there is no package.json next to the entry, so the define is the
 * only source of truth there.
 */
declare const PKG_VERSION: string | undefined;

export function pkgVersion(): string {
  try {
    // esbuild replaces the reference when the define is set; otherwise this
    // throws (not defined) or is undefined at runtime.
    const injected = typeof PKG_VERSION !== 'undefined' ? PKG_VERSION : undefined;
    if (typeof injected === 'string' && injected.length > 0) return injected;
  } catch {
    // ReferenceError in non-bundled dev — fall through to package.json.
  }
  try {
    const url = new URL('../package.json', import.meta.url);
    const pkg = JSON.parse(readFileSync(url, 'utf8')) as { version?: unknown };
    return typeof pkg.version === 'string' ? pkg.version : '0.0.0';
  } catch {
    return '0.0.0';
  }
}

/** Text to print for a recognised flag, or `null` to render the TUI. */
export function handleCliFlags(argv: readonly string[]): string | null {
  if (argv.includes('--version')) return `pentest-chat ${pkgVersion()}\n`;
  if (argv.includes('--help')) return HELP;
  return null;
}
