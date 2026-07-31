"""CAD-IR 1.5 fillet and chamfer.

The contract's half of a blend is the naming. Whether a 6 mm round fits on the
corner it names is geometry and lives in the adapter; what can be decided by
reading the document is whether the selector could match nothing, whether an
asymmetric chamfer says which side its first distance belongs to, and whether the
body it blends exists at all.

The rule worth reading twice is the cardinality one. `all` and `zero_or_one` are
refused, and they are the two that look harmless: both let a selector match nothing,
and a blend of no edges is a feature that silently does not happen. The document is
valid, the build succeeds, every expectation still passes, and the drawing's rounded
corners are square. Nothing downstream can tell that apart from a document that
never asked for a fillet.
"""

import pytest
from pydantic import ValidationError

from cad_ir.blend import ChamferFeature, ChamferInputs, FilletFeature, FilletInputs
from cad_ir.canonical import CAD_IR_VERSION, CAD_IR_SCHEMA, FeatureType
from cad_ir.canonical_validator import validate_canonical
from cad_ir.errors import CadIrValidationError


def edges(**overrides) -> dict:
    selector = {
        "id": "selector.corners",
        "kind": "edge",
        "from_result": "body.main",
        "cardinality": {"type": "exactly_n", "value": 4},
        "where": {"curve_type": "line", "direction_parallel_to": "axis.z"},
    }
    selector.update(overrides)
    return selector


def top_face() -> dict:
    return {
        "id": "selector.top",
        "kind": "face",
        "from_result": "body.main",
        "cardinality": "exactly_one",
        "where": {"surface_type": "planar", "normal": {"parallel_to": "axis.z"}},
    }


def fillet(**overrides) -> dict:
    inputs = {"edges": edges(), "radius": 6.0}
    inputs.update(overrides)
    return {"id": "feature.corners", "type": "feature.fillet", "inputs": inputs}


def chamfer(**overrides) -> dict:
    inputs = {"edges": edges(), "distance": 2.0}
    inputs.update(overrides)
    return {"id": "feature.deburr", "type": "feature.chamfer", "inputs": inputs}


# --- what a document may say ----------------------------------------------


def test_a_fillet_names_edges_and_a_radius():
    parsed = FilletFeature(**fillet())
    assert parsed.type is FeatureType.FILLET
    assert parsed.inputs.edges.id == "selector.corners"
    assert parsed.inputs.radius == 6.0
    # A blend makes nothing, so there is nothing for a later feature to name.
    assert parsed.produces == []


def test_a_radius_may_be_a_parameter_like_any_other_dimension():
    """The whole point of naming it: a corner radius that moves with the drawing."""
    parsed = FilletFeature(**fillet(radius={"parameter": "corner_radius"}))
    assert parsed.inputs.radius.parameter == "corner_radius"


def test_a_chamfer_is_symmetric_unless_it_says_otherwise():
    parsed = ChamferFeature(**chamfer())
    assert parsed.type is FeatureType.CHAMFER
    assert (parsed.inputs.second_distance, parsed.inputs.angle_deg) == (None, None)
    assert parsed.inputs.measured_from is None


def test_an_asymmetric_chamfer_may_be_two_distances_or_a_distance_and_an_angle():
    two = ChamferInputs(**chamfer(second_distance=3.0, measured_from=top_face())["inputs"])
    assert two.second_distance == 3.0
    angled = ChamferInputs(**chamfer(angle_deg=30.0, measured_from=top_face())["inputs"])
    assert angled.angle_deg == 30.0


@pytest.mark.parametrize(
    "cardinality",
    ["exactly_one", "one_or_more", {"type": "exactly_n", "value": 4}],
)
def test_the_cardinalities_that_cannot_match_nothing_are_allowed(cardinality):
    assert FilletInputs(**{"edges": edges(cardinality=cardinality), "radius": 1.0})


# --- what it may not ------------------------------------------------------


@pytest.mark.parametrize("cardinality", ["all", "zero_or_one", {"type": "exactly_n", "value": 0}])
def test_a_blend_that_could_match_no_edges_is_refused(cardinality):
    """The failure this rule exists for is a *successful* build of the wrong part.

    `all` reads as "every edge that matches" and means "however many, including
    none". A document that rounds nothing and says so is a document nobody can
    distinguish from one that rounded four corners, until a customer opens the file.
    """
    with pytest.raises(ValidationError) as raised:
        FilletInputs(**{"edges": edges(cardinality=cardinality), "radius": 1.0})
    assert "no edges" in str(raised.value) or "does nothing" in str(raised.value)


@pytest.mark.parametrize("radius", [0.0, -1.0])
def test_a_literal_radius_must_be_positive(radius):
    with pytest.raises(ValidationError):
        FilletInputs(**{"edges": edges(), "radius": radius})


def test_a_chamfer_is_not_given_two_distances_and_an_angle():
    with pytest.raises(ValidationError):
        ChamferInputs(
            **{
                "edges": edges(),
                "distance": 2.0,
                "second_distance": 3.0,
                "angle_deg": 30.0,
                "measured_from": top_face(),
            }
        )


def test_an_asymmetric_chamfer_must_name_the_face_it_measures_from():
    """Two distances say nothing until something says which side is which.

    The kernel's answer to "which side?" is whichever face it visited first, so a
    document that leaves it out has not described a part — it has described two.
    """
    with pytest.raises(ValidationError) as raised:
        ChamferInputs(**{"edges": edges(), "distance": 2.0, "second_distance": 3.0})
    assert "measured from" in str(raised.value)


def test_a_symmetric_chamfer_must_not_name_one():
    """The same distance on both faces, so naming one of them says nothing.

    Refused rather than ignored: build123d refuses it too, and a field that is
    silently dropped is a field an author believes did something.
    """
    with pytest.raises(ValidationError):
        ChamferInputs(**{"edges": edges(), "distance": 2.0, "measured_from": top_face()})


def test_a_chamfer_is_measured_from_exactly_one_face():
    with pytest.raises(ValidationError):
        ChamferInputs(
            **{
                "edges": edges(),
                "distance": 2.0,
                "second_distance": 3.0,
                "measured_from": {**top_face(), "cardinality": "one_or_more"},
            }
        )


@pytest.mark.parametrize("angle", [0.0, 90.0, 120.0])
def test_a_chamfer_angle_is_between_the_two_degenerate_cases(angle):
    """0° removes nothing and 90° cuts parallel to the face it is measured from."""
    with pytest.raises(ValidationError):
        ChamferInputs(
            **{
                "edges": edges(),
                "distance": 2.0,
                "angle_deg": angle,
                "measured_from": top_face(),
            }
        )


def test_a_blend_produces_nothing():
    with pytest.raises(ValidationError):
        FilletFeature(**{**fillet(), "produces": [{"id": "body.rounded", "kind": "solid_body"}]})


# --- the body a selector names --------------------------------------------


def plate(*features, **overrides) -> dict:
    """A plate, plus whatever features the test wants after it."""
    value = {
        "schema": CAD_IR_SCHEMA,
        "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm"},
        "parameters": [
            {"id": "thickness", "type": "length", "value": 10.0, "unit": "mm"},
        ],
        "features": [
            {
                "id": "feature.plate",
                "type": "solid.extrude",
                "depends_on": [],
                "produces": [{"id": "body.main", "kind": "solid_body"}],
                "inputs": {
                    "sketch": {
                        "id": "sketch.plate",
                        "plane": {"on": "base", "plane": "XY"},
                        "outer": {
                            "type": "rectangle",
                            "center": [0.0, 0.0],
                            "width": 60.0,
                            "height": 40.0,
                        },
                    },
                    "direction": "+Z",
                    "distance": {"parameter": "thickness"},
                },
            },
            *features,
        ],
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": 60.0, "y": 40.0, "z": 10.0}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }
    value.update(overrides)
    return value


def codes(value: dict) -> set[str]:
    with pytest.raises(CadIrValidationError) as raised:
        validate_canonical(value)
    return {issue.code for issue in raised.value.issues}


def test_a_plate_with_a_fillet_on_it_is_a_valid_document():
    document = validate_canonical(
        plate({**fillet(radius={"parameter": "corner_radius"}), "depends_on": ["feature.plate"]},
              parameters=[
                  {"id": "thickness", "type": "length", "value": 10.0, "unit": "mm"},
                  {"id": "corner_radius", "type": "length", "value": 6.0, "unit": "mm"},
              ])
    )
    assert [feature.type for feature in document.features] == [
        FeatureType.SOLID_EXTRUDE,
        FeatureType.FILLET,
    ]


def test_a_selector_naming_a_body_nothing_builds_is_refused():
    """`from_result` was unchecked until 1.5, and a fillet is *entirely* a selector.

    A document naming a body no feature produces would otherwise be blended against
    whatever the engine happened to be holding, which is the closest thing to an
    index this contract has left.
    """
    blend = {**fillet(edges=edges(from_result="body.other")), "depends_on": ["feature.plate"]}
    assert codes(plate(blend)) == {"FEATURE_RESULT_UNAVAILABLE"}


def test_a_selector_naming_a_body_built_later_is_refused():
    """Features are built in array order, so "later" is "not yet"."""
    value = plate({**fillet(), "depends_on": ["feature.plate"]})
    value["features"] = list(reversed(value["features"]))
    assert "FEATURE_RESULT_UNAVAILABLE" in codes(value)


def test_two_selectors_may_not_share_a_name():
    """A selector id is what a resolution trace and a repair prompt name."""
    value = plate(
        {**fillet(), "depends_on": ["feature.plate"]},
        {**chamfer(), "depends_on": ["feature.plate"]},
    )
    assert codes(value) == {"DUPLICATE_ID"}
