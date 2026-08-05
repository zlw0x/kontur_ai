"""Drafting the walls of a body that already exists, on real geometry.

Every number here is arithmetic from the drawing, and the two that matter most are the
ones no extrusion can produce: two walls of four, and the outer wall of a turned part.
That is the whole justification for the operation existing, so it is asserted rather
than described.

The rest is the kernel's failure modes, measured. A draft steep enough to close the
section it starts from returns a **pyramid that reports itself invalid** at exactly the
closing angle, and throws `Standard_ConstructionError` **with an empty message** past it
— the first time this kernel has volunteered that its own answer is wrong, and a raw
OCCT throw carrying no text at all.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_ir.canonical import CAD_IR_SCHEMA, CAD_IR_VERSION  # noqa: E402
from cad_ir.canonical_validator import validate_canonical  # noqa: E402

from cad_engine_build123d.adapter import build_part  # noqa: E402
from cad_engine_build123d.errors import CadEngineError  # noqa: E402

SIDE, HEIGHT, ANGLE = 40.0, 20.0, 10.0
LEAN = math.tan(math.radians(ANGLE))


def walls(cardinality=None, where=None, sid="selector.walls") -> dict:
    return {"id": sid, "kind": "face", "from_result": "body.main",
            "cardinality": cardinality or {"type": "exactly_n", "value": 4},
            "where": where or {"surface_type": "planar",
                               "normal": {"perpendicular_to": "axis.z"}}}


def flat(direction: str, sid: str) -> dict:
    return {"id": sid, "kind": "face", "from_result": "body.main",
            "cardinality": "exactly_one",
            "where": {"surface_type": "planar",
                      "normal": {"parallel_to": "axis.z", "direction": direction}}}


def block(side: float = SIDE, height: float = HEIGHT) -> dict:
    return {
        "id": "feature.block", "type": "solid.extrude", "enabled": True,
        "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
        "inputs": {
            "sketch": {"id": "sketch.block", "plane": {"on": "base", "plane": "XY"},
                       "outer": {"type": "rectangle", "center": [0.0, 0.0], "width": side,
                                 "height": side, "rotation_deg": 0.0},
                       "inner": [], "construction": [], "constraints": [], "dimensions": []},
            "direction": "+Z", "distance": height,
        },
    }


def drafted(angle: float = ANGLE, faces=None, neutral=None, depends="feature.block") -> dict:
    return {
        "id": "feature.draw_in", "type": "feature.draft", "enabled": True,
        "depends_on": [depends], "produces": [],
        "inputs": {"faces": faces or walls(),
                   "neutral_face": neutral or flat("negative", "selector.base"),
                   "angle_deg": angle},
    }


def document(features: list[dict], size=(SIDE, SIDE, HEIGHT)) -> dict:
    return {
        "schema": CAD_IR_SCHEMA, "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "drafted"},
        "parameters": [],
        "features": features,
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": size[0], "y": size[1], "z": size[2]}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def built(features: list[dict]):
    return build_part(validate_canonical(document(features)))


def refused(features: list[dict]) -> CadEngineError:
    with pytest.raises(CadEngineError) as raised:
        build_part(validate_canonical(document(features)))
    return raised.value


def prismatoid(side: float, height: float, lean: float) -> float:
    far, mid = side - 2 * height * lean, side - height * lean
    return height / 6 * (side**2 + 4 * mid**2 + far**2)


# --- what the drawing says ----------------------------------------------------


def test_every_wall_drawn_in_is_the_solid_a_taper_builds():
    """The case that is *not* the justification, and is here because of that.

    POSTMVP-024 measured these two routes as the same part, and it is why the operation
    was refused three times before it was accepted. If they ever stop agreeing, one of
    them is wrong.
    """
    part = built([block(), drafted()])

    assert float(part.volume) == pytest.approx(prismatoid(SIDE, HEIGHT, LEAN), abs=1e-6)
    box = part.bounding_box()
    # The neutral face is the base, so the base keeps the drawing's size.
    assert (float(box.max.X), float(box.max.Y)) == pytest.approx((SIDE / 2, SIDE / 2), abs=1e-9)


def test_the_named_face_holds_its_size_whichever_end_it_is():
    """The sign convention, as an assertion rather than a comment.

    A positive angle draws the walls in *away from* the neutral face, and the same
    number comes back whether the document names the base or the top. That is only true
    because the engine turns the face's normal inward; read straight off the face, a
    base points down and out of the part, and the same document would come back
    37 974.1029 mm³ — a part that grows where the drawing shrinks.
    """
    from_base = built([block(), drafted(neutral=flat("negative", "selector.base"))])
    from_top = built([block(), drafted(neutral=flat("positive", "selector.top"))])

    expected = prismatoid(SIDE, HEIGHT, LEAN)
    assert float(from_base.volume) == pytest.approx(expected, abs=1e-6)
    assert float(from_top.volume) == pytest.approx(expected, abs=1e-6)


def test_a_negative_angle_lets_the_walls_out():
    """`taper_deg`'s rule, deliberately unchanged (ADR-033): a moulded cavity states a
    negative draft explicitly rather than having the engine flip a sign nobody can see."""
    part = built([block(), drafted(angle=-ANGLE)])

    assert float(part.volume) == pytest.approx(prismatoid(SIDE, HEIGHT, -LEAN), abs=1e-6)
    assert float(part.bounding_box().max.X) > SIDE / 2


def test_two_walls_of_four_is_a_part_no_extrusion_makes():
    """The first of the two gaps. `taper_deg` draws in every wall its extrusion makes;
    this draws in the pair facing x and leaves the pair facing y standing.

    `a·h·(a − h·tanθ)`, from `∫₀ʰ (a − 2·z·tanθ)·a dz`.
    """
    part = built([block(), drafted(faces=walls(
        cardinality={"type": "exactly_n", "value": 2},
        where={"surface_type": "planar", "normal": {"parallel_to": "axis.x"}}))])

    assert float(part.volume) == pytest.approx(SIDE * HEIGHT * (SIDE - HEIGHT * LEAN), abs=1e-6)
    box = part.bounding_box()
    # The undrafted pair still stands where the drawing put it.
    assert float(box.max.Y) == pytest.approx(SIDE / 2, abs=1e-9)
    assert float(box.max.X) == pytest.approx(SIDE / 2, abs=1e-9)


def test_a_turned_wall_can_be_drafted_and_no_extrusion_made_it():
    """The second gap, and the sharper one: `taper_deg` cannot reach a revolved body at
    all. The outer wall becomes a cone, so the volume is the frustum less the bore."""
    outer, bore = 20.0, 10.0
    axis = {"type": "line", "id": "axis.centre", "start": [0.0, 0.0], "end": [0.0, HEIGHT]}
    tube = {
        "id": "feature.tube", "type": "solid.revolve", "enabled": True,
        "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
        "inputs": {
            "sketch": {"id": "sketch.section", "plane": {"on": "base", "plane": "XZ"},
                       "outer": {"type": "rectangle", "center": [(outer + bore) / 2, HEIGHT / 2],
                                 "width": outer - bore, "height": HEIGHT, "rotation_deg": 0.0},
                       "inner": [], "construction": [axis], "constraints": [], "dimensions": []},
            "axis": {"kind": "construction_line", "entity": "axis.centre"},
            "angle_deg": 360.0,
        },
    }
    wall = {"id": "selector.outer", "kind": "face", "from_result": "body.main",
            "cardinality": "exactly_one",
            "where": {"surface_type": "cylindrical",
                      "radius_mm": {"value": outer, "tolerance": 0.01}}}
    part = build_part(validate_canonical(document(
        [tube, drafted(faces=wall, depends="feature.tube")],
        size=(2 * outer, 2 * outer, HEIGHT))))

    top = outer - HEIGHT * LEAN
    expected = (math.pi * HEIGHT / 3 * (outer**2 + outer * top + top**2)
                - math.pi * bore**2 * HEIGHT)
    assert float(part.volume) == pytest.approx(expected, abs=1e-6)


def test_a_draft_changes_no_face_count():
    """Which is why `surface_face_count` cannot see one, and why the claim needed a word
    of its own (ADR-033's amendment). Six faces before and six after."""
    square = built([block()])
    leaning = built([block(), drafted()])

    assert len(square.faces()) == len(leaning.faces()) == 6


# --- what the engine refuses --------------------------------------------------


def test_an_angle_that_closes_the_section_is_refused_rather_than_exported():
    """40 wide over 20 tall closes at 45°, and the kernel's answer there is a pyramid it
    marks invalid — 10 666.6667 mm³ where a frustum was asked for. The first operation
    where the kernel says its own answer is wrong; exporting it would put a STEP nobody
    can open in front of a customer."""
    error = refused([block(), drafted(angle=45.0)])

    assert error.code == "DRAFT_TOO_STEEP"
    assert error.stage == "feature"


def test_an_angle_past_the_closing_point_is_a_bare_kernel_throw_and_is_named():
    """`Standard_ConstructionError` with an empty message. Without the wrap it escapes
    the worker's typed-error contract as a crash, the way `StdFail_NotDone` did before
    ENGINE-MIG-006 named it."""
    error = refused([block(), drafted(angle=60.0)])

    assert error.code == "DRAFT_TOO_STEEP"


def test_a_neutral_face_that_is_not_planar_is_refused():
    post = {
        "id": "feature.block", "type": "solid.extrude", "enabled": True,
        "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
        "inputs": {
            "sketch": {"id": "sketch.post", "plane": {"on": "base", "plane": "XY"},
                       "outer": {"type": "circle", "center": [0.0, 0.0], "radius": 15.0},
                       "inner": [], "construction": [], "constraints": [], "dimensions": []},
            "direction": "+Z", "distance": HEIGHT,
        },
    }
    curved = {"id": "selector.curved", "kind": "face", "from_result": "body.main",
              "cardinality": "exactly_one",
              "where": {"surface_type": "cylindrical",
                        "radius_mm": {"value": 15.0, "tolerance": 0.01}}}
    error = refused([post, drafted(faces=curved, neutral=dict(curved, id="selector.wall"))])

    assert error.code == "DRAFT_NEUTRAL_FACE_NOT_PLANAR"
    assert error.stage == "selector"


def test_a_selector_that_names_no_wall_says_which_clause_emptied_it():
    error = refused([block(), drafted(faces=walls(
        cardinality="exactly_one",
        where={"surface_type": "planar", "normal": {"perpendicular_to": "axis.z"},
               "area_mm2": {"value": 9999.0, "tolerance": 0.5}}))])

    assert error.code in ("SELECTOR_NO_MATCH", "SELECTOR_AMBIGUOUS")
    assert "area_mm2" in error.safe_message


def test_a_draft_with_nothing_built_yet_says_so():
    value = document([block(), drafted()])
    value["features"][0]["enabled"] = False
    with pytest.raises(CadEngineError) as raised:
        build_part(validate_canonical(value))

    assert raised.value.code in ("UNSUPPORTED_FEATURE_SET", "FEATURE_RESULT_UNAVAILABLE")
