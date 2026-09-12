"""Generate the printable A4 scale-reference sheet and its on-screen preview.

FR-02 needs a marker of an exactly known physical size. Two things can silently go wrong, and
both produce millimetres that are confidently wrong rather than missing:

1. **The bit pattern.** The ArUco 4x4_50 dictionary is a fixed codebook, not an algorithm. It is
   read here from OpenCV — the same library the backend's detector uses — so the tag on paper and
   the tag the detector looks for cannot diverge. Never hand-draw a marker.
2. **The print scale.** A printer set to "fit to page" shrinks the tag by a few percent, every
   downstream millimetre is wrong by that factor, and it looks like a code bug for days
   (CLAUDE.md §8). So the sheet carries its own ruler: if 100 mm on the paper does not measure
   100 mm, the print is wrong and nothing else on it can be trusted.

The page is rendered at exactly 15 px/mm, which makes every millimetre an integer number of
pixels and the 40 mm tag exactly 600 px — six cells of 100. At 300 dpi, 40 mm would be 472.44 px
and the cells would not divide evenly, which is how a marker ends up a fraction of a millimetre
off its declared size.

Requires `opencv-contrib-python-headless` and `Pillow`. Run once; the output is committed.

    python3 scripts/make-marker-sheet.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# 15 px/mm: every millimetre is an integer pixel, and 40 mm divides into 6 cells of exactly 100 px.
PX_PER_MM = 15
DPI = PX_PER_MM * 25.4  # 381.0, exact

A4_W_MM, A4_H_MM = 210, 297
W, H = A4_W_MM * PX_PER_MM, A4_H_MM * PX_PER_MM

MARKER_MM = 40.0
MARKER_ID = 0
QUIET_ZONE_MM = 5.0

# ID-1, the card fallback. ISO/IEC 7810.
ID1_W_MM, ID1_H_MM = 85.60, 53.98

REG = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"

INK = 0
PAPER = 255
GREY = 110
WARN = 0

HERE = Path(__file__).resolve().parent.parent
PDF = HERE / "assets" / "marker" / "anupalan-marker-a4.pdf"
PNG = HERE / "assets" / "marker" / "marker-preview.png"


def mm(value: float) -> int:
    """Millimetres to pixels. Rounds to the nearest pixel; at 15 px/mm that is 1/15 mm."""
    return round(value * PX_PER_MM)


def font_for_mm(path: str, cap_mm: float) -> ImageFont.FreeTypeFont:
    """Pick the font size whose rendered cap height is closest to `cap_mm`."""
    target = cap_mm * PX_PER_MM
    lo, hi = 4, 600
    best, best_err = None, 1e9

    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(path, mid)
        box = f.getbbox("0")
        got = box[3] - box[1]
        err = abs(got - target)
        if err < best_err:
            best, best_err = f, err
        if got < target:
            lo = mid + 1
        else:
            hi = mid - 1

    assert best is not None
    return best


def aruco_marker(side_px: int) -> Image.Image:
    """The ArUco 4x4_50 tag, straight from OpenCV's codebook. Never hand-drawn."""
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    array = cv2.aruco.generateImageMarker(dictionary, MARKER_ID, side_px, borderBits=1)
    return Image.fromarray(array).convert("L")


def bit_grid() -> list[list[int]]:
    """The 4x4 payload, for the printed identity line and for the test to pin."""
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    # 6 cells across at 1 px each: border ring plus the 4x4 payload.
    cells = cv2.aruco.generateImageMarker(dictionary, MARKER_ID, 6, borderBits=1)
    return [[int(cells[y][x] > 127) for x in range(1, 5)] for y in range(1, 5)]


img = Image.new("L", (W, H), PAPER)
d = ImageDraw.Draw(img)

h1 = font_for_mm(BOLD, 5.0)
h2 = font_for_mm(BOLD, 3.2)
body = font_for_mm(REG, 2.6)
small = font_for_mm(REG, 2.2)
mono_label = font_for_mm(BOLD, 2.4)

MARGIN_MM = 15.0
y = MARGIN_MM


def text(value: str, y_mm: float, font: ImageFont.FreeTypeFont, *, x_mm: float = MARGIN_MM,
         fill: int = INK, centre: bool = False) -> float:
    """Draw a line and return the y in mm just below it."""
    box = d.textbbox((0, 0), value, font=font)
    x = (W - (box[2] - box[0])) / 2 if centre else mm(x_mm)
    d.text((x - box[0], mm(y_mm) - box[1]), value, font=font, fill=fill)
    return y_mm + (box[3] - box[1]) / PX_PER_MM


# ---------------------------------------------------------------- heading

y = text("Anupalan — scale reference sheet", y, h1)
y = text(
    "The millimetre measurements in every report are derived from this tag's known size.",
    y + 2.5,
    body,
    fill=GREY,
)

# ---------------------------------------------------------------- the warning that matters most

box_top = y + 5
box_h = 21.0
d.rectangle([mm(MARGIN_MM), mm(box_top), W - mm(MARGIN_MM), mm(box_top + box_h)],
            outline=WARN, width=mm(0.6))

inner = box_top + 4.0
inner = text("PRINT AT 100%.  DO NOT USE “FIT TO PAGE” OR “SHRINK TO FIT”.", inner, h2,
             x_mm=MARGIN_MM + 4)
text(
    "A printer that scales the page makes every millimetre in every report wrong by the same",
    inner + 2.6,
    body,
    x_mm=MARGIN_MM + 4,
)
text(
    "factor. Measure the ruler below before you use this sheet.",
    inner + 6.2,
    body,
    x_mm=MARGIN_MM + 4,
)

y = box_top + box_h + 12

# ---------------------------------------------------------------- the tag

marker_px = mm(MARKER_MM)
assert marker_px % 6 == 0, f"marker must divide into 6 cells, got {marker_px} px"

marker = aruco_marker(marker_px)
marker_x = (W - marker_px) // 2
marker_y = mm(y)
img.paste(marker, (marker_x, marker_y))

# Cut guide, outside the quiet zone, so the tag can become a card.
cut_pad = QUIET_ZONE_MM + 3.0
d.rectangle(
    [marker_x - mm(cut_pad), marker_y - mm(cut_pad),
     marker_x + marker_px + mm(cut_pad), marker_y + marker_px + mm(cut_pad)],
    outline=GREY,
    width=max(1, mm(0.2)),
)

# Dimension arrows spanning exactly the tag's edges, placed clear of the quiet zone.
dim_y = marker_y + marker_px + mm(QUIET_ZONE_MM + 6.0)
tick = mm(1.6)
d.line([marker_x, dim_y, marker_x + marker_px, dim_y], fill=INK, width=max(1, mm(0.25)))
for x in (marker_x, marker_x + marker_px):
    d.line([x, dim_y - tick, x, dim_y + tick], fill=INK, width=max(1, mm(0.25)))

label = f"{MARKER_MM:.1f} mm"
lbox = d.textbbox((0, 0), label, font=mono_label)
lw, lh = lbox[2] - lbox[0], lbox[3] - lbox[1]
d.rectangle([(W - lw) / 2 - mm(2), dim_y - lh / 2 - mm(1.5),
             (W + lw) / 2 + mm(2), dim_y + lh / 2 + mm(1.5)], fill=PAPER)
d.text(((W - lw) / 2 - lbox[0], dim_y - lh / 2 - lbox[1]), label, font=mono_label, fill=INK)

y = (dim_y + mm(10)) / PX_PER_MM

# ---------------------------------------------------------------- the scale check

y = text("1 · Check the print scale", y, h2)
y = text(
    "Lay a ruler along the scale below. 100 mm must measure 100 mm, and the tag above must",
    y + 2.6,
    body,
)
y = text("measure 40 mm on every side. If either is off, reprint — do not proceed.", y + 3.6, body)

rule_y = y + 8
rule_x = mm(MARGIN_MM)
rule_len = mm(100)

d.line([rule_x, rule_y := mm(rule_y), rule_x + rule_len, rule_y], fill=INK,
       width=max(1, mm(0.3)))

for i in range(101):
    x = rule_x + mm(i)
    if i % 10 == 0:
        length, width_px = mm(4.5), max(1, mm(0.3))
    elif i % 5 == 0:
        length, width_px = mm(3.0), max(1, mm(0.2))
    else:
        length, width_px = mm(1.8), 1
    d.line([x, rule_y, x, rule_y - length], fill=INK, width=width_px)

    if i % 10 == 0:
        tick_label = str(i)
        tbox = d.textbbox((0, 0), tick_label, font=small)
        d.text((x - (tbox[2] - tbox[0]) / 2 - tbox[0], rule_y + mm(1.5) - tbox[1]),
               tick_label, font=small, fill=INK)

text("mm", rule_y / PX_PER_MM - 4.5, small, x_mm=MARGIN_MM + 101.5, fill=GREY)

y = rule_y / PX_PER_MM + 10

# ---------------------------------------------------------------- the card fallback

y = text("2 · Or use a standard card", y, h2)
y = text(
    "Any ID-1 card — debit, credit, Aadhaar, driving licence — is 85.60 × 53.98 mm by standard.",
    y + 2.6,
    body,
)
y = text(
    "Lay yours on the outline below. If it does not match exactly, it is not ID-1; use the tag.",
    y + 3.6,
    body,
)

card_y = mm(y + 6)
card_x = mm(MARGIN_MM)
card_w, card_h = mm(ID1_W_MM), mm(ID1_H_MM)

# Landscape, and the right way round: a portrait outline would have people measuring the short
# edge against the long one and concluding their perfectly standard card is not ID-1.
assert card_w > card_h, "the ID-1 outline must be landscape"
assert abs(card_w / PX_PER_MM - ID1_W_MM) <= 0.05, f"card width off: {card_w} px"
assert abs(card_h / PX_PER_MM - ID1_H_MM) <= 0.05, f"card height off: {card_h} px"

d.rectangle([card_x, card_y, card_x + card_w, card_y + card_h], outline=INK,
            width=max(1, mm(0.3)))
text(f"{ID1_W_MM:.2f} × {ID1_H_MM:.2f} mm", (card_y + card_h) / PX_PER_MM + 2.5, small,
     x_mm=MARGIN_MM, fill=GREY)

y = (card_y + card_h) / PX_PER_MM + 6

# ---------------------------------------------------------------- capture guidance

# This sheet is what the user is holding while they take the photograph, so the capture rules
# belong on it rather than only in the app.
y = text("3 · Photograph the pack with the reference in frame", y, h2)
y = text(
    "Lay the reference flat against the same face as the label, never on another side of the pack:",
    y + 2.6,
    body,
)
y = text(
    "a reference on a different plane is measured at the wrong scale, and nothing warns you.",
    y + 3.6,
    body,
)
y = text(
    "Keep all four corners in frame and the camera square — past about 25° the shutter is disabled.",
    y + 3.6,
    body,
)

# ---------------------------------------------------------------- footer

grid = bit_grid()
grid_text = " ".join("".join(str(b) for b in row) for row in grid)

FOOTER_H_MM = 11.0
BOTTOM_MARGIN_MM = 6.0

# Anchored to the bottom, but pushed down if the body ran long — and if it cannot fit, that is a
# layout error worth failing on rather than a footer quietly printed over step 3.
footer_top = max(y + 5, A4_H_MM - MARGIN_MM - FOOTER_H_MM)

if footer_top + FOOTER_H_MM > A4_H_MM - BOTTOM_MARGIN_MM:
    raise SystemExit(
        f"the body runs to {y:.1f} mm, leaving no room for the footer above "
        f"{A4_H_MM - BOTTOM_MARGIN_MM:.1f} mm — shorten a step or raise the page budget"
    )

foot = footer_top
foot = text(
    "Keep the tag flat and matte. A curled or glossy marker measures short, and a marker shown "
    "on a screen is never valid —",
    foot,
    small,
    fill=GREY,
)
foot = text(
    "its size is unknown and it is backlit. Print it, measure it, then photograph it with the pack.",
    foot + 3.2,
    small,
    fill=GREY,
)
text(
    f"ArUco 4x4_50 · id {MARKER_ID} · {MARKER_MM:.1f} mm · quiet zone {QUIET_ZONE_MM:.0f} mm · "
    f"payload {grid_text} · rendered at {PX_PER_MM} px/mm",
    foot + 4.5,
    small,
    fill=GREY,
)

# ---------------------------------------------------------------- quiet-zone assertion

# Nothing may be printed within the quiet zone. A stray mark there breaks detection in a way that
# looks like a bad photograph, so it is asserted rather than eyeballed.
ring = QUIET_ZONE_MM
x0, y0 = marker_x - mm(ring), marker_y - mm(ring)
x1, y1 = marker_x + marker_px + mm(ring), marker_y + marker_px + mm(ring)
region = img.crop((x0, y0, x1, y1)).load()

for py in range(y1 - y0):
    for px in range(x1 - x0):
        inside_tag = (
            mm(ring) <= px < mm(ring) + marker_px and mm(ring) <= py < mm(ring) + marker_px
        )
        if not inside_tag and region[px, py] != PAPER:
            raise SystemExit(
                f"quiet zone violated at ({px}, {py}) — something is printed within "
                f"{ring} mm of the tag"
            )

# ---------------------------------------------------------------- detector round trip

# Two separate claims, and it is worth keeping them apart.
#
# The tag is exactly 40 mm on the page **by construction**: 600 px at 15 px/mm, asserted above.
# That is arithmetic, not measurement, and it is the number the backend is told to trust.
#
# What the detector adds is *recognition*: that the bit pattern is a real 4x4_50 id 0 and that
# nothing in the composition broke it. Its corner estimate carries a one-pixel convention
# difference — corner at pixel centre versus pixel boundary — so it reports 599 px, 39.933 mm, on
# this page, while the same PDF rasterised by pdftoppm measures 600.0 px exactly. One pixel here is
# 0.067 mm, or 0.17%, and it is not a defect in the artwork. Do not chase it; the tolerance below
# is sized to allow it and to catch a real rescale, which would be percent-level.
page = np.array(img)
detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
found_corners, found_ids, _ = detector.detectMarkers(page)

if found_ids is None:
    raise SystemExit("the detector found no marker on the composed page")

detected = found_ids.ravel().tolist()
if detected != [MARKER_ID]:
    raise SystemExit(f"expected exactly [{MARKER_ID}] on the page, detector found {detected}")

quad = found_corners[0].reshape(4, 2)
measured_mm = [
    float(np.linalg.norm(quad[i] - quad[(i + 1) % 4])) / PX_PER_MM for i in range(4)
]
worst = max(abs(side - MARKER_MM) for side in measured_mm)

# 0.15 mm is a little over two pixels: loose enough for the corner convention, tight enough that a
# printer-style rescale (millimetres, not pixels) cannot slip through.
if worst > 0.15:
    raise SystemExit(
        f"tag measures {[round(s, 4) for s in measured_mm]} mm, off by {worst:.4f} mm "
        f"from the declared {MARKER_MM} mm"
    )

# ---------------------------------------------------------------- write

PDF.parent.mkdir(parents=True, exist_ok=True)

# Bilevel, so the PDF is a compact fax-style image and the tag's edges stay hard. Greys in the
# body text dither, which is fine on paper and keeps the file small.
img.convert("1").save(PDF, "PDF", resolution=DPI)

# On-screen preview: the tag plus its quiet zone, deliberately small and never to scale.
preview_side = marker_px + 2 * mm(QUIET_ZONE_MM)
preview = img.crop((marker_x - mm(QUIET_ZONE_MM), marker_y - mm(QUIET_ZONE_MM),
                    marker_x - mm(QUIET_ZONE_MM) + preview_side,
                    marker_y - mm(QUIET_ZONE_MM) + preview_side))
preview.resize((480, 480), Image.NEAREST).save(PNG, optimize=True)

pdf_sha = hashlib.sha256(PDF.read_bytes()).hexdigest()[:16]

print(f"wrote {PDF.relative_to(HERE)} ({PDF.stat().st_size // 1024} KB, sha256 {pdf_sha}…)")
print(f"wrote {PNG.relative_to(HERE)} ({PNG.stat().st_size // 1024} KB)")
print(f"page {A4_W_MM}x{A4_H_MM} mm at {PX_PER_MM} px/mm = {W}x{H} px, {DPI:g} dpi")
print(f"tag {MARKER_MM} mm = {marker_px} px = 6 cells of {marker_px // 6} px")
print(f"payload 4x4: {grid_text}")
print(
    f"detector round trip: id {detected[0]}, "
    f"sides {[round(s * PX_PER_MM, 1) for s in measured_mm]} px "
    f"= {[round(s, 3) for s in measured_mm]} mm "
    f"(tag is {marker_px} px = {MARKER_MM} mm by construction)"
)
