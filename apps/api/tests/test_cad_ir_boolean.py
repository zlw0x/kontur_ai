"""CAD-IR 1.7: bodies, and the booleans between them.

`source_body` has been in the contract since 1.1 and pointed at the only body there
was, so the engine could ignore it without anyone noticing. This version makes a body
a thing the document creates by name, targets by name and combines by name.

The rule that carries the most weight is the dullest: **a document that says nothing
behaves exactly as it did.** A feature with no `new_body` and no `source_body` still
fuses into the body being built, because the alternative — every solid feature making
its own body — would silently turn every multi-feature part written before 1.7 into a
multi-body one.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cad_ir.boolean import BooleanFeature, BooleanInputs, BooleanOp
from cad_ir.canonical import CAD_IR_SCHEMA, CAD_IR_VERSION, SolidExtrudeInputs
from cad_ir_fixtures import fixture

from cad_ir.canonical_validator import validate_canonical
from cad_ir.errors import CadIrValidationError
from cad_ir.shape_claim import ShapeClaim, disagreements



def bracket() -> dict:
    return fixture("boolean-bracket")


def feature(value: dict, name: str) -> dict:
    for item in value["features"]:
        if item["id"] == name:
            return item
    raise AssertionError(f"no feature {name}")


def codes(value: dict) -> set[str]:
    with pytest.raises(CadIrValidationError) as raised:
        validate_canonical(value)
    return {issue.code for issue in raised.value.issues}


def sketch() -> dict:
    return {
        "id": "sketch.block",
        "plane": {"on": "base", "plane": "XY"},
        "outer": {"type": "rectangle", "center": [0.0, 0.0], "width": 40.0, "height": 20.0},
    }


# --- what a document may say ----------------------------------------------


def test_a_feature_may_start_a_body_of_its_own():
    parsed = SolidExtrudeInputs(
        sketch=sketch(), direction="+Z", distance=10.0, new_body=True
    )
    assert parsed.new_body is True
    assert parsed.source_body is None


def test_saying_nothing_means_the_body_being_built():
    """The behaviour every document written before 1.7 relies on."""
    parsed = SolidExtrudeInputs(sketch=sketch(), direction="+Z", distance=10.0)
    assert parsed.new_body is False
    assert parsed.source_body is None


def test_a_boolean_names_a_target_and_at_least_one_tool():
    parsed = BooleanInputs(
        op="subtract", target={"result": "body.main"}, tools=[{"result": "body.punch"}]
    )
    assert parsed.op is BooleanOp.SUBTRACT
    assert parsed.keep_tools is False


def test_a_boolean_may_keep_its_tools():
    parsed = BooleanInputs(
        op="union",
        target={"result": "body.main"},
        tools=[{"result": "body.a"}, {"result": "body.b"}],
        keep_tools=True,
    )
    assert [item.result for item in parsed.tools] == ["body.a", "body.b"]


# --- what it may not ------------------------------------------------------


def test_a_feature_does_not_both_start_a_body_and_add_to_one():
    with pytest.raises(ValidationError):
        SolidExtrudeInputs(
            sketch=sketch(),
            direction="+Z",
            distance=10.0,
            new_body=True,
            source_body={"result": "body.main"},
        )


def test_a_body_is_not_both_the_target_and_a_tool():
    """Subtracting a body from itself is nothing; uniting it with itself is a no-op
    that reads as an operation."""
    with pytest.raises(ValidationError) as raised:
        BooleanInputs(
            op="subtract", target={"result": "body.main"}, tools=[{"result": "body.main"}]
        )
    assert "both the target and a tool" in str(raised.value)


def test_a_body_is_a_tool_once():
    with pytest.raises(ValidationError):
        BooleanInputs(
            op="union",
            target={"result": "body.main"},
            tools=[{"result": "body.a"}, {"result": "body.a"}],
        )


def test_a_boolean_needs_a_tool():
    with pytest.raises(ValidationError):
        BooleanInputs(op="union", target={"result": "body.main"}, tools=[])


def test_a_boolean_produces_nothing():
    """The result *is* the target body, under the name it already has."""
    with pytest.raises(ValidationError):
        BooleanFeature(
            id="feature.weld",
            type="feature.boolean",
            inputs={"op": "union", "target": {"result": "body.a"},
                    "tools": [{"result": "body.b"}]},
            produces=[{"id": "body.welded", "kind": "solid_body"}],
        )


# --- the document as a whole ----------------------------------------------


def test_the_fixture_is_a_valid_document():
    document = validate_canonical(bracket())
    assert [feature.id for feature in document.features] == [
        "feature.plate",
        "feature.rib",
        "feature.weld_rib",
        "feature.punch",
        "feature.bore",
        "feature.stud",
    ]


def test_a_body_nothing_can_name_is_refused():
    """A body with no name could never be cut, blended or combined.

    It would arrive in the delivered STEP as a lump with no history, and no selector
    could reach it to say anything about it.
    """
    feature(value := bracket(), "feature.rib")["produces"] = []
    assert "CAD_IR_INVALID" in codes(value)


def test_a_boolean_whose_target_no_feature_produces_is_refused():
    feature(value := bracket(), "feature.weld_rib")["inputs"]["target"] = {
        "result": "body.absent"
    }
    assert "FEATURE_RESULT_UNAVAILABLE" in codes(value)


def test_a_boolean_that_runs_before_its_tool_is_refused():
    value = bracket()
    order = [item["id"] for item in value["features"]]
    weld = order.index("feature.weld_rib")
    rib = order.index("feature.rib")
    value["features"][weld], value["features"][rib] = (
        value["features"][rib],
        value["features"][weld],
    )
    assert codes(value) & {"FEATURE_RESULT_UNAVAILABLE", "FEATURE_ORDER_INVALID"}


# --- what a claim says about lumps of material -----------------------------


def test_the_claim_still_counts_what_a_reader_counts():
    """`solids` is lumps of material as a drawing reader counts them.

    The bracket is a plate, a rib welded to it, a bore through it and a stud standing
    apart: three additive features, of which one was consumed by a boolean and one is
    a body of its own. A reader looking at the drawing counts three things that are
    made of metal, and that is what the claim carries — the *body* count is a
    different question, and `body_count` is the expectation that asks it.
    """
    document = validate_canonical(bracket())
    assert disagreements(
        document,
        ShapeClaim(
            profile="rectangle",
            openings=[{"kind": "round", "count": 1}],
            solids=3,
            thickness="plate_thickness",
        ),
    ) == []


def test_a_body_count_and_a_solid_claim_are_different_questions():
    """The document declares two bodies and the claim declares three solids.

    Both are right, and a milestone that conflated them would have had to break one:
    `body_count` is measured off the delivered file, and `solids` is what somebody
    counted on a drawing.
    """
    document = validate_canonical(bracket())
    bodies = next(
        item for item in document.expectations if str(item.type) == "body_count"
    )
    assert bodies.value == 2
    assert disagreements(
        document, ShapeClaim(profile="rectangle",
                             openings=[{"kind": "round", "count": 1}], solids=3)
    ) == []
