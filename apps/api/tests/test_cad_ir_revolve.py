"""CAD-IR 1.4 revolve.

The contract's job is the half of a revolve that can be decided by reading the
document: that it names an axis at all, that the axis is a line, that it names a
line of the sketch it belongs to, and that the angle is an angle. Whether the
profile actually describes a solid — whether it crosses the axis — is geometry,
needs the parameters resolved, and lives in the adapter with every other
geometric check.

The one thing this version deliberately does *not* offer is an inferred axis. The
roadmap allows one "at high confidence"; the contract has no field for it,
because an inferred axis is a guess nothing downstream can check. The profile is
valid either way and the build succeeds either way, and the difference between a
bush and a disc is only which line the profile went round.
"""

import pytest
from pydantic import ValidationError

from cad_ir.canonical import CAD_IR_VERSION, FeatureType
from cad_ir.canonical_validator import validate_canonical
from cad_ir.revolve import RevolveByConstructionLine, RevolveInputs, SolidRevolveFeature

CENTRE_LINE = {"type": "line", "id": "axis.centre", "start": [0.0, 0.0], "end": [0.0, 30.0]}


def section(**overrides) -> dict:
    """A bush's cross-section: a rectangle to the right of x = 0."""
    sketch = {
        "id": "sketch.section",
        "plane": {"on": "base", "plane": "XZ"},
        "outer": {
            "type": "rectangle",
            "id": "profile.section",
            "center": [10.0, 15.0],
            "width": 4.0,
            "height": 30.0,
        },
        "construction": [CENTRE_LINE],
    }
    sketch.update(overrides.pop("sketch", {}))
    return {
        "sketch": sketch,
        "axis": {"kind": "construction_line", "entity": "axis.centre"},
        **overrides,
    }


def feature(**overrides) -> dict:
    return {
        "id": "feature.bush",
        "type": "solid.revolve",
        "inputs": section(**overrides),
    }


# --- what the document may say --------------------------------------------


def test_a_revolve_names_its_axis_as_a_construction_line():
    parsed = SolidRevolveFeature(**feature())
    assert parsed.type is FeatureType.SOLID_REVOLVE
    assert isinstance(parsed.inputs.axis, RevolveByConstructionLine)
    # A full turn is the default, because it is what almost every drawing means.
    assert parsed.inputs.angle_deg == 360.0
    assert parsed.inputs.both_directions is False


def test_a_revolve_may_state_its_axis_as_two_points_instead():
    parsed = SolidRevolveFeature(
        **feature(axis={"kind": "points", "axis": {"start": [0.0, 0.0], "end": [0.0, 1.0]}})
    )
    assert parsed.inputs.axis.axis.end == [0.0, 1.0]


def test_an_axis_may_be_parametric_like_any_other_coordinate():
    """A centre line that grows with the part is what a parameter is for."""
    parsed = SolidRevolveFeature(
        **feature(
            axis={
                "kind": "points",
                "axis": {"start": [0.0, 0.0], "end": [0.0, {"parameter": "bush_height"}]},
            }
        )
    )
    assert parsed.inputs.axis.axis.end[1].parameter == "bush_height"


def test_a_partial_revolve_may_sweep_half_each_way():
    parsed = SolidRevolveFeature(**feature(angle_deg=90.0, both_directions=True))
    assert (parsed.inputs.angle_deg, parsed.inputs.both_directions) == (90.0, True)


# --- what it may not ------------------------------------------------------


def test_an_axis_of_two_identical_points_is_not_an_axis():
    with pytest.raises(ValidationError):
        RevolveInputs(
            **section(axis={"kind": "points", "axis": {"start": [1.0, 2.0], "end": [1.0, 2.0]}})
        )


def test_an_axis_must_name_a_construction_line_of_its_own_sketch():
    """Not a segment of the profile, and not a name from somewhere else.

    A profile revolved about one of its own sides is a drawing revolving part of
    itself, and a name that resolves to nothing is a document about a part that
    does not exist.
    """
    with pytest.raises(ValidationError):
        RevolveInputs(**section(axis={"kind": "construction_line", "entity": "profile.section"}))
    with pytest.raises(ValidationError):
        RevolveInputs(**section(axis={"kind": "construction_line", "entity": "axis.elsewhere"}))


def test_an_axis_must_name_a_line_rather_than_any_construction_entity():
    """A circle is construction geometry too, and it is not an axis."""
    circle = {"type": "circle", "id": "axis.centre", "center": [0.0, 0.0], "radius": 5.0}
    with pytest.raises(ValidationError):
        RevolveInputs(**section(sketch={"construction": [circle]}))


@pytest.mark.parametrize("angle", [0.0, -90.0, 360.5, 720.0])
def test_a_revolve_turns_more_than_nothing_and_at_most_once(angle):
    with pytest.raises(ValidationError):
        RevolveInputs(**section(angle_deg=angle))


def test_a_full_turn_in_both_directions_is_refused_as_a_contradiction():
    """Half of 360 each way is 360.

    Accepting it would change nothing about the solid and everything about what a
    reader believes the document says, which is the worst kind of accepted field.
    """
    with pytest.raises(ValidationError):
        RevolveInputs(**section(angle_deg=360.0, both_directions=True))


# --- the document as a whole ----------------------------------------------


def document(**overrides) -> dict:
    return {
        "schema": "cad-ai/cad-ir",
        "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm"},
        "parameters": [],
        "features": [
            {
                "id": "feature.bush",
                "type": "solid.revolve",
                "enabled": True,
                "depends_on": [],
                "produces": [{"id": "body.bush", "kind": "solid_body"}],
                "inputs": section(),
            }
        ],
        "expectations": [
            {
                "id": "expect.bounds",
                "type": "bounding_box",
                "size_mm": {"x": 24.0, "y": 24.0, "z": 30.0},
                "tolerance_mm": 0.05,
            },
            {"id": "expect.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1.0"},
        **overrides,
    }


def test_a_revolve_document_passes_the_trusted_gate():
    parsed = validate_canonical(document())
    assert [feature.type for feature in parsed.features] == [FeatureType.SOLID_REVOLVE]


def test_a_cut_revolve_declares_the_body_it_cuts_and_the_feature_that_made_it():
    """The same rule every cut obeys: a result is used only after it is produced,
    and only by a feature that says it depends on the producer."""
    doc = document()
    doc["features"].append(
        {
            "id": "feature.groove",
            "type": "cut.revolve",
            "enabled": True,
            "depends_on": ["feature.bush"],
            "produces": [],
            "inputs": {**section(), "source_body": {"result": "body.bush"}},
        }
    )
    parsed = validate_canonical(doc)
    assert parsed.features[1].type is FeatureType.CUT_REVOLVE

    orphaned = document()
    orphaned["features"].append(
        {
            "id": "feature.groove",
            "type": "cut.revolve",
            "enabled": True,
            "depends_on": [],
            "produces": [],
            "inputs": {**section(), "source_body": {"result": "body.bush"}},
        }
    )
    with pytest.raises(Exception) as refused:
        validate_canonical(orphaned)
    assert "FEATURE_DEPENDENCY_MISSING" in str(refused.value)
