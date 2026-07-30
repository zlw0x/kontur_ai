"""CAD-IR 1.3 sketch constraints and driving dimensions.

Version 1.2 made the sketch a real object with every coordinate a literal. That
builds a part; it does not deliver one. A customer who opens the M3D finds
unconstrained geometry, and changing a width means moving four lines by hand.

Constraints here are **assertions about the geometry the document already
states**, not instructions that produce it. The coordinates stay explicit and
stay the truth; a constraint says something that must already be true of them.

That choice is what keeps three things at once. Determinism: the geometry that
reaches the kernel is the geometry that was validated, because nothing solves it
into something else. Parametricity: the constraints are applied to the KOMPAS
sketch, so the delivered model is editable. And a class of AI error becomes
catchable — a drawing read as "these two edges are parallel" whose extracted
coordinates say otherwise is a misreading, and it now has a name instead of
quietly producing a part nobody notices is wrong.

The residual is stated rather than hidden. A document whose coordinates the AI
could not compute — a tangent arc between two lines, where the tangent point
needs trigonometry — is still not expressible, because the coordinates have to
be there to be compared against. Making the solver authoritative rather than
confirmatory is a later decision and needs a way to record that the geometry
delivered is not the geometry written. See ADR-022.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .base import Id, Scalar, StrictModel


class ConstraintKind(StrEnum):
    """Every constraint KOMPAS v22 was measured to support.

    Named after what they mean rather than after the integers KOMPAS uses. The
    integers were identified by measurement — the type libraries export no
    enumerations at all — and live in the adapter, next to the COM call they
    belong to.
    """

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    TANGENT = "tangent"
    CONCENTRIC = "concentric"
    COINCIDENT = "coincident"
    MIDPOINT = "midpoint"
    EQUAL_LENGTH = "equal_length"
    EQUAL_RADIUS = "equal_radius"
    COLLINEAR = "collinear"
    SYMMETRIC = "symmetric"
    FIXED = "fixed"
    POINT_ON_CURVE = "point_on_curve"
    ALIGNED_HORIZONTALLY = "aligned_horizontally"
    ALIGNED_VERTICALLY = "aligned_vertically"


#: Constraints about one entity on its own. `fixed` pins it; the rest say
#: something about its direction.
UNARY_KINDS: frozenset[ConstraintKind] = frozenset(
    {ConstraintKind.HORIZONTAL, ConstraintKind.VERTICAL, ConstraintKind.FIXED}
)

#: `symmetric` is the only one that needs a third entity to be symmetric about.
AXIAL_KINDS: frozenset[ConstraintKind] = frozenset({ConstraintKind.SYMMETRIC})


#: The constraints for which `of_point` and `to_point` mean anything. Everything
#: else is about a whole entity, and naming a point there would be noise a reader
#: has to decide to ignore.
POINT_CONSTRAINT_KINDS: frozenset[ConstraintKind] = frozenset(
    {
        ConstraintKind.COINCIDENT,
        ConstraintKind.MIDPOINT,
        ConstraintKind.POINT_ON_CURVE,
        ConstraintKind.ALIGNED_HORIZONTALLY,
        ConstraintKind.ALIGNED_VERTICALLY,
        ConstraintKind.COLLINEAR,
    }
)

class SketchPoint(StrEnum):
    """Which point of an entity a point constraint is about.

    Naming it is not optional. In a closed contour consecutive segments meet
    end-to-start, so a coincidence that always meant "start to start" would be
    false for every corner of every rectangle.
    """

    START = "start"
    END = "end"
    CENTER = "center"


class SketchConstraint(StrictModel):
    """One statement about the sketch that must already be true.

    `of` and `to` name entities by their sketch-local ids, never by position in
    a list. A constraint on "segment 2" would change meaning when segments are
    reordered, which is the index problem ADR-019 exists to prevent, one level
    down.
    """

    id: Id
    kind: ConstraintKind
    of: Id
    to: Id | None = None
    axis: Id | None = None
    of_point: SketchPoint = SketchPoint.START
    to_point: SketchPoint = SketchPoint.START

    @model_validator(mode="after")
    def validate_operands(self) -> "SketchConstraint":
        unary = self.kind in UNARY_KINDS
        if unary and self.to is not None:
            raise ValueError(f"a {self.kind} constraint applies to one entity, so it takes no partner")
        if not unary and self.to is None:
            raise ValueError(f"a {self.kind} constraint needs a partner")
        if self.kind in AXIAL_KINDS and self.axis is None:
            raise ValueError(f"a {self.kind} constraint needs an axis to be symmetric about")
        if self.kind not in AXIAL_KINDS and self.axis is not None:
            raise ValueError(f"a {self.kind} constraint has no use for an axis")
        if self.to is not None and self.to == self.of:
            # Everything is parallel to itself. A self-referring constraint
            # states nothing and hides the entity that was meant.
            raise ValueError("a constraint cannot relate an entity to itself")
        if self.axis is not None and self.axis in (self.of, self.to):
            raise ValueError("the axis of a symmetry cannot be one of its operands")
        if self.kind not in POINT_CONSTRAINT_KINDS:
            # Stating a point where a point means nothing is noise a reader has
            # to decide to ignore, and the next reader may decide differently.
            for field in ("of_point", "to_point"):
                if getattr(self, field) is not SketchPoint.START:
                    raise ValueError(
                        f"a {self.kind} constraint is about whole entities, so {field} means nothing"
                    )
        return self


class DimensionKind(StrEnum):
    """The dimension kinds KOMPAS was measured to bind to a named variable.

    Angular joined the list once `IAngleDimensions.Add` was swept properly. An
    earlier probe tried types 0 to 4, found nothing, and recorded that angular
    dimensions do not exist; sweeping -2 to 64 found that only 10 and 39 create,
    and that 10 measures the angle between the two arms. That was a statement
    about the range swept, not about KOMPAS — see
    docs/TASK-POSTMVP-007-sketch-constraints.md.
    """

    LENGTH = "length"
    RADIUS = "radius"
    DIAMETER = "diameter"
    ANGLE = "angle"


class DrivingDimension(StrictModel):
    """A named measurement of the sketch, stated and then verified.

    The `id` is the stable name the roadmap asks for — `base_width`,
    `hole_pitch_x`, `wall_thickness` — and it becomes the variable's name in the
    KOMPAS model, so the same word appears in the document, in the delivered
    file and in any later diff.

    `value` is what the document says the measurement is. The adapter reads what
    KOMPAS measured and refuses the difference: a dimension that disagrees with
    the geometry it dimensions is a document contradicting itself.

    These now genuinely drive. A dimension carries two KOMPAS constraints: one
    that names its variable and one that fixes it. With only the first the number
    is an annotation — setting it changes nothing and a rebuild puts the
    measurement back — which is what 1.3 shipped before the second was found.

    `to` is named by an angle and by nothing else. An angle measures a relation
    between two entities; every other kind measures a property of one.
    """

    id: Id
    kind: DimensionKind
    of: Id
    value: Scalar
    to: Id | None = None

    @model_validator(mode="after")
    def validate_positive_literal(self) -> "DrivingDimension":
        # A parameter reference is checked where parameters are; a literal can
        # be checked here, and a length of zero is never a measurement.
        if isinstance(self.value, (int, float)) and not self.value > 0:
            raise ValueError(f"a {self.kind} dimension must be positive")
        if isinstance(self.value, (int, float)) and self.kind is DimensionKind.ANGLE:
            # An angle between two straight entities is under 180 degrees by
            # construction. A document asking for more has measured the reflex
            # side, which is a different angle from the one it names.
            if not self.value < 180:
                raise ValueError("an angle dimension must be under 180 degrees")
        if self.kind is DimensionKind.ANGLE and self.to is None:
            raise ValueError("an angle dimension is between two entities and needs both")
        if self.kind is not DimensionKind.ANGLE and self.to is not None:
            raise ValueError(f"a {self.kind} dimension is of one entity, so it takes no second")
        if self.to is not None and self.to == self.of:
            raise ValueError("an angle cannot be measured between an entity and itself")
        return self


ConstraintList = Annotated[list[SketchConstraint], Field(max_length=256)]
DimensionList = Annotated[list[DrivingDimension], Field(max_length=128)]
