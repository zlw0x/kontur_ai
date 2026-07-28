"""Selector contracts.

The failure this layer exists to prevent is silent: `edge 17` still validates
and still builds after a dimension changes, it is just a different edge. So
these tests are mostly about what the contract refuses to express.
"""

import pytest
from pydantic import ValidationError

from cad_ir.selectors import (
    Axis,
    Cardinality,
    Convexity,
    CurveType,
    EdgePredicates,
    EdgeSelector,
    ExactlyN,
    FacePredicates,
    FaceSelector,
    Measurement,
    ResolutionStep,
    SelectorErrorCode,
    SelectorResolution,
    SurfaceType,
    cardinality_failure,
    satisfies_cardinality,
)


def top_face_selector(**overrides) -> dict:
    """The top face of a plate, named by what makes it the top face."""
    return {
        "id": "selector.top_face",
        "kind": "face",
        "from_result": "body.main",
        "where": {
            "surface_type": "planar",
            "normal": {"parallel_to": "axis.z", "direction": "positive"},
            "position": {"extreme_along": "axis.z", "extreme": "maximum"},
        },
        "cardinality": "exactly_one",
        **overrides,
    }


def hole_rim_selector(**overrides) -> dict:
    return {
        "id": "selector.hole_rims",
        "kind": "edge",
        "from_result": "body.main",
        "where": {
            "curve_type": "circle",
            "radius_mm": {"value": 2.5, "tolerance": 0.01},
            "adjacent": {"contains_surface_types": ["planar", "cylindrical"]},
        },
        "cardinality": {"type": "exactly_n", "value": 2},
        **overrides,
    }


def test_a_face_is_named_by_meaning_rather_than_position_in_a_list():
    selector = FaceSelector(**top_face_selector())

    assert selector.where.surface_type is SurfaceType.PLANAR
    assert selector.where.normal.parallel_to is Axis.Z
    assert selector.where.position.extreme is not None
    assert selector.cardinality is Cardinality.EXACTLY_ONE


def test_an_edge_selector_describes_the_rim_without_knowing_where_it_is():
    selector = EdgeSelector(**hole_rim_selector())

    assert selector.where.curve_type is CurveType.CIRCLE
    assert selector.where.radius_mm.matches(2.505)
    assert not selector.where.radius_mm.matches(2.6)
    assert isinstance(selector.cardinality, ExactlyN)
    assert selector.cardinality.value == 2


def test_an_index_has_nowhere_to_go():
    """The whole point. A closed schema means a raw topology index cannot be
    expressed even by a caller who wants to."""
    for smuggled in ({"edge_index": 17}, {"face_id": 4}, {"index": 0}):
        broken = hole_rim_selector()
        broken["where"].update(smuggled)
        with pytest.raises(ValidationError):
            EdgeSelector(**broken)


def test_a_selector_with_no_predicates_is_refused():
    """An empty predicate set matches every face on the body. With
    `exactly_one` that is a coin toss dressed as a selector."""
    with pytest.raises(ValidationError):
        FaceSelector(**top_face_selector(where={}))
    with pytest.raises(ValidationError):
        EdgeSelector(**hole_rim_selector(where={}))


def test_a_tolerance_is_required_rather_than_defaulted():
    """Comparing floating-point geometry for equality is a bug waiting for a
    rebuild; letting the tolerance default hides that choice."""
    with pytest.raises(ValidationError):
        Measurement(value=2.5)
    with pytest.raises(ValidationError):
        Measurement(value=2.5, tolerance=-0.1)
    assert Measurement(value=2.5, tolerance=0).matches(2.5)


def test_a_measurement_must_be_finite():
    with pytest.raises(ValidationError):
        Measurement(value=float("inf"), tolerance=0.1)
    with pytest.raises(ValidationError):
        Measurement(value=float("nan"), tolerance=0.1)


def test_a_normal_predicate_must_name_an_axis_and_not_contradict_itself():
    with pytest.raises(ValidationError):
        FaceSelector(**top_face_selector(where={"surface_type": "planar", "normal": {}}))
    with pytest.raises(ValidationError):
        FaceSelector(
            **top_face_selector(
                where={
                    "surface_type": "planar",
                    "normal": {"parallel_to": "axis.z", "perpendicular_to": "axis.x"},
                }
            )
        )


def test_a_direction_without_an_axis_means_nothing():
    with pytest.raises(ValidationError):
        FaceSelector(
            **top_face_selector(where={"surface_type": "planar", "normal": {"direction": "positive"}})
        )


def test_a_position_predicate_states_an_extreme_or_a_centre_completely():
    with pytest.raises(ValidationError):
        FaceSelector(**top_face_selector(where={"position": {"extreme_along": "axis.z"}}))
    with pytest.raises(ValidationError):
        FaceSelector(**top_face_selector(where={"position": {"extreme": "maximum"}}))
    with pytest.raises(ValidationError):
        FaceSelector(**top_face_selector(where={"position": {}}))

    fine = FaceSelector(
        **top_face_selector(
            where={"position": {"center_along": "axis.x", "center_value_mm": {"value": 15, "tolerance": 0.01}}}
        )
    )
    assert fine.where.position.center_along is Axis.X


def test_predicates_that_cannot_apply_to_the_stated_geometry_are_refused():
    with pytest.raises(ValidationError):
        FaceSelector(
            **top_face_selector(
                where={"surface_type": "planar", "radius_mm": {"value": 3, "tolerance": 0.01}}
            )
        )
    # A curved face has a different normal at every point.
    with pytest.raises(ValidationError):
        FaceSelector(
            **top_face_selector(
                where={"surface_type": "cylindrical", "normal": {"parallel_to": "axis.z"}}
            )
        )
    with pytest.raises(ValidationError):
        EdgeSelector(
            **hole_rim_selector(
                where={"curve_type": "line", "radius_mm": {"value": 3, "tolerance": 0.01}}
            )
        )


def test_a_cylindrical_face_may_be_found_by_radius():
    selector = FaceSelector(
        **top_face_selector(
            where={"surface_type": "cylindrical", "radius_mm": {"value": 2.5, "tolerance": 0.01}}
        )
    )

    assert selector.where.radius_mm.matches(2.5)


def test_convexity_distinguishes_an_outer_rim_from_an_inner_one():
    selector = EdgeSelector(
        **hole_rim_selector(where={"curve_type": "circle", "convexity": "concave"})
    )

    assert selector.where.convexity is Convexity.CONCAVE


# --- cardinality -----------------------------------------------------------


@pytest.mark.parametrize(
    "cardinality,count,expected",
    [
        (Cardinality.EXACTLY_ONE, 1, True),
        (Cardinality.EXACTLY_ONE, 0, False),
        (Cardinality.EXACTLY_ONE, 2, False),
        (Cardinality.ZERO_OR_ONE, 0, True),
        (Cardinality.ZERO_OR_ONE, 1, True),
        (Cardinality.ZERO_OR_ONE, 2, False),
        (Cardinality.ONE_OR_MORE, 0, False),
        (Cardinality.ONE_OR_MORE, 7, True),
        (Cardinality.ALL, 0, True),
        (Cardinality.ALL, 7, True),
    ],
)
def test_cardinality_is_checked_rather_than_assumed(cardinality, count, expected):
    assert satisfies_cardinality(cardinality, count) is expected


def test_exactly_n_says_what_the_document_claims_about_the_part():
    four_holes = ExactlyN(type="exactly_n", value=4)

    assert satisfies_cardinality(four_holes, 4)
    # A fifth hole means the document no longer describes the part; that the
    # count is wrong is the useful signal, not something to absorb.
    assert not satisfies_cardinality(four_holes, 5)


def test_the_failure_code_distinguishes_the_three_disappointments():
    """Nothing matched, too many matched, and "not that many" call for three
    different repairs."""
    assert cardinality_failure(Cardinality.EXACTLY_ONE, 0) is SelectorErrorCode.NO_MATCH
    assert cardinality_failure(Cardinality.EXACTLY_ONE, 2) is SelectorErrorCode.AMBIGUOUS
    assert cardinality_failure(Cardinality.ZERO_OR_ONE, 3) is SelectorErrorCode.AMBIGUOUS
    assert (
        cardinality_failure(ExactlyN(type="exactly_n", value=4), 3)
        is SelectorErrorCode.CARDINALITY_MISMATCH
    )


# --- resolution trace ------------------------------------------------------


def test_a_trace_records_what_each_predicate_eliminated():
    resolution = SelectorResolution(
        selector_id="selector.top_face",
        kind="face",
        initial_candidates=6,
        steps=[
            {"predicate": "surface_type=planar", "before": 6, "after": 4},
            {"predicate": "normal parallel +Z", "before": 4, "after": 2},
            {"predicate": "maximum position on Z", "before": 2, "after": 1},
        ],
        result_count=1,
        satisfied=True,
    )

    assert [step.after for step in resolution.steps] == [4, 2, 1]
    assert resolution.error_code is None


def test_a_filter_cannot_grow_the_candidate_set():
    with pytest.raises(ValidationError):
        ResolutionStep(predicate="surface_type=planar", before=2, after=3)


def test_an_unsatisfied_resolution_must_say_why():
    with pytest.raises(ValidationError):
        SelectorResolution(
            selector_id="selector.top_face",
            kind="face",
            initial_candidates=6,
            result_count=2,
            satisfied=False,
        )

    explained = SelectorResolution(
        selector_id="selector.top_face",
        kind="face",
        initial_candidates=6,
        steps=[{"predicate": "surface_type=planar", "before": 6, "after": 2}],
        result_count=2,
        satisfied=False,
        error_code=SelectorErrorCode.AMBIGUOUS,
    )
    assert explained.error_code is SelectorErrorCode.AMBIGUOUS


def test_a_satisfied_resolution_carries_no_error_code():
    with pytest.raises(ValidationError):
        SelectorResolution(
            selector_id="selector.top_face",
            kind="face",
            initial_candidates=1,
            result_count=1,
            satisfied=True,
            error_code=SelectorErrorCode.NO_MATCH,
        )
