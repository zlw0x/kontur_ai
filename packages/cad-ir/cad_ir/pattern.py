"""CAD-IR 1.6: patterns and mirror — a feature repeated, not a feature copied.

A pattern names an earlier feature and says where else it happens. That is the
whole idea, and it is the first operation whose input is another *feature* rather
than geometry or a selector.

Why it is worth having at all, when six holes can already be written as six
contours with explicit coordinates: because the count becomes something the document
*states*. Six coordinates are six chances to get a number wrong and no way to notice;
"six, 60° apart, about this axis" is one intent, and a shape claim that read six
holes off the drawing can be compared against it.

Four decisions.

*Instance zero is the source feature's own position.* A pattern of six adds five,
because the sixth is already in the part. The alternative — a pattern that also
rebuilds the original — makes a document where disabling the source silently changes
how many instances exist.

*The step is stated, never divided.* A `total_angle` field has two defensible
readings for a closed circle: six instances 60° apart, or six instances spanning 360°
with the last on top of the first. A document meaning one and read as the other
builds a plausible wrong part, which is the same argument ADR-024 makes about an
inferred axis.

*A skipped instance is named by its ordinal, and that is not an index into
geometry.* ADR-019 forbids naming a *face* by position because the kernel decides
the order. A pattern's instances are numbered by the document itself — direction,
step, count — so ordinal 3 is the same instance after any parameter change. Skipping
zero is refused: a document that wants no original should disable the feature.

*A grid is a pattern of a pattern.* `of` may name another pattern, so two linear
patterns crossed are a grid and there is no third operation to test. What is left
out is a pattern along a curve, which needs a curve in the document that nothing
else has a use for yet.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from .base import (
    FeatureResult,
    FeatureType,
    Id,
    ParameterRef,
    Provenance,
    Scalar,
    StrictModel,
    stated_number,
)
from .selectors import Axis
from .sketch import BasePlaneName
from .base import ResultRef


class PatternDirection(StrEnum):
    """The world axis a linear pattern runs along.

    The same six spellings an extrusion uses for its direction, and deliberately
    not an arbitrary vector: a drawing repeats holes along an edge of the part, and
    an arbitrary direction is a thing to get subtly wrong for no gain a drawing asks
    for.
    """

    PLUS_X = "+X"
    MINUS_X = "-X"
    PLUS_Y = "+Y"
    MINUS_Y = "-Y"
    PLUS_Z = "+Z"
    MINUS_Z = "-Z"


#: A point in world coordinates, each component a number or a parameter.
Point3 = Annotated[list[Scalar], Field(min_length=3, max_length=3)]


class LinearPattern(StrictModel):
    kind: Literal["linear"]
    direction: PatternDirection
    spacing_mm: Scalar
    #: Including the original. Two is the smallest pattern that repeats anything.
    count: Annotated[int, Field(ge=2, le=1000)]

    @model_validator(mode="after")
    def validate_spacing(self) -> "LinearPattern":
        spacing = stated_number(self.spacing_mm)
        if spacing is not None and spacing <= 0:
            # A zero step puts every instance on top of the original, which is a
            # boolean with itself and a document that meant something else.
            raise ValueError("a linear pattern's spacing must be positive")
        return self


class CircularPattern(StrictModel):
    """Instances turned about an axis through a point the document states.

    `step_deg` is the angle between consecutive instances. Six holes on a bolt
    circle is six at 60°, and the arithmetic that produced 60 belongs to whoever read
    the drawing rather than to this contract.
    """

    kind: Literal["circular"]
    axis: Axis
    #: A point the axis passes through. A bolt circle is about the part's centre,
    #: which is a coordinate, not an axis.
    through: Point3
    step_deg: Scalar
    count: Annotated[int, Field(ge=2, le=1000)]

    @model_validator(mode="after")
    def validate_step(self) -> "CircularPattern":
        step = stated_number(self.step_deg)
        if step is None:
            return self
        if step == 0 or abs(step) >= 360:
            raise ValueError(
                "a circular pattern's step is more than 0 and less than 360 degrees"
            )
        return self


class MirrorPattern(StrictModel):
    """One reflection about a plane. Not a count, so nothing to skip."""

    kind: Literal["mirror"]
    plane: Union[BasePlaneName, ResultRef]


PatternSpec = Annotated[
    Union[LinearPattern, CircularPattern, MirrorPattern],
    Field(discriminator="kind"),
]


class PatternInputs(StrictModel):
    """Which feature repeats, and where.

    `of` is a feature id rather than a result id: what repeats is the *operation* —
    a cut stays a cut and an added boss stays added — and a result id would name the
    body it happened to leave behind.
    """

    of: Id
    pattern: PatternSpec
    #: Instance ordinals to leave out, counting the original as 0.
    skip: Annotated[list[Annotated[int, Field(ge=1, le=999)]], Field(max_length=999)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_skips(self) -> "PatternInputs":
        if self.skip and isinstance(self.pattern, MirrorPattern):
            raise ValueError(
                "a mirror has one reflection and no instances to skip; leave the "
                "feature out instead"
            )
        if len(set(self.skip)) != len(self.skip):
            raise ValueError("an instance is skipped once or not at all")
        count = getattr(self.pattern, "count", 2)
        beyond = sorted(item for item in self.skip if item >= count)
        if beyond:
            raise ValueError(
                f"instance(s) {beyond} are skipped and the pattern has only {count} "
                "(counting the original as 0)"
            )
        if len(self.skip) >= count - 1:
            # Every repeat skipped is a feature that does nothing, and it reads as
            # if it did — the same failure an edge blend that matches nothing has.
            raise ValueError(
                "every instance this pattern would add is skipped, so it repeats nothing"
            )
        return self


class PatternFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.PATTERN]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    #: Always empty. A pattern repeats an operation on the body that is already
    #: there; it does not introduce a result a later feature could name. Naming the
    #: instances individually would be inventing ids for geometry nobody selected.
    produces: Annotated[list[FeatureResult], Field(max_length=0)] = Field(default_factory=list)
    inputs: PatternInputs
    provenance: Provenance | None = None


def instance_count(inputs: PatternInputs) -> int:
    """How many instances the finished part has, the original included.

    One place, because three of them need it: the engine that builds the copies, the
    capability pass that describes the document, and the shape claim that counts what
    a drawing said it saw.
    """
    total = 2 if isinstance(inputs.pattern, MirrorPattern) else int(inputs.pattern.count)
    return total - len(inputs.skip)


__all__ = [
    "CircularPattern",
    "LinearPattern",
    "MirrorPattern",
    "PatternDirection",
    "PatternFeature",
    "PatternInputs",
    "PatternSpec",
    "instance_count",
]
