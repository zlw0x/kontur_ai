"""Geometry is named by what it means, never by an index (ADR-019).

Ported from the C# resolver suite. Like it, these run on descriptors alone and
need no CAD library — which is the property that makes the matching layer worth
keeping separate from the reading layer in the first place.

The cases that matter are the ambiguous ones. A selector that quietly picks one
of two equally good faces builds a different part on a different day, and no
later check would notice.
"""

import pytest
from cad_ir.selectors import FaceSelector

from cad_engine_build123d.errors import CadEngineError
from cad_engine_build123d.selectors import require_one, resolve_faces
from cad_engine_build123d.descriptors import Box, FaceDescriptor


def face(
    face_id,
    surface_type="planar",
    area=100.0,
    centroid=(0.0, 0.0, 0.0),
    z_min=0.0,
    z_max=0.0,
    normal=(0.0, 0.0, 1.0),
    radius=None,
    adjacent=(),
):
    return FaceDescriptor(
        id=face_id,
        surface_type=surface_type,
        area_mm2=area,
        centroid=centroid,
        bounds=Box((-10.0, -10.0, z_min), (10.0, 10.0, z_max)),
        normal=normal,
        radius_mm=radius,
        adjacent_surface_types=tuple(adjacent),
        adjacent_face_count=len(adjacent),
    )


def selector(where, cardinality="exactly_one", selector_id="sel.target"):
    return FaceSelector(
        id=selector_id,
        kind="face",
        from_result="body.main",
        where=where,
        cardinality=cardinality,
    )


def plate_faces():
    """A plate: a top, a bottom, four sides and a hole's cylinder."""
    return [
        face("top", z_min=8.0, z_max=8.0, normal=(0, 0, 1), area=600.0),
        face("bottom", z_min=0.0, z_max=0.0, normal=(0, 0, -1), area=600.0),
        face("side.left", normal=(-1, 0, 0), z_max=8.0, area=240.0),
        face("side.right", normal=(1, 0, 0), z_max=8.0, area=240.0),
        face("side.front", normal=(0, -1, 0), z_max=8.0, area=480.0),
        face("side.back", normal=(0, 1, 0), z_max=8.0, area=480.0),
        face("hole", surface_type="cylindrical", normal=None, radius=2.5, z_max=8.0, area=126.0),
    ]


# --- what a selector is for --------------------------------------------------


def test_the_top_face_is_named_by_meaning_and_found():
    resolution = resolve_faces(
        selector(
            {
                "surface_type": "planar",
                "normal": {"parallel_to": "axis.z", "direction": "positive"},
                "position": {"extreme_along": "axis.z", "extreme": "maximum"},
            }
        ),
        plate_faces(),
    )

    assert resolution.satisfied
    assert [item.id for item in resolution.matched] == ["top"]


def test_a_cylinder_is_found_by_its_radius():
    resolution = resolve_faces(
        selector(
            {"surface_type": "cylindrical", "radius_mm": {"value": 2.5, "tolerance": 0.01}}
        ),
        plate_faces(),
    )

    assert [item.id for item in resolution.matched] == ["hole"]


# --- the refusals ------------------------------------------------------------


def test_two_equally_good_faces_are_ambiguous_rather_than_arbitrary():
    """The case the whole design exists for. Predicates filter and never score,
    so a tie is reported as a tie."""
    faces = [
        face("hole.left", surface_type="cylindrical", normal=None, radius=2.5),
        face("hole.right", surface_type="cylindrical", normal=None, radius=2.5),
    ]

    resolution = resolve_faces(selector({"surface_type": "cylindrical"}), faces)

    assert not resolution.satisfied
    assert resolution.failure_code == "SELECTOR_AMBIGUOUS"


def test_a_predicate_that_matches_nothing_says_so():
    resolution = resolve_faces(selector({"surface_type": "spherical"}), plate_faces())

    assert resolution.failure_code == "SELECTOR_NO_MATCH"


def test_the_trace_says_which_clause_removed_what():
    """The difference between "found nothing" and knowing which clause was
    wrong."""
    resolution = resolve_faces(
        selector({"surface_type": "planar", "area_mm2": {"value": 9999.0, "tolerance": 0.1}}),
        plate_faces(),
    )

    assert [(step.predicate, step.before, step.after) for step in resolution.trace] == [
        ("surface_type", 7, 6),
        ("area_mm2", 6, 0),
    ]


def test_a_failure_carries_its_trace_into_the_error():
    with pytest.raises(CadEngineError) as caught:
        require_one(
            resolve_faces(selector({"surface_type": "spherical"}), plate_faces()),
            selector({"surface_type": "spherical"}),
        )

    assert caught.value.code == "SELECTOR_NO_MATCH"
    assert "surface_type 7 -> 0" in caught.value.safe_message


# --- how the predicates behave ----------------------------------------------


def test_an_extreme_is_a_ranking_over_what_survived_not_a_test_on_one_face():
    """Applied after the other predicates on purpose: ranking the wrong
    population would pick the highest face of a set the document excluded."""
    faces = [
        face("high.cylinder", surface_type="cylindrical", normal=None, z_max=20.0),
        face("low.plane", z_max=8.0),
    ]

    resolution = resolve_faces(
        selector(
            {
                "surface_type": "planar",
                "position": {"extreme_along": "axis.z", "extreme": "maximum"},
            }
        ),
        faces,
    )

    assert [item.id for item in resolution.matched] == ["low.plane"]


def test_faces_at_the_same_extreme_tie_rather_than_one_winning_by_noise():
    faces = [face("one", z_max=8.0), face("two", z_max=8.0 + 1e-9)]

    resolution = resolve_faces(
        selector({"position": {"extreme_along": "axis.z", "extreme": "maximum"}}),
        faces,
    )

    assert resolution.failure_code == "SELECTOR_AMBIGUOUS"
    assert len(resolution.matched) == 2


def test_a_face_with_no_measurable_normal_never_matches_a_normal_predicate():
    """A cylinder has no single normal. Treating "unknown" as "close enough"
    would pick it for a reason that is not true of it."""
    resolution = resolve_faces(
        selector({"normal": {"parallel_to": "axis.z", "direction": "positive"}}),
        [face("hole", surface_type="cylindrical", normal=None)],
    )

    assert resolution.failure_code == "SELECTOR_NO_MATCH"


def test_a_missing_measurement_never_matches_a_measured_predicate():
    resolution = resolve_faces(
        selector({"radius_mm": {"value": 2.5, "tolerance": 0.01}}),
        [face("flat", radius=None)],
    )

    assert resolution.failure_code == "SELECTOR_NO_MATCH"


def test_adjacency_needs_every_named_surface_type_to_be_present():
    faces = [
        face("with.cylinder", adjacent=("cylindrical", "planar")),
        face("without", adjacent=("planar",)),
    ]

    resolution = resolve_faces(
        selector({"adjacent": {"contains_surface_types": ["cylindrical"]}}), faces
    )

    assert [item.id for item in resolution.matched] == ["with.cylinder"]


# --- cardinality -------------------------------------------------------------


def test_zero_or_one_tolerates_nothing_and_refuses_two():
    empty = resolve_faces(
        selector({"surface_type": "spherical"}, cardinality="zero_or_one"), plate_faces()
    )
    assert empty.satisfied

    both = resolve_faces(
        selector({"surface_type": "planar"}, cardinality="zero_or_one"), plate_faces()
    )
    assert both.failure_code == "SELECTOR_AMBIGUOUS"


def test_one_or_more_wants_at_least_one():
    assert resolve_faces(
        selector({"surface_type": "planar"}, cardinality="one_or_more"), plate_faces()
    ).satisfied
    assert not resolve_faces(
        selector({"surface_type": "spherical"}, cardinality="one_or_more"), plate_faces()
    ).satisfied


def test_all_accepts_whatever_survived_including_nothing():
    assert resolve_faces(
        selector({"surface_type": "spherical"}, cardinality="all"), plate_faces()
    ).satisfied


def test_exactly_n_separates_too_few_from_too_many():
    faces = plate_faces()
    too_few = resolve_faces(
        selector({"surface_type": "cylindrical"}, cardinality={"type": "exactly_n", "value": 3}),
        faces,
    )
    too_many = resolve_faces(
        selector({"surface_type": "planar"}, cardinality={"type": "exactly_n", "value": 2}),
        faces,
    )

    assert too_few.failure_code == "SELECTOR_NO_MATCH"
    assert too_many.failure_code == "SELECTOR_AMBIGUOUS"


# --- what a centre is ------------------------------------------------------


def test_a_hole_is_centred_on_its_axis_and_not_on_its_own_surface():
    """The defect POSTMVP-010 found in the layer POSTMVP-005 built.

    `topology.py` filled `centroid` from build123d's `center()`, which defaults to
    `CenterOf.GEOMETRY` — the middle of the surface's parameter domain. For a planar
    face that is the centroid; for a cylinder it is a point *on* the surface, so the
    centre of a Ø8 hole at x = -50 came back as x = -54.

    Nothing failed, which is what made it worth a test: a document selecting "the face
    centred on x = -50" simply did not match it, and a document selecting x = -54
    matched something no drawing describes. Needs the CAD library, so it sits with the
    reading half rather than the matching half.
    """
    build123d = pytest.importorskip("build123d", reason="the CAD engine is not installed")
    from cad_engine_build123d.topology import read_edges, read_faces

    plate = build123d.Box(60, 40, 10)
    bore = build123d.Pos(-20, 5, 0) * build123d.Cylinder(radius=4, height=20)
    part = (plate - bore).clean()

    wall = next(
        face for face in read_faces(part) if face.surface_type == "cylindrical"
    )
    assert (round(wall.centroid[0], 6), round(wall.centroid[1], 6)) == (-20.0, 5.0)

    rim = next(edge for edge in read_edges(part) if edge.curve_type == "circle")
    assert (round(rim.centroid[0], 6), round(rim.centroid[1], 6)) == (-20.0, 5.0)


# --- the two upward faces a stepped part has ---------------------------------


def stepped_faces() -> list:
    """A flanged bushing's flats: a shoulder facing up, and the sleeve's end above it.

    The topology a real run stopped on. "Planar face facing +Z" matches both, and a
    selection that declares `exactly_one` cannot choose between them — which is the
    refusal `SELECTOR_AMBIGUOUS` exists to give rather than a coin toss.
    """
    return [
        face("flange.bottom", normal=(0, 0, -1), z_max=0.0, area=1017.0),
        face("flange.shoulder", normal=(0, 0, 1), z_max=5.0, area=565.0),
        face("sleeve.end", normal=(0, 0, 1), z_max=30.0, area=251.0),
    ]


UPWARD = {"surface_type": "planar",
          "normal": {"parallel_to": "axis.z", "direction": "positive"}}
TOPMOST = {**UPWARD, "position": {"extreme_along": "axis.z", "extreme": "maximum"}}


def test_the_upward_face_of_a_stepped_part_is_ambiguous():
    """The measured reason the profile offers a second selection."""
    resolution = resolve_faces(selector(UPWARD), stepped_faces())

    assert not resolution.satisfied
    assert sorted(item.id for item in resolution.matched) == [
        "flange.shoulder", "sleeve.end"]


def test_the_topmost_upward_face_of_a_stepped_part_is_one_face():
    resolution = resolve_faces(selector(TOPMOST), stepped_faces())

    assert resolution.satisfied
    assert [item.id for item in resolution.matched] == ["sleeve.end"]


def test_the_topmost_selection_still_names_the_only_face_of_a_plain_part():
    """A plate has one upward face and both selections find it, so the second offer
    cannot make a document that was right into a document that is wrong."""
    for where in (UPWARD, TOPMOST):
        resolution = resolve_faces(selector(where), plate_faces())
        assert [item.id for item in resolution.matched] == ["top"], where
