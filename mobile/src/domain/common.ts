/**
 * Primitives shared across the domain.
 *
 * Unit conventions are naming conventions, enforced by review rather than by the type system
 * (CLAUDE.md §5). `Paise` and `Millimetres` are aliases of `number`, so the discipline is that a
 * field carrying one **says so in its name** — `mrpPaise`, `heightMm`. A field called `height`
 * is a bug report waiting to happen.
 */

/** Money. Always an integer number of paise — never rupees, never a float. */
export type Paise = number;

/** Length. Always float millimetres. */
export type Millimetres = number;

/** ISO-8601 timestamp in UTC, e.g. `2026-09-12T06:14:22Z`. */
export type IsoDateTime = string;

/** ISO-8601 date, e.g. `2026-09-12`. */
export type IsoDate = string;

/**
 * A rectangle in the coordinate space of the **rectified** image, in pixels.
 *
 * Rectified, not raw: the pipeline warps every image to a fixed px/mm plane, and findings are
 * anchored there. Converting to millimetres is a division by `pxPerMm` on the asset, never an
 * assumption (CLAUDE.md §3.3).
 */
export interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One page of a cursor-paginated collection (docs/02-trd.md §5). */
export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}
