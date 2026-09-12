/**
 * vision-camera frame processor plugin — on-device marker detection.
 *
 * A small native plugin wrapping OpenCV ArUco, feeding the FR-01 capture gates at frame rate.
 *
 * Two things to know before touching this (CLAUDE.md §8, docs/03-implementation-plan.md §P3.3):
 *
 * 1. **Expo Go will not run frame processors.** You need an EAS dev client build. Build it on
 *    day one of mobile work; discovering this in week three costs days.
 * 2. **Do not let this plugin block the rest of the app.** If the native work stalls, ship the
 *    interim version that uploads a frame every 500 ms for server-side gate checks, and swap the
 *    plugin in later behind the same interface.
 *
 * The marker must print at exactly 100% scale. If the printer scales the page, every millimetre
 * downstream is wrong and the bug looks like a code bug for days. Verify printed markers with a
 * ruler.
 *
 * Not implemented yet — P3.
 */

export {};
