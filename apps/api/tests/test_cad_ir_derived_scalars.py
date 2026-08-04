"""Every size in the contract, stated through CAD-IR 1.11's arithmetic.

ADR-034 widened `Scalar` from two members to four. Nine range checks in this contract
were written against two, each in the same shape:

    if isinstance(value, ParameterRef):
        return                      # a promise about a number this module never sees
    if float(value) <= 0:
        raise ValueError(...)

Seven of them crashed. `float(ScalarQuotient(...))` raises `TypeError` **from inside a
pydantic validator**, which is not a refusal: it escapes as a raw type error, reaches
the caller as `SCHEMA_INVALID` carrying the message "float() argument must be a string
or a real number", and the check it was guarding never runs. So a document that drove a
fillet radius from a diameter was refused with a Python diagnostic, and one that drove a
wall thickness from a negative parameter was not checked at all.

`base.stated_number` is one function for the whole shape, so the next member of `Scalar`
cannot reintroduce it. This file is the guard: every scalar the contract range-checks,
accepted through the arithmetic, and the literal refusals still refusing.
"""

from __future__ import annotations

import pytest
from cad_ir.base import (
    ParameterRef,
    ScalarNegation,
    ScalarQuotient,
    negates,
    parameters_of,
    stated_number,
)
from cad_ir.blend import ChamferInputs, FilletInputs
from cad_ir.canonical import SolidExtrudeInputs
from cad_ir.pattern import CircularPattern, LinearPattern
from cad_ir.revolve import RevolveInputs
from cad_ir.shell import ShellInputs
from pydantic import ValidationError

#: Half of a stated overall dimension: the case ADR-034 exists for.
HALF = {"divide": {"parameter": "p_total"}, "by": 2.0}
#: And the other one, a symmetric pair.
TURNED = {"negate": {"parameter": "p_total"}}

FACES = {"id": "selector.top", "kind": "face", "from_result": "body.main",
         "cardinality": "exactly_one", "where": {"surface_type": "planar"}}
EDGES = {"id": "selector.corners", "kind": "edge", "from_result": "body.main",
         "cardinality": {"type": "exactly_n", "value": 4},
         "where": {"curve_type": "line"}}
SKETCH = {"id": "sketch.section", "plane": {"on": "base", "plane": "XY"},
          "outer": {"type": "rectangle", "center": [10.0, 5.0], "width": 4.0,
                    "height": 10.0, "rotation_deg": 0.0},
          "inner": [], "construction": [], "constraints": [], "dimensions": []}

#: Every size the contract checks a range on, and how to state one.
SIZES = {
    "fillet radius": lambda value: FilletInputs(edges=EDGES, radius=value),
    "chamfer distance": lambda value: ChamferInputs(edges=EDGES, distance=value),
    "chamfer second distance": lambda value: ChamferInputs(
        edges=EDGES, distance=1.0, second_distance=value,
        measured_from={"id": "selector.face", "kind": "face", "from_result": "body.main",
                       "cardinality": "exactly_one", "where": {"surface_type": "planar"}}),
    "shell thickness": lambda value: ShellInputs(faces=FACES, thickness=value),
    "pattern spacing": lambda value: LinearPattern(
        kind="linear", direction="+X", spacing_mm=value, count=3),
    "pattern step": lambda value: CircularPattern(
        kind="circular", axis="axis.z", through=[0.0, 0.0, 0.0], step_deg=value, count=3),
    "extrusion taper": lambda value: SolidExtrudeInputs(
        sketch=SKETCH, direction="+Z", distance=10.0, taper_deg=value),
    "revolve angle": lambda value: RevolveInputs(
        sketch=SKETCH, axis={"kind": "points", "axis": {"start": [0.0, 0.0], "end": [0.0, 30.0]}},
        angle_deg=value),
}


@pytest.mark.parametrize("name", sorted(SIZES))
@pytest.mark.parametrize("derived", [HALF, TURNED], ids=["quotient", "negation"])
def test_every_size_may_be_derived_from_a_parameter(name, derived):
    """Accepted, not crashed. Seven of these eight raised `TypeError` before the fix."""
    assert SIZES[name](derived) is not None


@pytest.mark.parametrize("name", sorted(SIZES))
def test_every_size_may_still_be_named_outright(name):
    assert SIZES[name]({"parameter": "p_total"}) is not None


# --- and the literal checks still fire ---------------------------------------


@pytest.mark.parametrize("size", [0.0, -1.0])
def test_a_literal_fillet_radius_must_still_be_positive(size):
    with pytest.raises(ValidationError):
        FilletInputs(edges=EDGES, radius=size)


@pytest.mark.parametrize("size", [0.0, -3.0])
def test_a_literal_wall_thickness_must_still_be_positive(size):
    with pytest.raises(ValidationError):
        ShellInputs(faces=FACES, thickness=size)


def test_a_literal_pattern_spacing_must_still_be_positive():
    with pytest.raises(ValidationError):
        LinearPattern(kind="linear", direction="+X", spacing_mm=0.0, count=3)


@pytest.mark.parametrize("step", [0.0, 360.0, -360.0])
def test_a_literal_pattern_step_is_still_bounded(step):
    with pytest.raises(ValidationError):
        CircularPattern(kind="circular", axis="axis.z", through=[0.0, 0.0, 0.0],
                        step_deg=step, count=3)


@pytest.mark.parametrize("taper", [90.0, -90.0])
def test_a_literal_taper_is_still_bounded(taper):
    with pytest.raises(ValidationError):
        SolidExtrudeInputs(sketch=SKETCH, direction="+Z", distance=10.0, taper_deg=taper)


# --- the three helpers, on their own ------------------------------------------


def scalar(value):
    """A parsed scalar from the shape a document writes it in."""
    if not isinstance(value, dict):
        return value
    if "divide" in value:
        return ScalarQuotient(divide=scalar(value["divide"]), by=value["by"])
    if "negate" in value:
        return ScalarNegation(negate=scalar(value["negate"]))
    return ParameterRef(**value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12.5, 12.5),
        (7, 7.0),
        ({"parameter": "p_total"}, None),
        (HALF, None),
        (TURNED, None),
        (None, None),
        # `True` is an `int` in Python and 1.0 would be a plausible size. A range check
        # that accepted it would compare a boolean against millimetres.
        (True, None),
    ],
)
def test_stated_number_is_the_literal_or_nothing(value, expected):
    assert stated_number(scalar(value)) == expected


def test_parameters_of_reads_through_the_arithmetic():
    assert parameters_of(ScalarQuotient(**HALF)) == {"p_total"}
    assert parameters_of(ScalarNegation(**TURNED)) == {"p_total"}
    assert parameters_of(ScalarNegation(negate=ScalarQuotient(**HALF))) == {"p_total"}
    assert parameters_of(40.0) == frozenset()


@pytest.mark.parametrize(
    ("value", "turned"),
    [
        (5.0, False),
        ({"parameter": "p_total"}, False),
        (HALF, False),
        (TURNED, True),
        ({"negate": {"negate": {"parameter": "p_total"}}}, False),
        ({"divide": {"parameter": "p_total"}, "by": -2.0}, True),
        ({"negate": {"divide": {"parameter": "p_total"}, "by": -2.0}}, False),
    ],
)
def test_negates_answers_every_spelling_of_a_sign(value, turned):
    assert negates(scalar(value)) is turned
