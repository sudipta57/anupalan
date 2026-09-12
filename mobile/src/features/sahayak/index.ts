/**
 * Sahayak — the BIS / Indian Standards assistant chat (SIH26107).
 *
 * Implements **TRD FR-07 Sahayak chat**: English and Hindi, answers with inline source chips
 * that open the source on tap. Two entry points — free chat, and "Check BIS requirement for this
 * product" from a scan.
 *
 * An answer with no supporting source shows an explicit "not found in official sources" response
 * with a link to the relevant BIS page, never a fabricated one. Requests for the technical
 * content of a standard (test limits, clause text, tolerance tables) are refused and pointed at
 * the BIS purchase route — standards are priced and copyrighted, and that refusal is a design
 * feature, not a gap (CLAUDE.md §3.5, docs/01-architecture.md §7).
 *
 * Not implemented yet — P4. The applicability entry point ships before free chat
 * (docs/03-implementation-plan.md §9).
 */

export {};
