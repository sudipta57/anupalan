/**
 * Capture — guided camera with live quality gates.
 *
 * Implements **TRD FR-01 Guided capture** and **TRD FR-02 Marker onboarding**.
 *
 * A vision-camera frame processor evaluates four gates and shows each as pass/fail:
 * ArUco marker detected with all four corners in frame; blur (variance of Laplacian >= 120);
 * glare (fraction of pixels >= 250 luminance below 2%); tilt (<= 25 degrees).
 *
 * The shutter stays **disabled** while any gate fails, and each failing gate shows a specific
 * instruction — "move closer", "reduce glare", "hold flatter". Rejecting bad input at capture
 * time is worth more than any post-processing (docs/01-architecture.md §5 S1).
 *
 * FR-02: first run offers the printed marker PDF (A4, 40 mm tag, 5 mm quiet zone) or an ID-1
 * card (85.60 x 53.98 mm) as fallback. `markerType` and `markerMm` go on every scan, and a scan
 * cannot be submitted without them — no marker means no millimetres (CLAUDE.md §3.3).
 *
 * Expo Go cannot run frame processors. This feature needs an EAS dev client build
 * (CLAUDE.md §8); see mobile/README.md.
 *
 * Not implemented yet — P3.
 */

export {};
