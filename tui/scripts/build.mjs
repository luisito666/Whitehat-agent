/**
 * Package the TUI into one self-contained file: `dist/pentest-chat.js`.
 *
 * The plan said "pastel bake → dist/pentest-chat", but pastel
 * (vadimdemedes/pastel) has no `bake` / standalone-binary command — it is a
 * file-routing framework whose `pastel build` only emits a `build/` directory of
 * JS that still needs `node`. So this is the pragmatic fallback: a single
 * esbuild bundle (Ink, React and the fetch client all inlined), a
 * `#!/usr/bin/env node` shebang, `chmod +x`, wired as the package `bin`. It
 * still needs `node` on PATH, but ships as one file with no `node_modules`.
 *
 *   node scripts/build.mjs      (or: pnpm build)
 */
import { chmodSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const entry = fileURLToPath(new URL('../src/main.tsx', import.meta.url));
const outfile = fileURLToPath(new URL('../dist/pentest-chat.js', import.meta.url));

/**
 * Ink does `await import('./devtools.js')` (→ `react-devtools-core`) only when
 * `DEV === 'true'`. That dep is not in the tree and the branch is never taken in
 * normal use, but esbuild still tries to resolve it while bundling. Stub it with
 * an inert module so the bundle stays fully self-contained (external:none) and
 * `--version` / `--help` never touch it.
 */
const stubReactDevtools = {
  name: 'stub-react-devtools-core',
  setup(b) {
    b.onResolve({ filter: /^react-devtools-core$/ }, () => ({
      path: 'react-devtools-core',
      namespace: 'stub-rdt',
    }));
    b.onLoad({ filter: /.*/, namespace: 'stub-rdt' }, () => ({
      contents: 'export default { initialize() {}, connectToDevTools() {} };',
      loader: 'js',
    }));
  },
};

await build({
  entryPoints: [entry],
  outfile,
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node22',
  // external:none — everything but Node builtins goes in the bundle.
  minify: false,
  jsx: 'automatic',
  banner: {
    // Shebang + a real `require` for the few CJS deps that call it (e.g.
    // signal-exit does `require('assert')`); esbuild's ESM output otherwise
    // shims `require` with a stub that throws on Node builtins.
    js: [
      '#!/usr/bin/env node',
      "import { createRequire as __createRequire } from 'node:module';",
      'const require = __createRequire(import.meta.url);',
    ].join('\n'),
  },
  plugins: [stubReactDevtools],
  logLevel: 'info',
});

chmodSync(outfile, 0o755);
console.log(`built ${outfile}`);
