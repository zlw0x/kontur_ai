"""CAD-IR 1.12: draft — the third operation that names faces, and the first that leans them.

Three milestones refused an operation on the grounds that composition already said it
(POSTMVP-011 holes, POSTMVP-022 ribs, POSTMVP-024 draft), and the rule they arrived at is
what this has to pass: **an operation earns its place only when it says something
composition cannot.** `taper_deg` drafts an extrusion as it is created, so it draws in
every wall that extrusion makes and reaches no body an extrusion did not build. Both of
those are measured gaps, and both are corpus cases.

What is decided here rather than left to the kernel: a selector that cannot match
nothing, one neutral face rather than several, and an angle that is neither zero nor past
the point where a wall lies in the neutral plane.
"""

from __future__ import annotations

import pytest
from cad_ir.canonical import CAD_IR_SCHEMA, CAD_IR_VERSION
from cad_ir.canonical_validator import validate_canonical
from cad_ir.draft import DRAFT_LIMIT_DEG, DraftInputs
from cad_ir.errors import CadIrValidationError
from cad_ir.shape_claim import ProfileKind, ShapeClaim, disagreements
from pydantic import ValidationError

SIDE, HEIGHT = 40.0, 20.0
ANGLE = {"id": "p_draft", "type": "angle", "unit": "deg", "value": 3.0, "status": "confirmed"}


def walls(cardinality=None, **overrides) -> dict:
    return {
        "id": "selector.walls", "kind": "face", "from_result": "body.main",
        "cardinality": cardinality or {"type": "exactly_n", "value": 4},
        "where": {"surface_type": "planar", "normal": {"perpendicular_to": "axis.z"}},
        **overrides,
    }


def base(**overrides) -> dict:
    return {
        "id": "selector.base", "kind": "face", "from_result": "body.main",
        "cardinality": "exactly_one",
        "where": {"surface_type": "planar",
                  "normal": {"parallel_to": "axis.z", "direction": "negative"}},
        **overrides,
    }


def block() -> dict:
    return {
        "id": "feature.block", "type": "solid.extrude", "enabled": True,
        "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
        "inputs": {
            "sketch": {"id": "sketch.block", "plane": {"on": "base", "plane": "XY"},
                       "outer": {"type": "rectangle", "center": [0.0, 0.0], "width": SIDE,
                                 "height": SIDE, "rotation_deg": 0.0},
                       "inner": [], "construction": [], "constraints": [], "dimensions": []},
            "direction": "+Z", "distance": HEIGHT,
        },
    }


def drafted(angle=3.0, faces=None, neutral=None) -> dict:
    return {
        "id": "feature.draw_in", "type": "feature.draft", "enabled": True,
        "depends_on": ["feature.block"], "produces": [],
        "inputs": {"faces": faces or walls(), "neutral_face": neutral or base(),
                   "angle_deg": angle},
    }


def document(features: list[dict], parameters: list[dict] | None = None) -> dict:
    return {
        "schema": CAD_IR_SCHEMA, "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "drafted-boss"},
        "parameters": parameters or [],
        "features": features,
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": SIDE, "y": SIDE, "z": HEIGHT}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def codes(value: dict) -> list[str]:
    with pytest.raises(CadIrValidationError) as raised:
        validate_canonical(value)
    return [issue.code for issue in raised.value.issues]


# --- the contract ------------------------------------------------------------


def test_a_draft_of_named_walls_about_a_named_face_is_valid():
    parsed = validate_canonical(document([block(), drafted()]))

    assert parsed.features[1].inputs.angle_deg == 3.0
    assert str(parsed.features[1].inputs.neutral_face.id) == "selector.base"


def test_a_draft_produces_nothing_because_it_makes_no_body():
    """`produces` is empty, like a shell's and a blend's: the body was already there,
    and a result id here would name it a second time."""
    value = document([block(), drafted()])
    value["features"][1]["produces"] = [{"id": "body.drafted", "kind": "solid_body"}]

    assert codes(value) == ["SCHEMA_INVALID"]


@pytest.mark.parametrize("cardinality", ["all", "zero_or_one", {"type": "exactly_n", "value": 0}])
def test_a_selector_that_may_match_nothing_is_refused(cardinality):
    """The rule a blend has had since ADR-026 and a shell since ADR-030, third time.

    A draft that treated no faces is a successful feature that did not happen, and
    nothing downstream sees it: a draft changes no face count, no body count, and — on
    the walls it leaves alone — no bounding box either.
    """
    with pytest.raises(ValidationError):
        DraftInputs(faces=walls(cardinality=cardinality), neutral_face=base(), angle_deg=3.0)


@pytest.mark.parametrize("cardinality", ["exactly_one", "one_or_more",
                                         {"type": "exactly_n", "value": 4}])
def test_a_selector_that_must_match_something_is_accepted(cardinality):
    inputs = DraftInputs(faces=walls(cardinality=cardinality), neutral_face=base(),
                         angle_deg=3.0)

    assert inputs.angle_deg == 3.0


@pytest.mark.parametrize("cardinality", ["one_or_more", {"type": "exactly_n", "value": 2}])
def test_the_neutral_face_must_be_exactly_one(cardinality):
    """Two faces are two planes, and the engine would pick one. The same reasoning as
    an asymmetric chamfer naming the face it measures from (ADR-026)."""
    with pytest.raises(ValidationError):
        DraftInputs(faces=walls(), neutral_face=base(cardinality=cardinality), angle_deg=3.0)


def test_the_two_selectors_need_different_ids():
    """A trace naming `selector.walls` has to mean one of them."""
    with pytest.raises(ValidationError):
        DraftInputs(faces=walls(), neutral_face=base(id="selector.walls"), angle_deg=3.0)


def test_a_draft_of_zero_degrees_is_refused():
    """A feature that does nothing, wearing the name of one that does. It would also be
    invisible: nothing the claim or the expectations count changes."""
    with pytest.raises(ValidationError):
        DraftInputs(faces=walls(), neutral_face=base(), angle_deg=0.0)


@pytest.mark.parametrize("angle", [90.0, -90.0, DRAFT_LIMIT_DEG + 0.5, 180.0])
def test_an_angle_at_or_past_a_right_angle_is_refused(angle):
    """At 90° the wall lies in the neutral plane. The angles below the limit that still
    close the section are the engine's to catch — how far the walls reach is something
    only the kernel knows — and it does, with `DRAFT_TOO_STEEP`."""
    with pytest.raises(ValidationError):
        DraftInputs(faces=walls(), neutral_face=base(), angle_deg=angle)


@pytest.mark.parametrize("angle", [DRAFT_LIMIT_DEG, -DRAFT_LIMIT_DEG, 3.0, -3.0])
def test_an_angle_inside_the_limit_is_accepted(angle):
    assert DraftInputs(faces=walls(), neutral_face=base(), angle_deg=angle).angle_deg == angle


def test_an_angle_named_by_a_parameter_is_not_range_checked_here():
    """A reference carries no number for the contract to check, including no zero. The
    engine resolves it and refuses a zero in front of the kernel."""
    inputs = DraftInputs(faces=walls(), neutral_face=base(),
                         angle_deg={"parameter": "p_draft"})

    assert inputs.angle_deg.parameter == "p_draft"


def test_an_angle_derived_from_a_parameter_is_accepted_too():
    """CAD-IR 1.11's arithmetic, and the guard that seven range checks needed: a draft
    stated as half an included angle must not crash the validator (ADR-034's amendment)."""
    inputs = DraftInputs(faces=walls(), neutral_face=base(),
                         angle_deg={"divide": {"parameter": "p_included"}, "by": 2.0})

    assert inputs.angle_deg.by == 2.0


def test_a_draft_naming_a_body_no_feature_builds_is_refused():
    value = document([block(), drafted(faces=walls(from_result="body.absent"))])

    assert "FEATURE_RESULT_UNAVAILABLE" in codes(value)


# --- what it means for the claim ----------------------------------------------


def claim(**kwargs) -> ShapeClaim:
    return ShapeClaim(profile=ProfileKind.RECTANGLE, **kwargs)


def test_the_claim_reads_a_draft_feature_as_it_reads_a_taper():
    """A drawing marks an angle on a wall; which of the two ways the compilation reached
    for is not something it says. So `ShapeClaim.draft` is satisfied by either."""
    value = document([block(), drafted(angle={"parameter": "p_draft"})], parameters=[ANGLE])

    assert disagreements(validate_canonical(value), claim(draft="p_draft")) == []


def test_a_part_read_as_drafted_and_built_with_square_walls_is_still_caught():
    found = disagreements(validate_canonical(document([block()])), claim(draft="p_draft"))

    assert [item.code for item in found] == ["DRAFT_PARAMETER"]
    assert found[0].built == "no taper"


def test_a_draft_feature_that_negates_the_named_angle_is_caught():
    """The hole ADR-034 opened, closed on the new operation as well as on `taper_deg`."""
    value = document([block(), drafted(angle={"negate": {"parameter": "p_draft"}})],
                     parameters=[ANGLE])
    found = disagreements(validate_canonical(value), claim(draft="p_draft"))

    assert [item.code for item in found] == ["DRAFT_PARAMETER"]
    assert found[0].built == "the negation of p_draft"


def test_a_draft_feature_built_from_a_literal_has_lost_the_name():
    found = disagreements(validate_canonical(document([block(), drafted(angle=3.0)])),
                          claim(draft="p_draft"))

    assert [item.code for item in found] == ["DRAFT_PARAMETER"]
    assert "literal" in found[0].detail


def test_a_draft_changes_nothing_else_the_claim_counts():
    """Which is why the claim needs a word for it at all. The outline, the openings and
    the solid count are the same, and so is the bounding box when the neutral face is the
    one the drawing dimensions."""
    leaning = validate_canonical(document([block(), drafted(angle={"parameter": "p_draft"})],
                                          parameters=[ANGLE]))
    square = validate_canonical(document([block()]))
    stated = claim()

    assert disagreements(leaning, stated) == disagreements(square, stated) == []
