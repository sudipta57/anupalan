/**
 * Bulk listing check — **TRD FR-10**, Mode B only.
 *
 * *Accept: a 50-row CSV produces 50 result rows with a summary count, and no metric rule ever
 * returns PASS or FAIL from listing text alone.*
 *
 * | File | What it decides |
 * |---|---|
 * | `metric-rules.ts` | Which rules are millimetre comparisons. The one list, shared with the mock. |
 * | `parse.ts` | Turning a paste into rows, and refusing to submit more than fifty. |
 * | `guard.ts` | Checking what came back. The client's enforcement of the criterion. |
 * | `results.ts` | Summary counts and row ordering. |
 * | `export.ts` | The CSV. Pure serialisation, thin filesystem and share calls. |
 * | `row-card.tsx` | One result row. Imported by the screen directly. |
 *
 * Two refusals carry this stage, and both are about a count a reader will trust without checking.
 *
 * **Over fifty rows blocks rather than truncates** (`parse.ts`). Fifty-one pasted, fifty checked, a
 * table showing fifty — and a seller who believes their catalogue was cleared. The dropped row is
 * the one that was non-compliant, and the result has already been mailed on by the time anyone
 * notices. Same shape as Stage 9's report gate.
 *
 * **A metric verdict from listing text is refused, downgraded and reported** (`guard.ts`). This one
 * assumes the backend is wrong and checks, because of what the failure would look like if it were:
 * `LM-9-2-TABLE1 · PASS · 4.2 mm` beside a gazette citation, from a source containing no millimetres
 * at all. It would look exactly like the product working, and it is the most convincing wrong output
 * this system can produce. The realistic cause is not a bug but a well-meant feature — a Rule 9 path
 * that reads the listing's own photograph — landing three layers away from anyone thinking about
 * CLAUDE.md §3.3.
 *
 * Everything except `export.ts` is pure.
 */

export {
  METRIC_RULE_IDS,
  PAGE_CONTEXT_RULE_IDS,
  isMetricRule,
  needsPageContext,
} from './metric-rules';

export {
  MAX_ROWS,
  MAX_SOURCE_LENGTH,
  blocksSubmit,
  canSubmit,
  kindOf,
  parseListings,
  splitCsvLine,
} from './parse';
export type { ParseResult, ParsedRow, SubmitBlock } from './parse';

export { isClean, sanitise, violations } from './guard';
export type { GuardViolation } from './guard';

export {
  NOT_ASSESSABLE_REASON_KEYS,
  cleanRows,
  erroredRows,
  orderedRows,
  rowLabel,
  rowsWith,
} from './results';

export {
  BULK_DIRECTORY,
  BULK_MIME_TYPE,
  CSV_COLUMNS,
  csvField,
  csvFileNameFor,
  shareCsv,
  toCsv,
  writeCsv,
} from './export';

/**
 * `ListingRowCard` is deliberately **not** re-exported here.
 *
 * The same narrowing `features/history` and `features/sahayak` apply: this barrel is otherwise pure
 * apart from `export.ts`, and a test importing the parser should not drag the component tree in. The
 * screen imports `./row-card` directly.
 */
