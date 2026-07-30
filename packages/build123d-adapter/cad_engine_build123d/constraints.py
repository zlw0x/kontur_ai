"""Check that a sketch's declared constraints are true of its coordinates.

A constraint in CAD-IR is an **assertion about the geometry the document already
states**, never an instruction that produces it (ADR-022). The coordinates stay
the truth; a constraint says something that must already hold of them.

That is what makes a class of AI error catchable. A drawing read as "these two
edges are parallel" whose extracted coordinates say otherwise is a misreading,
and it now has a name instead of quietly producing a part nobody notices is
wrong.

Nothing is repaired. The geometry is not nudged to satisfy the constraint and the
constraint is not dropped to satisfy the geometry — either would be a guess about
which half of the document was right.

Ported from the C# validator this engine replaces, check for check and tolerance
for tolerance, so a document that was refused before is refused now for the same
reason. What is *not* ported is the part that applied constraints to the model:
build123d has no constraint solver and a STEP file cannot carry them, which
ADR-023 records as a real cost of the migration. The checking survives; the
editable delivered model does not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cad_ir.constraints import ConstraintKind, DimensionKind, SketchPoint

from .entities import ConstrainedEntity, Point2
from .errors import CadEngineError

#: How exactly a declared relation must hold.
#:
#: Looser than machine epsilon, because a coordinate is written to a few decimals
#: and a derived relation accumulates the rounding of both operands. A micron of
#: coincidence is well inside any drawing's intent and well outside a genuine
#: mistake.
TOLERANCE = 1e-6

#: Angles are compared on unit-normalised vectors, where the same physical
#: tolerance is a much smaller number.
ANGLE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class DegreesOfFreedom:
    """How much of the sketch is still free to move."""

    total: int
    removed: int

    @property
    def remaining(self) -> int:
        return self.total - self.removed

    @property
    def is_over_constrained(self) -> bool:
        return self.removed > self.total

    def __str__(self) -> str:
        return f"{self.remaining} of {self.total} degrees of freedom remain"


def validate(
    entities: list[ConstrainedEntity],
    constraints: list,
    dimensions: list,
    params,
) -> DegreesOfFreedom:
    """Refuse anything the coordinates contradict; report the freedom left."""
    by_id = _index(entities)
    _reject_duplicates(constraints)
    _reject_contradictions(constraints)

    for constraint in constraints:
        _check(constraint, by_id)
    for dimension in dimensions:
        _check_dimension(dimension, by_id, params)

    return _count(entities, constraints)


def _index(entities: list[ConstrainedEntity]) -> dict[str, ConstrainedEntity]:
    by_id: dict[str, ConstrainedEntity] = {}
    for entity in entities:
        if entity.id in by_id:
            raise _invalid(
                "SKETCH_ENTITY_DUPLICATE",
                f"Two sketch entities are named {entity.id}, so a constraint on it "
                "means two things.",
            )
        by_id[entity.id] = entity
    return by_id


def _resolve(entity_id: str, by_id: dict, what: str) -> ConstrainedEntity:
    entity = by_id.get(str(entity_id))
    if entity is None:
        raise _invalid(
            "CONSTRAINT_OPERAND_MISSING",
            f"{what} names {entity_id}, which the sketch has no entity for.",
        )
    return entity


def _reject_duplicates(constraints: list) -> None:
    """The same relation stated twice.

    Harmless to the geometry and harmful to the document: it usually means one of
    the two meant a different pair, and the duplicate hid the mistake.
    """
    seen: set[str] = set()
    for constraint in constraints:
        # Unordered for the symmetric relations: parallel(a, b) and parallel(b, a)
        # are one statement.
        if constraint.to is None:
            operands = f"{constraint.of}.{constraint.of_point}"
        else:
            operands = "|".join(
                sorted(
                    [
                        f"{constraint.of}.{constraint.of_point}",
                        f"{constraint.to}.{constraint.to_point}",
                    ]
                )
            )
        key = f"{constraint.kind}:{operands}:{constraint.axis}"
        if key in seen:
            raise _invalid(
                "CONSTRAINT_DUPLICATE",
                f"Constraint {constraint.id} states {_describe(constraint)} a second time.",
            )
        seen.add(key)


#: Only the contradictions that are contradictions whatever the geometry is.
#: Everything subtler shows up as a constraint that simply does not hold, which
#: is checked next and reports better.
_INCOMPATIBLE = (
    (ConstraintKind.HORIZONTAL, ConstraintKind.VERTICAL),
    (ConstraintKind.PARALLEL, ConstraintKind.PERPENDICULAR),
    (ConstraintKind.ALIGNED_HORIZONTALLY, ConstraintKind.ALIGNED_VERTICALLY),
)


def _reject_contradictions(constraints: list) -> None:
    for left_kind, right_kind in _INCOMPATIBLE:
        for first in [item for item in constraints if item.kind is left_kind]:
            for second in [item for item in constraints if item.kind is right_kind]:
                if not _same_operands(first, second):
                    continue
                raise _invalid(
                    "CONSTRAINT_CONTRADICTION",
                    f"Constraints {first.id} and {second.id} cannot both hold: "
                    f"{_describe(first)} and {_describe(second)}.",
                )


def _same_operands(left, right) -> bool:
    if left.to is None and right.to is None:
        return left.of == right.of
    if left.to is None or right.to is None:
        return False
    return sorted([str(left.of), str(left.to)]) == sorted([str(right.of), str(right.to)])


# ---------------------------------------------------------------------------
# One constraint
# ---------------------------------------------------------------------------


def _check(constraint, by_id: dict) -> None:
    what = f"Constraint {constraint.id}"
    subject = _resolve(constraint.of, by_id, what)
    partner = None if constraint.to is None else _resolve(constraint.to, by_id, what)
    axis = None if constraint.axis is None else _resolve(constraint.axis, by_id, what)

    kind = constraint.kind
    of_point = _point_name(constraint.of_point)
    to_point = _point_name(constraint.to_point)

    if kind is ConstraintKind.FIXED:
        # `fixed` says the entity may not be moved by a later edit. That is about
        # editing, not about coordinates, so there is nothing it can fail.
        holds = True
    elif kind is ConstraintKind.HORIZONTAL:
        holds = abs(_require_curve(subject, what).direction[1]) <= TOLERANCE
    elif kind is ConstraintKind.VERTICAL:
        holds = abs(_require_curve(subject, what).direction[0]) <= TOLERANCE
    elif kind is ConstraintKind.PARALLEL:
        holds = _is_parallel(_require_curve(subject, what), _require_curve(partner, what))
    elif kind is ConstraintKind.PERPENDICULAR:
        holds = _is_perpendicular(
            _require_curve(subject, what), _require_curve(partner, what)
        )
    elif kind is ConstraintKind.EQUAL_LENGTH:
        holds = abs(subject.length - partner.length) <= TOLERANCE
    elif kind is ConstraintKind.EQUAL_RADIUS:
        holds = abs(_require_radius(subject, what) - _require_radius(partner, what)) <= TOLERANCE
    elif kind is ConstraintKind.ALIGNED_HORIZONTALLY:
        holds = abs(subject.point_at(of_point).y - partner.point_at(to_point).y) <= TOLERANCE
    elif kind is ConstraintKind.ALIGNED_VERTICALLY:
        holds = abs(subject.point_at(of_point).x - partner.point_at(to_point).x) <= TOLERANCE
    elif kind in (ConstraintKind.COINCIDENT, ConstraintKind.CONCENTRIC):
        # Concentricity is a coincidence of centres, which for two circles is
        # what a coincidence already means.
        holds = subject.point_at(of_point).distance_to(
            partner.point_at(to_point)
        ) <= TOLERANCE
    elif kind is ConstraintKind.MIDPOINT:
        holds = subject.point_at(of_point).distance_to(partner.midpoint) <= TOLERANCE
    elif kind is ConstraintKind.POINT_ON_CURVE:
        holds = _is_on(subject.point_at(of_point), partner)
    elif kind is ConstraintKind.COLLINEAR:
        holds = _is_parallel(
            _require_curve(subject, what), _require_curve(partner, what)
        ) and _is_on(subject.point_at(of_point), partner)
    elif kind is ConstraintKind.TANGENT:
        holds = _is_tangent(subject, partner, what)
    elif kind is ConstraintKind.SYMMETRIC:
        holds = _is_symmetric(subject, partner, _require_curve(axis, what))
    else:
        raise _invalid(
            "UNSUPPORTED_CONSTRAINT",
            f"{what} is a {kind} constraint, which this build cannot check.",
        )

    if not holds:
        raise _invalid(
            "CONSTRAINT_NOT_SATISFIED",
            f"{what} states {_describe(constraint)}, and the coordinates the document "
            "gives do not. A constraint is a statement about the geometry, not an "
            "instruction to change it.",
        )


def _check_dimension(dimension, by_id: dict, params) -> None:
    what = f"Dimension {dimension.id}"
    subject = _resolve(dimension.of, by_id, what)

    kind = dimension.kind
    if kind is DimensionKind.LENGTH:
        measured = subject.length
    elif kind is DimensionKind.RADIUS:
        measured = _require_radius(subject, what)
    elif kind is DimensionKind.DIAMETER:
        measured = _require_radius(subject, what) * 2
    elif kind is DimensionKind.ANGLE:
        measured = _angle_between(
            _require_curve(subject, what),
            _require_curve(_resolve(dimension.to, by_id, what), what),
        )
    else:
        raise _invalid(
            "UNSUPPORTED_DIMENSION", f"{what} is of a kind this build cannot measure."
        )

    # The stated value is a scalar like any other, so it may name a parameter:
    # a plate whose hole radius follows its width is what parameters are for.
    stated = params.resolve(dimension.value, f"{what} value")
    unit = " degrees" if kind is DimensionKind.ANGLE else " mm"
    if abs(measured - stated) > TOLERANCE:
        raise _invalid(
            "DIMENSION_DISAGREES_WITH_GEOMETRY",
            f"{what} says {stated:.4f}{unit} and the geometry measures "
            f"{measured:.4f}{unit}. A dimension that disagrees with what it dimensions "
            "is a document contradicting itself.",
        )


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def _require_curve(entity: ConstrainedEntity | None, what: str) -> ConstrainedEntity:
    if entity is None or not entity.is_curve:
        name = "nothing" if entity is None else f"{entity.id} is a {entity.kind}"
        raise _invalid(
            "CONSTRAINT_OPERAND_INVALID", f"{what} needs a line or an arc; {name}."
        )
    return entity


def _require_radius(entity: ConstrainedEntity | None, what: str) -> float:
    if entity is None or entity.radius is None:
        name = "nothing" if entity is None else f"{entity.id} is a {entity.kind}"
        raise _invalid(
            "CONSTRAINT_OPERAND_INVALID",
            f"{what} needs something with a radius; {name}.",
        )
    return entity.radius


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    return (0.0, 0.0) if length <= TOLERANCE else (vector[0] / length, vector[1] / length)


def _is_parallel(left: ConstrainedEntity, right: ConstrainedEntity) -> bool:
    ax, ay = _unit(left.direction)
    bx, by = _unit(right.direction)
    return abs(ax * by - ay * bx) <= ANGLE_TOLERANCE


def _is_perpendicular(left: ConstrainedEntity, right: ConstrainedEntity) -> bool:
    ax, ay = _unit(left.direction)
    bx, by = _unit(right.direction)
    return abs(ax * bx + ay * by) <= ANGLE_TOLERANCE


def _is_on(point: Point2, partner: ConstrainedEntity) -> bool:
    """Is the point on the partner — its circle, or its line?"""
    if partner.kind == "circle" and partner.center is not None and partner.radius is not None:
        return abs(point.distance_to(partner.center) - partner.radius) <= TOLERANCE
    dx, dy = _unit(partner.direction)
    # Distance from the point to the infinite line through the partner.
    return abs(dx * (point.y - partner.start.y) - dy * (point.x - partner.start.x)) <= TOLERANCE


def _is_tangent(
    subject: ConstrainedEntity, partner: ConstrainedEntity, what: str
) -> bool:
    round_one = subject if subject.is_round else partner
    other = partner if subject.is_round else subject
    if round_one.center is None or round_one.radius is None:
        raise _invalid(
            "CONSTRAINT_OPERAND_INVALID",
            f"{what} needs at least one arc or circle; {subject.id} and {partner.id} "
            "are both straight.",
        )

    if other.is_round and other.center is not None and other.radius is not None:
        distance = round_one.center.distance_to(other.center)
        return (
            abs(distance - (round_one.radius + other.radius)) <= TOLERANCE
            or abs(distance - abs(round_one.radius - other.radius)) <= TOLERANCE
        )

    dx, dy = _unit(other.direction)
    gap = abs(
        dx * (round_one.center.y - other.start.y) - dy * (round_one.center.x - other.start.x)
    )
    return abs(gap - round_one.radius) <= TOLERANCE


def _is_symmetric(
    subject: ConstrainedEntity, partner: ConstrainedEntity, axis: ConstrainedEntity
) -> bool:
    """Is each operand the other's mirror image across the axis?"""
    return (
        _mirror(subject.start, axis).distance_to(partner.start) <= TOLERANCE
        and _mirror(subject.end, axis).distance_to(partner.end) <= TOLERANCE
    )


def _mirror(point: Point2, axis: ConstrainedEntity) -> Point2:
    dx, dy = _unit(axis.direction)
    offset_x = point.x - axis.start.x
    offset_y = point.y - axis.start.y
    # Reflect the offset about the axis direction, then put it back.
    along = offset_x * dx + offset_y * dy
    across_x = offset_x - 2 * along * dx
    across_y = offset_y - 2 * along * dy
    return Point2(axis.start.x - across_x, axis.start.y - across_y)


def _angle_between(left: ConstrainedEntity, right: ConstrainedEntity) -> float:
    """The angle between two curves, in degrees, in [0, 180).

    Taken between the directions the entities were written in. A segment written
    end-to-start rather than start-to-end therefore reads as its supplement —
    that is not a quirk to paper over, it is the same fact a draughtsman sees
    when an arrow points the other way.
    """
    ax, ay = _unit(left.direction)
    bx, by = _unit(right.direction)
    return math.degrees(math.atan2(abs(ax * by - ay * bx), max(-1.0, min(1.0, ax * bx + ay * by))))


# ---------------------------------------------------------------------------
# Degrees of freedom
# ---------------------------------------------------------------------------

#: A plain count, not a solver. Exact for independent constraints and optimistic
#: for redundant ones, which is why it is reported rather than enforced.
_FREEDOM = {"line": 4, "circle": 3, "arc": 5, "point": 2}

_REMOVES = {
    ConstraintKind.FIXED: 4,
    ConstraintKind.HORIZONTAL: 1,
    ConstraintKind.VERTICAL: 1,
    ConstraintKind.PARALLEL: 1,
    ConstraintKind.PERPENDICULAR: 1,
    ConstraintKind.EQUAL_LENGTH: 1,
    ConstraintKind.EQUAL_RADIUS: 1,
    ConstraintKind.ALIGNED_HORIZONTALLY: 1,
    ConstraintKind.ALIGNED_VERTICALLY: 1,
    ConstraintKind.POINT_ON_CURVE: 1,
    ConstraintKind.TANGENT: 1,
    ConstraintKind.COINCIDENT: 2,
    ConstraintKind.CONCENTRIC: 2,
    ConstraintKind.MIDPOINT: 2,
    ConstraintKind.COLLINEAR: 2,
    ConstraintKind.SYMMETRIC: 2,
}


def _count(entities: list[ConstrainedEntity], constraints: list) -> DegreesOfFreedom:
    total = sum(_FREEDOM.get(entity.kind, 0) for entity in entities)
    removed = sum(_REMOVES.get(constraint.kind, 0) for constraint in constraints)
    return DegreesOfFreedom(total, removed)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _point_name(value) -> str:
    return value.value if isinstance(value, SketchPoint) else str(value)


def _describe(constraint) -> str:
    parts = [str(constraint.of), str(constraint.kind)]
    if constraint.to is not None:
        parts.append(str(constraint.to))
    if constraint.axis is not None:
        parts.append(f"about {constraint.axis}")
    return " ".join(parts)


def _invalid(code: str, message: str) -> CadEngineError:
    return CadEngineError(code, "sketch", message)


__all__ = ["DegreesOfFreedom", "validate", "TOLERANCE"]
