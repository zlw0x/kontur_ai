"""Semantic selectors: naming geometry by what it means, not where it sits.

A fillet, a chamfer, a shell and every operation after them has to say which
faces or edges it applies to. The obvious way is an index — `edge 17` — and it
is wrong: after a width changes from 40 to 60, or a hole is added before the
one being modified, edge 17 is a different edge. The document still validates,
the build still succeeds, and the part is wrong.

So a selector describes the geometry instead: the planar face whose normal
points along +Z and which is furthest along Z is the top face of a plate, and
stays the top face whatever the plate's dimensions become.

Two rules make this safe rather than merely clever.

*Cardinality is declared, never inferred.* A selector says how many results it
expects. Matching two faces where one was expected is an error, not a coin
toss, because picking one at random produces a plausible-looking wrong part.

*Resolution is deterministic.* Predicates filter; they do not score. There is
no "closest match" and no confidence threshold. When the predicates do not
narrow to the declared cardinality the build stops and hands the trace to a
repair agent, which can then add the predicate that disambiguates.

Nothing in CAD-IR 1.1 references a selector yet. These are the contracts the
resolver and the operations after it are built against.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from .base import Id, StrictModel


class SelectorKind(StrEnum):
    FACE = "face"
    EDGE = "edge"


class SurfaceType(StrEnum):
    PLANAR = "planar"
    CYLINDRICAL = "cylindrical"
    CONICAL = "conical"
    SPHERICAL = "spherical"
    TOROIDAL = "toroidal"


class CurveType(StrEnum):
    LINE = "line"
    CIRCLE = "circle"
    ARC = "arc"
    ELLIPSE = "ellipse"
    SPLINE = "spline"


class Axis(StrEnum):
    X = "axis.x"
    Y = "axis.y"
    Z = "axis.z"


class Direction(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class Extreme(StrEnum):
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class Convexity(StrEnum):
    CONVEX = "convex"
    CONCAVE = "concave"
    TANGENT = "tangent"


class Cardinality(StrEnum):
    EXACTLY_ONE = "exactly_one"
    ZERO_OR_ONE = "zero_or_one"
    ONE_OR_MORE = "one_or_more"
    ALL = "all"


class ExactlyN(StrictModel):
    """A count the document states rather than discovers.

    `exactly_n` is how a pattern says "these four mounting holes". If the model
    grows a fifth, the mismatch is the point: the document no longer describes
    the part.
    """

    type: Literal["exactly_n"]
    value: Annotated[int, Field(ge=0, le=1000)]


CardinalitySpec = Union[Cardinality, ExactlyN]


class Measurement(StrictModel):
    """A measured quantity with the tolerance it must be matched within.

    The tolerance is required. Comparing floating-point geometry for equality
    is a bug waiting for a rebuild, and letting it default hides the choice
    from whoever later wonders why a face stopped matching.
    """

    value: float
    tolerance: Annotated[float, Field(ge=0, le=1000)]

    @model_validator(mode="after")
    def validate_finite(self) -> "Measurement":
        if self.value != self.value or self.value in (float("inf"), float("-inf")):
            raise ValueError("a measurement must be finite")
        return self

    def matches(self, measured: float) -> bool:
        return abs(measured - self.value) <= self.tolerance


class NormalPredicate(StrictModel):
    parallel_to: Axis | None = None
    perpendicular_to: Axis | None = None
    direction: Direction | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "NormalPredicate":
        if self.parallel_to is not None and self.perpendicular_to is not None:
            raise ValueError("a normal predicate states parallelism or perpendicularity, not both")
        if self.direction is not None and self.parallel_to is None:
            # A direction is meaningless without an axis to be directed along.
            raise ValueError("a normal direction requires parallel_to")
        if self.parallel_to is None and self.perpendicular_to is None:
            raise ValueError("a normal predicate must name an axis")
        return self


class PositionPredicate(StrictModel):
    extreme_along: Axis | None = None
    extreme: Extreme | None = None
    center_along: Axis | None = None
    center_value_mm: Measurement | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "PositionPredicate":
        if (self.extreme_along is None) != (self.extreme is None):
            raise ValueError("extreme_along and extreme are stated together or not at all")
        if (self.center_along is None) != (self.center_value_mm is None):
            raise ValueError("center_along and center_value_mm are stated together or not at all")
        if self.extreme_along is None and self.center_along is None:
            raise ValueError("a position predicate must state an extreme or a centre")
        return self


class AdjacencyPredicate(StrictModel):
    """What the geometry touches.

    An edge between a flat face and a cylinder is the rim of a hole, and says
    so without knowing where the hole is.
    """

    contains_surface_types: Annotated[list[SurfaceType], Field(min_length=1, max_length=5)]
    face_count: Annotated[int, Field(ge=1, le=64)] | None = None


class FacePredicates(StrictModel):
    surface_type: SurfaceType | None = None
    normal: NormalPredicate | None = None
    position: PositionPredicate | None = None
    area_mm2: Measurement | None = None
    radius_mm: Measurement | None = None
    adjacent: AdjacencyPredicate | None = None
    produced_by: Id | None = None

    @model_validator(mode="after")
    def validate_predicates(self) -> "FacePredicates":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            # An empty predicate set matches every face on the body. With
            # cardinality `all` that is a way to say "the whole surface"; with
            # `exactly_one` it is a coin toss dressed as a selector.
            raise ValueError("a face selector must state at least one predicate")
        if self.radius_mm is not None and self.surface_type is SurfaceType.PLANAR:
            raise ValueError("a planar face has no radius")
        if self.normal is not None and self.surface_type not in (None, SurfaceType.PLANAR):
            # A curved face has a different normal at every point, so a single
            # normal predicate cannot mean anything definite about it.
            raise ValueError("a normal predicate applies only to a planar face")
        return self


class EdgePredicates(StrictModel):
    curve_type: CurveType | None = None
    length_mm: Measurement | None = None
    radius_mm: Measurement | None = None
    direction_parallel_to: Axis | None = None
    position: PositionPredicate | None = None
    adjacent: AdjacencyPredicate | None = None
    convexity: Convexity | None = None
    produced_by: Id | None = None

    @model_validator(mode="after")
    def validate_predicates(self) -> "EdgePredicates":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("an edge selector must state at least one predicate")
        if self.radius_mm is not None and self.curve_type is CurveType.LINE:
            raise ValueError("a straight edge has no radius")
        return self


class FaceSelector(StrictModel):
    id: Id
    kind: Literal[SelectorKind.FACE]
    from_result: Id
    where: FacePredicates
    cardinality: CardinalitySpec


class EdgeSelector(StrictModel):
    id: Id
    kind: Literal[SelectorKind.EDGE]
    from_result: Id
    where: EdgePredicates
    cardinality: CardinalitySpec


Selector = Annotated[Union[FaceSelector, EdgeSelector], Field(discriminator="kind")]


# --------------------------------------------------------------------------
# Resolution outcome
# --------------------------------------------------------------------------


class SelectorErrorCode(StrEnum):
    NO_MATCH = "SELECTOR_NO_MATCH"
    AMBIGUOUS = "SELECTOR_AMBIGUOUS"
    CARDINALITY_MISMATCH = "SELECTOR_CARDINALITY_MISMATCH"
    UNSUPPORTED_PREDICATE = "SELECTOR_UNSUPPORTED_PREDICATE"
    INVALID_TOLERANCE = "SELECTOR_INVALID_TOLERANCE"
    RESULT_KIND_MISMATCH = "SELECTOR_RESULT_KIND_MISMATCH"


class ResolutionStep(StrictModel):
    """One predicate and what it eliminated.

    The trace is what a repair agent reads. "Two candidates remained after the
    surface-type and normal filters" tells it to add a position predicate;
    "no matches" alone tells it nothing.
    """

    predicate: Annotated[str, Field(min_length=1, max_length=200)]
    before: Annotated[int, Field(ge=0)]
    after: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_monotonic(self) -> "ResolutionStep":
        if self.after > self.before:
            raise ValueError("a filter cannot produce more candidates than it received")
        return self


class SelectorResolution(StrictModel):
    selector_id: Id
    kind: SelectorKind
    initial_candidates: Annotated[int, Field(ge=0)]
    steps: Annotated[list[ResolutionStep], Field(max_length=32)] = Field(default_factory=list)
    result_count: Annotated[int, Field(ge=0)]
    satisfied: bool
    error_code: SelectorErrorCode | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "SelectorResolution":
        if self.satisfied and self.error_code is not None:
            raise ValueError("a satisfied resolution carries no error code")
        if not self.satisfied and self.error_code is None:
            raise ValueError("an unsatisfied resolution must say why")
        return self


class SelectorError(Exception):
    """Resolution failed; the trace explains where."""

    def __init__(self, code: SelectorErrorCode, message: str, resolution: SelectorResolution | None = None):
        super().__init__(message)
        self.code = code
        self.resolution = resolution


def satisfies_cardinality(cardinality: CardinalitySpec, count: int) -> bool:
    if isinstance(cardinality, ExactlyN):
        return count == cardinality.value
    return {
        Cardinality.EXACTLY_ONE: count == 1,
        Cardinality.ZERO_OR_ONE: count <= 1,
        Cardinality.ONE_OR_MORE: count >= 1,
        Cardinality.ALL: True,
    }[cardinality]


def cardinality_failure(cardinality: CardinalitySpec, count: int) -> SelectorErrorCode:
    """Say which kind of disappointment this is.

    Nothing matched, too many matched, or the count is simply not the declared
    one — three different repairs, so three different codes.
    """
    if count == 0:
        return SelectorErrorCode.NO_MATCH
    if cardinality in (Cardinality.EXACTLY_ONE, Cardinality.ZERO_OR_ONE) and count > 1:
        return SelectorErrorCode.AMBIGUOUS
    return SelectorErrorCode.CARDINALITY_MISMATCH
