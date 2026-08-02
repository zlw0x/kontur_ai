"""CAD-IR 1.8: shell, and the claim's first word for how much of the part is there.

Every operation before this one answers "what shape is it?". A shell answers a
different question, and the contract is shaped by one consequence: a hollow part and
a solid one of the same size agree about the outline, the openings, the body count
and the bounding box. Nothing that measures the outside can tell them apart.

So two things are stated here rather than left to the engine: a shell's selector may
not permit zero matches, and a claim may name the parameter that holds the wall.
"""

import pytest
from pydantic import ValidationError

from cad_ir.canonical import CAD_IR_SCHEMA, CAD_IR_VERSION
from cad_ir.canonical_validator import validate_canonical
from cad_ir.errors import CadIrValidationError
from cad_ir.shape_claim import OpeningClaim, ProfileKind, ShapeClaim, disagreements
from cad_ir.shell import ShellDirection, ShellInputs

WIDTH, HEIGHT, DEPTH = 100.0, 60.0, 40.0


def face_selector(cardinality="exactly_one", from_result="body.main") -> dict:
    return {
        "id": "selector.top", "kind": "face", "from_result": from_result,
        "cardinality": cardinality,
        "where": {"surface_type": "planar",
                  "normal": {"parallel_to": "axis.z", "direction": "positive"}},
    }


def shell_feature(thickness=3.0, direction="inward", **selector) -> dict:
    return {
        "id": "feature.hollow", "type": "feature.shell", "enabled": True,
        "depends_on": ["feature.block"], "produces": [],
        "inputs": {"faces": face_selector(**selector), "thickness": thickness,
                   "direction": direction},
    }


def block(distance=DEPTH) -> dict:
    return {
        "id": "feature.block", "type": "solid.extrude", "enabled": True,
        "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
        "inputs": {
            "sketch": {"id": "sketch.block", "plane": {"on": "base", "plane": "XY"},
                       "outer": {"type": "rectangle", "center": [0.0, 0.0],
                                 "width": WIDTH, "height": HEIGHT, "rotation_deg": 0.0},
                       "inner": [], "construction": [], "constraints": [],
                       "dimensions": []},
            "direction": "+Z", "distance": distance,
        },
    }


def document(features: list[dict], parameters: list[dict] | None = None) -> dict:
    return {
        "schema": CAD_IR_SCHEMA, "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "enclosure"},
        "parameters": parameters or [],
        "features": features,
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": WIDTH, "y": HEIGHT, "z": DEPTH}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def codes(value: dict) -> set[str]:
    with pytest.raises(CadIrValidationError) as raised:
        validate_canonical(value)
    return {issue.code for issue in raised.value.issues}


# --- the contract ----------------------------------------------------------


def test_a_shell_is_a_document_the_contract_accepts():
    parsed = validate_canonical(document([block(), shell_feature()]))

    hollow = parsed.features[1]
    assert hollow.inputs.direction is ShellDirection.INWARD
    assert hollow.produces == []


@pytest.mark.parametrize("cardinality", ["all", "zero_or_one", {"type": "exactly_n", "value": 0}])
def test_a_shell_may_not_declare_a_cardinality_that_opens_nothing(cardinality):
    """The rule that carries the operation.

    A blend refuses these because blending nothing is a feature that silently does not
    happen. A shell refuses them for a harder reason: an offset with no open faces is
    a *different operation* — it shrinks the solid — so the document does not get the
    part it asked for minus one step, it gets a smaller solid one.
    """
    with pytest.raises(ValidationError):
        ShellInputs(faces=face_selector(cardinality), thickness=3.0)

    assert "SCHEMA_INVALID" in codes(document([block(), shell_feature(cardinality=cardinality)]))


def test_a_shell_that_opens_one_or_more_faces_is_accepted():
    """The two ways to say it, and they are the two a drawing means.

    `exactly_one` is an open-topped box. `exactly_n` is a duct open at both ends, and
    the count is the point: a document that says two and finds three has found a face
    nobody drew.
    """
    for cardinality in ("exactly_one", "one_or_more", {"type": "exactly_n", "value": 2}):
        validate_canonical(document([block(), shell_feature(cardinality=cardinality)]))


def test_a_wall_of_no_thickness_is_not_a_wall():
    with pytest.raises(ValidationError):
        ShellInputs(faces=face_selector(), thickness=0.0)
    with pytest.raises(ValidationError):
        ShellInputs(faces=face_selector(), thickness=-2.0)


def test_a_named_wall_is_left_for_the_engine_to_resolve():
    """A `ParameterRef` is a promise about a number this contract never sees.

    Refusing it here would mean re-implementing parameter resolution in the validator,
    and the engine checks it again in front of the kernel.
    """
    inputs = ShellInputs(faces=face_selector(), thickness={"parameter": "p_wall"})
    assert inputs.thickness.parameter == "p_wall"


def test_a_shell_naming_a_body_no_feature_builds_is_refused():
    value = document([block(), shell_feature(from_result="body.absent")])
    assert "FEATURE_RESULT_UNAVAILABLE" in codes(value)


def test_a_pattern_cannot_repeat_a_shell():
    """A pattern re-runs the operation that made material, at an offset.

    A shell made none: it modified the body that was there. Repeating it three times
    would mean applying it to the same solid three times, which is either a no-op or
    nonsense depending on how the kernel felt. Refused in the contract, where the
    document can still be repaired, rather than in the engine as an unsupported tool.
    """
    value = document([block(), shell_feature(), {
        "id": "feature.row", "type": "feature.pattern", "enabled": True,
        "depends_on": ["feature.hollow"], "produces": [],
        "inputs": {"of": "feature.hollow",
                   "pattern": {"kind": "linear", "direction": "+X",
                               "spacing_mm": 20.0, "count": 3}, "skip": []},
    }])
    assert "UNSUPPORTED_FEATURE_SET" in codes(value)


# --- the claim -------------------------------------------------------------


WALL_PARAMETER = {"id": "p_wall", "type": "length", "unit": "mm", "value": 3.0,
                  "status": "confirmed"}


def hollow_document(thickness=None) -> dict:
    return document(
        [block(), shell_feature(thickness=thickness or {"parameter": "p_wall"})],
        parameters=[WALL_PARAMETER],
    )


def claim(**kwargs) -> ShapeClaim:
    return ShapeClaim(profile=ProfileKind.RECTANGLE, openings=[], solids=1, **kwargs)


def test_a_hollow_part_built_hollow_agrees():
    assert disagreements(validate_canonical(hollow_document()), claim(wall="p_wall")) == []


def test_a_part_read_as_hollow_and_built_solid_is_caught():
    """The check the wall exists for, and the only one that catches this.

    A document that forgot the shell builds a billet: the outline is right, the
    openings are right, the body count is right, the bounding box is right, and the
    part weighs four times what the drawing says.
    """
    found = disagreements(validate_canonical(document([block()])), claim(wall="p_wall"))

    assert [item.code for item in found] == ["WALL_PARAMETER"]
    assert found[0].built == "no shell"


def test_a_wall_built_from_a_literal_has_lost_the_name_the_drawing_gave_it():
    found = disagreements(validate_canonical(hollow_document(thickness=3.0)),
                          claim(wall="p_wall"))

    assert [item.code for item in found] == ["WALL_PARAMETER"]
    assert "literal" in found[0].detail


def test_a_wall_built_from_the_wrong_parameter_is_named():
    value = document(
        [block(distance={"parameter": "p_depth"}),
         shell_feature(thickness={"parameter": "p_depth"})],
        parameters=[{"id": "p_depth", "type": "length", "unit": "mm", "value": 40.0,
                     "status": "confirmed"}],
    )
    found = disagreements(validate_canonical(value), claim(wall="p_wall"))

    assert [item.code for item in found] == ["WALL_PARAMETER"]
    assert found[0].built == "p_depth"


def test_a_reader_who_saw_no_wall_does_not_contradict_a_document_that_shells():
    """Silence is not a claim, here as everywhere in the claim (POSTMVP-016).

    A section view that did not show the wall is a reading that says nothing about it,
    and a claim that says nothing agrees with either. The check exists for the drawing
    that plainly gives a wall thickness against a document that ignored it.
    """
    assert disagreements(validate_canonical(hollow_document()), claim()) == []


def test_a_shell_changes_nothing_else_the_claim_counts():
    """A hollowed part is the same outline, the same openings and the same one solid.

    Which is the whole problem, stated as a test: every other field of the claim is
    satisfied by the wrong part.
    """
    hollow = validate_canonical(hollow_document())
    solid = validate_canonical(document([block()]))
    stated = ShapeClaim(profile=ProfileKind.RECTANGLE, openings=[], solids=1)

    assert disagreements(hollow, stated) == disagreements(solid, stated) == []


def test_a_disabled_shell_is_a_document_that_does_not_hollow():
    """`enabled: false` means "not this one", and the claim reads it that way.

    A shell switched off is exactly the billet case above, and a claim that named a
    wall should say so rather than being satisfied by a feature that will not run.
    """
    value = hollow_document()
    value["features"][1]["enabled"] = False
    found = disagreements(validate_canonical(value), claim(wall="p_wall"))

    assert [item.code for item in found] == ["WALL_PARAMETER"]


def test_the_wall_and_the_thickness_are_different_questions():
    """`thickness` is how deep the part is; `wall` is how much of it is material.

    Both name a parameter, and a document can get one right and the other wrong. An
    enclosure whose depth is `p_depth` and whose wall is a literal contradicts one and
    satisfies the other.
    """
    value = document(
        [block(distance={"parameter": "p_depth"}), shell_feature(thickness=3.0)],
        parameters=[{"id": "p_depth", "type": "length", "unit": "mm", "value": 40.0,
                     "status": "confirmed"}],
    )
    found = disagreements(
        validate_canonical(value),
        ShapeClaim(profile=ProfileKind.RECTANGLE, openings=[], solids=1,
                   thickness="p_depth", wall="p_wall"),
    )

    assert [item.code for item in found] == ["WALL_PARAMETER"]


def test_a_hollow_part_can_still_have_openings_read_off_the_drawing():
    """The two are independent: a wall says how much material, an opening says a hole.

    A vented enclosure has both, and neither check should be confused by the other.
    """
    value = document([
        {**block(),
         "inputs": {**block()["inputs"],
                    "sketch": {**block()["inputs"]["sketch"],
                               "inner": [{"type": "circle", "center": [0.0, 0.0],
                                          "radius": 5.0}]}}},
        shell_feature(),
    ], parameters=[WALL_PARAMETER])
    value["features"][1]["inputs"]["thickness"] = {"parameter": "p_wall"}

    stated = ShapeClaim(
        profile=ProfileKind.RECTANGLE,
        openings=[OpeningClaim(kind="round", count=1, through=True)],
        solids=1,
        wall="p_wall",
    )
    assert disagreements(validate_canonical(value), stated) == []
