"""Regenerate the end-to-end label fixture and its matching OCR dump.

    cd backend && .venv/Scripts/python.exe tests/fixtures/generate_label_fixture.py

Produces two files that **must stay consistent with each other**:

* ``images/label_250g_printed.png`` — a synthetic label carrying a real 40 mm ArUco marker;
* ``ocr/label_250g_printed.json`` — the OCR dump the stub engine replays for it.

The consistency is the whole point. The pipeline runs OCR on the *rectified* image and hands the
resulting word boxes to metrology, which crops them and measures the glyphs inside. A dump whose
polygons were invented would send metrology to an empty region, and the end-to-end test would
quietly measure nothing while still passing every assertion that did not look at millimetres.

So the polygons here are computed, not guessed: each string's box in source coordinates is
projected through the same homography ``rectify`` produces, which is exactly where the text ends
up in the image the pipeline measures.

Text heights are chosen so the label exercises a mix of verdicts rather than passing everything.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from app.services.vision.marker import detect_marker
from app.services.vision.rectify import rectify

HERE = Path(__file__).parent
MARKER_MM = 40.0
SOURCE_PX_PER_MM = 8
CANVAS = (700, 900)  # height, width

FONT = cv2.FONT_HERSHEY_SIMPLEX
CAP_HEIGHT_AT_SCALE_1 = 22.0
"""Approximate cap height in pixels of HERSHEY_SIMPLEX at fontScale 1.0."""

# (text, x, baseline_y, cap height in mm, stroke thickness, language)
LINES = [
    ("Kalyani Foods Pvt Ltd", 400, 80, 3.0, 2, "en"),
    ("12 GT Road, Kalyani, Nadia", 400, 115, 2.2, 1, "en"),
    ("West Bengal 741235", 400, 145, 2.2, 1, "en"),
    ("Roasted Chana", 60, 430, 5.0, 3, "en"),
    ("Net Qty: 250 g", 60, 490, 3.5, 2, "en"),
    ("MRP Rs. 120.00", 60, 540, 3.0, 2, "en"),
    ("(inclusive of all taxes)", 60, 570, 2.0, 1, "en"),
    ("Mfg: 03/2026", 60, 610, 2.5, 2, "en"),
    ("Consumer Care: 1800110011", 60, 650, 2.2, 1, "en"),
    ("care@kalyanifoods.example", 60, 680, 2.0, 1, "en"),
]


def build() -> None:
    height, width = CANVAS
    image = np.full((height, width), 245, dtype=np.uint8)

    side = int(MARKER_MM * SOURCE_PX_PER_MM)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    image[40 : 40 + side, 40 : 40 + side] = cv2.aruco.generateImageMarker(
        dictionary, 0, side
    )

    boxes: list[tuple[str, str, tuple[int, int, int, int]]] = []
    for text, x, baseline_y, mm, thickness, language in LINES:
        scale = (mm * SOURCE_PX_PER_MM) / CAP_HEIGHT_AT_SCALE_1
        cv2.putText(image, text, (x, baseline_y), FONT, scale, 0, thickness, cv2.LINE_AA)

        (text_width, text_height), descender = cv2.getTextSize(text, FONT, scale, thickness)
        boxes.append(
            (text, language, (x, baseline_y - text_height, text_width, text_height + descender))
        )

    image_path = HERE / "images" / "label_250g_printed.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(image_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 9])

    # Project each source box into the rectified plane — where the pipeline actually measures.
    corners = detect_marker(image)
    if corners is None:
        raise SystemExit("marker not detected in the generated fixture; the fixture is broken")
    rectified = rectify(image, corners, marker_mm=MARKER_MM)

    dump = []
    for text, language, (x, y, box_width, box_height) in boxes:
        source_corners = np.array(
            [
                [[x, y]],
                [[x + box_width, y]],
                [[x + box_width, y + box_height]],
                [[x, y + box_height]],
            ],
            dtype=np.float32,
        )
        warped = cv2.perspectiveTransform(source_corners, rectified.homography).reshape(4, 2)
        dump.append(
            {
                "text": text,
                "polygon": [[round(float(px), 1), round(float(py), 1)] for px, py in warped],
                "confidence": 0.95,
                "language": language,
            }
        )

    ocr_path = HERE / "ocr" / "label_250g_printed.json"
    ocr_path.parent.mkdir(parents=True, exist_ok=True)
    ocr_path.write_text(
        json.dumps(dump, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"wrote {image_path} ({image_path.stat().st_size / 1024:.1f} KB)")
    print(f"wrote {ocr_path} ({len(dump)} words, polygons in rectified coordinates)")


if __name__ == "__main__":
    build()
