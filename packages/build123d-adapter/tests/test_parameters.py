"""Resolving a document's parameters to numbers.

`Parameters` had no tests of its own — it was exercised only through whatever the
adapter happened to build, so every branch of `resolve` was reachable and unproven.

The 1.11 half is ADR-034's arithmetic. `resolve` is the only place in the engine where
a `Scalar` becomes a float, which is why two new scalar forms could be added without
touching any of its twenty-four call sites — and it is also why the recursion had no
test until now. The rows below are the table from
`docs/acceptance/POSTMVP-016-runs-2-6-*`: the dimensions a reading stage put in a
document with a citation to the drawing, which the geometry then restated as a
literal because the contract gave it nowhere to go.

Two branches of `Parameters.of` are deliberately absent from this file: they refuse a
parameter defined as another parameter, and one with no value at all. Both are
unreachable — `Parameter.value` is a plain required `float` in the canonical model, so
the document cannot carry either. They are left standing rather than tested against a
hand-built object, which would be a test of the test.

Nothing here needs a CAD kernel: it is arithmetic and refusals.
"""

from __future__ import annotations

import pytest
from cad_engine_build123d.errors import CadEngineError
from cad_engine_build123d.parameters import Parameters
from cad_ir.base import ParameterRef, ScalarNegation, ScalarQuotient
from pydantic import ValidationError


def parameters(**values: float) -> Parameters:
    return Parameters(values)


def named(name: str) -> ParameterRef:
    return ParameterRef(parameter=name)


def half(name: str) -> ScalarQuotient:
    return ScalarQuotient(divide=named(name), by=2.0)


# --- what the class already promised -----------------------------------------


def test_a_number_resolves_to_itself():
    assert parameters().resolve(12.5, "a distance") == 12.5
    assert parameters().resolve(7, "a distance") == 7.0


def test_a_reference_resolves_to_the_value():
    assert parameters(p_depth=8.0).resolve(named("p_depth"), "a depth") == 8.0


def test_a_reference_to_a_parameter_the_document_does_not_define_is_refused():
    with pytest.raises(CadEngineError) as raised:
        parameters(p_depth=8.0).resolve(named("p_absent"), "a depth")

    assert raised.value.code == "PARAMETER_UNRESOLVED"
    assert "p_absent" in raised.value.safe_message


def test_a_boolean_is_not_a_number():
    """`True` is an `int` in Python and 1.0 would be a plausible distance. The check
    that stops it predates these tests and had nothing holding it in place."""
    with pytest.raises(CadEngineError) as raised:
        parameters().resolve(True, "a distance")

    assert raised.value.code == "CAD_IR_INVALID"


def test_a_string_is_not_a_number():
    with pytest.raises(CadEngineError) as raised:
        parameters().resolve("40", "a distance")

    assert raised.value.code == "CAD_IR_INVALID"


# --- CAD-IR 1.11: the two derived forms --------------------------------------


@pytest.mark.parametrize(
    ("parameter", "value", "expected", "why"),
    [
        ("outer_diameter", 80.0, 40.0, "the flange contour takes a radius"),
        ("hole_diameter", 6.0, 3.0, "so does a hole"),
        ("hole_pcd", 60.0, 30.0, "a pitch circle diameter states the centres"),
    ],
)
def test_a_diameter_drives_a_radius(parameter, value, expected, why):
    assert parameters(**{parameter: value}).resolve(half(parameter), why) == expected


def test_one_parameter_drives_both_sides_of_a_symmetric_outline():
    """The lever-plate's row in that table, and the one a division cannot reach.

    `cap_radius` = 15 means y = +15 *and* y = −15. Before ADR-034 a document
    referenced the parameter on one side and wrote a literal on the other, which is a
    symmetry that stops being one as soon as the parameter changes.
    """
    values = parameters(cap_radius=15.0)
    top = values.resolve(named("cap_radius"), "the top of the cap")
    bottom = values.resolve(ScalarNegation(negate=named("cap_radius")), "the bottom")

    assert (top, bottom) == (15.0, -15.0)
    assert top == -bottom


def test_the_two_forms_compose():
    """Half a diameter, the other way — the near edge of a centred outline."""
    node = ScalarNegation(negate=half("plate_width"))

    assert parameters(plate_width=40.0).resolve(node, "the near edge") == -20.0


def test_a_derived_scalar_still_names_a_parameter_the_document_must_define():
    with pytest.raises(CadEngineError) as raised:
        parameters(p_depth=8.0).resolve(half("p_absent"), "a radius")

    assert raised.value.code == "PARAMETER_UNRESOLVED"
    assert "p_absent" in raised.value.safe_message


def test_a_derived_scalar_bottoms_out_in_a_literal_too():
    """`divide` takes a `Scalar`, so a bare number is legal underneath it. It says
    nothing a literal would not, and refusing it would be a rule about spelling
    rather than about the part."""
    assert parameters().resolve(ScalarQuotient(divide=80.0, by=2.0), "a radius") == 40.0


# --- what the contract refuses ------------------------------------------------


@pytest.mark.parametrize("by", [0.0, -0.0, float("inf"), float("nan")])
def test_a_divisor_that_is_not_a_finite_non_zero_constant_is_refused(by):
    """Refused in the contract rather than survived in the engine: a division by zero
    reaching `resolve` would be an infinity the geometry is then built from."""
    with pytest.raises(ValidationError):
        ScalarQuotient(divide=named("p_depth"), by=by)


def test_a_divisor_may_not_be_a_parameter():
    """One dimension divided by another is a relationship the drawing did not state."""
    with pytest.raises(ValidationError):
        ScalarQuotient(divide=named("p_depth"), by={"parameter": "p_other"})


def test_a_scalar_may_not_nest_deeper_than_three_operations():
    """The bound exists because the nodes are recursive and a document is written by a
    model: nothing else stops a tower a thousand deep from being schema-valid."""
    third = ScalarNegation(negate=ScalarQuotient(divide=half("p_depth"), by=2.0))

    with pytest.raises(ValidationError):
        ScalarQuotient(divide=third, by=2.0)


def test_a_derived_scalar_carries_nothing_else():
    with pytest.raises(ValidationError):
        ScalarQuotient(divide=named("p_depth"), by=2.0, times=3.0)
