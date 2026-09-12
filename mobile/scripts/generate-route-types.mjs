/**
 * Regenerate `.expo/types/router.d.ts` without starting Metro.
 *
 * `experiments.typedRoutes` makes every `router.push()` and `<Link href>` check against the real
 * route tree, which is worth having — a renamed screen becomes a compile error instead of a blank
 * page found in a demo. But the declaration file is normally written by the **dev server's**
 * file watcher, which means `npx tsc --noEmit` on a fresh clone, or in CI, typechecks against
 * either a stale route union or none at all. `npx expo export` does not write it either.
 *
 * So this calls the same generator the dev server uses. It reaches into a transitive dependency
 * of `@expo/cli`, which is not a public API: if an SDK upgrade moves it, this script fails loudly
 * with the path it tried, and `npx expo start` is always the fallback that regenerates the file.
 *
 *     npm run types:routes
 */

import { createRequire } from 'node:module';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';

const APP_ROOT = path.resolve(import.meta.dirname, '..', 'app');
const OUTPUT_DIR = path.resolve(import.meta.dirname, '..', '.expo', 'types');

/** The generator lives under @expo/cli, which lives under expo. Walk the chain to find it. */
function resolveGenerator() {
  let require = createRequire(path.resolve(import.meta.dirname, '..') + '/');

  for (const id of ['expo/package.json', '@expo/cli/package.json']) {
    require = createRequire(require.resolve(id));
  }

  return require.resolve('@expo/router-server/build/typed-routes/index.js');
}

if (!existsSync(APP_ROOT)) {
  console.error(`No app directory at ${APP_ROOT}`);
  process.exit(1);
}

// The generator reads this to find the routes, and returns early without it.
process.env.EXPO_ROUTER_APP_ROOT = APP_ROOT;

let generatorPath;
try {
  generatorPath = resolveGenerator();
} catch (cause) {
  console.error(
    'Could not find the expo-router type generator. Run `npx expo start` once instead — ' +
      'the dev server writes .expo/types/router.d.ts itself.'
  );
  console.error(cause);
  process.exit(1);
}

const { regenerateDeclarations } = await import(generatorPath);

mkdirSync(OUTPUT_DIR, { recursive: true });
regenerateDeclarations(OUTPUT_DIR);

// `regenerateDeclarations` is debounced by a second, because Metro fires paired add/delete events
// when a folder is renamed. Nothing to await, so wait it out.
await new Promise((resolve) => setTimeout(resolve, 1_500));

const written = path.join(OUTPUT_DIR, 'router.d.ts');
if (!existsSync(written)) {
  console.error(`Generator ran but wrote nothing to ${written}`);
  process.exit(1);
}

console.log(`wrote ${path.relative(process.cwd(), written)}`);
