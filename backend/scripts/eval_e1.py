"""E1 — metrology accuracy (B22, TRD §7, docs/03-implementation-plan.md §P0.4).

    python -m scripts.eval_e1 --dir ../eval/e1

**The number this prints decides whether the product's differentiator is real.** P0's gate reads
it directly: MAE ≤ 0.3 mm and ≥ 90% within ±0.3 mm and the millimetre claim stands; above 0.5 mm
and the honest move is to stop claiming automated font checking altogether
(``docs/eval-results.md``). So this script measures what the pipeline measures, through the same
functions, and never through a shortcut that would flatter it.

Corpus layout
-------------
``--dir`` holds the captures and one ``truth.csv``::

    eval/e1/
      truth.csv
      pixel6a_25cm_15deg_bright.jpg
      ...

``truth.csv`` has one row per **line of digits** in one image::

    image,line,truth_mm,x_mm,y_mm,w_mm,h_mm
    pixel6a_25cm_15deg_bright.jpg,0,0.8,20.0,40.0,60.0,3.0
    pixel6a_25cm_15deg_bright.jpg,1,1.0,20.0,46.0,60.0,3.0

``truth_mm`` is the caliper-measured or PDF-exact cap height of that line. The five ``*_mm``
columns are the line's region **in the rectified plane**, measured from the rectified image's
origin — a generated chart knows these by construction, and for a real label they are read off
with a ruler once.

The region is required rather than optional, and that is a deliberate refusal to be convenient.
Without it the script would have to guess which measured glyph belongs to which truth height, and
the obvious guess — assign each measurement to the nearest truth value — flatters the result
exactly where it matters: a 0.8 mm line measured at 0.95 mm would be scored against 1.0 mm and
recorded as a 0.05 mm error instead of a 0.15 mm one.

Conditions in the filename
--------------------------
``<phone>_<dist>_<angle>_<light>.jpg``, as in §P0.3. Parsed only to label the worst case in the
output; an unparseable name is reported as the filename itself rather than dropped.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.common import fmt_mm, mean, missing_corpus, percent, print_header

LAYOUT = """
Expected layout:

  eval/e1/
    truth.csv
    <phone>_<dist>_<angle>_<light>.jpg
    ...

truth.csv columns: image,line,truth_mm,x_mm,y_mm,w_mm,h_mm
  one row per line of digits; the *_mm region is in the rectified plane.

The corpus is not committed (eval/ is gitignored) — see docs/eval-results.md.
"""

_CONDITION = re.compile(
    r"^(?P<phone>[^_]+)_(?P<dist>\d+)\s*cm_(?P<angle>\d+)\s*deg_(?P<light>[^.]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TruthRow:
    image: str
    line: int
    truth_mm: float
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float


@dataclass(frozen=True)
class Sample:
    """One measured glyph against its truth."""

    image: str
    line: int
    truth_mm: float
    measured_mm: float
    conditions: str

    @property
    def error_mm(self) -> float:
        return abs(self.measured_mm - self.truth_mm)


def conditions_of(image: str) -> str:
    """``angle=15, dist=25, light=bright`` from the filename, or the filename itself."""
    match = _CONDITION.match(image)
    if match is None:
        return image
    return (
        f"angle={match.group('angle')}, dist={match.group('dist')}, "
        f"light={match.group('light')}"
    )


def read_truth(path: Path) -> list[TruthRow]:
    """Parse ``truth.csv``. A malformed row is fatal — a silently skipped truth row is a sample
    quietly removed from the denominator, which moves the headline number."""
    rows: list[TruthRow] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for number, raw in enumerate(csv.DictReader(handle), start=2):
            try:
                rows.append(
                    TruthRow(
                        image=(raw["image"] or "").strip(),
                        line=int(raw["line"]),
                        truth_mm=float(raw["truth_mm"]),
                        x_mm=float(raw["x_mm"]),
                        y_mm=float(raw["y_mm"]),
                        w_mm=float(raw["w_mm"]),
                        h_mm=float(raw["h_mm"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SystemExit(f"{path}:{number}: {exc}. Columns: {LAYOUT.strip()}") from exc
    return rows


def measure_image(
    image_path: Path, truths: Sequence[TruthRow], marker_mm: float
) -> tuple[list[Sample], str | None]:
    """Measure every truth line in one capture.

    Returns the samples and, when the image could not be measured at all, the reason. A reason is
    reported rather than raised: one unreadable capture out of sixty is a data point about capture
    reliability, not a run to abandon.
    """
    import cv2
    import numpy as np

    from app.config import settings
    from app.services.rules.types import BBox
    from app.services.vision.marker import detect_marker, quality
    from app.services.vision.metrology import measure_text_span
    from app.services.vision.rectify import RectificationError, rectify

    data = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if data is None:
        return [], "unreadable image"

    image = np.asarray(data, dtype=np.uint8)
    corners = detect_marker(image)
    if corners is None:
        # No marker means no millimetres (CLAUDE.md §3.3). Counted as a failed capture, never
        # measured anyway.
        return [], "no marker detected"

    try:
        rectified = rectify(image, corners, marker_mm)
    except RectificationError as exc:
        return [], f"rectification failed: {exc}"

    capture = quality(image, corners)
    px_per_mm = rectified.px_per_mm
    conditions = conditions_of(image_path.name)

    samples: list[Sample] = []
    for truth in truths:
        bbox = BBox(
            x=truth.x_mm * px_per_mm,
            y=truth.y_mm * px_per_mm,
            width=truth.w_mm * px_per_mm,
            height=truth.h_mm * px_per_mm,
        )
        measurements = measure_text_span(
            rectified.image,
            bbox,
            capture,
            field_code="e1",
            baseline_uncertainty_mm=settings.CURVATURE_MAX_RESIDUAL_MM,
            px_per_mm=int(px_per_mm),
        )
        heights = [
            m.height_mm
            for m in measurements
            if m.height_mm is not None and not m.is_mark
        ]
        if not heights:
            continue

        # The median of the line, which is what the pipeline uses: one glyph that merged with its
        # neighbour must not move the line's reading.
        ordered = sorted(heights)
        median = ordered[len(ordered) // 2]
        samples.append(
            Sample(
                image=image_path.name,
                line=truth.line,
                truth_mm=truth.truth_mm,
                measured_mm=median,
                conditions=conditions,
            )
        )

    return samples, None


def report(samples: Sequence[Sample], images: int) -> None:
    """Print the exact shape of §P0.4."""
    if not samples:
        print("samples: 0 glyph rows across 0 images")
        print("no measurable samples — nothing to report")
        return

    errors = [sample.error_mm for sample in samples]
    within_03 = sum(1 for error in errors if error <= 0.3)
    within_05 = sum(1 for error in errors if error <= 0.5)
    worst = max(samples, key=lambda sample: sample.error_mm)

    by_truth: dict[float, list[float]] = {}
    for sample in samples:
        by_truth.setdefault(sample.truth_mm, []).append(sample.error_mm)
    breakdown = "  |  ".join(
        f"{truth:g}mm MAE {fmt_mm(mean(values))}" for truth, values in sorted(by_truth.items())
    )

    print(f"samples: {len(samples)} glyph rows across {images} images")
    print(
        f"MAE: {fmt_mm(mean(errors))} mm   |  "
        f"within ±0.3mm: {percent(within_03, len(errors)):.1f}%  |  "
        f"within ±0.5mm: {percent(within_05, len(errors)):.1f}%"
    )
    print(f"worst case: {fmt_mm(worst.error_mm)} mm  ({worst.conditions})")
    print(f"by truth height:  {breakdown}")


def gate(samples: Sequence[Sample]) -> str:
    """P0's decision gate, stated rather than left for the reader to apply."""
    if not samples:
        return "no samples — gate not evaluated"

    errors = [sample.error_mm for sample in samples]
    mae = mean(errors)
    hit_rate = percent(sum(1 for error in errors if error <= 0.3), len(errors))

    if mae <= 0.3 and hit_rate >= 90.0:
        return "PASS — proceed as planned; this is the headline slide"
    if mae <= 0.5:
        return (
            "MARGINAL — proceed, but tighten the capture gates (max 15 deg, max 30 cm) and "
            "widen the BORDERLINE band"
        )
    return (
        "FAIL — do not claim automated font checking. Reposition to presence/format checking "
        "plus assisted measurement"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E1 — metrology accuracy against ground truth")
    parser.add_argument("--dir", type=Path, required=True, help="corpus directory")
    parser.add_argument(
        "--truth", type=Path, default=None, help="truth.csv (default: <dir>/truth.csv)"
    )
    parser.add_argument(
        "--marker-mm",
        type=float,
        default=40.0,
        help="printed size of the ArUco tag in the captures (FR-02); per-corpus, never a constant",
    )
    args = parser.parse_args(argv)

    corpus: Path = args.dir
    truth_path: Path = args.truth or corpus / "truth.csv"

    if not corpus.is_dir() or not truth_path.is_file():
        return missing_corpus(corpus, expected=LAYOUT)

    print_header("E1 — metrology", corpus=corpus, extra=[f"marker: {args.marker_mm:g} mm"])

    truths = read_truth(truth_path)
    by_image: dict[str, list[TruthRow]] = {}
    for row in truths:
        by_image.setdefault(row.image, []).append(row)

    samples: list[Sample] = []
    skipped: list[tuple[str, str]] = []
    for name in sorted(by_image):
        path = corpus / name
        if not path.is_file():
            skipped.append((name, "file not found"))
            continue
        measured, reason = measure_image(path, by_image[name], args.marker_mm)
        if reason is not None:
            skipped.append((name, reason))
        samples.extend(measured)

    report(samples, images=len(by_image) - len(skipped))
    print()
    print(f"gate: {gate(samples)}")

    if skipped:
        # Printed, never hidden. A corpus where a tenth of the captures had no detectable marker
        # is telling you something about capture reliability that the MAE cannot.
        print()
        print(f"unmeasurable captures: {len(skipped)} of {len(by_image)}")
        for name, reason in skipped:
            print(f"  {name}: {reason}")

    return 0


if __name__ == "__main__":  # pragma: no cover — module entrypoint
    sys.exit(main())
