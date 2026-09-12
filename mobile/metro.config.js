/**
 * Metro configuration.
 *
 * Exists for one reason: **keeping the mock backend out of a live bundle** (Stage 13, NFR-07).
 *
 * The obvious approach does not work, and it is worth writing down why, because it looks like it
 * should. `src/api/transport.ts` reaches the fixtures through a conditional `require` behind
 * `API_MODE === 'live'`, which `babel-preset-expo` inlines to a literal — so the branch is
 * statically dead in a live build. But Metro resolves `require()` targets while building the module
 * graph, *before* any dead-code elimination runs, so a `require` inside an unreachable branch still
 * pulls its whole subtree into the bundle. `npm run verify:bundle` found exactly that: 220 seeded
 * scans, the base64 sample PDF and every gazette citation were in a production export.
 *
 * So the exclusion happens at resolution time instead. With `EXPO_PUBLIC_API_MODE=live`, anything
 * under `src/api/mock/` resolves to an empty module. The conditional `require`s are never reached in
 * that build, so nothing notices.
 *
 * **Deliberately keyed on the env var, not on `NODE_ENV`.** A development build against the live
 * backend should also be free of fixtures — that is the configuration the Stage 13 cutover is
 * checked in — and a production build in mock mode (a demo APK with no backend) must still work.
 * The mode decides, not the build type.
 *
 * Adds no dependency. `expo/metro-config` ships with Expo.
 */

const { getDefaultConfig } = require('expo/metro-config');
const path = require('node:path');

const config = getDefaultConfig(__dirname);

const MOCK_DIR = path.join(__dirname, 'src', 'api', 'mock');
const EMPTY_MODULE = path.join(__dirname, 'scripts', 'empty-module.js');

if (process.env.EXPO_PUBLIC_API_MODE === 'live') {
  const upstream = config.resolver.resolveRequest;

  config.resolver.resolveRequest = (context, moduleName, platform) => {
    const resolve = upstream ?? context.resolveRequest;
    const resolved = resolve(context, moduleName, platform);

    // Matched on the **resolved** path rather than the request string, so `./mock`,
    // `@/api/mock/scenario` and a relative path from inside the folder are all covered by one rule.
    if (
      resolved &&
      typeof resolved.filePath === 'string' &&
      resolved.filePath.startsWith(MOCK_DIR + path.sep)
    ) {
      return { type: 'sourceFile', filePath: EMPTY_MODULE };
    }

    return resolved;
  };
}

module.exports = config;
