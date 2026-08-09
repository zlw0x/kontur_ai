"""A hundred drawings, each with what it must produce written down beside it.

    python scripts/make_labelled_drawings.py .local/labelled 100

Everything before this milestone was about the service not breaking. This is about
whether it *works*, and there is no other way to find out: a drawing is read by a
model, and the only evidence about how well is a body of drawings whose answers were
known before the model saw them.

Three rules, taken from the golden corpus (POSTMVP-013) because they are what make a
body of cases evidence rather than a large test.

**Every expected number is closed-form from the drawing.** A plate is `w × h × t`; a
hole removes `π r² t`; a boss adds `a × b × c`; a blind pocket removes `π r² d`. None
of it is read back from the engine, so a case cannot be satisfied by the engine
agreeing with itself.

**The generator is dumb on purpose.** It substitutes numbers into drawing shapes and
does no geometry. There is nothing in it that could compensate for a mistake
downstream, and a case is cheap enough that coverage comes from combinations rather
than from drawing a hundred sheets by hand.

**Each drawing states exactly what its family asks about and no more.** A plate that
also had a boss on it would answer two questions at once and neither cleanly.

What the label carries is not only the geometry. It also carries the **dimensions the
drawing states in words**, keyed by meaning, because a clarification question asks for
one of those and the run has to be able to answer it from the drawing rather than from
a guess. How often that lookup fails is itself a measurement — see
`scripts/run_labelled_orders.py`.
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SCALE = 7  # pixels per millimetre
MARGIN = 96
INK = (20, 20, 20)
THIN = (110, 110, 110)


def font(size: int) -> ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


@dataclass
class Label:
    """What this drawing must become, and what it says in words."""

    id: str
    family: str
    #: The overall size of the finished part, in the order the verifier reports it.
    bounding_box: list[float]
    #: Closed form, in mm³.
    volume_mm3: float
    #: Openings that break out the far side — what the mesh's genus must come to.
    through_holes: int
    #: Separate lumps of material a reader would count on the sheet.
    solids: int
    #: Every dimension the sheet states, keyed by meaning rather than by the name a
    #: model happens to choose. A clarification question is answered from this.
    stated: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "bounding_box": [round(value, 4) for value in self.bounding_box],
            "volume_mm3": round(self.volume_mm3, 4),
            "through_holes": self.through_holes,
            "solids": self.solids,
            "stated": {key: round(value, 4) for key, value in self.stated.items()},
        }


# --- drawing primitives ----------------------------------------------------------


def arrow(draw: ImageDraw.ImageDraw, x0: float, y0: float, x1: float, y1: float) -> None:
    draw.line([x0, y0, x1, y1], fill=INK, width=2)
    head = 7
    if abs(y1 - y0) < 1:
        for x, sign in ((x0, 1), (x1, -1)):
            draw.polygon([(x, y0), (x + sign * head, y0 - 4), (x + sign * head, y0 + 4)], fill=INK)
    else:
        for y, sign in ((y0, 1), (y1, -1)):
            draw.polygon([(x0, y), (x0 - 4, y + sign * head), (x0 + 4, y + sign * head)], fill=INK)


def centred(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, typeface) -> None:
    box = draw.textbbox((0, 0), text, font=typeface)
    draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2), text, font=typeface, fill=INK)


def horizontal_dimension(draw, x0, x1, y, text, typeface, tick_from) -> None:
    for x in (x0, x1):
        draw.line([x, tick_from, x, y + 8], fill=THIN, width=1)
    arrow(draw, x0, y, x1, y)
    centred(draw, (x0 + x1) / 2, y - 13, text, typeface)


def vertical_dimension(draw, y0, y1, x, text, typeface, tick_from) -> None:
    for y in (y0, y1):
        draw.line([tick_from, y, x - 8, y], fill=THIN, width=1)
    arrow(draw, x, y0, x, y1)
    centred(draw, x - 16, (y0 + y1) / 2, text, typeface)


def number(value: float) -> str:
    """A dimension as a drawing writes it: no trailing zero on a whole millimetre."""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


# --- the families ------------------------------------------------------------------


def plate(case: str, rng: random.Random) -> tuple[Image.Image, Label]:
    """A rectangular plate with round through-holes on the centreline.

    The simplest thing the service claims to do, and the one every other family is a
    variation of. Volume is `w·h·t − n·π·r²·t`.
    """
    width = rng.choice([50, 60, 70, 80, 90, 100, 120])
    height = rng.choice([30, 36, 40, 50, 60])
    thickness = rng.choice([5, 6, 8, 10, 12])
    holes = rng.choice([1, 2, 2, 3, 4])
    diameter = rng.choice([4, 5, 6, 8])
    margin = rng.choice([12, 15, 18, 20])
    # Evenly spaced between the two end holes, which is how a sheet dimensions a row.
    pitch = (width - 2 * margin) / (holes - 1) if holes > 1 else 0.0

    image, draw, geometry = _sheet(width, height, thickness)
    left, top, right, bottom, label_font = geometry
    centre_y = (top + bottom) / 2
    radius = diameter / 2 * SCALE
    centres = [left + (margin + index * pitch) * SCALE for index in range(holes)]
    for cx in centres:
        draw.ellipse([cx - radius, centre_y - radius, cx + radius, centre_y + radius],
                     outline=INK, width=2)
        draw.line([cx - radius - 7, centre_y, cx + radius + 7, centre_y], fill=THIN, width=1)
        draw.line([cx, centre_y - radius - 7, cx, centre_y + radius + 7], fill=THIN, width=1)

    horizontal_dimension(draw, left, right, bottom + 34, number(width), label_font, bottom + 6)
    vertical_dimension(draw, top, bottom, left - 40, number(height), label_font, left - 6)
    horizontal_dimension(draw, left, centres[0], top - 30, number(margin), label_font, top - 6)
    if holes > 1:
        horizontal_dimension(
            draw, centres[0], centres[-1], top - 62,
            f"{holes - 1}x{number(pitch)}={number(width - 2 * margin)}" if holes > 2
            else number(pitch),
            label_font, top - 36,
        )
    draw.text((right + 14, centre_y - 30), f"{holes}x Ø{number(diameter)}",
              font=label_font, fill=INK)
    draw.text((right + 14, centre_y - 8), "сквозн.",
              font=label_font, fill=INK)

    volume = width * height * thickness - holes * math.pi * (diameter / 2) ** 2 * thickness
    return image, Label(
        id=case, family="plate",
        bounding_box=[float(width), float(height), float(thickness)],
        volume_mm3=volume, through_holes=holes, solids=1,
        stated={
            "length": width, "width": height, "thickness": thickness,
            "hole_diameter": diameter, "hole_radius": diameter / 2,
            "hole_from_left": margin, "hole_from_bottom": height / 2,
            "hole_pitch": pitch, "hole_count": holes,
        },
    )


def flange(case: str, rng: random.Random) -> tuple[Image.Image, Label]:
    """A round flange with a central bore and holes on a pitch circle.

    Volume is `π(R² − r²)t − k·π·ρ²·t`. The bolt circle is the interesting part: nine
    earlier runs showed the reading counts the holes correctly and compiles them as
    separate contours rather than as a pattern, so this family is where that gets
    counted rather than remembered.
    """
    outer = rng.choice([60, 70, 80, 90, 100])
    bore = rng.choice([16, 20, 25, 30])
    thickness = rng.choice([6, 8, 10, 12])
    holes = rng.choice([3, 4, 6])
    hole_diameter = rng.choice([5, 6, 8])
    pitch_circle = rng.choice([outer - 16, outer - 20])

    size = int(outer * SCALE) + MARGIN * 2
    image = Image.new("RGB", (size, size + int(thickness * SCALE) + MARGIN), "white")
    draw = ImageDraw.Draw(image)
    label_font = font(17)
    cx = cy = MARGIN + outer * SCALE / 2
    for diameter, width_, colour in ((outer, 3, INK), (bore, 2, INK)):
        r = diameter / 2 * SCALE
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=width_)
    pcd_r = pitch_circle / 2 * SCALE
    draw.ellipse([cx - pcd_r, cy - pcd_r, cx + pcd_r, cy + pcd_r], outline=THIN, width=1)
    for index in range(holes):
        angle = 2 * math.pi * index / holes - math.pi / 2
        hx, hy = cx + pcd_r * math.cos(angle), cy + pcd_r * math.sin(angle)
        r = hole_diameter / 2 * SCALE
        draw.ellipse([hx - r, hy - r, hx + r, hy + r], outline=INK, width=2)

    draw.text((cx + outer * SCALE / 2 + 12, cy - 60),
              f"Ø{number(outer)}", font=label_font, fill=INK)
    draw.text((cx + outer * SCALE / 2 + 12, cy - 36),
              f"Ø{number(bore)}", font=label_font, fill=INK)
    draw.text((cx + outer * SCALE / 2 + 12, cy - 12),
              f"{holes}x Ø{number(hole_diameter)}", font=label_font, fill=INK)
    draw.text((cx + outer * SCALE / 2 + 12, cy + 12),
              f"на Ø{number(pitch_circle)}", font=label_font, fill=INK)

    side_top = int(cy + outer * SCALE / 2) + 56
    side_h = int(thickness * SCALE)
    draw.rectangle([MARGIN, side_top, MARGIN + int(outer * SCALE), side_top + side_h],
                   outline=INK, width=2)
    vertical_dimension(draw, side_top, side_top + side_h, MARGIN - 40,
                       number(thickness), label_font, MARGIN - 6)

    volume = (
        math.pi * ((outer / 2) ** 2 - (bore / 2) ** 2) * thickness
        - holes * math.pi * (hole_diameter / 2) ** 2 * thickness
    )
    return image, Label(
        id=case, family="flange",
        bounding_box=[float(outer), float(outer), float(thickness)],
        volume_mm3=volume,
        # The bore counts: it goes through as well.
        through_holes=holes + 1, solids=1,
        stated={
            "outer_diameter": outer, "outer_radius": outer / 2,
            "bore_diameter": bore, "bore_radius": bore / 2,
            "thickness": thickness, "hole_diameter": hole_diameter,
            "hole_radius": hole_diameter / 2,
            "pitch_circle_diameter": pitch_circle, "pitch_circle_radius": pitch_circle / 2,
            "hole_count": holes,
        },
    )


def pad(case: str, rng: random.Random) -> tuple[Image.Image, Label]:
    """A plate with a rectangular boss standing on it — two lumps of material.

    `solids: 2` is the whole point: it is the one claim field that a plate cannot
    exercise, and the bounding box grows in Z by the boss rather than by the plate.
    """
    width = rng.choice([60, 70, 80, 90])
    height = rng.choice([40, 50, 60])
    thickness = rng.choice([8, 10, 12])
    pad_w = rng.choice([20, 24, 30])
    pad_h = rng.choice([16, 20, 24])
    pad_t = rng.choice([5, 6, 8, 10])

    image, draw, geometry = _sheet(width, height, thickness + pad_t)
    left, top, right, bottom, label_font = geometry
    cx, cy = (left + right) / 2, (top + bottom) / 2
    half_w, half_h = pad_w * SCALE / 2, pad_h * SCALE / 2
    draw.rectangle([cx - half_w, cy - half_h, cx + half_w, cy + half_h], outline=INK, width=2)

    horizontal_dimension(draw, left, right, bottom + 34, number(width), label_font, bottom + 6)
    vertical_dimension(draw, top, bottom, left - 40, number(height), label_font, left - 6)
    horizontal_dimension(draw, cx - half_w, cx + half_w, top - 30, number(pad_w),
                         label_font, top - 6)
    draw.text((right + 14, cy - 30), f"{number(pad_w)}x{number(pad_h)}",
              font=label_font, fill=INK)
    draw.text((right + 14, cy - 6),
              f"бобышка h={number(pad_t)}",
              font=label_font, fill=INK)
    draw.text((right + 14, cy + 18),
              f"плита s={number(thickness)}",
              font=label_font, fill=INK)

    volume = width * height * thickness + pad_w * pad_h * pad_t
    return image, Label(
        id=case, family="pad",
        bounding_box=[float(width), float(height), float(thickness + pad_t)],
        volume_mm3=volume, through_holes=0, solids=2,
        stated={
            "length": width, "width": height, "thickness": thickness,
            "pad_length": pad_w, "pad_width": pad_h, "pad_height": pad_t,
            "total_height": thickness + pad_t,
        },
    )


def pocket(case: str, rng: random.Random) -> tuple[Image.Image, Label]:
    """A plate with a round pocket that stops in the material.

    The family that exercises `through: false`. A misread depth is otherwise a
    document that is valid, builds, and measures exactly what it declares — including
    the hole count it wrote to match — so the only thing that catches it is the number
    on the sheet.
    """
    width = rng.choice([50, 60, 70, 80])
    height = rng.choice([40, 50, 60])
    thickness = rng.choice([10, 12, 15, 16])
    diameter = rng.choice([16, 20, 25])
    depth = rng.choice([4, 5, 6, 8])
    depth = min(depth, thickness - 4)

    image, draw, geometry = _sheet(width, height, thickness)
    left, top, right, bottom, label_font = geometry
    cx, cy = (left + right) / 2, (top + bottom) / 2
    r = diameter / 2 * SCALE
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, width=2)
    draw.line([cx - r - 8, cy, cx + r + 8, cy], fill=THIN, width=1)
    draw.line([cx, cy - r - 8, cx, cy + r + 8], fill=THIN, width=1)

    horizontal_dimension(draw, left, right, bottom + 34, number(width), label_font, bottom + 6)
    vertical_dimension(draw, top, bottom, left - 40, number(height), label_font, left - 6)
    draw.text((right + 14, cy - 30), f"Ø{number(diameter)}", font=label_font, fill=INK)
    # The depth, stated in words, and the note that it does not break through.
    draw.text((right + 14, cy - 6), f"глуб. {number(depth)}",
              font=label_font, fill=INK)
    draw.text((right + 14, cy + 18),
              "не сквозн.",
              font=label_font, fill=INK)
    draw.text((left, bottom + 58), f"s={number(thickness)}", font=label_font, fill=INK)

    volume = width * height * thickness - math.pi * (diameter / 2) ** 2 * depth
    return image, Label(
        id=case, family="pocket",
        bounding_box=[float(width), float(height), float(thickness)],
        # Nothing goes through: the genus of the solid is 0.
        volume_mm3=volume, through_holes=0, solids=1,
        stated={
            "length": width, "width": height, "thickness": thickness,
            "pocket_diameter": diameter, "pocket_radius": diameter / 2,
            "pocket_depth": depth,
        },
    )


def _sheet(width: float, height: float, tall: float):
    """A front view and a side view on one sheet, with the plate already drawn."""
    plate_w, plate_h = int(width * SCALE), int(height * SCALE)
    side_h = max(int(tall * SCALE), 12)
    image = Image.new(
        "RGB",
        (plate_w + MARGIN * 2 + 150, plate_h + side_h + MARGIN * 3),
        "white",
    )
    draw = ImageDraw.Draw(image)
    left, top = MARGIN, MARGIN
    right, bottom = left + plate_w, top + plate_h
    draw.rectangle([left, top, right, bottom], outline=INK, width=3)
    side_top = bottom + 74
    draw.rectangle([left, side_top, right, side_top + side_h], outline=INK, width=2)
    label_font = font(17)
    vertical_dimension(draw, side_top, side_top + side_h, left - 40, number(tall),
                       label_font, left - 6)
    return image, draw, (left, top, right, bottom, label_font)


FAMILIES = {"plate": plate, "flange": flange, "pad": pad, "pocket": pocket}


def main(argv: list[str]) -> int:
    target = Path(argv[1] if len(argv) > 1 else ".local/labelled")
    count = int(argv[2]) if len(argv) > 2 else 100
    # Seeded, so the hundredth run of this generator produces the hundred drawings the
    # first one did. A corpus that changes under you cannot be compared with itself.
    rng = random.Random(int(argv[3]) if len(argv) > 3 else 20260809)
    target.mkdir(parents=True, exist_ok=True)

    names = list(FAMILIES)
    labels = []
    for index in range(count):
        family = names[index % len(names)]
        case = f"{family}-{index:03d}"
        image, label = FAMILIES[family](case, rng)
        image.save(target / f"{case}.png")
        labels.append(label.as_dict())

    (target / "labels.json").write_text(
        json.dumps({"schema_version": "1.0", "cases": labels}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    for label in labels:
        counts[label["family"]] = counts.get(label["family"], 0) + 1
    print(f"{len(labels)} drawings in {target}")
    for family, total in sorted(counts.items()):
        print(f"  {family:8} {total}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main(sys.argv))
