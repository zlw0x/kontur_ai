"""A constraint is an assertion about coordinates the document already states.

So the tests that matter are the refusals: a constraint that does not hold is a
document saying two different things about the same part, which in practice means
a misread drawing.

Ported from the C# suite this engine replaces, case for case. They run without
build123d installed — the checks work on numbers and know nothing about a kernel,
and a test file that needed OpenCascade to prove that would prove the opposite.
"""

import pytest
from cad_ir.constraints import (
    ConstraintKind,
    DimensionKind,
    DrivingDimension,
    SketchConstraint,
    SketchPoint,
)

from cad_engine_build123d.constraints import validate
from cad_engine_build123d.entities import ConstrainedEntity, Point2
from cad_engine_build123d.errors import CadEngineError


class Literals:
    """The parameter resolver, for documents whose scalars are all numbers."""

    def resolve(self, value, what):
        return float(value)


PARAMS = Literals()


def line(entity_id, x1, y1, x2, y2):
    return ConstrainedEntity(entity_id, "line", Point2(x1, y1), Point2(x2, y2))


def circle(entity_id, x, y, radius):
    centre = Point2(x, y)
    return ConstrainedEntity(entity_id, "circle", centre, centre, centre, radius)


def arc(entity_id, x1, y1, x2, y2, cx, cy):
    start, centre = Point2(x1, y1), Point2(cx, cy)
    return ConstrainedEntity(
        entity_id, "arc", start, Point2(x2, y2), centre, centre.distance_to(start)
    )


def rectangle():
    """A 20 x 10 rectangle with every side named."""
    return [
        line("seg.top", 0, 10, 20, 10),
        line("seg.right", 20, 10, 20, 0),
        line("seg.bottom", 20, 0, 0, 0),
        line("seg.left", 0, 0, 0, 10),
    ]


def c(constraint_id, kind, of, to=None, axis=None, of_point="start", to_point="start"):
    return SketchConstraint(
        id=constraint_id,
        kind=kind,
        of=of,
        to=to,
        axis=axis,
        of_point=SketchPoint(of_point),
        to_point=SketchPoint(to_point),
    )


def check(entities, *constraints, dimensions=()):
    return validate(entities, list(constraints), list(dimensions), PARAMS)


def code_of(call):
    with pytest.raises(CadEngineError) as caught:
        call()
    return caught.value.code


# --- constraints that hold -------------------------------------------------


def test_a_constraint_true_of_the_geometry_is_accepted():
    check(
        rectangle(),
        c("c.1", ConstraintKind.HORIZONTAL, "seg.top"),
        c("c.2", ConstraintKind.VERTICAL, "seg.left"),
        c("c.3", ConstraintKind.PARALLEL, "seg.top", "seg.bottom"),
        c("c.4", ConstraintKind.PERPENDICULAR, "seg.top", "seg.left"),
        c("c.5", ConstraintKind.EQUAL_LENGTH, "seg.top", "seg.bottom"),
        c("c.6", ConstraintKind.COINCIDENT, "seg.left", "seg.bottom", to_point="end"),
    )


def test_a_coincidence_between_two_circles_is_concentricity():
    """A circle's defining point is its centre, which is why one relation covers
    both spellings."""
    check(
        [circle("hole.a", 5, 5, 3), circle("hole.b", 5, 5, 8)],
        c("c.concentric", ConstraintKind.COINCIDENT, "hole.a", "hole.b"),
    )
    check(
        [circle("hole.a", 5, 5, 3), circle("hole.b", 5, 5, 8)],
        c("c.concentric", ConstraintKind.CONCENTRIC, "hole.a", "hole.b"),
    )


def test_tangency_holds_both_ways_round():
    # Externally tangent: centres 10 apart, radii 4 and 6.
    check([circle("ent.a", 0, 0, 4), circle("ent.b", 10, 0, 6)],
          c("c.outer", ConstraintKind.TANGENT, "ent.a", "ent.b"))
    # Internally tangent: centres 2 apart, radii 4 and 6.
    check([circle("ent.a", 0, 0, 4), circle("ent.b", 2, 0, 6)],
          c("c.inner", ConstraintKind.TANGENT, "ent.a", "ent.b"))
    # A circle of radius 5 centred 5 above a horizontal line touches it.
    check([circle("ent.a", 10, 5, 5), line("ent.l", 0, 0, 40, 0)],
          c("c.line", ConstraintKind.TANGENT, "ent.a", "ent.l"))


def test_a_midpoint_and_a_point_on_a_curve_are_checked_against_real_positions():
    check(
        [line("axis", 0, 0, 20, 0), line("stub", 10, 0, 10, 5)],
        c("c.mid", ConstraintKind.MIDPOINT, "stub", "axis"),
        c("c.on", ConstraintKind.POINT_ON_CURVE, "stub", "axis"),
    )


def test_symmetry_is_checked_by_mirroring_across_the_axis():
    # The axis is x = 10; the left segment mirrors onto the right one.
    check(
        [
            line("seg.left", 5, 0, 5, 8),
            line("seg.right", 15, 0, 15, 8),
            line("line.mid", 10, -5, 10, 15),
        ],
        c("c.mirror", ConstraintKind.SYMMETRIC, "seg.left", "seg.right", axis="line.mid"),
    )


def test_collinearity_needs_both_parallelism_and_a_point_on_the_line():
    check([line("ent.a", 0, 0, 10, 0), line("ent.b", 20, 0, 30, 0)],
          c("c.collinear", ConstraintKind.COLLINEAR, "ent.b", "ent.a"))


def test_fixed_is_always_satisfied_because_it_says_nothing_about_coordinates():
    """`fixed` says the entity may not be moved by a later edit. That is about
    editing, not about coordinates, so there is nothing it can fail."""
    check(rectangle(), c("c.pin", ConstraintKind.FIXED, "seg.top"))


# --- the refusals that matter ----------------------------------------------


def test_a_parallel_constraint_on_edges_that_are_not_parallel_is_refused():
    """The headline case. An extraction that says two edges are parallel while
    the coordinates it also extracted say otherwise has misread one of them."""
    with pytest.raises(CadEngineError) as caught:
        check(rectangle(), c("c.wrong", ConstraintKind.PARALLEL, "seg.top", "seg.left"))

    assert caught.value.code == "CONSTRAINT_NOT_SATISFIED"
    assert "seg.top parallel seg.left" in caught.value.safe_message
    assert "not an instruction to change it" in caught.value.safe_message


def test_a_horizontal_constraint_on_a_sloping_segment_is_refused():
    assert code_of(
        lambda: check([line("slope", 0, 0, 10, 1)],
                      c("c.h", ConstraintKind.HORIZONTAL, "slope"))
    ) == "CONSTRAINT_NOT_SATISFIED"


def test_a_coincidence_between_points_that_do_not_coincide_is_refused():
    assert code_of(
        lambda: check([line("ent.a", 0, 0, 10, 0), line("ent.b", 0.5, 0, 10, 5)],
                      c("c.co", ConstraintKind.COINCIDENT, "ent.a", "ent.b"))
    ) == "CONSTRAINT_NOT_SATISFIED"


def test_tangency_that_misses_by_a_millimetre_is_refused():
    assert code_of(
        lambda: check([circle("ent.a", 0, 0, 4), circle("ent.b", 11, 0, 6)],
                      c("c.t", ConstraintKind.TANGENT, "ent.a", "ent.b"))
    ) == "CONSTRAINT_NOT_SATISFIED"


def test_symmetry_that_is_not_a_mirror_image_is_refused():
    assert code_of(
        lambda: check(
            [
                line("seg.left", 5, 0, 5, 8),
                line("seg.right", 16, 0, 16, 8),
                line("line.mid", 10, -5, 10, 15),
            ],
            c("c.mirror", ConstraintKind.SYMMETRIC, "seg.left", "seg.right", axis="line.mid"),
        )
    ) == "CONSTRAINT_NOT_SATISFIED"


# --- addressing -------------------------------------------------------------


def test_a_constraint_naming_an_entity_the_sketch_does_not_have_is_refused():
    assert code_of(
        lambda: check(rectangle(), c("c.x", ConstraintKind.HORIZONTAL, "seg.absent"))
    ) == "CONSTRAINT_OPERAND_MISSING"


def test_two_entities_sharing_a_name_are_refused_before_any_constraint_is_checked():
    assert code_of(
        lambda: check([line("same", 0, 0, 1, 0), line("same", 0, 1, 1, 1)])
    ) == "SKETCH_ENTITY_DUPLICATE"


def test_a_direction_constraint_on_a_circle_is_refused_as_the_wrong_operand():
    with pytest.raises(CadEngineError) as caught:
        check([circle("hole", 0, 0, 3)], c("c.h", ConstraintKind.HORIZONTAL, "hole"))

    assert caught.value.code == "CONSTRAINT_OPERAND_INVALID"
    assert "is a circle" in caught.value.safe_message


def test_an_equal_radius_constraint_between_two_straight_segments_is_refused():
    assert code_of(
        lambda: check(rectangle(),
                      c("c.r", ConstraintKind.EQUAL_RADIUS, "seg.top", "seg.bottom"))
    ) == "CONSTRAINT_OPERAND_INVALID"


def test_asking_a_segment_for_a_centre_is_refused_rather_than_answered():
    with pytest.raises(CadEngineError) as caught:
        line("ent.a", 0, 0, 1, 0).point_at("center")

    assert caught.value.code == "CONSTRAINT_OPERAND_INVALID"


# --- duplicates and contradictions ------------------------------------------


def test_the_same_relation_stated_twice_is_refused_even_with_operands_swapped():
    """Stating the same relation twice does the geometry no harm and the document
    plenty: it usually means one of the two meant a different pair."""
    assert code_of(
        lambda: check(rectangle(),
                      c("c.1", ConstraintKind.PARALLEL, "seg.top", "seg.bottom"),
                      c("c.2", ConstraintKind.PARALLEL, "seg.bottom", "seg.top"))
    ) == "CONSTRAINT_DUPLICATE"


def test_a_segment_cannot_be_declared_both_horizontal_and_vertical():
    with pytest.raises(CadEngineError) as caught:
        check([line("ent.a", 0, 0, 0, 0)],
              c("c.h", ConstraintKind.HORIZONTAL, "ent.a"),
              c("c.v", ConstraintKind.VERTICAL, "ent.a"))

    assert caught.value.code == "CONSTRAINT_CONTRADICTION"
    assert "cannot both hold" in caught.value.safe_message


def test_a_pair_cannot_be_declared_both_parallel_and_perpendicular():
    assert code_of(
        lambda: check(rectangle(),
                      c("c.p", ConstraintKind.PARALLEL, "seg.top", "seg.bottom"),
                      c("c.q", ConstraintKind.PERPENDICULAR, "seg.bottom", "seg.top"))
    ) == "CONSTRAINT_CONTRADICTION"


# --- driving dimensions ------------------------------------------------------


def dimension(dimension_id, kind, of, value, to=None):
    return DrivingDimension(id=dimension_id, kind=kind, of=of, value=value, to=to)


def test_a_dimension_that_matches_the_geometry_is_accepted():
    check(
        [line("seg.top", 0, 10, 20, 10), circle("hole", 5, 5, 2.5)],
        dimensions=[
            dimension("base_width", DimensionKind.LENGTH, "seg.top", 20),
            dimension("hole_radius", DimensionKind.RADIUS, "hole", 2.5),
            dimension("hole_dia", DimensionKind.DIAMETER, "hole", 5),
        ],
    )


def test_a_dimension_that_disagrees_with_the_geometry_is_refused():
    """A dimension is what a customer reads off the drawing. One that disagrees
    with what it dimensions is a document contradicting itself."""
    with pytest.raises(CadEngineError) as caught:
        check(
            [line("seg.top", 0, 10, 20, 10)],
            dimensions=[dimension("base_width", DimensionKind.LENGTH, "seg.top", 25)],
        )

    assert caught.value.code == "DIMENSION_DISAGREES_WITH_GEOMETRY"
    assert "25.0000" in caught.value.safe_message
    assert "20.0000" in caught.value.safe_message


def test_a_radius_dimension_on_a_straight_segment_is_refused():
    assert code_of(
        lambda: check(
            [line("seg.top", 0, 10, 20, 10)],
            dimensions=[dimension("dim.r", DimensionKind.RADIUS, "seg.top", 5)],
        )
    ) == "CONSTRAINT_OPERAND_INVALID"


def test_a_diameter_is_twice_the_radius_and_is_checked_as_such():
    assert code_of(
        lambda: check(
            [circle("hole", 0, 0, 2.5)],
            dimensions=[dimension("dim.d", DimensionKind.DIAMETER, "hole", 2.5)],
        )
    ) == "DIMENSION_DISAGREES_WITH_GEOMETRY"


def test_an_angle_between_two_entities_is_measured_and_checked():
    check(
        [line("base", 0, 0, 40, 0), line("arm", 0, 0, 20, 20)],
        dimensions=[dimension("corner", DimensionKind.ANGLE, "base", 45, to="arm")],
    )
    assert code_of(
        lambda: check(
            [line("base", 0, 0, 40, 0), line("arm", 0, 0, 20, 20)],
            dimensions=[dimension("corner", DimensionKind.ANGLE, "base", 60, to="arm")],
        )
    ) == "DIMENSION_DISAGREES_WITH_GEOMETRY"


# --- degrees of freedom ------------------------------------------------------


def test_degrees_of_freedom_are_counted_and_reported_rather_than_enforced():
    """A document with explicit coordinates is normally under-constrained and that
    is fine: the coordinates are the truth."""
    freedom = check(
        rectangle(),
        c("c.1", ConstraintKind.HORIZONTAL, "seg.top"),
        c("c.2", ConstraintKind.VERTICAL, "seg.left"),
        c("c.3", ConstraintKind.COINCIDENT, "seg.left", "seg.bottom", to_point="end"),
    )

    assert (freedom.total, freedom.removed, freedom.remaining) == (16, 4, 12)
    assert not freedom.is_over_constrained
    assert "12 of 16" in str(freedom)


def test_an_arc_counts_for_more_than_a_line_and_a_circle_for_less():
    assert check([arc("ent.a", 0, 5, 5, 0, 0, 0)]).total == 5
    assert check([line("ent.l", 0, 0, 5, 0)]).total == 4
    assert check([circle("ent.c", 0, 0, 5)]).total == 3


def test_over_constraining_is_reported_rather_than_refused():
    freedom = check(
        [circle("ent.a", 0, 0, 3), circle("ent.b", 0, 0, 3)],
        c("c.1", ConstraintKind.FIXED, "ent.a"),
        c("c.2", ConstraintKind.FIXED, "ent.b"),
        c("c.3", ConstraintKind.COINCIDENT, "ent.a", "ent.b"),
    )

    assert freedom.is_over_constrained
