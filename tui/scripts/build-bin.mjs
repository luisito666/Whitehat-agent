/**
 * Build a standalone binary of the TUI with Node's built-in SEA support
 * (`node --build-sea`, available in Node >= 26). No external tools: the
 * injection step that used to require the unmaintained `postject` was moved
 * into Node core (joyeecheung.github.io — "Improving Single Executable
 * Application Building for Node.js", Jan 2026).
 *
 * Pipeline (from the repo tui/ dir, or any cwd):
 *
 *   1. `node scripts/build.mjs`            → dist/pentest-chat.js (ESM bundle)
 *   2. sea-config.json with mainFormat:"module" — the bundle is the SEA main
 *      script directly. Ink 6 / yoga-layout use top-level await, so the main
 *      must be ESM ("module"); a CJS wrapper is NOT needed on Node >= 26.
 *   3. `node --build-sea sea-config.json`  → dist/bin/pentest-chat-linux-<arch>
 *   4. smoke: the binary answers `--version` without node on PATH.
 *
 * Usage:
 *   node scripts/build-bin.mjs            (or: pnpm build:bin)
 *
 * Requires Node >= 26 (only for building — the produced binary embeds that
 * Node, so the target machine needs nothing).
 *
 * Output size note: the binary is ~150 MB because it embeds the full Node
 * runtime. That is the price of a true standalone (vs the ~1.8 MB bundle that
 * still needs node on PATH).
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { arch as osArch, platform as osPlatform } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const tuiDir = fileURLToPath(new URL('..', import.meta.url));
const bundleRel = 'dist/pentest-chat.js';
const bundleAbs = join(tuiDir, bundleRel);
const outDir = join(tuiDir, 'dist', 'bin');
const configPath = join(tuiDir, 'sea-config.json');

// --- guards -------------------------------------------------------------
const [major] = process.versions.node.split('.').map(Number);
if (major < 26) {
  console.error(
    `build-bin requires Node >= 26 for \`node --build-sea\` (found ${process.versions.node}). ` +
      'Install one with e.g. `nvs add 26 && nvs use 26`. The produced binary is standalone; ' +
      'only the build machine needs Node 26.',
  );
  process.exit(1);
}
if (osPlatform() !== 'linux') {
  // --build-sea also supports darwin (Mach-O) and win32 (PE); only linux was
  // exercised so far, so be explicit instead of shipping an untested artifact.
  console.error(`build-bin: untested platform ${osPlatform()} — refusing to build.`);
  process.exit(1);
}

// --- 1. bundle ----------------------------------------------------------
const bundle = spawnSync(process.execPath, [join(tuiDir, 'scripts', 'build.mjs')], {
  stdio: 'inherit',
  cwd: tuiDir,
});
if (bundle.status !== 0) process.exit(bundle.status ?? 1);

// --- 2. sea config ------------------------------------------------------
// `output` is relative to the config file. `disableExperimentalSEAWarning`
// silences the startup warning; `useCodeCache` pre-compiles the main script.
const seaConfig = {
  main: bundleRel,
  mainFormat: 'module',
  output: 'dist/bin/pentest-chat-linux-' + osArch(),
  disableExperimentalSEAWarning: true,
  useCodeCache: true,
  useSnapshot: false,
};
writeFileSync(configPath, JSON.stringify(seaConfig, null, 2) + '\n');
console.log(`wrote ${configPath}`);

// --- 3. build the binary ------------------------------------------------
mkdirSync(outDir, { recursive: true });
const sea = spawnSync(process.execPath, ['--build-sea', 'sea-config.json'], {
  stdio: 'inherit',
  cwd: tuiDir,
});
rmSync(configPath); // transient build file — never commit it
if (sea.status !== 0) process.exit(sea.status ?? 1);

// --- 4. smoke test ------------------------------------------------------
// Run with a scrubbed PATH to prove the binary needs no node install. --version
// covers the whole chain: SEA loader → ESM main → top-level await (yoga) → cli.
const binOut = join(outDir, 'pentest-chat-linux-' + osArch());
const smoke = spawnSync(
  '/usr/bin/env',
  ['PATH=/usr/bin:/bin', binOut, '--version'],
  { encoding: 'utf8' },
);
const expected = `pentest-chat ${JSON.parse(readFileSync(join(tuiDir, 'package.json'), 'utf8')).version ?? '0.0.0'}\n`;
if (smoke.status !== 0 || smoke.stdout !== expected) {
  console.error(`smoke failed: rc=${smoke.status} stdout=${JSON.stringify(smoke.stdout)} stderr=${smoke.stderr ?? ''}`);
  process.exit(1);
}
console.log(`smoke OK (no node on PATH): ${smoke.stdout.trim()}`);
console.log(`built ${binOut}`);

function readPkg() {
  return readFileSync(join(tuiDir, 'package.json'), 'utf8');
}
