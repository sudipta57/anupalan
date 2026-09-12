"""Generate the rectified sample label and its bounding boxes from one source.

The image is rendered at exactly PX_PER_MM = 20, the same scale the vision pipeline rectifies
to, so a glyph measured at 92 px really is 4.60 mm. Boxes and cap heights are emitted alongside
the PNG, which is the point: hand-authoring coordinates against an image someone else drew is
how overlays end up misaligned.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PX_PER_MM = 20
W_MM, H_MM = 70, 100
W, H = W_MM * PX_PER_MM, H_MM * PX_PER_MM

REG = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"

INK = (26, 26, 26)
PAPER = (250, 248, 243)
ACCENT = (140, 30, 30)


def cap_px(font: ImageFont.FreeTypeFont) -> int:
    """True cap height in px, measured off a rendered digit rather than font metrics."""
    box = font.getbbox("0")
    return box[3] - box[1]


def font_for_cap_mm(path: str, cap_mm: float) -> tuple[ImageFont.FreeTypeFont, float]:
    """Pick the font size whose rendered cap height is closest to `cap_mm`."""
    target = cap_mm * PX_PER_MM
    lo, hi = 4, 400
    best, best_err = None, 1e9
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(path, mid)
        got = cap_px(f)
        err = abs(got - target)
        if err < best_err:
            best, best_err = f, err
        if got < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return best, cap_px(best) / PX_PER_MM


img = Image.new("RGB", (W, H), PAPER)
d = ImageDraw.Draw(img)

# Pack border, inset 3 mm
d.rectangle([3 * PX_PER_MM, 3 * PX_PER_MM, W - 3 * PX_PER_MM, H - 3 * PX_PER_MM],
            outline=(205, 198, 186), width=3)

regions: dict[str, dict] = {}


def line(key: str, text: str, y_mm: float, cap_mm: float, *, bold=False, colour=INK,
         x_mm: float = 6.0, centre=False, record=True):
    font, actual_cap = font_for_cap_mm(BOLD if bold else REG, cap_mm)
    box = d.textbbox((0, 0), text, font=font)
    w = box[2] - box[0]
    x = (W - w) / 2 if centre else x_mm * PX_PER_MM
    y = y_mm * PX_PER_MM
    d.text((x - box[0], y - box[1]), text, font=font, fill=colour)
    drawn = d.textbbox((x - box[0], y - box[1]), text, font=font)
    if record:
        pad = 4
        regions[key] = {
            "text": text,
            "capHeightMm": round(actual_cap, 2),
            "box": {
                "x": int(drawn[0]) - pad,
                "y": int(drawn[1]) - pad,
                "width": int(drawn[2] - drawn[0]) + pad * 2,
                "height": int(drawn[3] - drawn[1]) + pad * 2,
            },
        }
    return drawn


line("brand", "SAMPOORNA", 8, 7.0, bold=True, centre=True, colour=ACCENT)
line("common_name", "Whole Wheat Atta", 20, 3.2, bold=True, centre=True)
line("tagline", "100% Chakki Fresh", 26.5, 2.0, centre=True, colour=(120, 116, 108), record=False)

d.line([6 * PX_PER_MM, 33 * PX_PER_MM, (W_MM - 6) * PX_PER_MM, 33 * PX_PER_MM],
       fill=(215, 208, 196), width=2)

# Net quantity — 1 kg is above 500 g, so Table-I requires 4.0 mm. Drawn at 4.6 mm: a clean PASS.
line("net_quantity", "Net Wt. 1 kg", 38, 4.6, bold=True)

# A badge inside the clear space around the quantity declaration — this is what makes the
# Rule 9(1) proviso finding BORDERLINE rather than a comfortable PASS.
bx0, by0 = int(46.5 * PX_PER_MM), int(37.5 * PX_PER_MM)
bx1, by1 = int(64 * PX_PER_MM), int(43.5 * PX_PER_MM)
d.rounded_rectangle([bx0, by0, bx1, by1], radius=6, outline=ACCENT, width=2)
badge_font, _ = font_for_cap_mm(BOLD, 1.8)
d.text((bx0 + 12, by0 + 14), "BEST QUALITY", font=badge_font, fill=ACCENT)
regions["qty_clear_space"] = {
    "text": "clear space around net quantity",
    "capHeightMm": None,
    "box": {"x": bx0 - 4, "y": by0 - 4, "width": bx1 - bx0 + 8, "height": by1 - by0 + 8},
}

# MRP without the inclusive-of-all-taxes wording — a deliberate FAIL on LM-MRP-INCLUSIVE-WORDING.
line("mrp", "MRP ₹ 249.00", 48, 3.4, bold=True)
line("mfg_month_year", "MFG: 03/2026", 55, 2.4)
line("manufacturer_name", "Mfd by: Annapurna Foods Pvt Ltd", 61, 1.8)
line("manufacturer_address", "Plot 14, MIDC Industrial Area, Nashik,", 65, 1.5)
line("manufacturer_address_2", "Maharashtra 422010, India", 68, 1.5, record=False)
line("consumer_care", "Consumer care: Ms R Iyer, 1800-123-4567", 73, 1.5)

# Fine print at 0.9 mm — below the 1.0 mm floor in Rule 9(3). A deliberate FAIL.
line("fine_print", "Batch AT-2603-11  ·  Store in a cool, dry place", 80, 0.9)
line("fssai", "FSSAI Lic. No. 10012043000123", 84, 0.9, record=False)

HERE = Path(__file__).resolve().parent.parent
PNG = HERE / "assets" / "fixtures" / "rectified-label.png"
TS = HERE / "src" / "api" / "mock" / "fixtures" / "label.ts"

PNG.parent.mkdir(parents=True, exist_ok=True)
img.save(PNG, optimize=True)

header = '''/**
 * Geometry of the sample rectified label.
 *
 * GENERATED — do not edit by hand. Regenerate both this file and the PNG it describes with:
 *
 *     python3 scripts/make-sample-label.py
 *
 * Image and coordinates come from one run, because hand-authoring boxes against an image
 * someone else drew is precisely how FR-05's overlay ends up misaligned.
 *
 * The image is rendered at exactly 20 px/mm — the scale the vision pipeline rectifies to — so a
 * cap height of 92 px really is 4.60 mm. The measurements in the fixtures are therefore
 * arithmetically true of the picture on screen, not decorative.
 */

import type { BBox } from \'@/domain\';

export const LABEL_IMAGE = require(\'@/assets/fixtures/rectified-label.png\') as number;

'''

body = [header]
body.append(f"export const LABEL_WIDTH_PX = {W};\n")
body.append(f"export const LABEL_HEIGHT_PX = {H};\n\n")
body.append("/** Pixels per millimetre. Matches the backend PX_PER_MM; never written at a call site. */\n")
body.append(f"export const LABEL_PX_PER_MM = {PX_PER_MM};\n\n")
body.append("export interface LabelRegion {\n")
body.append("  /** The text as it appears on the pack. */\n  text: string;\n")
body.append("  /** Measured cap height in millimetres, or null where the region is not a text run. */\n")
body.append("  capHeightMm: number | null;\n  box: BBox;\n}\n\n")
body.append("export const LABEL_REGIONS = {\n")
for key, r in regions.items():
    cap = "null" if r["capHeightMm"] is None else r["capHeightMm"]
    b = r["box"]
    text = r["text"].replace("\\", "\\\\").replace("\'", "\\\'")
    body.append(f"  {key}: {{\n    text: \'{text}\',\n    capHeightMm: {cap},\n")
    body.append(f"    box: {{ x: {b['x']}, y: {b['y']}, width: {b['width']}, height: {b['height']} }},\n  }},\n")
body.append("} as const satisfies Record<string, LabelRegion>;\n\n")
body.append("export type LabelRegionKey = keyof typeof LABEL_REGIONS;\n")

TS.parent.mkdir(parents=True, exist_ok=True)
TS.write_text("".join(body))

print(f"wrote {PNG.relative_to(HERE)} ({PNG.stat().st_size // 1024} KB)")
print(f"wrote {TS.relative_to(HERE)} ({len(regions)} regions)")
