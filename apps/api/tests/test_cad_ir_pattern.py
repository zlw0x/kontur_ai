"""CAD-IR 1.6 patterns and mirror.

Six holes could already be written as six circles with six sets of coordinates, so
what a pattern adds is not geometry — it is a *stated count*. Everything below is
about that count: what the contract refuses because it would make the count a lie,
and how a shape claim compares the count the document states against the one the
drawing was read as.

That last part is the milestone's real point. A pattern is the first operation the
reading stage can actually ask for: "six round openings" is something a drawing shows
and a claim can carry, unlike a rounded corner.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cad_ir.canonical import CAD_IR_SCHEMA, CAD_IR_VERSION, FeatureType
from cad_ir.canonical_validator import validate_canonical
from cad_ir.errors import CadIrValidationError
from cad_ir.pattern import PatternFeature, PatternInputs, instance_count
from cad_ir.shape_claim import ShapeClaim, disagreements

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir"


def flange() -> dict:
    return json.loads((FIXTURES / "patterned-flange.v1_10.json").read_text("utf-8"))


def feature(value: dict, name: str) -> dict:
    for item in value["features"]:
        if item["id"] == name:
            return item
    raise AssertionError(f"no feature {name}")


def linear(**overrides) -> dict:
    spec = {"kind": "linear", "direction": "+X", "spacing_mm": 20.0, "count": 4}
    spec.update(overrides)
    return spec


def inputs(**overrides) -> dict:
    value = {"of": "feature.hole", "pattern": linear()}
    value.update(overrides)
    return value


def codes(value: dict) -> set[str]:
    with pytest.raises(CadIrValidationError) as raised:
        validate_canonical(value)
    return {issue.code for issue in raised.value.issues}


# --- what a document may say ----------------------------------------------


def test_a_linear_pattern_names_a_feature_a_direction_and_a_count():
    parsed = PatternInputs(**inputs())
    assert parsed.of == "feature.hole"
    assert parsed.pattern.count == 4
    assert instance_count(parsed) == 4


def test_a_circular_pattern_states_the_step_rather_than_a_total():
    """Six at 60°, not six spanning 360°.

    A total angle has two defensible readings for a closed circle — six instances 60°
    apart, or six spanning 360° with the last on top of the first — and a document
    meaning one and read as the other builds a plausible wrong part.
    """
    parsed = PatternInputs(
        **inputs(pattern={"kind": "circular", "axis": "axis.z", "through": [0.0, 0.0, 0.0],
                          "step_deg": 60.0, "count": 6})
    )
    assert parsed.pattern.step_deg == 60.0
    assert instance_count(parsed) == 6


def test_a_mirror_is_one_reflection_about_a_named_plane():
    parsed = PatternInputs(**inputs(pattern={"kind": "mirror", "plane": "YZ"}))
    assert instance_count(parsed) == 2


def test_a_spacing_and_a_step_may_be_parameters():
    parsed = PatternInputs(**inputs(pattern=linear(spacing_mm={"parameter": "pitch"})))
    assert parsed.pattern.spacing_mm.parameter == "pitch"


def test_a_skipped_instance_lowers_the_count_the_part_ends_up_with():
    assert instance_count(PatternInputs(**inputs(skip=[2]))) == 3


# --- what it may not ------------------------------------------------------


def test_a_pattern_of_one_is_not_a_pattern():
    with pytest.raises(ValidationError):
        PatternInputs(**inputs(pattern=linear(count=1)))


@pytest.mark.parametrize("spacing", [0.0, -5.0])
def test_a_zero_or_negative_spacing_is_refused(spacing):
    """Every instance on top of the original is a boolean with itself."""
    with pytest.raises(ValidationError):
        PatternInputs(**inputs(pattern=linear(spacing_mm=spacing)))


@pytest.mark.parametrize("step", [0.0, 360.0, 720.0])
def test_a_step_that_is_no_step_is_refused(step):
    with pytest.raises(ValidationError):
        PatternInputs(
            **inputs(pattern={"kind": "circular", "axis": "axis.z", "through": [0.0, 0.0, 0.0],
                              "step_deg": step, "count": 4})
        )


def test_the_original_may_not_be_skipped():
    """Instance zero is the source feature's own position.

    A document that wants it gone should disable the feature; skipping it here would
    make a pattern quietly delete the thing it repeats.
    """
    with pytest.raises(ValidationError):
        PatternInputs(**inputs(skip=[0]))


def test_skipping_every_repeat_leaves_a_feature_that_does_nothing():
    """The same rule an edge blend has, for the same reason (ADR-026).

    A pattern that adds no instance is valid, builds, and is indistinguishable from a
    document that never asked for one.
    """
    with pytest.raises(ValidationError) as raised:
        PatternInputs(**inputs(pattern=linear(count=3), skip=[1, 2]))
    assert "repeats nothing" in str(raised.value)


def test_an_instance_beyond_the_count_cannot_be_skipped():
    with pytest.raises(ValidationError):
        PatternInputs(**inputs(pattern=linear(count=3), skip=[7]))


def test_a_mirror_has_no_instances_to_skip():
    with pytest.raises(ValidationError):
        PatternInputs(**inputs(pattern={"kind": "mirror", "plane": "XY"}, skip=[1]))


def test_a_pattern_produces_nothing():
    with pytest.raises(ValidationError):
        PatternFeature(
            id="feature.row",
            type="feature.pattern",
            inputs=inputs(),
            produces=[{"id": "body.copies", "kind": "solid_body"}],
        )


# --- the feature it repeats ------------------------------------------------


def test_the_fixture_is_a_valid_document():
    document = validate_canonical(flange())
    kinds = [feature.type for feature in document.features]
    assert kinds.count(FeatureType.PATTERN) == 4


def test_a_pattern_of_a_feature_nobody_declared_is_refused():
    value = flange()
    feature(value, "feature.bolt_circle")["inputs"]["of"] = "feature.absent"
    assert "FEATURE_DEPENDENCY_MISSING" in codes(value)


def test_a_pattern_must_depend_on_what_it_repeats():
    """The graph is where the build order comes from.

    A pattern that used a feature without depending on it would be correct only for
    as long as nobody reordered the array.
    """
    value = flange()
    feature(value, "feature.bolt_circle")["depends_on"] = ["feature.plate"]
    assert "FEATURE_DEPENDENCY_MISSING" in codes(value)


def test_a_pattern_of_a_disabled_feature_is_refused():
    """Five holes around a hole that is not there.

    It builds. Every instance lands at an offset from a position nothing occupies, and
    the part has five holes where the drawing shows six — which is why this is a
    document-level refusal rather than something the engine discovers.
    """
    value = flange()
    feature(value, "feature.bolt_hole")["enabled"] = False
    assert "FEATURE_DISABLED_SOURCE" in codes(value)


def test_disabling_the_pattern_as_well_is_a_document_that_means_it():
    value = flange()
    feature(value, "feature.bolt_hole")["enabled"] = False
    feature(value, "feature.bolt_circle")["enabled"] = False
    value["expectations"] = [
        item for item in value["expectations"] if item["id"] != "inv_bolt_holes"
    ]
    value["expectations"] = [
        item if item["id"] != "inv_holes" else {**item, "value": 6}
        for item in value["expectations"]
    ]
    assert validate_canonical(value)


# --- what a claim can now say ----------------------------------------------


def test_a_bolt_circle_is_six_openings_to_whoever_read_the_drawing():
    """The count the document states, compared with the count off the drawing.

    Twelve openings: four mounting holes, six bolt holes, two slots. The document
    spells out three cuts and four patterns; the drawing shows twelve holes. This is
    the first operation where a claim and a document have something to disagree about
    that neither invented.
    """
    document = validate_canonical(flange())
    claim = ShapeClaim(
        profile="rectangle",
        openings=[{"kind": "round", "count": 10}, {"kind": "slot", "count": 2}],
        thickness="plate_thickness",
    )
    assert disagreements(document, claim) == []


def test_a_pattern_that_repeats_the_wrong_number_of_times_contradicts_the_claim():
    value = flange()
    feature(value, "feature.bolt_circle")["inputs"]["pattern"]["count"] = 8
    found = disagreements(
        validate_canonical(value),
        ShapeClaim(
            profile="rectangle",
            openings=[{"kind": "round", "count": 10}, {"kind": "slot", "count": 2}],
        ),
    )
    assert [item.code for item in found] == ["OPENING_COUNT"]
    assert "12 round" in found[0].built


def test_instances_that_coincide_are_caught_here_and_nowhere_else():
    """Twelve at 60° is six holes drilled twice.

    The geometry is identical to the correct part, so every measurement passes: the
    volume, the face counts and the mesh genus all agree. The claim is the only thing
    that compares what the document *says* against what the drawing said, so it is the
    only thing that can notice.
    """
    value = flange()
    bolts = feature(value, "feature.bolt_circle")["inputs"]["pattern"]
    bolts["count"] = 12
    found = disagreements(
        validate_canonical(value),
        ShapeClaim(
            profile="rectangle",
            openings=[{"kind": "round", "count": 10}, {"kind": "slot", "count": 2}],
        ),
    )
    assert [item.code for item in found] == ["OPENING_COUNT"]


def test_a_grid_multiplies_and_a_claim_counts_the_product():
    """Two by two is four, and a claim that read four agrees with a document
    that writes one hole and two patterns of two."""
    document = validate_canonical(flange())
    claim = ShapeClaim(profile="rectangle", openings=[{"kind": "round", "count": 4}])
    found = disagreements(document, claim)
    # Six bolt holes and two slots are also openings, so the claim is short by eight
    # rather than wrong about the grid.
    assert [item.code for item in found] == ["OPENING_COUNT"]
    assert "4 round" in found[0].claimed
    assert "10 round" in found[0].built


def test_a_patterned_boss_is_counted_as_lumps_of_material():
    value = flange()
    value["features"].append({
        "id": "feature.pad", "type": "solid.extrude", "enabled": True,
        "depends_on": ["feature.plate"], "produces": [],
        "inputs": {
            "direction": "+Z", "distance": 3.0,
            "sketch": {
                "id": "sketch.pad", "plane": {"on": "base", "plane": "XY"},
                "outer": {"type": "circle", "center": [0.0, 30.0], "radius": 5.0},
                "inner": [], "construction": [], "constraints": [], "dimensions": [],
            },
        },
    })
    value["features"].append({
        "id": "feature.pads", "type": "feature.pattern", "enabled": True,
        "depends_on": ["feature.pad"], "produces": [],
        "inputs": {
            "of": "feature.pad",
            "pattern": {"kind": "linear", "direction": "+X", "spacing_mm": 20.0, "count": 3},
            "skip": [],
        },
    })
    document = validate_canonical(value)
    openings = [{"kind": "round", "count": 10}, {"kind": "slot", "count": 2}]
    # One plate and three pads is four lumps of material.
    assert disagreements(
        document, ShapeClaim(profile="rectangle", openings=openings, solids=4)
    ) == []
    assert [
        item.code
        for item in disagreements(
            document, ShapeClaim(profile="rectangle", openings=openings, solids=2)
        )
    ] == ["SOLID_COUNT"]
