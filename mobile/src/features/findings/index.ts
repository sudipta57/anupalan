/**
 * Findings viewer — the rectified image with tappable bounding boxes, plus a grouped list.
 *
 * Implements **TRD FR-05 Findings viewer** and **TRD FR-06 Low-confidence confirmation**.
 *
 * FR-05: results render as the rectified image with tappable boxes and a list grouped into
 * Failures / Borderline / Not assessable / Passed. Tapping a finding highlights its box and
 * shows what was required, what was observed, and the rule citation verbatim — without leaving
 * the screen. Every FAIL and BORDERLINE must have a box that highlights on tap.
 *
 * FR-06: any extracted field below confidence 0.75 is shown in a confirmation sheet with its
 * image crop before the verdict is finalised. The correction is recorded with `source=human` and
 * the verdict recomputes.
 *
 * **This screen carries the advisory disclaimer** — a pre-audit tool, not a certification
 * (CLAUDE.md §3.8). Overlay boxes must align with the rectified image at all zoom levels.
 *
 * Not implemented yet — P3.
 */

export {};
