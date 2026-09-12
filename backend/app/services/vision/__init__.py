"""Vision pipeline — marker detection, metric rectification, OCR, glyph metrology.

Implements, in docs/01-architecture.md §5 order:

* **TRD FR-21 Rectification** — detect the ArUco marker, compute the homography, warp to
  ``PX_PER_MM`` (``marker.py``, ``rectify.py``). Accept: a printed 10.00 mm bar measures
  10.00 ± 0.25 mm across 20 captures at ≤ 25° and 10-40 cm.
* **TRD FR-22 OCR** — PaddleOCR PP-OCRv4 behind an ``OCREngine`` interface
  (``detect_and_recognise(image) -> list[Word]``), with a second implementation proving the
  interface holds (``ocr.py``).
* **TRD FR-23 Glyph metrology** — numeral cap-height in mm, per-glyph width/height ratio and
  an uncertainty band from blur, tilt and px/mm (``metrology.py``). Accept: within ±0.3 mm of
  caliper truth for ≥ 90% of the E1 set.

Non-negotiables that apply here (CLAUDE.md §3):

* Millimetres require the marker. No marker means metric rules return ``NOT_ASSESSABLE`` —
  never estimate, infer or guess a physical size.
* ``PX_PER_MM`` is imported from ``app.config``. Never write ``20`` at a call site.
* OCR bounding boxes are **not** glyph heights — they include ascenders, descenders and
  padding. Glyph measurement goes through connected components on the rectified image, never
  through OCR polygons.
* Planar homography under-measures on curved packs: detect high curvature and downgrade metric
  rules to ``NOT_ASSESSABLE`` rather than reporting a confident wrong number.

Modules planned: ``marker.py``, ``rectify.py``, ``ocr.py``, ``metrology.py``, ``quality.py``.
Not implemented yet — P0 spike first, then P2.3.
"""
