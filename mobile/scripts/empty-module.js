/**
 * The module the mock backend resolves to in a live build.
 *
 * `metro.config.js` redirects every `src/api/mock/**` request here when
 * `EXPO_PUBLIC_API_MODE=live`, so the fixtures are not in the release bundle at all (NFR-07). The
 * conditional `require`s in `src/api/transport.ts` and `src/api/dev.ts` are never reached in that
 * build — `API_MODE === 'live'` short-circuits before them — so nothing ever reads these exports.
 *
 * It is deliberately an empty object rather than a throwing stub. A throw would turn a resolver
 * mistake into a crash on a user's phone; an empty object turns it into an immediate, obvious
 * `undefined is not a function` in testing, and `npm run verify:bundle` is what catches it before
 * either.
 */

module.exports = {};
