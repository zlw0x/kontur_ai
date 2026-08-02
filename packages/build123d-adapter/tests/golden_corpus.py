"""The golden corpus: documents whose answers are arithmetic, not memories.

POSTMVP-013. Every earlier milestone was accepted on one fixture and a handful of
refusals, which is enough to show an operation works and not enough to promote it out
of `experimental`. This is the body of evidence: every operation the engine declares,
built at several sizes, with what it must measure derived from the drawing rather than
recorded from a previous run.

Three rules make it a corpus rather than a large test.

*Every expected number is closed-form.* A plate is `w × h × t`; a hole removes
`π r² t`; a regular n-gon of circumradius R has area `½ n R² sin(2π/n)`; a slot is
`π r² + 2 r L`; a partial revolve removes the fraction of a turn it did not sweep. None
of it is read back from the engine, so a case cannot be satisfied by the engine agreeing
with itself — the argument ADR-018 makes about expectations, applied to the corpus that
checks them.

*Cases are generated, and the generator is dumb on purpose.* It substitutes numbers into
document shapes. It does no geometry, so there is nothing in it that could compensate for
a mistake in the engine, and a case is cheap enough that coverage comes from combinations
rather than from hand-writing files.

*A negative case names the code it must fail with.* "Refused" is not a result. A document
that crosses its own axis must fail with `REVOLVE_PROFILE_CROSSES_AXIS` and not with
something the kernel threw on the way past, because the repair loop reacts to the code.

The hand-written fixtures under `tests/fixtures/cad-ir/` stay where they are and keep
their own acceptance records: they are the parts whose numbers came off KOMPAS or off a
drawing, and they are the reason this generator can be trusted to be dumb.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from cad_ir.canonical import CAD_IR_VERSION

CAD_IR = {"schema": "cad-ai/cad-ir", "schema_version": CAD_IR_VERSION}


@dataclass(frozen=True)
class Case:
    """One document, and what a drawing says it must be."""

    id: str
    document: dict[str, Any]
    #: The volume the arithmetic above gives, in mm³.
    volume_mm3: float
    #: Where that number comes from, in words. Not decoration: a figure whose source
    #: cannot be named is a figure somebody typed to make a test pass.
    arithmetic: str
    bodies: int = 1


@dataclass(frozen=True)
class Refusal:
    """One document that must be refused, and the code it must be refused with."""

    id: str
    document: dict[str, Any]
    code: str
    why: str
    #: Refused by reading the document rather than by the engine.
    by_contract: bool = False


# ---------------------------------------------------------------------------
# Document shapes
# ---------------------------------------------------------------------------


def length(pid: str, value: float) -> dict[str, Any]:
    return {"id": pid, "type": "length", "unit": "mm", "value": value, "status": "confirmed"}


def sketch(name: str, outer: dict, inner: list[dict] | None = None, plane: dict | None = None,
           construction: list[dict] | None = None) -> dict[str, Any]:
    return {
        "id": f"sketch.{name}",
        "plane": plane or {"on": "base", "plane": "XY"},
        "outer": outer,
        "inner": inner or [],
        "construction": construction or [],
        "constraints": [],
        "dimensions": [],
    }


def rectangle(width: float, height: float, centre=(0.0, 0.0)) -> dict[str, Any]:
    return {"type": "rectangle", "center": list(centre), "width": width, "height": height,
            "rotation_deg": 0.0}


def circle(radius: float, centre=(0.0, 0.0)) -> dict[str, Any]:
    return {"type": "circle", "center": list(centre), "radius": radius}


def slot(radius: float, span: float, centre=(0.0, 0.0)) -> dict[str, Any]:
    return {"type": "slot",
            "start": [centre[0] - span / 2, centre[1]],
            "end": [centre[0] + span / 2, centre[1]],
            "radius": radius}


def polygon(sides: int, circumradius: float, centre=(0.0, 0.0)) -> dict[str, Any]:
    return {"type": "regular_polygon", "center": list(centre), "sides": sides,
            "circumradius": circumradius, "rotation_deg": 0.0}


def extrude(fid: str, body: str | None, thickness: float, outer: dict,
            inner: list[dict] | None = None, depends: list[str] | None = None,
            new_body: bool = False, plane: dict | None = None) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "sketch": sketch(fid.split(".")[-1], outer, inner, plane),
        "direction": "+Z",
        "distance": thickness,
    }
    if new_body:
        inputs["new_body"] = True
    return {
        "id": fid, "type": "solid.extrude", "enabled": True,
        "depends_on": depends or [],
        "produces": [{"id": body, "kind": "solid_body"}] if body else [],
        "inputs": inputs,
    }


def cut(fid: str, outer: dict, depends: list[str], source: str = "body.main",
        distance: float | None = None) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "sketch": sketch(fid.split(".")[-1], outer),
        "direction": "+Z",
        "source_body": {"result": source},
    }
    if distance is None:
        inputs["through_all"] = True
    else:
        inputs["distance"] = distance
    return {"id": fid, "type": "cut.extrude", "enabled": True, "depends_on": depends,
            "produces": [], "inputs": inputs}


def document(name: str, features: list[dict], size: tuple[float, float, float],
             bodies: int = 1, holes: int | None = None,
             parameters: list[dict] | None = None,
             extra: list[dict] | None = None) -> dict[str, Any]:
    expectations: list[dict[str, Any]] = [
        {"id": "inv.box", "type": "bounding_box",
         "size_mm": {"x": size[0], "y": size[1], "z": size[2]}, "tolerance_mm": 0.05},
        {"id": "inv.bodies", "type": "body_count", "value": bodies},
    ]
    if holes is not None:
        expectations.append({"id": "inv.holes", "type": "through_hole_count", "value": holes})
    expectations.extend(extra or [])
    return {
        **CAD_IR,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": name},
        "parameters": parameters or [],
        "features": features,
        "expectations": expectations,
        "metadata": {"generator": "golden-corpus", "generator_version": CAD_IR_VERSION},
    }


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


def _plates() -> list[Case]:
    """A plain plate at three sizes. The simplest thing the engine builds."""
    cases = []
    for width, height, thickness in ((40.0, 20.0, 10.0), (120.0, 80.0, 6.0), (15.0, 15.0, 3.0)):
        cases.append(Case(
            id=f"plate-{width:g}x{height:g}x{thickness:g}",
            document=document(
                "plate",
                [extrude("feature.plate", "body.main", thickness, rectangle(width, height))],
                (width, height, thickness), holes=0),
            volume_mm3=width * height * thickness,
            arithmetic=f"{width:g} × {height:g} × {thickness:g}",
        ))
    return cases


def _discs() -> list[Case]:
    cases = []
    for radius, thickness in ((20.0, 8.0), (5.0, 2.0)):
        cases.append(Case(
            id=f"disc-r{radius:g}",
            document=document(
                "disc",
                [extrude("feature.disc", "body.main", thickness, circle(radius))],
                (2 * radius, 2 * radius, thickness), holes=0),
            volume_mm3=math.pi * radius**2 * thickness,
            arithmetic=f"π × {radius:g}² × {thickness:g}",
        ))
    return cases


def _polygons() -> list[Case]:
    """A regular n-gon has area ½ n R² sin(2π/n)."""
    cases = []
    for sides, radius in ((3, 20.0), (6, 15.0), (12, 10.0)):
        area = 0.5 * sides * radius**2 * math.sin(2 * math.pi / sides)
        thickness = 5.0
        # The bounding box, from the vertices the contract says the polygon has: the
        # first on +X and the rest every 360/n after it. Arithmetic, like the area —
        # a box read back off the built solid would be the engine checking itself.
        angles = [2 * math.pi * index / sides for index in range(sides)]
        xs = [radius * math.cos(angle) for angle in angles]
        ys = [radius * math.sin(angle) for angle in angles]
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        cases.append(Case(
            id=f"polygon-{sides}",
            document=document(
                "polygon",
                [extrude("feature.hub", "body.main", thickness, polygon(sides, radius))],
                (width, height, thickness), holes=0),
            volume_mm3=area * thickness,
            arithmetic=f"½ × {sides} × {radius:g}² × sin(2π/{sides}) × {thickness:g}",
        ))
    return cases


def _slots() -> list[Case]:
    """A slot is a rectangle with a half-disc at each end: π r² + 2 r L."""
    cases = []
    for radius, span in ((5.0, 30.0), (8.0, 8.0)):
        thickness = 4.0
        area = math.pi * radius**2 + 2 * radius * span
        cases.append(Case(
            id=f"slot-r{radius:g}-l{span:g}",
            document=document(
                "slot-plate",
                [extrude("feature.slot", "body.main", thickness, slot(radius, span))],
                (span + 2 * radius, 2 * radius, thickness), holes=0),
            volume_mm3=area * thickness,
            arithmetic=f"(π × {radius:g}² + 2 × {radius:g} × {span:g}) × {thickness:g}",
        ))
    return cases


def _paths() -> list[Case]:
    """A stadium written segment by segment: two lines and two end caps.

    The same outline the `slot` shape expands into, spelled out the long way, which is
    what a drawing agent produces when the outline is not one of the named shapes. Its
    area is the same arithmetic: π r² + 2 r L.
    """
    cases = []
    for radius, span, thickness in ((10.0, 40.0, 6.0), (6.0, 12.0, 3.0)):
        half = span / 2
        path = {
            "type": "path",
            "segments": [
                {"type": "line", "start": [-half, -radius], "end": [half, -radius]},
                {"type": "arc", "start": [half, -radius], "end": [half, radius],
                 "center": [half, 0.0], "sweep": "ccw"},
                {"type": "line", "start": [half, radius], "end": [-half, radius]},
                {"type": "arc", "start": [-half, radius], "end": [-half, -radius],
                 "center": [-half, 0.0], "sweep": "ccw"},
            ],
        }
        area = math.pi * radius**2 + 2 * radius * span
        cases.append(Case(
            id=f"path-stadium-r{radius:g}-l{span:g}",
            document=document(
                "stadium",
                [extrude("feature.plate", "body.main", thickness, path)],
                (span + 2 * radius, 2 * radius, thickness), holes=0),
            volume_mm3=area * thickness,
            arithmetic=f"(π × {radius:g}² + 2 × {radius:g} × {span:g}) × {thickness:g}, "
                       "spelled out as two lines and two arcs",
        ))
    return cases


def _holes() -> list[Case]:
    """Round holes, as islands and as cuts, one to four of them."""
    cases = []
    width, height, thickness, radius = 80.0, 40.0, 8.0, 4.0
    for count in (1, 2, 4):
        centres = [(-30.0 + index * 20.0, 0.0) for index in range(count)]
        islands = [circle(radius, centre) for centre in centres]
        cases.append(Case(
            id=f"islands-{count}",
            document=document(
                "island-plate",
                [extrude("feature.plate", "body.main", thickness,
                         rectangle(width, height), islands)],
                (width, height, thickness), holes=count),
            volume_mm3=width * height * thickness - count * math.pi * radius**2 * thickness,
            arithmetic=f"{width:g} × {height:g} × {thickness:g} − {count} × π × {radius:g}² × {thickness:g}",
        ))
        cuts = [
            cut(f"feature.hole{index}", circle(radius, centre), ["feature.plate"])
            for index, centre in enumerate(centres)
        ]
        cases.append(Case(
            id=f"cuts-{count}",
            document=document(
                "cut-plate",
                [extrude("feature.plate", "body.main", thickness, rectangle(width, height)), *cuts],
                (width, height, thickness), holes=count),
            volume_mm3=width * height * thickness - count * math.pi * radius**2 * thickness,
            arithmetic="the same plate, the same holes, cut instead of drawn as islands",
        ))
    return cases


def _blind_hole() -> list[Case]:
    """A hole that does not go through is not a handle, so the genus is 0."""
    width, height, thickness, radius, depth = 60.0, 40.0, 10.0, 6.0, 4.0
    return [Case(
        id="blind-hole",
        document=document(
            "blind",
            [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
             cut("feature.pocket", circle(radius), ["feature.plate"], distance=depth)],
            (width, height, thickness), holes=0),
        volume_mm3=width * height * thickness - math.pi * radius**2 * depth,
        arithmetic=f"{width:g} × {height:g} × {thickness:g} − π × {radius:g}² × {depth:g}",
    )]


def _cut_shapes() -> list[Case]:
    """An opening of every contour kind the sketch offers."""
    width, height, thickness = 80.0, 50.0, 6.0
    plate = width * height * thickness
    cases = []
    rectangular = 20.0 * 10.0
    cases.append(Case(
        id="cut-rectangular",
        document=document(
            "rect-cut",
            [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
             cut("feature.window", rectangle(20.0, 10.0), ["feature.plate"])],
            (width, height, thickness), holes=1),
        volume_mm3=plate - rectangular * thickness,
        arithmetic=f"plate − 20 × 10 × {thickness:g}",
    ))
    slot_area = math.pi * 4.0**2 + 2 * 4.0 * 20.0
    cases.append(Case(
        id="cut-slot",
        document=document(
            "slot-cut",
            [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
             cut("feature.slot", slot(4.0, 20.0), ["feature.plate"])],
            (width, height, thickness), holes=1),
        volume_mm3=plate - slot_area * thickness,
        arithmetic=f"plate − (π × 4² + 2 × 4 × 20) × {thickness:g}",
    ))
    hexagon = 0.5 * 6 * 8.0**2 * math.sin(2 * math.pi / 6)
    cases.append(Case(
        id="cut-polygonal",
        document=document(
            "hex-cut",
            [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
             cut("feature.hex", polygon(6, 8.0), ["feature.plate"])],
            (width, height, thickness), holes=1),
        volume_mm3=plate - hexagon * thickness,
        arithmetic=f"plate − ½ × 6 × 8² × sin(π/3) × {thickness:g}",
    ))
    return cases


def _bosses() -> list[Case]:
    """A boss on the plate: one body, two additive features."""
    width, height, thickness, radius = 60.0, 40.0, 8.0, 10.0
    cases = []
    for boss_height in (5.0, 20.0):
        cases.append(Case(
            id=f"boss-{boss_height:g}",
            document=document(
                "boss",
                [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
                 extrude("feature.boss", None, boss_height, circle(radius),
                         depends=["feature.plate"],
                         plane={"on": "datum", "plane": {"result": "plane.top"}})],
                (width, height, thickness + boss_height), holes=0,
                parameters=[length("thickness", thickness)]),
            volume_mm3=width * height * thickness + math.pi * radius**2 * boss_height,
            arithmetic=f"plate + π × {radius:g}² × {boss_height:g}",
        ))
        # The datum plane the boss sits on has to exist before it.
        cases[-1].document["features"].insert(1, {
            "id": "feature.top", "type": "datum.plane.offset", "enabled": True,
            "depends_on": ["feature.plate"],
            "produces": [{"id": "plane.top", "kind": "plane"}],
            "inputs": {"base": "XY", "offset_mm": {"parameter": "thickness"}, "flip": False},
        })
        cases[-1].document["features"][2]["depends_on"] = ["feature.plate", "feature.top"]
    return cases


def _face_selector() -> list[Case]:
    """A boss sketched on the face a selector names, rather than on a datum plane."""
    width, height, thickness, radius, boss = 60.0, 40.0, 8.0, 8.0, 6.0
    plane = {
        "on": "face",
        "face": {
            "id": "selector.top", "kind": "face", "from_result": "body.main",
            "cardinality": "exactly_one",
            "where": {
                "surface_type": "planar",
                "normal": {"parallel_to": "axis.z", "direction": "positive"},
                "position": {"extreme_along": "axis.z", "extreme": "maximum"},
            },
        },
    }
    return [Case(
        id="boss-on-selected-face",
        document=document(
            "selected-face",
            [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
             extrude("feature.pad", None, boss, circle(radius),
                     depends=["feature.plate"], plane=plane)],
            (width, height, thickness + boss), holes=0),
        volume_mm3=width * height * thickness + math.pi * radius**2 * boss,
        arithmetic=f"plate + π × {radius:g}² × {boss:g}, the boss on the face the selector names",
    )]


def _revolves() -> list[Case]:
    """A revolved annulus is π(R² − r²)h, and a partial one is that fraction of a turn."""
    outer, inner, height = 18.0, 8.0, 20.0
    full = math.pi * (outer**2 - inner**2) * height
    axis = {"type": "line", "id": "axis.centre", "start": [0.0, 0.0], "end": [0.0, height]}
    cases = []
    for angle in (360.0, 180.0, 90.0):
        profile = {"type": "rectangle", "center": [(outer + inner) / 2, height / 2],
                   "width": outer - inner, "height": height, "rotation_deg": 0.0}
        feature = {
            "id": "feature.ring", "type": "solid.revolve", "enabled": True,
            "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
            "inputs": {
                "sketch": sketch("section", profile, plane={"on": "base", "plane": "XZ"},
                                 construction=[axis]),
                "axis": {"kind": "construction_line", "entity": "axis.centre"},
                "angle_deg": angle,
            },
        }
        size = (2 * outer, 2 * outer, height) if angle == 360.0 else (
            (2 * outer, outer, height) if angle == 180.0 else (outer, outer, height)
        )
        cases.append(Case(
            id=f"revolve-{angle:g}",
            document=document("ring", [feature], size, holes=1 if angle == 360.0 else 0),
            volume_mm3=full * angle / 360.0,
            arithmetic=f"π({outer:g}² − {inner:g}²) × {height:g} × {angle:g}/360",
        ))
    return cases


def _fillets() -> list[Case]:
    """A corner fillet removes (1 − π/4) r² per corner, per unit of thickness."""
    width, height, thickness = 70.0, 50.0, 10.0
    cases = []
    for radius in (3.0, 8.0):
        blend = {
            "id": "feature.corners", "type": "feature.fillet", "enabled": True,
            "depends_on": ["feature.plate"], "produces": [],
            "inputs": {
                "edges": {
                    "id": "selector.corners", "kind": "edge", "from_result": "body.main",
                    "cardinality": {"type": "exactly_n", "value": 4},
                    "where": {"curve_type": "line", "convexity": "convex",
                              "direction_parallel_to": "axis.z"},
                },
                "radius": radius,
            },
        }
        cases.append(Case(
            id=f"fillet-r{radius:g}",
            document=document(
                "rounded",
                [extrude("feature.plate", "body.main", thickness, rectangle(width, height)), blend],
                (width, height, thickness), holes=0,
                extra=[{"id": "inv.rounds", "type": "surface_face_count",
                        "surface": "cylindrical",
                        "radius_mm": {"value": radius, "tolerance": 0.001}, "value": 4}]),
            volume_mm3=width * height * thickness
            - 4 * (1 - math.pi / 4) * radius**2 * thickness,
            arithmetic=f"plate − 4 × (1 − π/4) × {radius:g}² × {thickness:g}",
        ))
    return cases


def _chamfers() -> list[Case]:
    """A chamfer of `d` on a bore's rim removes ∫π(r² − R²) over the depth."""
    width, height, thickness, bore = 60.0, 60.0, 12.0, 6.0
    cases = []
    for distance in (2.0, 4.0):
        chamfer = {
            "id": "feature.deburr", "type": "feature.chamfer", "enabled": True,
            "depends_on": ["feature.bore"], "produces": [],
            "inputs": {
                "edges": {
                    "id": "selector.rim", "kind": "edge", "from_result": "body.main",
                    "cardinality": "exactly_one",
                    "where": {"curve_type": "circle",
                              "radius_mm": {"value": bore, "tolerance": 0.001},
                              "position": {"extreme_along": "axis.z", "extreme": "maximum"}},
                },
                "distance": distance,
            },
        }
        # A 45° cone from radius `bore` to `bore + d` over height `d`:
        # ∫₀^d π((bore + s)² − bore²) ds = π(bore d² + d³/3).
        removed = math.pi * (bore * distance**2 + distance**3 / 3)
        cases.append(Case(
            id=f"chamfer-{distance:g}",
            document=document(
                "chamfered-bore",
                [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
                 cut("feature.bore", circle(bore), ["feature.plate"]), chamfer],
                (width, height, thickness), holes=1),
            volume_mm3=width * height * thickness - math.pi * bore**2 * thickness - removed,
            arithmetic=f"plate − π × {bore:g}² × {thickness:g} − π({bore:g}·{distance:g}² + {distance:g}³/3)",
        ))
    return cases


def _patterns() -> list[Case]:
    """A pattern of n holes removes n of them, however the document says it."""
    width, height, thickness, radius = 100.0, 60.0, 8.0, 4.0
    plate = width * height * thickness
    hole = math.pi * radius**2 * thickness
    cases = []
    for count in (2, 5):
        cases.append(Case(
            id=f"pattern-linear-{count}",
            document=document(
                "linear-pattern",
                [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
                 cut("feature.hole", circle(radius, (-40.0, 0.0)), ["feature.plate"]),
                 {"id": "feature.row", "type": "feature.pattern", "enabled": True,
                  "depends_on": ["feature.hole"], "produces": [],
                  "inputs": {"of": "feature.hole",
                             "pattern": {"kind": "linear", "direction": "+X",
                                         "spacing_mm": 20.0, "count": count},
                             "skip": []}}],
                (width, height, thickness), holes=count),
            volume_mm3=plate - count * hole,
            arithmetic=f"plate − {count} × π × {radius:g}² × {thickness:g}",
        ))
    for count in (3, 6):
        cases.append(Case(
            id=f"pattern-circular-{count}",
            document=document(
                "circular-pattern",
                [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
                 cut("feature.hole", circle(radius, (25.0, 0.0)), ["feature.plate"]),
                 {"id": "feature.ring", "type": "feature.pattern", "enabled": True,
                  "depends_on": ["feature.hole"], "produces": [],
                  "inputs": {"of": "feature.hole",
                             "pattern": {"kind": "circular", "axis": "axis.z",
                                         "through": [0.0, 0.0, 0.0],
                                         "step_deg": 360.0 / count, "count": count},
                             "skip": []}}],
                (width, height, thickness), holes=count),
            volume_mm3=plate - count * hole,
            arithmetic=f"plate − {count} × π × {radius:g}² × {thickness:g}, {360 / count:g}° apart",
        ))
    return cases


def _grid_and_mirror() -> list[Case]:
    width, height, thickness, radius = 100.0, 60.0, 8.0, 4.0
    plate = width * height * thickness
    hole = math.pi * radius**2 * thickness
    grid = document(
        "grid",
        [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
         cut("feature.hole", circle(radius, (-40.0, -20.0)), ["feature.plate"]),
         {"id": "feature.row", "type": "feature.pattern", "enabled": True,
          "depends_on": ["feature.hole"], "produces": [],
          "inputs": {"of": "feature.hole",
                     "pattern": {"kind": "linear", "direction": "+X",
                                 "spacing_mm": 80.0, "count": 2}, "skip": []}},
         {"id": "feature.grid", "type": "feature.pattern", "enabled": True,
          "depends_on": ["feature.row"], "produces": [],
          "inputs": {"of": "feature.row",
                     "pattern": {"kind": "linear", "direction": "+Y",
                                 "spacing_mm": 40.0, "count": 2}, "skip": []}}],
        (width, height, thickness), holes=4)
    mirror = document(
        "mirror",
        [extrude("feature.plate", "body.main", thickness, rectangle(width, height)),
         cut("feature.hole", circle(radius, (30.0, 0.0)), ["feature.plate"]),
         {"id": "feature.mirror", "type": "feature.pattern", "enabled": True,
          "depends_on": ["feature.hole"], "produces": [],
          "inputs": {"of": "feature.hole", "pattern": {"kind": "mirror", "plane": "YZ"},
                     "skip": []}}],
        (width, height, thickness), holes=2)
    return [
        Case(id="pattern-grid", document=grid, volume_mm3=plate - 4 * hole,
             arithmetic="plate − 4 holes, from two counts of two"),
        Case(id="pattern-mirror", document=mirror, volume_mm3=plate - 2 * hole,
             arithmetic="plate − 2 holes, one drawn and one reflected"),
    ]


def _shells() -> list[Case]:
    """A wall of t keeps the outside and takes out the inside.

    Four numbers, all of them subtractions of one box or cylinder from another:

    - open at the top, inward: `W·H·T − (W−2t)(H−2t)(T−t)`, the cavity being the part
      minus one wall on four sides and one on the floor;
    - open at both ends: `W·H·T − (W−2t)(H−2t)·T`, no floor to subtract;
    - a cup: `πR²h − π(R−t)²(h−t)`;
    - outward: `(W+2t)(H+2t)(T+t) − W·H·T`, the wall grown outside the part, the part
      itself becoming the cavity — which is why the original volume is what is
      *removed* rather than what is kept.
    """

    def opening(sid: str, where: dict, cardinality: Any = "exactly_one") -> dict[str, Any]:
        return {"id": sid, "kind": "face", "from_result": "body.main",
                "cardinality": cardinality, "where": where}

    def hollow(faces: dict, thickness: float, direction: str = "inward",
               depends: str = "feature.block") -> dict[str, Any]:
        return {"id": "feature.hollow", "type": "feature.shell", "enabled": True,
                "depends_on": [depends], "produces": [],
                "inputs": {"faces": faces, "thickness": thickness, "direction": direction}}

    # By where the face looks, not by where it reaches: an "extreme along z" predicate
    # matches the four sides of a box too, because their upper edges touch the top.
    top = opening("selector.top", {"surface_type": "planar",
                                   "normal": {"parallel_to": "axis.z",
                                              "direction": "positive"}})
    ends = opening("selector.ends",
                   {"surface_type": "planar", "normal": {"parallel_to": "axis.z"}},
                   {"type": "exactly_n", "value": 2})

    width, height, depth = 100.0, 60.0, 40.0
    cases: list[Case] = []
    for wall in (2.0, 5.0):
        cases.append(Case(
            id=f"shell-box-t{wall:g}",
            document=document(
                "enclosure",
                [extrude("feature.block", "body.main", depth, rectangle(width, height)),
                 hollow(top, wall)],
                (width, height, depth), holes=0),
            volume_mm3=width * height * depth
            - (width - 2 * wall) * (height - 2 * wall) * (depth - wall),
            arithmetic=(
                f"{width:g}·{height:g}·{depth:g} − "
                f"({width:g}−2·{wall:g})({height:g}−2·{wall:g})({depth:g}−{wall:g})"
            ),
        ))

    wall = 3.0
    cases.append(Case(
        id="shell-open-at-both-ends",
        document=document(
            "duct",
            [extrude("feature.block", "body.main", depth, rectangle(width, height)),
             hollow(ends, wall)],
            (width, height, depth),
            # A tube is genus 1: the cavity runs from one open end to the other, which
            # is a through hole to anything counting them off the finished solid.
            holes=1),
        volume_mm3=width * height * depth
        - (width - 2 * wall) * (height - 2 * wall) * depth,
        arithmetic=f"{width:g}·{height:g}·{depth:g} − 94·54·{depth:g}",
    ))

    radius, tall, wall = 20.0, 50.0, 2.0
    cases.append(Case(
        id="shell-cup",
        document=document(
            "cup",
            [extrude("feature.block", "body.main", tall, circle(radius)),
             hollow(top, wall)],
            (2 * radius, 2 * radius, tall), holes=0),
        volume_mm3=math.pi * radius**2 * tall - math.pi * (radius - wall) ** 2 * (tall - wall),
        arithmetic=f"π·{radius:g}²·{tall:g} − π·{radius - wall:g}²·{tall - wall:g}",
    ))

    wall = 3.0
    cases.append(Case(
        id="shell-outward",
        document=document(
            "sleeve",
            [extrude("feature.block", "body.main", depth, rectangle(width, height)),
             hollow(top, wall, direction="outward")],
            # The wall is added outside, so the part is 2t wider and t taller: the open
            # face gets no wall, which is the whole difference between the two
            # directions and the reason the bounding box states it.
            (width + 2 * wall, height + 2 * wall, depth + wall), holes=0,
            extra=[{"id": "inv.walls", "type": "surface_face_count",
                    "surface": "planar", "value": 11}]),
        volume_mm3=(width + 2 * wall) * (height + 2 * wall) * (depth + wall)
        - width * height * depth,
        arithmetic=f"106·66·43 − {width:g}·{height:g}·{depth:g}",
    ))
    return cases


def _bodies_and_booleans() -> list[Case]:
    """Two bodies, and each of the three booleans between them."""
    thickness = 10.0
    first, second = 40.0, 40.0
    cases: list[Case] = []

    def two(op: str | None, offset: float, span: float, keep: bool = False) -> dict[str, Any]:
        """Two blocks, and one boolean between them.

        `span` is stated per case rather than derived, because each operation leaves a
        different extent: a union spans both blocks, a subtraction spans what is left of
        the first, and an intersection spans only the overlap.
        """
        features = [
            extrude("feature.first", "body.first", thickness, rectangle(first, 40.0)),
            extrude("feature.second", "body.second", thickness,
                    rectangle(second, 40.0, (offset, 0.0)),
                    depends=["feature.first"], new_body=True),
        ]
        if op:
            features.append({
                "id": "feature.combine", "type": "feature.boolean", "enabled": True,
                "depends_on": ["feature.first", "feature.second"], "produces": [],
                "inputs": {"op": op, "target": {"result": "body.first"},
                           "tools": [{"result": "body.second"}], "keep_tools": keep},
            })
        return document("two-bodies", features, (span, 40.0, thickness),
                        bodies=2 if (op is None or keep) else 1, holes=0)

    overlap = 20.0
    cases.append(Case(
        id="two-separate-bodies",
        document=two(None, 100.0, span=140.0),
        volume_mm3=2 * first * 40.0 * thickness,
        arithmetic="two blocks, never combined", bodies=2))
    cases.append(Case(
        id="boolean-union",
        document=two("union", overlap, span=first + overlap),
        volume_mm3=(first + overlap) * 40.0 * thickness,
        arithmetic=f"a {first:g} block and one offset {overlap:g}, fused"))
    cases.append(Case(
        id="boolean-subtract",
        document=two("subtract", overlap, span=first - overlap),
        volume_mm3=(first - overlap) * 40.0 * thickness,
        arithmetic=f"the overlap {overlap:g} × 40 × {thickness:g} removed"))
    cases.append(Case(
        id="boolean-intersect",
        document=two("intersect", overlap, span=first - overlap),
        volume_mm3=(first - overlap) * 40.0 * thickness,
        arithmetic="only what both blocks occupy"))
    return cases


def kept_tool() -> Case:
    """Subtract and keep the tool: right geometry, and a mesh that is not one surface.

    Not in `positives()`, and the reason is the finding it produced. A kept tool that
    overlapped its target always leaves two bodies sharing the face the cut was made on
    — that is what "keep the tool" means — and two solids touching face-to-face are not
    a single closed surface. The manifold check refuses it, correctly: 5 edges with four
    incident triangles instead of two.

    So it is exercised by a test of its own (`test_corpus.py`), which asserts the solid is
    right and the verification refuses it. Putting it among the positives would have meant
    weakening a check to accommodate a part nobody should be delivered.
    """
    thickness, first, overlap = 10.0, 40.0, 20.0
    features = [
        extrude("feature.first", "body.first", thickness, rectangle(first, 40.0)),
        extrude("feature.second", "body.second", thickness,
                rectangle(first, 40.0, (overlap, 0.0)),
                depends=["feature.first"], new_body=True),
        {"id": "feature.combine", "type": "feature.boolean", "enabled": True,
         "depends_on": ["feature.first", "feature.second"], "produces": [],
         "inputs": {"op": "subtract", "target": {"result": "body.first"},
                    "tools": [{"result": "body.second"}], "keep_tools": True}},
    ]
    return Case(
        id="boolean-subtract-keeping-the-tool",
        document=document("kept-tool", features, (first + overlap, 40.0, thickness),
                          bodies=2, holes=0),
        volume_mm3=(first - overlap) * 40.0 * thickness + first * 40.0 * thickness,
        arithmetic="the cut block plus the tool the document keeps",
        bodies=2,
    )


def positives() -> list[Case]:
    """Every positive case, in a stable order."""
    return [
        *_plates(), *_discs(), *_polygons(), *_slots(), *_paths(), *_holes(),
        *_blind_hole(),
        *_cut_shapes(), *_bosses(), *_face_selector(), *_revolves(), *_fillets(),
        *_chamfers(), *_patterns(), *_grid_and_mirror(), *_shells(),
        *_bodies_and_booleans(),
    ]


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def negatives() -> list[Refusal]:
    """Documents that must be refused, each with the code it must carry."""
    thickness = 10.0
    plate = extrude("feature.plate", "body.main", thickness, rectangle(60.0, 40.0))

    def with_features(features: list[dict], **kwargs) -> dict[str, Any]:
        return document("negative", features, (60.0, 40.0, thickness), **kwargs)

    open_contour = {
        "type": "path",
        "segments": [
            {"type": "line", "start": [0.0, 0.0], "end": [20.0, 0.0]},
            {"type": "line", "start": [20.0, 0.0], "end": [20.0, 10.0]},
            {"type": "line", "start": [20.0, 10.0], "end": [1.0, 10.0]},
        ],
    }
    crossing = {
        "type": "path",
        "segments": [
            {"type": "line", "start": [0.0, 0.0], "end": [20.0, 20.0]},
            {"type": "line", "start": [20.0, 20.0], "end": [20.0, 0.0]},
            {"type": "line", "start": [20.0, 0.0], "end": [0.0, 20.0]},
            {"type": "line", "start": [0.0, 20.0], "end": [0.0, 0.0]},
        ],
    }
    axis = {"type": "line", "id": "axis.centre", "start": [0.0, 0.0], "end": [0.0, 20.0]}
    straddling = {"type": "rectangle", "center": [0.0, 10.0], "width": 20.0, "height": 20.0,
                  "rotation_deg": 0.0}

    return [
        Refusal(
            id="open-contour",
            document=with_features(
                [extrude("feature.plate", "body.main", thickness, open_contour)], holes=0),
            code="SKETCH_NOT_CLOSED",
            why="a profile whose last segment does not return to the first",
        ),
        Refusal(
            id="self-crossing-contour",
            document=with_features(
                [extrude("feature.plate", "body.main", thickness, crossing)], holes=0),
            code="SKETCH_INVALID",
            why="a bow-tie outline, which the kernel reports as a face of no area",
        ),
        Refusal(
            id="island-outside-the-outline",
            document=with_features(
                [extrude("feature.plate", "body.main", thickness,
                         rectangle(60.0, 40.0), [circle(4.0, (100.0, 0.0))])], holes=0),
            code="SKETCH_ISLAND_OUTSIDE_PROFILE",
            why="a hole beside the part rather than in it",
        ),
        Refusal(
            id="zero-thickness",
            document=with_features(
                [extrude("feature.plate", "body.main", 0.0, rectangle(60.0, 40.0))], holes=0),
            code="DIMENSION_OUT_OF_RANGE",
            why="an extrusion of no distance is not a solid",
        ),
        Refusal(
            id="revolve-crossing-its-axis",
            document=with_features([{
                "id": "feature.ring", "type": "solid.revolve", "enabled": True,
                "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
                "inputs": {
                    "sketch": sketch("section", straddling,
                                     plane={"on": "base", "plane": "XZ"},
                                     construction=[axis]),
                    "axis": {"kind": "construction_line", "entity": "axis.centre"},
                    "angle_deg": 360.0,
                },
            }], holes=0),
            code="REVOLVE_PROFILE_CROSSES_AXIS",
            why="a profile that straddles its axis sweeps through itself",
        ),
        Refusal(
            id="fillet-larger-than-the-material",
            document=with_features([plate, {
                "id": "feature.corners", "type": "feature.fillet", "enabled": True,
                "depends_on": ["feature.plate"], "produces": [],
                "inputs": {
                    "edges": {"id": "selector.corners", "kind": "edge",
                              "from_result": "body.main",
                              "cardinality": {"type": "exactly_n", "value": 4},
                              "where": {"curve_type": "line",
                                        "direction_parallel_to": "axis.z"}},
                    "radius": 30.0,
                },
            }], holes=0),
            code="BLEND_FAILED",
            why="a 30 mm round on a 40 mm plate",
        ),
        Refusal(
            id="blend-selector-matches-nothing",
            document=with_features([plate, {
                "id": "feature.corners", "type": "feature.fillet", "enabled": True,
                "depends_on": ["feature.plate"], "produces": [],
                "inputs": {
                    "edges": {"id": "selector.absent", "kind": "edge",
                              "from_result": "body.main", "cardinality": "one_or_more",
                              "where": {"curve_type": "circle"}},
                    "radius": 2.0,
                },
            }], holes=0),
            code="SELECTOR_NO_MATCH",
            why="a plain plate has no circular edges to round",
        ),
        Refusal(
            id="blend-selector-matches-too-many",
            document=with_features([plate, {
                "id": "feature.corners", "type": "feature.fillet", "enabled": True,
                "depends_on": ["feature.plate"], "produces": [],
                "inputs": {
                    "edges": {"id": "selector.two", "kind": "edge",
                              "from_result": "body.main",
                              "cardinality": {"type": "exactly_n", "value": 2},
                              "where": {"curve_type": "line",
                                        "direction_parallel_to": "axis.z"}},
                    "radius": 2.0,
                },
            }], holes=0),
            code="SELECTOR_AMBIGUOUS",
            why="four vertical edges where the document declared two",
        ),
        Refusal(
            id="predicate-this-engine-cannot-evaluate",
            document=with_features([plate, {
                "id": "feature.corners", "type": "feature.fillet", "enabled": True,
                "depends_on": ["feature.plate"], "produces": [],
                "inputs": {
                    "edges": {"id": "selector.made_by", "kind": "edge",
                              "from_result": "body.main", "cardinality": "one_or_more",
                              "where": {"produced_by": "feature.plate"}},
                    "radius": 2.0,
                },
            }], holes=0),
            code="SELECTOR_UNSUPPORTED_PREDICATE",
            why="the kernel's topology does not record which feature made a face",
        ),
        Refusal(
            id="shell-thicker-than-the-part",
            document=with_features([plate, {
                "id": "feature.hollow", "type": "feature.shell", "enabled": True,
                "depends_on": ["feature.plate"], "produces": [],
                "inputs": {
                    "faces": {"id": "selector.top", "kind": "face",
                              "from_result": "body.main", "cardinality": "exactly_one",
                              "where": {"surface_type": "planar",
                                        "normal": {"parallel_to": "axis.z",
                                                   "direction": "positive"}}},
                    "thickness": 25.0, "direction": "inward",
                },
            }], holes=0),
            code="SHELL_NO_CAVITY",
            # The measured surprise: the kernel does not refuse this. It returns the
            # solid it was given, whole, and every other check in the document passes.
            why="two 25 mm walls meet inside a 40 mm plate, leaving no cavity at all",
        ),
        Refusal(
            id="shell-opening-a-face-that-is-not-there",
            document=with_features([plate, {
                "id": "feature.hollow", "type": "feature.shell", "enabled": True,
                "depends_on": ["feature.plate"], "produces": [],
                "inputs": {
                    "faces": {"id": "selector.bore", "kind": "face",
                              "from_result": "body.main", "cardinality": "one_or_more",
                              "where": {"surface_type": "cylindrical"}},
                    "thickness": 2.0, "direction": "inward",
                },
            }], holes=0),
            code="SELECTOR_NO_MATCH",
            why="a plain plate has no cylindrical face to open",
        ),
        Refusal(
            id="shell-that-opens-nothing",
            document=with_features([plate, {
                "id": "feature.hollow", "type": "feature.shell", "enabled": True,
                "depends_on": ["feature.plate"], "produces": [],
                "inputs": {
                    "faces": {"id": "selector.any", "kind": "face",
                              "from_result": "body.main", "cardinality": "zero_or_one",
                              "where": {"surface_type": "cylindrical"}},
                    "thickness": 2.0, "direction": "inward",
                },
            }], holes=0),
            code="SCHEMA_INVALID",
            why=(
                "a cardinality that permits zero open faces; an offset with nothing "
                "open shrinks the solid instead of hollowing it"
            ),
            by_contract=True,
        ),
        Refusal(
            id="pattern-of-a-shell",
            document=with_features([plate, {
                "id": "feature.hollow", "type": "feature.shell", "enabled": True,
                "depends_on": ["feature.plate"], "produces": [],
                "inputs": {
                    "faces": {"id": "selector.top", "kind": "face",
                              "from_result": "body.main", "cardinality": "exactly_one",
                              "where": {"surface_type": "planar",
                                        "normal": {"parallel_to": "axis.z",
                                                   "direction": "positive"}}},
                    "thickness": 2.0, "direction": "inward",
                },
            }, {
                "id": "feature.row", "type": "feature.pattern", "enabled": True,
                "depends_on": ["feature.hollow"], "produces": [],
                "inputs": {"of": "feature.hollow",
                           "pattern": {"kind": "linear", "direction": "+X",
                                       "spacing_mm": 20.0, "count": 3}, "skip": []},
            }], holes=0),
            code="UNSUPPORTED_FEATURE_SET",
            why="a shell modifies the body, so there is no copy of it to place",
            by_contract=True,
        ),
        Refusal(
            id="intersection-of-bodies-that-do-not-touch",
            document=with_features([
                extrude("feature.first", "body.first", thickness, rectangle(40.0, 40.0)),
                extrude("feature.second", "body.second", thickness,
                        rectangle(40.0, 40.0, (200.0, 0.0)),
                        depends=["feature.first"], new_body=True),
                {"id": "feature.combine", "type": "feature.boolean", "enabled": True,
                 "depends_on": ["feature.first", "feature.second"], "produces": [],
                 "inputs": {"op": "intersect", "target": {"result": "body.first"},
                            "tools": [{"result": "body.second"}], "keep_tools": False}},
            ], holes=0),
            code="BOOLEAN_EMPTY",
            why="two blocks 200 mm apart have nothing in common",
        ),
        Refusal(
            id="cut-with-nothing-to-cut",
            document=with_features(
                [cut("feature.hole", circle(4.0), [])], holes=0),
            code="FEATURE_RESULT_UNAVAILABLE",
            why="a cut naming a body no feature builds",
            by_contract=True,
        ),
        Refusal(
            id="pattern-of-a-disabled-feature",
            document=with_features([
                plate,
                {**cut("feature.hole", circle(4.0, (-20.0, 0.0)), ["feature.plate"]),
                 "enabled": False},
                {"id": "feature.row", "type": "feature.pattern", "enabled": True,
                 "depends_on": ["feature.hole"], "produces": [],
                 "inputs": {"of": "feature.hole",
                            "pattern": {"kind": "linear", "direction": "+X",
                                        "spacing_mm": 20.0, "count": 3}, "skip": []}},
            ], holes=0),
            code="FEATURE_DISABLED_SOURCE",
            why="five instances around a hole that is not there",
            by_contract=True,
        ),
        Refusal(
            id="unresolved-parameter-used",
            document=with_features([{
                **extrude("feature.plate", "body.main", 10.0, rectangle(60.0, 40.0)),
                "inputs": {
                    "sketch": sketch("plate", rectangle(60.0, 40.0)),
                    "direction": "+Z",
                    "distance": {"parameter": "unknown_depth"},
                },
            }], holes=0, parameters=[
                {"id": "unknown_depth", "type": "length", "unit": "mm", "value": 0.0,
                 "status": "unresolved"}]),
            code="UNRESOLVED_PARAMETER_USED",
            why="a question nobody answered, used as a dimension",
            by_contract=True,
        ),
        Refusal(
            id="body-that-nothing-can-name",
            document=with_features([
                extrude("feature.first", "body.first", thickness, rectangle(40.0, 40.0)),
                {**extrude("feature.second", None, thickness,
                           rectangle(40.0, 40.0, (60.0, 0.0)),
                           depends=["feature.first"], new_body=True),
                 "produces": []},
            ], holes=0, bodies=2),
            code="CAD_IR_INVALID",
            why="a separate body with no name no selector could reach",
            by_contract=True,
        ),
        Refusal(
            id="execution-detail-in-a-name",
            document={
                **with_features([plate], holes=0),
                "document": {"units": "mm", "part_type": "single_part",
                             "coordinate_system": "right_handed",
                             "name": "run C:\\build\\make.exe"},
            },
            code="EXECUTION_DETAIL_PRESENT",
            why="CAD-IR describes intent, and a path is not intent",
            by_contract=True,
        ),
        Refusal(
            id="version-from-the-future",
            document={**with_features([plate], holes=0), "schema_version": "9.9"},
            code="CAD_IR_VERSION_TOO_NEW",
            why="a build from the future may use a field this one would ignore",
            by_contract=True,
        ),
    ]


__all__ = ["Case", "Refusal", "kept_tool", "negatives", "positives"]
