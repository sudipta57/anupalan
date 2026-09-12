/**
 * Verify the mock backend is absent from a production bundle — Stage 13, NFR-07.
 *
 * *Done when: … the mock transport is gone from the release build.*
 *
 * The claim this script exists to check is easy to make and easy to get wrong. `__DEV__` gates keep
 * the dev panels off a user's screen; they do nothing about what is in the bundle. A single static
 * `import` of `@/api/mock` anywhere in `app/` or `src/` pulls the whole fixture graph into the
 * release build — 220 seeded scans, a base64 PDF, a base64 DOCX, every gazette citation — as
 * unreachable code that still costs cold-start parse time against NFR-02's three-second budget, and
 * that still ships a working offline fake of a compliance tool inside the real one.
 *
 * So the mock is reached through conditional `require`s behind compile-time constants
 * (`src/api/transport.ts` and `src/api/dev.ts`), and this script proves the elimination actually
 * happened rather than assuming Metro did it.
 *
 * **The sentinels are strings that exist only in the mock.** They are checked against the exported
 * JavaScript, not against the module graph, because minification and inlining are exactly the steps
 * that could go either way. If any of them appears, the fixtures are in the build.
 *
 * Run: `npm run verify:bundle`
 */

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { join } from 'node:path';

const OUT_DIR = '.bundle-check';

/**
 * Strings that appear in the fixture layer and nowhere else.
 *
 * Each is chosen to be distinctive enough that a match is real. `No mock route for` is the mock
 * router's fallback error; `mock-access-` is its token prefix; `scn_hero_atta` is the hero scan id;
 * `standards-india-handbook` is Stage 11's deliberately fabricated citation host; `JVBERi0` is the
 * base64 prologue of the sample PDF (`%PDF-`).
 */
const SENTINELS = [
  'No mock route for',
  'mock-access-',
  'scn_hero_atta',
  'standards-india-handbook',
  'JVBERi0',
];

function bundleFiles(dir) {
  const found = [];

  const walk = (current) => {
    for (const entry of readdirSync(current)) {
      const path = join(current, entry);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      if (entry.endsWith('.js') || entry.endsWith('.hbc')) found.push(path);
    }
  };

  walk(dir);
  return found;
}

function main() {
  if (existsSync(OUT_DIR)) rmSync(OUT_DIR, { recursive: true, force: true });

  console.log('Exporting a production bundle with EXPO_PUBLIC_API_MODE=live …');

  execFileSync(
    'npx',
    ['expo', 'export', '--platform', 'android', '--output-dir', OUT_DIR, '--no-minify'],
    {
      stdio: 'inherit',
      env: {
        ...process.env,
        NODE_ENV: 'production',
        EXPO_PUBLIC_API_MODE: 'live',
        EXPO_NO_TELEMETRY: '1',
      },
    }
  );

  const files = bundleFiles(OUT_DIR);
  if (files.length === 0) {
    console.error('No bundle produced — nothing was verified.');
    process.exit(1);
  }

  // From `statSync`, not from the decoded string's length. The Android bundle is Hermes bytecode:
  // reading it as UTF-8 turns invalid byte sequences into replacement characters, so a character
  // count is not a byte count and wobbles between builds of identical size. The sentinel *search* is
  // unaffected — ASCII bytes always decode to themselves, so a literal ASCII string survives intact.
  let totalBytes = 0;
  const hits = [];

  for (const file of files) {
    totalBytes += statSync(file).size;
    const source = readFileSync(file, 'utf8');

    for (const sentinel of SENTINELS) {
      if (source.includes(sentinel)) hits.push({ file, sentinel });
    }
  }

  console.log(`\nBundle: ${files.length} file(s), ${(totalBytes / 1_048_576).toFixed(2)} MB`);
  // `--no-minify` is deliberate: it keeps the sentinels findable as literal strings. Minification
  // only removes more, so a clean unminified bundle implies a clean minified one.
  console.log('Exported with --no-minify, so a sentinel would be visible as a literal string.');

  if (hits.length > 0) {
    console.error('\nFAIL — the mock backend is in the production bundle:');
    for (const { file, sentinel } of hits) console.error(`  ${sentinel}  in  ${file}`);
    console.error(
      '\nSomething imports `@/api/mock` statically. Route it through `src/api/dev.ts`.'
    );
    process.exit(1);
  }

  console.log(`\nPASS — none of the ${SENTINELS.length} mock sentinels appear in the bundle.`);
  rmSync(OUT_DIR, { recursive: true, force: true });
}

main();
