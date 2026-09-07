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
  Ctrl+P   abre/cierra la puerta de aprobación (solo lectura)
  l        vista del ledger (con el prompt vacío)
  s        vista de estado / overview (con el prompt vacío)
  r        recarga la vista del ledger
  Esc      vuelve al chat
  Ctrl+C   salir

Entorno:
  PENTEST_TUI_URL  URL del sidecar de chat (por defecto http://127.0.0.1:9000)
`;

/** Version from ../package.json (tui/package.json under tsx and after bundling). */
export function pkgVersion(): string {
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
