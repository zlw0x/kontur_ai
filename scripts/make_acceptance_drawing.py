"""Generate the reference drawing used by the acceptance run.

The MVP accepts a rectangular plate with circular through-holes, dimensioned in
millimetres. Drawing it here rather than checking in a photograph keeps the
acceptance input reproducible: the same script always yields the same bytes, so
a failed run can be repeated against exactly the same input.

    python scripts/make_acceptance_drawing.py out.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Part: 60 x 30 x 8 mm plate, two 5 mm diameter through-holes on the long axis.
WIDTH_MM, HEIGHT_MM, DEPTH_MM = 60.0, 30.0, 8.0
HOLE_DIAMETER_MM = 5.0
HOLE_OFFSET_MM = 15.0

SCALE = 8  # pixels per millimetre
MARGIN = 90
INK = (20, 20, 20)
THIN = (110, 110, 110)


def font(size: int) -> ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "acceptance-plate.png")

    plate_w, plate_h = int(WIDTH_MM * SCALE), int(HEIGHT_MM * SCALE)
    side_h = int(DEPTH_MM * SCALE)
    canvas_w = plate_w + MARGIN * 2
    canvas_h = plate_h + side_h + MARGIN * 3

    image = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(image)
    label = font(18)
    title = font(22)

    left, top = MARGIN, MARGIN
    right, bottom = left + plate_w, top + plate_h

    # --- front view -------------------------------------------------------
    draw.rectangle([left, top, right, bottom], outline=INK, width=3)

    hole_r = HOLE_DIAMETER_MM / 2 * SCALE
    centre_y = top + plate_h / 2
    for offset in (HOLE_OFFSET_MM, WIDTH_MM - HOLE_OFFSET_MM):
        cx = left + offset * SCALE
        draw.ellipse([cx - hole_r, centre_y - hole_r, cx + hole_r, centre_y + hole_r],
                     outline=INK, width=3)
        draw.line([cx - hole_r - 8, centre_y, cx + hole_r + 8, centre_y], fill=THIN, width=1)
        draw.line([cx, centre_y - hole_r - 8, cx, centre_y + hole_r + 8], fill=THIN, width=1)

    # centre line of the plate
    draw.line([left - 12, centre_y, right + 12, centre_y], fill=THIN, width=1)

    # --- width dimension, below the front view ----------------------------
    dim_y = bottom + 34
    draw.line([left, bottom + 6, left, dim_y + 8], fill=THIN, width=1)
    draw.line([right, bottom + 6, right, dim_y + 8], fill=THIN, width=1)
    arrow(draw, left, dim_y, right, dim_y)
    text_centered(draw, (left + right) / 2, dim_y - 20, "60", label)

    # --- height dimension, left of the front view -------------------------
    dim_x = left - 40
    draw.line([left - 6, top, dim_x - 8, top], fill=THIN, width=1)
    draw.line([left - 6, bottom, dim_x - 8, bottom], fill=THIN, width=1)
    arrow(draw, dim_x, top, dim_x, bottom)
    text_centered(draw, dim_x - 18, (top + bottom) / 2, "30", label)

    # --- hole spacing -----------------------------------------------------
    pitch_y = top - 34
    first_x = left + HOLE_OFFSET_MM * SCALE
    last_x = left + (WIDTH_MM - HOLE_OFFSET_MM) * SCALE
    draw.line([first_x, top - 6, first_x, pitch_y - 8], fill=THIN, width=1)
    draw.line([last_x, top - 6, last_x, pitch_y - 8], fill=THIN, width=1)
    arrow(draw, first_x, pitch_y, last_x, pitch_y)
    text_centered(draw, (first_x + last_x) / 2, pitch_y - 20, "30", label)

    # hole callout
    draw.line([last_x + hole_r, centre_y - hole_r, last_x + 60, centre_y - 52], fill=INK, width=2)
    draw.text((last_x + 62, centre_y - 66), "2x Ø5 THRU", font=label, fill=INK)

    # --- side view (thickness) -------------------------------------------
    side_top = bottom + MARGIN
    draw.rectangle([left, side_top, right, side_top + side_h], outline=INK, width=3)
    side_dim_x = left - 40
    draw.line([left - 6, side_top, side_dim_x - 8, side_top], fill=THIN, width=1)
    draw.line([left - 6, side_top + side_h, side_dim_x - 8, side_top + side_h], fill=THIN, width=1)
    arrow(draw, side_dim_x, side_top, side_dim_x, side_top + side_h)
    text_centered(draw, side_dim_x - 18, side_top + side_h / 2, "8", label)

    draw.text((left, canvas_h - 34), "PLATE  —  ALL DIMENSIONS IN MM", font=title, fill=INK)

    image.save(target, format="PNG")
    print(f"wrote {target} ({target.stat().st_size} bytes) "
          f"{WIDTH_MM}x{HEIGHT_MM}x{DEPTH_MM} mm, 2 x d{HOLE_DIAMETER_MM} through")
    return 0


def arrow(draw: ImageDraw.ImageDraw, x0: float, y0: float, x1: float, y1: float) -> None:
    draw.line([x0, y0, x1, y1], fill=INK, width=2)
    head = 7
    if y0 == y1:
        for x, direction in ((x0, 1), (x1, -1)):
            draw.polygon(
                [(x, y0), (x + direction * head, y0 - 4), (x + direction * head, y0 + 4)], fill=INK
            )
    else:
        for y, direction in ((y0, 1), (y1, -1)):
            draw.polygon(
                [(x0, y), (x0 - 4, y + direction * head), (x0 + 4, y + direction * head)], fill=INK
            )


def text_centered(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, font_) -> None:
    box = draw.textbbox((0, 0), text, font=font_)
    draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2), text, font=font_, fill=INK)


if __name__ == "__main__":
    raise SystemExit(main())
