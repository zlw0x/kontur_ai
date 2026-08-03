"""The drawings POSTMVP-016's runs need, and nothing else.

Six scenarios are owed and four drawings cover them: scenarios 5 and 6 re-use two
of these with the analysis hand-edited, because what they test is what happens
when the *reading* is wrong, and the only way to be sure a reading is wrong is to
make it wrong.

Each drawing states exactly what its scenario asks about and no more. A blind
pocket drawing that also had a boss on it would answer two questions at once and
neither cleanly — if the run failed, nothing would say which feature the reader
tripped over.

    python scripts/make_scenario_drawings.py .local/drawings

Every dimension here is also written into the module's docstring table below, so a
run's expected numbers come from the drawing rather than from whatever the model
happened to say.

| drawing        | part                                    | what the run asks |
|----------------|-----------------------------------------|-------------------|
| blind-pocket   | 60 x 40 x 12 plate, Ø20 pocket 5 deep   | does the reader say `through: false`? |
| ambiguous      | the same, with the depth note removed   | does the reader say nothing rather than guess? |
| pad            | 60 x 40 x 10 plate, 20 x 20 pad 6 tall  | does `solids` come back 2? |
| bolt-circle    | Ø80 flange 8 thick, six Ø6 on a Ø60 PCD | one hole and a pattern, or six holes? |
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCALE = 8  # pixels per millimetre
MARGIN = 100
INK = (20, 20, 20)
THIN = (110, 110, 110)


def font(size: int) -> ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def centred(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, typeface) -> None:
    box = draw.textbbox((0, 0), text, font=typeface)
    draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2), text,
              fill=INK, font=typeface)


def dimension(draw, x1, y1, x2, y2, text, typeface, above=True) -> None:
    """One dimension line with arrows and a value, the way a drawing states it."""
    draw.line([x1, y1, x2, y2], fill=THIN, width=1)
    for x, y, sign in ((x1, y1, 1), (x2, y2, -1)):
        if y1 == y2:
            draw.polygon([(x, y), (x + 6 * sign, y - 3), (x + 6 * sign, y + 3)], fill=THIN)
        else:
            draw.polygon([(x, y), (x - 3, y + 6 * sign), (x + 3, y + 6 * sign)], fill=THIN)
    if y1 == y2:
        centred(draw, (x1 + x2) / 2, y1 + (-14 if above else 14), text, typeface)
    else:
        centred(draw, x1 - 20, (y1 + y2) / 2, text, typeface)


def blind_pocket(path: Path, *, state_depth: bool) -> None:
    """A plate with a pocket that does not go through.

    The section view is what carries the answer: the pocket stops short of the
    bottom, and a reader that only looked at the plan view would have no way to
    know. `state_depth` writes the depth note; without it the drawing shows a
    pocket whose depth is genuinely not stated, which is scenario 2.
    """
    width, height, thickness, pocket_d, pocket_depth = 60.0, 40.0, 12.0, 20.0, 5.0
    plate_w, plate_h = int(width * SCALE), int(height * SCALE)
    side_h = int(thickness * SCALE)
    image = Image.new("RGB", (plate_w + MARGIN * 2, plate_h + side_h + MARGIN * 3), "white")
    draw = ImageDraw.Draw(image)
    label, title = font(18), font(22)

    left, top = MARGIN, MARGIN
    right, bottom = left + plate_w, top + plate_h
    draw.rectangle([left, top, right, bottom], outline=INK, width=2)

    cx, cy = (left + right) / 2, (top + bottom) / 2
    radius = pocket_d / 2 * SCALE
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=INK, width=2)
    draw.line([cx - radius - 10, cy, cx + radius + 10, cy], fill=THIN, width=1)
    draw.line([cx, cy - radius - 10, cx, cy + radius + 10], fill=THIN, width=1)

    dimension(draw, left, top - 30, right, top - 30, f"{width:.0f}", label)
    dimension(draw, right + 30, top, right + 30, bottom, f"{height:.0f}", label)
    draw.line([cx + radius, cy - radius, cx + 70, cy - 60], fill=INK, width=2)
    centred(draw, cx + 110, cy - 68, f"Ø{pocket_d:.0f}", label)

    # The section, below the plan. The pocket is drawn as a step in the material
    # rather than a gap through it, which is the whole point of the scenario.
    side_top = bottom + MARGIN
    draw.rectangle([left, side_top, right, side_top + side_h], outline=INK, width=2)
    pocket_half = pocket_d / 2 * SCALE
    depth_px = pocket_depth * SCALE
    draw.rectangle([cx - pocket_half, side_top, cx + pocket_half, side_top + depth_px],
                   outline=INK, width=2, fill="white")
    dimension(draw, right + 30, side_top, right + 30, side_top + side_h, f"{thickness:.0f}", label)
    if state_depth:
        dimension(draw, cx + pocket_half + 24, side_top,
                  cx + pocket_half + 24, side_top + depth_px, f"{pocket_depth:.0f}", label)

    centred(draw, image.width / 2, image.height - 34,
            "PLATE WITH POCKET" + ("" if state_depth else "  (DEPTH NOT SHOWN)"), title)
    image.save(path)
    note = f"pocket depth {pocket_depth:.0f}" if state_depth else "pocket depth unstated"
    print(f"wrote {path} — {width:.0f}x{height:.0f}x{thickness:.0f}, "
          f"Ø{pocket_d:.0f} pocket, {note}")


def plan_only(path: Path) -> None:
    """A plate seen from above only, with a circle on it and no section.

    The other kind of ambiguity, and the one `OpeningClaim.through` was actually
    built for. `ambiguous-depth.png` leaves a *number* off the drawing, and the
    reading stage answers that by asking for it — which is better than staying
    silent and is not what nullable `through` is for.

    Here nothing is missing that could be asked for. Every dimension the drawing
    would carry is on it. What is absent is the **view** that would settle whether
    the circle is a hole or a pocket, and no question to a customer recovers it:
    they would have to draw the section. A reader that cannot settle it should say
    nothing, and a claim that says nothing agrees with either.
    """
    width, height, thickness, hole_d = 60.0, 40.0, 12.0, 20.0
    plate_w, plate_h = int(width * SCALE), int(height * SCALE)
    image = Image.new("RGB", (plate_w + MARGIN * 2, plate_h + MARGIN * 2), "white")
    draw = ImageDraw.Draw(image)
    label, title = font(18), font(22)

    left, top = MARGIN, MARGIN
    right, bottom = left + plate_w, top + plate_h
    draw.rectangle([left, top, right, bottom], outline=INK, width=2)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    radius = hole_d / 2 * SCALE
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=INK, width=2)
    draw.line([cx - radius - 10, cy, cx + radius + 10, cy], fill=THIN, width=1)
    draw.line([cx, cy - radius - 10, cx, cy + radius + 10], fill=THIN, width=1)

    dimension(draw, left, top - 30, right, top - 30, f"{width:.0f}", label)
    dimension(draw, right + 30, top, right + 30, bottom, f"{height:.0f}", label)
    draw.line([cx + radius, cy - radius, cx + 70, cy - 60], fill=INK, width=2)
    centred(draw, cx + 110, cy - 68, f"Ø{hole_d:.0f}", label)

    # The thickness as a note rather than a view. A drawing that states it this
    # way is complete about size and silent about depth, which is the point.
    centred(draw, left + 90, bottom + 34, f"PLATE t = {thickness:.0f}", label)

    centred(draw, image.width / 2, image.height - 30, "PLATE — PLAN VIEW ONLY", title)
    image.save(path)
    print(f"wrote {path} — {width:.0f}x{height:.0f}x{thickness:.0f}, "
          f"Ø{hole_d:.0f} circle, no section: through-ness unknowable")


def pad(path: Path) -> None:
    """A plate with a second solid standing on it."""
    width, height, thickness, pad_side, pad_h = 60.0, 40.0, 10.0, 20.0, 6.0
    plate_w, plate_h = int(width * SCALE), int(height * SCALE)
    side_h = int((thickness + pad_h) * SCALE)
    image = Image.new("RGB", (plate_w + MARGIN * 2, plate_h + side_h + MARGIN * 3), "white")
    draw = ImageDraw.Draw(image)
    label, title = font(18), font(22)

    left, top = MARGIN, MARGIN
    right, bottom = left + plate_w, top + plate_h
    draw.rectangle([left, top, right, bottom], outline=INK, width=2)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    half = pad_side / 2 * SCALE
    draw.rectangle([cx - half, cy - half, cx + half, cy + half], outline=INK, width=2)

    dimension(draw, left, top - 30, right, top - 30, f"{width:.0f}", label)
    dimension(draw, right + 30, top, right + 30, bottom, f"{height:.0f}", label)
    dimension(draw, cx - half, cy + half + 26, cx + half, cy + half + 26,
              f"{pad_side:.0f}", label, above=False)

    side_top = bottom + MARGIN
    plate_px = thickness * SCALE
    pad_px = pad_h * SCALE
    draw.rectangle([left, side_top + pad_px, right, side_top + pad_px + plate_px],
                   outline=INK, width=2)
    draw.rectangle([cx - half, side_top, cx + half, side_top + pad_px], outline=INK, width=2)
    dimension(draw, right + 30, side_top + pad_px, right + 30, side_top + pad_px + plate_px,
              f"{thickness:.0f}", label)
    dimension(draw, cx + half + 24, side_top, cx + half + 24, side_top + pad_px,
              f"{pad_h:.0f}", label)

    centred(draw, image.width / 2, image.height - 34, "PLATE WITH PAD", title)
    image.save(path)
    print(f"wrote {path} — {width:.0f}x{height:.0f}x{thickness:.0f} plate, "
          f"{pad_side:.0f}x{pad_side:.0f}x{pad_h:.0f} pad, 2 solids")


def bolt_circle(path: Path) -> None:
    """A flange with six holes evenly spaced on a pitch circle.

    The one drawing where the *count* is the question. Six holes 60 degrees apart
    is expressible as six contours or as one and a pattern, and only the second
    gives the claim a count to disagree with.
    """
    outer_d, thickness, hole_d, pcd, count = 80.0, 8.0, 6.0, 60.0, 6
    size = int(outer_d * SCALE)
    side_h = int(thickness * SCALE)
    image = Image.new("RGB", (size + MARGIN * 2, size + side_h + MARGIN * 3), "white")
    draw = ImageDraw.Draw(image)
    label, title = font(18), font(22)

    cx, cy = MARGIN + size / 2, MARGIN + size / 2
    outer_r = outer_d / 2 * SCALE
    draw.ellipse([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], outline=INK, width=2)

    pcd_r = pcd / 2 * SCALE
    draw.ellipse([cx - pcd_r, cy - pcd_r, cx + pcd_r, cy + pcd_r], outline=THIN, width=1)
    hole_r = hole_d / 2 * SCALE
    for index in range(count):
        angle = math.radians(index * 360 / count)
        hx, hy = cx + pcd_r * math.cos(angle), cy + pcd_r * math.sin(angle)
        draw.ellipse([hx - hole_r, hy - hole_r, hx + hole_r, hy + hole_r], outline=INK, width=2)
        draw.line([hx - hole_r - 8, hy, hx + hole_r + 8, hy], fill=THIN, width=1)
        draw.line([hx, hy - hole_r - 8, hx, hy + hole_r + 8], fill=THIN, width=1)

    dimension(draw, cx - outer_r, cy - outer_r - 34, cx + outer_r, cy - outer_r - 34,
              f"Ø{outer_d:.0f}", label)
    centred(draw, cx + pcd_r + 78, cy - pcd_r - 12, f"Ø{pcd:.0f} PCD", label)
    centred(draw, cx + outer_r + 66, cy + 40, f"{count} × Ø{hole_d:.0f}", label)

    side_top = MARGIN * 2 + size
    draw.rectangle([cx - outer_r, side_top, cx + outer_r, side_top + side_h],
                   outline=INK, width=2)
    dimension(draw, cx + outer_r + 30, side_top, cx + outer_r + 30, side_top + side_h,
              f"{thickness:.0f}", label)

    centred(draw, image.width / 2, image.height - 34, "FLANGE", title)
    image.save(path)
    print(f"wrote {path} — Ø{outer_d:.0f}x{thickness:.0f}, "
          f"{count} x Ø{hole_d:.0f} on Ø{pcd:.0f} PCD")


def main() -> int:
    # These lines print diameters, and "Ø" does not exist in the code page a
    # Windows console falls back to when stdout is a pipe. The drawings are
    # written before that ever matters, so the failure lands after the work is
    # done and looks like the generator broke when nothing did.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".local/drawings")
    target.mkdir(parents=True, exist_ok=True)
    blind_pocket(target / "blind-pocket.png", state_depth=True)
    blind_pocket(target / "ambiguous-depth.png", state_depth=False)
    plan_only(target / "plan-only.png")
    pad(target / "pad.png")
    bolt_circle(target / "bolt-circle.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
