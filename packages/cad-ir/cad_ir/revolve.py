"""CAD-IR 1.4: revolve.

The first operation added after the engine changed, and the first one whose
contract was written without a COM probe in front of it. Under KOMPAS an
operation began by measuring which integers the kernel used; on OpenCascade a
revolve is a documented call, so the design work is all about what a *document*
may say rather than about what the kernel will accept.

**The axis is always explicit.** The roadmap allows inferring one "only at high
confidence", and this contract does not offer it. An inferred axis is a guess
about the part that nothing downstream can check: the profile is valid either
way, the build succeeds either way, and the difference between a bush and a disc
is which line the profile went round. A document that cannot name its axis has
not finished reading the drawing.

**A profile may touch the axis but never cross it.** Crossing means the two sides
sweep through each other, and what comes out is not a solid anyone drew. That one
is geometry — it needs the parameters resolved — so like every other geometric
check it lives in the adapter, in front of the kernel, and not here.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from .base import FeatureResult, FeatureType, Id, Provenance, ResultRef, Scalar, StrictModel
from .sketch import ConstructionLine, Point2, Sketch


class RevolveAxis(StrictModel):
    """The line the profile goes round, in the sketch's own plane.

    Two points rather than a point and a direction: the same two numbers a
    drawing gives, and no normalisation for a reader to get wrong. They are in
    sketch coordinates, because that is where the profile is — an axis in world
    coordinates would have to be projected onto the sketch plane, and a document
    whose axis is off the plane would then be silently corrected onto it.
    """

    start: Point2
    end: Point2

    @model_validator(mode="after")
    def validate_distinct(self) -> "RevolveAxis":
        if self.start == self.end:
            raise ValueError("a revolve axis needs two distinct points")
        return self


class RevolveByConstructionLine(StrictModel):
    """The axis is a named construction line in the same sketch.

    The form a drawing usually takes: a centre line is drawn, and the profile is
    dimensioned from it. Naming it keeps one line as the single statement of
    where the axis is, so moving it moves the axis rather than leaving two
    numbers to disagree.
    """

    kind: Literal["construction_line"]
    entity: Id


class RevolveByPoints(StrictModel):
    kind: Literal["points"]
    axis: RevolveAxis


RevolveAxisSpec = Annotated[
    Union[RevolveByConstructionLine, RevolveByPoints], Field(discriminator="kind")
]


class RevolveInputs(StrictModel):
    """One revolve.

    `angle_deg` is how far round, and 360 is the ordinary case. Partial angles
    are allowed because the roadmap asks for them and because a segment of a disc
    is a real part; `both_directions` sweeps half each way, which is how a
    drawing states a symmetric partial revolve without moving the profile.
    """

    sketch: Sketch
    axis: RevolveAxisSpec
    angle_deg: Scalar = 360.0
    both_directions: bool = False
    source_body: ResultRef | None = None
    #: A body of its own rather than an addition to the one being built (1.7).
    new_body: bool = False

    @model_validator(mode="after")
    def validate_angle(self) -> "RevolveInputs":
        if isinstance(self.angle_deg, (int, float)):
            if not 0 < float(self.angle_deg) <= 360:
                raise ValueError("a revolve turns more than 0 and at most 360 degrees")
        return self

    @model_validator(mode="after")
    def validate_axis_entity(self) -> "RevolveInputs":
        """A named axis names a construction line of this sketch, and nothing else.

        Checked here rather than in the adapter for the same reason `Sketch`
        checks its own names: it is a statement about the document, not about
        geometry. An axis naming a profile segment would also be a drawing that
        revolves a part of itself, and an axis naming a circle is not a line at
        all.

        `both_directions` is refused on a full turn in the same breath. Half of
        360 each way is 360, so it changes nothing about the solid and everything
        about what a reader thinks the document says.
        """
        if isinstance(self.axis, RevolveByConstructionLine):
            lines = {
                entity.id
                for entity in self.sketch.construction
                if isinstance(entity, ConstructionLine)
            }
            if self.axis.entity not in lines:
                raise ValueError(
                    f"the axis names {self.axis.entity}, which is not a construction line "
                    f"of sketch {self.sketch.id}"
                )
        if self.both_directions and self.angle_deg == 360.0:
            raise ValueError("a full turn is the same in both directions; drop both_directions")
        return self


class SolidRevolveFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.SOLID_REVOLVE]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(max_length=64)] = Field(default_factory=list)
    inputs: RevolveInputs
    provenance: Provenance | None = None


class CutRevolveFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.CUT_REVOLVE]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(max_length=64)] = Field(default_factory=list)
    inputs: RevolveInputs
    provenance: Provenance | None = None


__all__ = [
    "CutRevolveFeature",
    "RevolveAxis",
    "RevolveAxisSpec",
    "RevolveByConstructionLine",
    "RevolveByPoints",
    "RevolveInputs",
    "SolidRevolveFeature",
]
