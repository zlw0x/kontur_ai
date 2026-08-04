"""The two ways an extrusion travels, and the claim's word for the one a drawing marks.

CAD-IR 1.10 gave an extrusion `both_directions` and `taper_deg` (ADR-033). The rules
they brought are stated in the contract and were tested only through the engine's own
corpus, which needs a CAD kernel to run; the refusals below need nothing but the
contract, and a refusal that only a kernel can prove is a refusal CI cannot see.

The claim's word for a draft is here for the reason the whole claim exists. A drafted
extrusion and a square one agree about the outline, the openings, the solid count and
— unlike a shell, which at least changes the *material* visibly — about the bounding
box as well, whenever the draft narrows. `test_a_narrowing_draft_is_invisible_to_every`
`_other_field` is that sentence as an assertion.
"""

import pytest
from pydantic import ValidationError

from cad_ir.canonical import (
    CAD_IR_SCHEMA,
    CAD_IR_VERSION,
    TAPER_LIMIT_DEG,
    CutExtrudeInputs,
    SolidExtrudeInputs,
)
from cad_ir.canonical_validator import validate_canonical
from cad_ir.shape_claim import ProfileKind, ShapeClaim, disagreements

WIDTH, HEIGHT, DEPTH = 40.0, 40.0, 20.0

DRAFT = {"id": "p_draft", "type": "angle", "unit": "deg", "value": 5.0, "status": "confirmed"}


def sketch(name="sketch.pad", width=WIDTH, height=HEIGHT) -> dict:
    return {
        "id": name, "plane": {"on": "base", "plane": "XY"},
        "outer": {"type": "rectangle", "center": [0.0, 0.0], "width": width,
                  "height": height, "rotation_deg": 0.0},
        "inner": [], "construction": [], "constraints": [], "dimensions": [],
    }


def pad(taper=None, **inputs) -> dict:
    feature = {
        "id": "feature.pad", "type": "solid.extrude", "enabled": True,
        "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
        "inputs": {"sketch": sketch(), "direction": "+Z", "distance": DEPTH, **inputs},
    }
    if taper is not None:
        feature["inputs"]["taper_deg"] = taper
    return feature


def pocket(taper=None, **inputs) -> dict:
    feature = {
        "id": "feature.pocket", "type": "cut.extrude", "enabled": True,
        "depends_on": ["feature.pad"], "produces": [],
        "inputs": {"sketch": sketch("sketch.pocket", 20.0, 20.0), "direction": "-Z",
                   "distance": 8.0, **inputs},
    }
    if taper is not None:
        feature["inputs"]["taper_deg"] = taper
    return feature


def document(features: list[dict], parameters: list[dict] | None = None) -> dict:
    return {
        "schema": CAD_IR_SCHEMA, "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "drafted-pad"},
        "parameters": parameters or [],
        "features": features,
        # The same two expectations satisfy the drafted pad and the square one, which is
        # the finding this file is about rather than a convenience: a narrowing taper
        # keeps the sketch as the widest section, so the box does not move.
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": WIDTH, "y": HEIGHT, "z": DEPTH}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def claim(**kwargs) -> ShapeClaim:
    return ShapeClaim(profile=ProfileKind.RECTANGLE, **kwargs)


def found(value: dict, **kwargs) -> list:
    return disagreements(validate_canonical(value), claim(**kwargs))


# --- the contract's own rules ----------------------------------------------


def test_a_taper_defaults_to_none_at_all():
    """Every document written before 1.10 means a square extrusion, and still does."""
    assert SolidExtrudeInputs(sketch=sketch(), direction="+Z", distance=DEPTH).taper_deg == 0.0


@pytest.mark.parametrize("taper", [TAPER_LIMIT_DEG, -TAPER_LIMIT_DEG, 0.0, 5.0, -5.0])
def test_a_taper_inside_the_limit_is_accepted(taper):
    inputs = SolidExtrudeInputs(sketch=sketch(), direction="+Z", distance=DEPTH,
                                taper_deg=taper)
    assert inputs.taper_deg == taper


@pytest.mark.parametrize("taper", [90.0, -90.0, TAPER_LIMIT_DEG + 0.5, 180.0])
def test_a_taper_at_or_past_a_right_angle_is_refused(taper):
    """At 90° the wall is parallel to the face it started from; past it the solid
    turns inside out. The engine's own `EXTRUDE_DRAFT_TOO_STEEP` catches the angles
    below the limit that still close the section — this is the range that has no
    geometric meaning at all, and it belongs in the contract."""
    with pytest.raises(ValidationError):
        SolidExtrudeInputs(sketch=sketch(), direction="+Z", distance=DEPTH, taper_deg=taper)


def test_a_taper_named_by_a_parameter_is_not_range_checked_here():
    """A reference carries no number for the contract to check. The engine resolves it
    and applies the same limit, which is the only place the value exists."""
    inputs = SolidExtrudeInputs(sketch=sketch(), direction="+Z", distance=DEPTH,
                                taper_deg={"parameter": "p_draft"})
    assert inputs.taper_deg.parameter == "p_draft"


def test_a_through_all_cut_may_not_be_tapered():
    """The engine measures a through-all tool against the body it cuts, so the far end
    of a tapered one would be a width the document never stated."""
    with pytest.raises(ValidationError):
        CutExtrudeInputs(sketch=sketch(), direction="-Z", through_all=True, taper_deg=5.0)


def test_a_through_all_cut_has_no_second_side_to_reach():
    with pytest.raises(ValidationError):
        CutExtrudeInputs(sketch=sketch(), direction="-Z", through_all=True,
                         both_directions=True)


def test_a_tapered_cut_that_states_its_distance_is_fine():
    inputs = CutExtrudeInputs(sketch=sketch(), direction="-Z", distance=8.0, taper_deg=5.0)
    assert (inputs.distance, inputs.taper_deg) == (8.0, 5.0)


# --- the claim's word for it ------------------------------------------------


def test_a_drafted_part_drafted_by_the_named_parameter_agrees():
    value = document([pad(taper={"parameter": "p_draft"})], parameters=[DRAFT])
    assert found(value, draft="p_draft") == []


def test_a_part_read_as_drafted_and_built_square_is_caught():
    """The check the draft exists for, and the only thing that catches it.

    A document that dropped the taper builds a prism: the outline is right, the
    openings are right, the solid count is right, and — because a narrowing taper keeps
    the sketch as the widest section — the bounding box is right too. The part holds a
    third less material than the drawing says.

    The document drops the *parameter* with the taper, which is what a real one does:
    CAD-IR 1.11 refuses a dimension nothing drives (`PARAMETER_DRIVES_NOTHING`), so a
    compilation that ignores the draft cannot keep the angle in its parameter list. That
    rule and this check overlap and neither replaces the other — the validator sees a
    declared angle driving nothing, and the claim sees a drawing that stated an angle
    the document does not mention at all.
    """
    disagreement = found(document([pad()]), draft="p_draft")

    assert [item.code for item in disagreement] == ["DRAFT_PARAMETER"]
    assert disagreement[0].built == "no taper"


def test_a_draft_built_from_a_literal_has_lost_the_name_the_drawing_gave_it():
    disagreement = found(document([pad(taper=5.0)]), draft="p_draft")

    assert [item.code for item in disagreement] == ["DRAFT_PARAMETER"]
    assert "literal" in disagreement[0].detail


def test_a_draft_built_from_the_wrong_parameter_is_named():
    value = document(
        [pad(taper={"parameter": "p_other"})],
        parameters=[{"id": "p_other", "type": "angle", "unit": "deg",
                     "value": 3.0, "status": "assumed"}],
    )
    disagreement = found(value, draft="p_draft")

    assert [item.code for item in disagreement] == ["DRAFT_PARAMETER"]
    assert disagreement[0].built == "p_other"


def test_a_named_draft_of_zero_degrees_is_square_walls_with_a_name_on_them():
    """The id and the angle reach the document from the same reading, and this is the
    one place the two can be made to disagree: a parameter referenced correctly and
    holding nothing. The walls are vertical whatever points at it."""
    value = document(
        [pad(taper={"parameter": "p_draft"})],
        parameters=[{**DRAFT, "value": 0.0}],
    )
    disagreement = found(value, draft="p_draft")

    assert [item.code for item in disagreement] == ["DRAFT_PARAMETER"]
    assert disagreement[0].built == "p_draft = 0"


def test_a_reader_who_saw_no_draft_does_not_contradict_a_document_that_tapers():
    """Silence is not a claim, here as everywhere (POSTMVP-016). A view that did not
    show the draft says nothing about it, and a claim that says nothing agrees with
    either. The check exists for the drawing that plainly marks an angle against a
    document that ignored it."""
    value = document([pad(taper={"parameter": "p_draft"})], parameters=[DRAFT])
    assert found(value) == []


def test_a_draft_on_a_cut_counts_as_the_document_drafting_something():
    """A moulded pocket is drafted too, and it is the tool that leans rather than the
    part. What the claim cannot see is *which* feature the drawing marked — recorded
    in `_draft_disagreement` rather than pretended away."""
    value = document(
        [pad(), pocket(taper={"parameter": "p_draft"})], parameters=[DRAFT]
    )
    assert found(value, draft="p_draft", openings=[{"kind": "rectangular", "count": 1,
                                                    "through": False}]) == []


def test_a_disabled_taper_is_a_document_that_extrudes_square():
    """`enabled: false` means "not this one", and the claim reads it that way."""
    value = document([pad(taper={"parameter": "p_draft"})], parameters=[DRAFT])
    value["features"][0]["enabled"] = False
    # A document whose only feature is switched off builds nothing, which the claim
    # says first and more loudly. Give it a square pad to build instead.
    value["features"].append(pad())
    value["features"][1]["id"] = "feature.square"
    value["features"][1]["produces"] = [{"id": "body.square", "kind": "solid_body"}]

    assert [item.code for item in found(value, draft="p_draft")] == ["DRAFT_PARAMETER"]


def test_a_draft_changes_nothing_else_the_claim_counts():
    """Which is the whole problem, stated as a test: every other field of the claim is
    satisfied by the square part."""
    drafted = validate_canonical(document([pad(taper={"parameter": "p_draft"})],
                                          parameters=[DRAFT]))
    square = validate_canonical(document([pad()]))
    stated = claim(thickness=None)

    assert disagreements(drafted, stated) == disagreements(square, stated) == []


def test_the_draft_and_the_wall_are_different_questions():
    """Both say how much of the part is there and neither implies the other: a cast
    boss is drafted and solid, and a sheet enclosure is hollow and square."""
    value = document([pad(taper={"parameter": "p_draft"})], parameters=[DRAFT])
    disagreement = found(value, draft="p_draft", wall="p_draft")

    assert [item.code for item in disagreement] == ["WALL_PARAMETER"]
    assert disagreement[0].built == "no shell"


# --- what CAD-IR 1.11's arithmetic changed about all of this -----------------

HALF_DRAFT = {"divide": {"parameter": "p_total_draft"}, "by": 2.0}
TOTAL_DRAFT = {"id": "p_total_draft", "type": "angle", "unit": "deg", "value": 10.0,
               "status": "confirmed"}


def test_a_taper_derived_from_a_parameter_is_refused_rather_than_crashing():
    """The defect ADR-034 left in seven range checks, in the one that matters here.

    `_validate_taper` guarded with `isinstance(value, ParameterRef)` and then called
    `float(value)`. That was right while a `Scalar` had two members; with four, a taper
    stated as half a parameter raised `TypeError` **from inside a pydantic validator** —
    not a refusal, and the range check it guarded never ran. `stated_number` is one
    function so the next member of `Scalar` cannot bring it back.
    """
    inputs = SolidExtrudeInputs(sketch=sketch(), direction="+Z", distance=DEPTH,
                                taper_deg=HALF_DRAFT)

    assert inputs.taper_deg.by == 2.0
    assert inputs.taper_deg.divide.parameter == "p_total_draft"


def test_the_claim_sees_a_parameter_through_the_arithmetic_that_scales_it():
    """A draft stated as half an overall angle is still driven by that parameter.

    Before this the claim asked whether the taper *is* a `ParameterRef`, so a document
    that used 1.11's arithmetic correctly was reported as having lost the name — the
    check telling the compiling agent to fix something it had done right.
    """
    value = document([pad(taper=HALF_DRAFT)], parameters=[TOTAL_DRAFT])

    assert found(value, draft="p_total_draft") == []


def test_a_thickness_stated_as_half_a_total_still_names_its_parameter():
    """The same fix, on the field that has had a word since ADR-025."""
    value = document(
        [pad(distance={"divide": {"parameter": "p_total_height"}, "by": 2.0})],
        parameters=[{"id": "p_total_height", "type": "length", "unit": "mm",
                     "value": 40.0, "status": "confirmed"}],
    )

    assert found(value, thickness="p_total_height") == []


def test_a_draft_the_document_turns_over_is_caught():
    """What ADR-034 took away, and this puts back.

    ADR-033 gave the claim a name and not a direction, and said so on the grounds that a
    canonical `Scalar` could not flip a sign: the sign the reading cited to the drawing
    was the sign the kernel received. `ScalarNegation` ends that. A document that tapers
    by the negation of the parameter names exactly what the drawing said and builds a
    part leaning the other way — with the drawing's outline, openings, solid count and
    bounding box.
    """
    value = document([pad(taper={"negate": {"parameter": "p_draft"}})], parameters=[DRAFT])
    disagreement = found(value, draft="p_draft")

    assert [item.code for item in disagreement] == ["DRAFT_PARAMETER"]
    assert disagreement[0].built == "the negation of p_draft"


def test_a_negative_divisor_turns_it_over_too():
    """The sign can hide in the divisor, and one place answers both spellings."""
    value = document(
        [pad(taper={"divide": {"parameter": "p_total_draft"}, "by": -2.0})],
        parameters=[TOTAL_DRAFT],
    )

    assert [item.code for item in found(value, draft="p_total_draft")] == ["DRAFT_PARAMETER"]


def test_two_negations_are_the_angle_the_drawing_gave():
    """Nobody writes this, and the check must not be fooled by it either way."""
    value = document(
        [pad(taper={"negate": {"negate": {"parameter": "p_draft"}}})],
        parameters=[DRAFT],
    )

    assert found(value, draft="p_draft") == []
