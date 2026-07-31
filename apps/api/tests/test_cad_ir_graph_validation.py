"""Everything here is rejected before a COM object exists.

The value of each case is that it fails with a typed reason at validation
time, rather than as a half-built model on the owner's machine.
"""

import pytest

from cad_ir.canonical import CAD_IR_SCHEMA, CAD_IR_VERSION
from cad_ir.canonical_validator import validate_canonical
from cad_ir.errors import CadIrValidationError


def base_feature(**overrides) -> dict:
    return {
        "id": "feature.base",
        "type": "solid.extrude",
        "depends_on": [],
        "produces": [{"id": "body.main", "kind": "solid_body"}],
        "inputs": {
            "sketch": {
                "id": "sketch.base",
                "plane": {"on": "base", "plane": "XY"},
                "outer": {
                    "type": "rectangle",
                    "center": [0.0, 0.0],
                    "width": {"parameter": "param.width"},
                    "height": 30.0,
                },
            },
            "direction": "+Z",
            "distance": 8.0,
        },
        **overrides,
    }


def cut_feature(**overrides) -> dict:
    return {
        "id": "feature.hole",
        "type": "cut.extrude",
        "depends_on": ["feature.base"],
        "produces": [],
        "inputs": {
            "sketch": {
                "id": "sketch.hole",
                "plane": {"on": "base", "plane": "XY"},
                "outer": {"type": "circle", "center": [0.0, 0.0], "radius": 2.5},
            },
            "direction": "+Z",
            "through_all": True,
            "source_body": {"result": "body.main"},
        },
        **overrides,
    }


def document(**overrides) -> dict:
    return {
        "schema": CAD_IR_SCHEMA,
        "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm"},
        "parameters": [{"id": "param.width", "type": "length", "value": 60.0, "unit": "mm"}],
        "features": [base_feature(), cut_feature()],
        "expectations": [
            {"id": "expect.bodies", "type": "body_count", "value": 1},
            {
                "id": "expect.bounds",
                "type": "bounding_box",
                "size_mm": {"x": 60.0, "y": 30.0, "z": 8.0},
                "tolerance_mm": 0.05,
            },
        ],
        "metadata": {"generator": "fixture", "generator_version": "1.0"},
        **overrides,
    }


def codes(callable_) -> set[str]:
    with pytest.raises(CadIrValidationError) as caught:
        callable_()
    return {issue.code for issue in caught.value.issues}


def test_a_well_formed_document_passes():
    parsed = validate_canonical(document())

    assert len(parsed.features) == 2
    assert parsed.features[1].inputs.source_body.result == "body.main"


# --- version gate ----------------------------------------------------------


def test_a_document_with_no_version_is_rejected_before_anything_is_read():
    broken = document()
    del broken["schema_version"]

    assert codes(lambda: validate_canonical(broken)) == {"CAD_IR_VERSION_MISSING"}


def test_a_newer_version_is_named_as_such_rather_than_called_invalid():
    """A build from the future may use a field this one would silently ignore.
    "Too new" tells an operator to upgrade; "invalid" sends them hunting."""
    assert codes(lambda: validate_canonical(document(schema_version="1.8"))) == {
        "CAD_IR_VERSION_TOO_NEW"
    }
    assert codes(lambda: validate_canonical(document(schema_version="2.0"))) == {
        "CAD_IR_VERSION_TOO_NEW"
    }


def test_a_legacy_version_is_told_to_normalise_rather_than_simply_refused():
    with pytest.raises(CadIrValidationError) as caught:
        validate_canonical(document(schema_version="0.1.0"))
    issue = caught.value.issues[0]
    assert issue.code == "CAD_IR_VERSION_UNSUPPORTED"
    assert "normalised" in issue.message


def test_an_unrecognisable_version_is_unsupported():
    assert codes(lambda: validate_canonical(document(schema_version="banana"))) == {
        "CAD_IR_VERSION_UNSUPPORTED"
    }


# --- feature graph ---------------------------------------------------------


def test_duplicate_feature_ids_are_rejected():
    duplicated = document(features=[base_feature(), base_feature()])

    assert "FEATURE_ID_DUPLICATE" in codes(lambda: validate_canonical(duplicated))


def test_a_missing_dependency_is_named():
    broken = document(features=[base_feature(), cut_feature(depends_on=["feature.ghost"])])

    assert "FEATURE_DEPENDENCY_MISSING" in codes(lambda: validate_canonical(broken))


def test_a_feature_cannot_depend_on_itself():
    broken = document(features=[base_feature(depends_on=["feature.base"])])

    assert "FEATURE_SELF_REFERENCE" in codes(lambda: validate_canonical(broken))


def test_a_dependency_cycle_is_detected():
    first = base_feature(depends_on=["feature.hole"])
    second = cut_feature(depends_on=["feature.base"])

    assert "FEATURE_DEPENDENCY_CYCLE" in codes(
        lambda: validate_canonical(document(features=[first, second]))
    )


def test_a_dependency_declared_after_its_dependent_is_rejected():
    """Features build in array order, so a dependency further down the list
    would be built after the feature that needs it."""
    reordered = document(features=[cut_feature(), base_feature()])

    assert "FEATURE_ORDER_INVALID" in codes(lambda: validate_canonical(reordered))


def test_a_result_that_no_feature_produces_is_rejected():
    broken = document(
        features=[
            base_feature(produces=[]),
            cut_feature(),
        ]
    )

    assert "FEATURE_RESULT_UNAVAILABLE" in codes(lambda: validate_canonical(broken))


def test_using_a_result_without_depending_on_its_producer_is_rejected():
    """Reachability, not just existence: the reference is only meaningful if
    the producing feature is guaranteed to have run."""
    broken = document(features=[base_feature(), cut_feature(depends_on=[])])

    assert "FEATURE_DEPENDENCY_MISSING" in codes(lambda: validate_canonical(broken))


def test_two_features_cannot_produce_the_same_result():
    broken = document(
        features=[
            base_feature(),
            cut_feature(produces=[{"id": "body.main", "kind": "solid_body"}]),
        ]
    )

    assert "FEATURE_ID_DUPLICATE" in codes(lambda: validate_canonical(broken))


# --- parameters ------------------------------------------------------------


def test_an_unknown_parameter_reference_is_rejected():
    broken = document(parameters=[])

    assert "PARAMETER_NOT_FOUND" in codes(lambda: validate_canonical(broken))


def test_an_unresolved_parameter_cannot_be_built_with():
    """An unresolved value is a question nobody answered. Building with it
    would silently invent a dimension."""
    broken = document(
        parameters=[
            {"id": "param.width", "type": "length", "value": 60.0, "unit": "mm", "status": "unresolved"}
        ]
    )

    assert "UNRESOLVED_PARAMETER_USED" in codes(lambda: validate_canonical(broken))


def test_a_disabled_feature_may_still_reference_an_unresolved_parameter():
    tolerated = document(
        parameters=[
            {"id": "param.width", "type": "length", "value": 60.0, "unit": "mm", "status": "unresolved"}
        ],
        features=[base_feature(enabled=False), cut_feature(depends_on=[])],
    )
    tolerated["features"][1]["inputs"].pop("source_body")

    assert validate_canonical(tolerated).features[0].enabled is False


def test_duplicate_parameter_ids_are_rejected():
    broken = document(
        parameters=[
            {"id": "param.width", "type": "length", "value": 60.0, "unit": "mm"},
            {"id": "param.width", "type": "length", "value": 61.0, "unit": "mm"},
        ]
    )

    assert "DUPLICATE_ID" in codes(lambda: validate_canonical(broken))


# --- expectations ----------------------------------------------------------


def test_a_document_without_verifiable_expectations_is_rejected():
    """Without them an independent verifier has nothing to check the produced
    solid against, and a wrong model looks exactly like a right one."""
    assert codes(lambda: validate_canonical(document(expectations=[]))) == {
        "REQUIRED_EXPECTATION_MISSING"
    }


# --- execution details -----------------------------------------------------


@pytest.mark.parametrize(
    "smuggled",
    [
        r"C:\Users\Zelentwagen\model.m3d",
        r"\\server\share\part",
        "../../etc/passwd",
        "run build.ps1",
        "powershell -c rebuild",
        "python3 build.py",
        "com_handle 0x00ff12ab",
        "face_index: 17",
        "edge id = 4",
    ],
)
def test_execution_details_are_rejected_wherever_free_text_is_allowed(smuggled):
    broken = document()
    broken["parameters"][0]["name"] = smuggled

    assert "EXECUTION_DETAIL_PRESENT" in codes(lambda: validate_canonical(broken))


def test_ordinary_descriptive_text_is_not_mistaken_for_a_command():
    for innocent in ("Plate width", "Ширина пластины", "hole pitch (30 mm)", "top face"):
        fine = document()
        fine["parameters"][0]["name"] = innocent
        assert validate_canonical(fine).parameters[0].name == innocent


def test_every_issue_is_reported_rather_than_only_the_first():
    """A repair agent given one error at a time needs one round trip per
    mistake; given all of them it can fix the document once."""
    broken = document(
        parameters=[],
        features=[base_feature(depends_on=["feature.ghost"]), cut_feature(depends_on=[])],
        expectations=[],
    )

    with pytest.raises(CadIrValidationError) as caught:
        validate_canonical(broken)
    assert len(caught.value.issues) >= 4
