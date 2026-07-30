"""CAD-IR 1.3 constraints and driving dimensions.

A constraint is an assertion about geometry the document already states, so the
contract's job is to make sure the assertion is *addressed* — that it names
entities that exist, exactly once each, with the right number of operands. That
it is *true* is geometry, and geometry lives in the adapter.
"""

import pytest
from pydantic import ValidationError

from cad_ir.constraints import ConstraintKind, DimensionKind, DrivingDimension, SketchConstraint
from cad_ir.sketch import Sketch

BASE_XY = {"on": "base", "plane": "XY"}


def rectangle_path(**overrides) -> dict:
    """A named square, so every side can be constrained."""
    return {
        "id": "sketch.base",
        "plane": BASE_XY,
        "outer": {
            "type": "path",
            "id": "contour.outer",
            "segments": [
                {"type": "line", "id": "seg.top", "start": [0.0, 10.0], "end": [20.0, 10.0]},
                {"type": "line", "id": "seg.right", "start": [20.0, 10.0], "end": [20.0, 0.0]},
                {"type": "line", "id": "seg.bottom", "start": [20.0, 0.0], "end": [0.0, 0.0]},
                {"type": "line", "id": "seg.left", "start": [0.0, 0.0], "end": [0.0, 10.0]},
            ],
        },
        **overrides,
    }


# --- addressing -----------------------------------------------------------


def test_a_sketch_carries_constraints_that_name_its_segments():
    parsed = Sketch(**rectangle_path(constraints=[
        {"id": "c.top_horizontal", "kind": "horizontal", "of": "seg.top"},
        {"id": "c.sides_parallel", "kind": "parallel", "of": "seg.left", "to": "seg.right"},
    ]))

    assert [c.kind for c in parsed.constraints] == [
        ConstraintKind.HORIZONTAL,
        ConstraintKind.PARALLEL,
    ]


def test_every_nameable_entity_is_reachable_including_the_contour_itself():
    """A constraint may be about a whole circle as well as about one segment, so
    contours are nameable too."""
    parsed = Sketch(**rectangle_path(inner=[
        {"type": "circle", "id": "hole.left", "center": [5.0, 5.0], "radius": 2.0},
    ]))

    named = {entity.id for entity in parsed.entities() if getattr(entity, "id", None)}
    assert named == {"contour.outer", "seg.top", "seg.right", "seg.bottom", "seg.left", "hole.left"}


def test_a_constraint_naming_nothing_is_refused():
    """The reference is what makes a constraint mean something. Silently ignoring
    an unresolvable one would weaken the sketch without saying so."""
    with pytest.raises(ValidationError, match="which no sketch entity carries"):
        Sketch(**rectangle_path(constraints=[
            {"id": "c.bad", "kind": "horizontal", "of": "seg.nonexistent"},
        ]))


def test_two_entities_cannot_share_a_name():
    """Two entities with the same id make every constraint on it mean two
    things."""
    with pytest.raises(ValidationError, match="duplicate sketch entity id"):
        Sketch(**rectangle_path(inner=[
            {"type": "circle", "id": "seg.top", "center": [5.0, 5.0], "radius": 2.0},
        ]))


def test_two_constraints_cannot_share_a_name():
    with pytest.raises(ValidationError, match="duplicate constraint id"):
        Sketch(**rectangle_path(constraints=[
            {"id": "c.same", "kind": "horizontal", "of": "seg.top"},
            {"id": "c.same", "kind": "vertical", "of": "seg.left"},
        ]))


def test_ids_are_optional_so_an_unconstrained_sketch_names_nothing():
    """A rectangle with no constraints should not have to invent a name for
    every side."""
    parsed = Sketch(
        id="sketch.plain",
        plane=BASE_XY,
        outer={"type": "rectangle", "center": [0.0, 0.0], "width": 20.0, "height": 10.0},
    )

    assert parsed.outer.id is None
    assert parsed.constraints == []


# --- operand shape --------------------------------------------------------


@pytest.mark.parametrize("kind", ["horizontal", "vertical", "fixed"])
def test_a_unary_constraint_takes_no_partner(kind):
    with pytest.raises(ValidationError, match="takes no partner"):
        SketchConstraint(id="c.x", kind=kind, of="seg.top", to="seg.bottom")


@pytest.mark.parametrize("kind", ["parallel", "perpendicular", "tangent", "concentric",
                                  "coincident", "midpoint", "equal_length", "equal_radius",
                                  "collinear", "point_on_curve", "aligned_horizontally",
                                  "aligned_vertically"])
def test_a_binary_constraint_needs_a_partner(kind):
    with pytest.raises(ValidationError, match="needs a partner"):
        SketchConstraint(id="c.x", kind=kind, of="seg.top")


def test_symmetry_needs_an_axis_and_nothing_else_may_have_one():
    with pytest.raises(ValidationError, match="needs an axis"):
        SketchConstraint(id="c.x", kind="symmetric", of="seg.left", to="seg.right")
    with pytest.raises(ValidationError, match="no use for an axis"):
        SketchConstraint(id="c.x", kind="parallel", of="seg.left", to="seg.right", axis="line.mid")

    parsed = SketchConstraint(
        id="c.mirror", kind="symmetric", of="seg.left", to="seg.right", axis="line.mid"
    )
    assert parsed.axis == "line.mid"


def test_a_constraint_cannot_relate_an_entity_to_itself():
    """Everything is parallel to itself. A self-referring constraint states
    nothing and hides the entity that was meant."""
    with pytest.raises(ValidationError, match="cannot relate an entity to itself"):
        SketchConstraint(id="c.x", kind="parallel", of="seg.top", to="seg.top")


def test_the_axis_of_a_symmetry_cannot_be_one_of_its_operands():
    with pytest.raises(ValidationError, match="cannot be one of its operands"):
        SketchConstraint(id="c.x", kind="symmetric", of="seg.left", to="seg.right", axis="seg.left")


def test_the_constraint_vocabulary_is_the_one_kompas_was_measured_to_support():
    assert {kind.value for kind in ConstraintKind} == {
        "horizontal", "vertical", "parallel", "perpendicular", "tangent", "concentric",
        "coincident", "midpoint", "equal_length", "equal_radius", "collinear", "symmetric",
        "fixed", "point_on_curve", "aligned_horizontally", "aligned_vertically",
    }


# --- driving dimensions ---------------------------------------------------


def test_a_driving_dimension_carries_the_stable_name_the_roadmap_asks_for():
    parsed = Sketch(**rectangle_path(dimensions=[
        {"id": "base_width", "kind": "length", "of": "seg.top", "value": 20.0},
    ]))

    dimension = parsed.dimensions[0]
    assert dimension.id == "base_width"
    assert dimension.kind is DimensionKind.LENGTH
    assert dimension.value == 20.0


def test_a_dimension_may_reference_a_parameter_so_the_part_stays_parametric():
    parsed = DrivingDimension(
        id="wall_thickness", kind="length", of="seg.left", value={"parameter": "param.wall"}
    )

    assert parsed.value.parameter == "param.wall"


def test_a_dimension_measuring_nothing_is_refused():
    with pytest.raises(ValidationError, match="which no sketch entity carries"):
        Sketch(**rectangle_path(dimensions=[
            {"id": "base_width", "kind": "length", "of": "seg.absent", "value": 20.0},
        ]))


def test_two_dimensions_cannot_share_a_name():
    """The name is what appears in the delivered model, so it has to be one
    measurement."""
    with pytest.raises(ValidationError, match="duplicate dimension id"):
        Sketch(**rectangle_path(dimensions=[
            {"id": "base_width", "kind": "length", "of": "seg.top", "value": 20.0},
            {"id": "base_width", "kind": "length", "of": "seg.bottom", "value": 20.0},
        ]))


@pytest.mark.parametrize("value", [0.0, -5.0])
def test_a_dimension_of_zero_or_less_is_never_a_measurement(value):
    with pytest.raises(ValidationError, match="must be positive"):
        DrivingDimension(id="base_width", kind="length", of="seg.top", value=value)


def test_angular_dimensions_are_absent_because_kompas_would_not_create_one():
    """`IAngleDimensions.Add` answers with nothing for every type tried, so an
    angular dimension cannot be created at all. Recorded rather than guessed at;
    see docs/TASK-POSTMVP-007-sketch-constraints.md."""
    assert {kind.value for kind in DimensionKind} == {"length", "radius", "diameter"}


# --- what the contract deliberately leaves to the adapter -----------------


def test_the_contract_does_not_check_that_a_constraint_is_true():
    """Whether these two segments really are parallel is geometry: it needs the
    parameters resolved and it has to run on the machine that drives KOMPAS."""
    parsed = Sketch(**rectangle_path(constraints=[
        {"id": "c.wrong", "kind": "parallel", "of": "seg.top", "to": "seg.left"},
    ]))

    assert parsed.constraints[0].kind is ConstraintKind.PARALLEL
