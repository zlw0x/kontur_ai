"""Resolving a document's parameters to numbers.

`Parameters` had no tests of its own — it was exercised only through whatever the
adapter happened to build, so its two refusals (a parameter defined as another
parameter, a parameter with no value) were reachable and unproven. They are proven
here.

The rest of the file is the arithmetic a `ScaledParameterRef` does, and it is the
five rows of the table in `docs/acceptance/POSTMVP-016-runs-2-6-*` that made the
`PARAMETER_DRIVES_NOTHING` check unshippable. Each row is a parameter the reading
stage put in a document with a citation to the drawing, which the geometry then
restated as a literal because the contract gave it nowhere to go. Every row is a
number here.

Nothing in this file needs a CAD kernel: it is arithmetic and refusals.
"""

from __future__ import annotations

import pytest
from cad_ir.base import ParameterRef, ScaledParameterRef
from cad_engine_build123d.errors import CadEngineError
from cad_engine_build123d.parameters import Parameters
from pydantic import ValidationError


def parameters(**values: float) -> Parameters:
    return Parameters(values)


# --- what the class already promised -----------------------------------------


def test_a_number_resolves_to_itself():
    assert parameters().resolve(12.5, "a distance") == 12.5
    assert parameters().resolve(7, "a distance") == 7.0


def test_a_reference_resolves_to_the_value():
    assert parameters(p_depth=8.0).resolve(ParameterRef(parameter="p_depth"), "a depth") == 8.0


def test_a_reference_to_a_parameter_the_document_does_not_define_is_refused():
    with pytest.raises(CadEngineError) as raised:
        parameters(p_depth=8.0).resolve(ParameterRef(parameter="p_absent"), "a depth")

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


# --- a parameter times a constant -------------------------------------------


@pytest.mark.parametrize(
    ("parameter", "value", "times", "expected", "why"),
    [
        ("outer_diameter", 80.0, 0.5, 40.0, "the flange contour takes a radius"),
        ("hole_diameter", 6.0, 0.5, 3.0, "so does a hole"),
        ("hole_pcd", 60.0, 0.5, 30.0, "a pitch circle diameter states the centres"),
        ("cap_radius", 15.0, -1.0, -15.0, "the other side of a symmetric outline"),
        ("plate_width", 40.0, -0.5, -20.0, "the near edge of a centred rectangle"),
    ],
)
def test_the_five_dimensions_a_reading_could_not_drive(parameter, value, times, expected, why):
    scaled = ScaledParameterRef(parameter=parameter, times=times)

    assert parameters(**{parameter: value}).resolve(scaled, why) == expected


def test_one_parameter_can_now_drive_both_sides_of_a_symmetric_outline():
    """The lever-plate's row in that table, and the one no single factor solves.

    `cap_radius` = 15 means y = +15 *and* y = −15. Before this a document referenced
    the parameter on one side and wrote a literal on the other, which is a symmetry
    that stops being one as soon as the parameter changes.
    """
    values = parameters(cap_radius=15.0)
    top = values.resolve(ParameterRef(parameter="cap_radius"), "the top of the cap")
    bottom = values.resolve(
        ScaledParameterRef(parameter="cap_radius", times=-1.0), "the bottom of the cap"
    )

    assert (top, bottom) == (15.0, -15.0)
    assert top == -bottom


def test_a_scaled_reference_to_an_undefined_parameter_is_refused_like_a_plain_one():
    with pytest.raises(CadEngineError) as raised:
        parameters(p_depth=8.0).resolve(
            ScaledParameterRef(parameter="p_absent", times=0.5), "a radius"
        )

    assert raised.value.code == "PARAMETER_UNRESOLVED"


def test_a_factor_that_scales_a_part_out_of_range_is_refused():
    """The bound is on the *result*, not only on the factor: 999 999 × 999 999 is two
    legal numbers and a part the size of a county."""
    with pytest.raises(CadEngineError) as raised:
        parameters(p_big=900_000.0).resolve(
            ScaledParameterRef(parameter="p_big", times=100.0), "a distance"
        )

    assert raised.value.code == "PARAMETER_UNRESOLVED"
    assert "outside the range" in raised.value.safe_message


# --- what the form refuses to say at all ------------------------------------


def test_a_factor_of_one_is_a_plain_reference():
    """Two spellings of one part is what canonical form exists to prevent (ADR-018),
    and it is the whole reason this is a scaled reference rather than an expression."""
    with pytest.raises(ValidationError):
        ScaledParameterRef(parameter="p_depth", times=1.0)


def test_a_factor_of_zero_drives_nothing():
    with pytest.raises(ValidationError):
        ScaledParameterRef(parameter="p_depth", times=0.0)


@pytest.mark.parametrize("times", [1e6, -1e6, 2e6, float("inf"), float("nan")])
def test_a_factor_outside_the_bounds_is_refused(times):
    with pytest.raises(ValidationError):
        ScaledParameterRef(parameter="p_depth", times=times)


def test_a_scaled_reference_carries_nothing_else():
    with pytest.raises(ValidationError):
        ScaledParameterRef(parameter="p_depth", times=0.5, plus=3.0)


def test_it_is_not_in_scalar_yet_and_that_is_on_purpose():
    """The one test that will fail when the contract takes it, which is when it should
    be deleted along with the note in `base.py`. Until then a document cannot reach the
    branch above, and a reader of either file should not have to guess whether it can.
    """
    from cad_ir.base import Scalar
    from typing import get_args

    assert ScaledParameterRef not in get_args(Scalar)
