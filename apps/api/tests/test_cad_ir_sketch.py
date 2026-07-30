"""CAD-IR 1.2 sketch contracts.

What matters here is what cannot be written down. The contract's job is to make
the ambiguous cases unrepresentable, so the geometric validator in the adapter
only has to check things that are genuinely about geometry.
"""

import pytest
from pydantic import ValidationError

from cad_ir.canonical import CAD_IR_SCHEMA, CAD_IR_VERSION, CadIrDocument
from cad_ir.canonical_validator import validate_canonical
from cad_ir.errors import CadIrValidationError
from cad_ir.sketch import (
    ArcSegment,
    PathContour,
    RegularPolygonContour,
    Sketch,
    SlotContour,
    Sweep,
)

BASE_XY = {"on": "base", "plane": "XY"}


def sketch(**overrides) -> dict:
    return {
        "id": "sketch.base",
        "plane": BASE_XY,
        "outer": {"type": "rectangle", "center": [0.0, 0.0], "width": 60.0, "height": 30.0},
        **overrides,
    }


def document(*features, parameters=None) -> dict:
    return {
        "schema": CAD_IR_SCHEMA,
        "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "name": "part"},
        "parameters": parameters
        or [{"id": "param.depth", "type": "length", "value": 8.0, "unit": "mm"}],
        "features": list(features),
        "expectations": [
            {
                "id": "expect.bounds",
                "type": "bounding_box",
                "size_mm": {"x": 60.0, "y": 30.0, "z": 8.0},
                "tolerance_mm": 0.05,
            },
            {"id": "expect.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "fixture", "generator_version": "1.0"},
    }


def base_feature(sketch_body: dict, **overrides) -> dict:
    return {
        "id": "feature.base",
        "type": "solid.extrude",
        "produces": [{"id": "body.main", "kind": "solid_body"}],
        "inputs": {
            "sketch": sketch_body,
            "direction": "+Z",
            "distance": {"parameter": "param.depth"},
        },
        **overrides,
    }


# --- the shapes ------------------------------------------------------------


def test_a_profile_can_be_spelled_out_as_a_closed_path_of_lines_and_arcs():
    contour = PathContour(
        type="path",
        segments=[
            {"type": "line", "start": [-10.0, 3.0], "end": [10.0, 3.0]},
            {"type": "arc", "start": [10.0, 3.0], "end": [10.0, -3.0], "center": [10.0, 0.0], "sweep": "cw"},
            {"type": "line", "start": [10.0, -3.0], "end": [-10.0, -3.0]},
            {"type": "arc", "start": [-10.0, -3.0], "end": [-10.0, 3.0], "center": [-10.0, 0.0], "sweep": "cw"},
        ],
    )

    assert [segment.type for segment in contour.segments] == ["line", "arc", "line", "arc"]
    assert isinstance(contour.segments[1], ArcSegment)


def test_a_sweep_direction_is_required_because_the_endpoints_do_not_imply_it():
    """Two arcs share every endpoint and centre and differ only in which way
    round they go, so the direction is information the geometry lacks."""
    with pytest.raises(ValidationError):
        ArcSegment(type="arc", start=[1.0, 0.0], end=[-1.0, 0.0], center=[0.0, 0.0])


def test_a_slot_and_a_polygon_are_contours_in_their_own_right():
    assert SlotContour(type="slot", start=[-10.0, 0.0], end=[10.0, 0.0], radius=3.0).radius == 3.0
    polygon = RegularPolygonContour(
        type="regular_polygon", center=[0.0, 0.0], sides=6, circumradius=12.0
    )
    assert polygon.sides == 6
    assert polygon.rotation_deg == 0.0


def test_a_polygon_needs_at_least_three_sides():
    with pytest.raises(ValidationError):
        RegularPolygonContour(type="regular_polygon", center=[0.0, 0.0], sides=2, circumradius=12.0)


def test_a_path_of_one_segment_cannot_bound_a_region():
    with pytest.raises(ValidationError):
        PathContour(type="path", segments=[{"type": "line", "start": [0.0, 0.0], "end": [1.0, 0.0]}])


def test_a_coordinate_may_be_a_parameter_so_a_part_stays_parametric():
    parsed = Sketch(**sketch(outer={
        "type": "slot",
        "start": [{"parameter": "param.left"}, 0.0],
        "end": [{"parameter": "param.right"}, 0.0],
        "radius": {"parameter": "param.slot_radius"},
    }))

    assert parsed.outer.radius.parameter == "param.slot_radius"


# --- islands ---------------------------------------------------------------


def test_a_sketch_states_one_profile_and_its_islands():
    parsed = Sketch(**sketch(inner=[
        {"type": "circle", "center": [-15.0, 0.0], "radius": 2.5},
        {"type": "circle", "center": [15.0, 0.0], "radius": 2.5},
    ]))

    assert parsed.outer.type == "rectangle"
    assert len(parsed.inner) == 2


def test_an_island_inside_an_island_cannot_be_written_down():
    """Nesting deeper than one level is out of scope, and the shape of the
    contract is what enforces that rather than a validator rule: a contour has
    nowhere to put a contour."""
    with pytest.raises(ValidationError):
        Sketch(**sketch(inner=[{"type": "circle", "center": [0.0, 0.0], "radius": 5.0,
                                "inner": [{"type": "circle", "center": [0.0, 0.0], "radius": 1.0}]}]))


# --- construction geometry -------------------------------------------------


def test_construction_geometry_is_kept_apart_from_the_profile():
    parsed = Sketch(**sketch(construction=[
        {"type": "point", "id": "point.bolt_centre", "at": [0.0, 0.0]},
        {"type": "line", "id": "line.centre", "start": [-30.0, 0.0], "end": [30.0, 0.0]},
    ]))

    assert [entity.id for entity in parsed.construction] == ["point.bolt_centre", "line.centre"]
    assert parsed.outer.type == "rectangle"


def test_two_construction_entities_cannot_share_a_name():
    with pytest.raises(ValidationError):
        Sketch(**sketch(construction=[
            {"type": "point", "id": "point.a", "at": [0.0, 0.0]},
            {"type": "point", "id": "point.a", "at": [1.0, 0.0]},
        ]))


# --- planes ----------------------------------------------------------------


def test_a_sketch_can_sit_on_a_face_named_by_a_selector():
    parsed = Sketch(**sketch(plane={
        "on": "face",
        "face": {
            "id": "selector.top",
            "kind": "face",
            "from_result": "body.main",
            "cardinality": "exactly_one",
            "where": {
                "surface_type": "planar",
                "normal": {"parallel_to": "axis.z", "direction": "positive"},
                "position": {"extreme_along": "axis.z", "extreme": "maximum"},
            },
        },
    }))

    assert parsed.plane.on == "face"
    assert parsed.plane.face.id == "selector.top"


def test_a_sketch_plane_selector_must_resolve_to_exactly_one_face():
    """A sketch sits on one face. "One or more" would leave the build picking,
    which is the coin toss selectors exist to prevent."""
    with pytest.raises(ValidationError):
        Sketch(**sketch(plane={
            "on": "face",
            "face": {
                "id": "selector.sides",
                "kind": "face",
                "from_result": "body.main",
                "cardinality": "one_or_more",
                "where": {"surface_type": "planar"},
            },
        }))


def test_a_datum_plane_is_a_feature_and_a_sketch_refers_to_its_result():
    datum = {
        "id": "feature.raised",
        "type": "datum.plane.offset",
        "produces": [{"id": "plane.raised", "kind": "plane"}],
        "inputs": {"base": "XY", "offset_mm": 20.0},
    }
    boss = base_feature(
        sketch(plane={"on": "datum", "plane": {"result": "plane.raised"}}),
        id="feature.boss",
        depends_on=["feature.raised"],
    )

    parsed = validate_canonical(document(datum, boss))

    assert parsed.features[0].produces[0].kind.value == "plane"
    assert parsed.features[1].inputs.sketch.plane.plane.result == "plane.raised"


def test_a_datum_plane_feature_must_say_it_produces_a_plane():
    with pytest.raises(ValidationError):
        CadIrDocument(**document({
            "id": "feature.raised",
            "type": "datum.plane.offset",
            "produces": [{"id": "plane.raised", "kind": "solid_body"}],
            "inputs": {"base": "XY", "offset_mm": 20.0},
        }))


def test_a_sketch_on_an_unproduced_plane_is_rejected_by_the_graph_gate():
    """The plane reference goes through the same result check as a body
    reference, which is the whole reason a datum plane is a feature."""
    boss = base_feature(sketch(plane={"on": "datum", "plane": {"result": "plane.missing"}}))

    with pytest.raises(CadIrValidationError) as caught:
        validate_canonical(document(boss))
    assert "FEATURE_RESULT_UNAVAILABLE" in {issue.code for issue in caught.value.issues}


# --- what the contract deliberately does not check -------------------------


def test_the_contract_does_not_pretend_to_check_that_a_contour_closes():
    """Closure is geometry, it needs the parameters resolved, and it has to run
    on the machine that drives KOMPAS. A half-check here would give false
    confidence about where the real gate is; see ADR-020."""
    open_path = sketch(outer={
        "type": "path",
        "segments": [
            {"type": "line", "start": [0.0, 0.0], "end": [10.0, 0.0]},
            {"type": "line", "start": [10.0, 0.0], "end": [10.0, 10.0]},
        ],
    })

    assert Sketch(**open_path).outer.type == "path"


def test_the_sweep_vocabulary_is_closed():
    assert [item.value for item in Sweep] == ["ccw", "cw"]
