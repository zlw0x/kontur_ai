"""CAD-IR 1.9: sweep — a profile that travels.

An extrude is a sweep along a straight line and a revolve is a sweep along a circle.
What this adds is a path the document *states*: a chain of lines and arcs, so a pipe
with two bends is one feature rather than three solids fused at the joints.

The path is the whole difficulty, and three properties of it are decided here.

*A path is open.* A closed one is a ring, and a ring made this way has a seam where
the sweep meets itself — a place the kernel has to decide something the document did
not say. A closed profile going round a closed path is a torus, which `solid.revolve`
already builds and states the axis of.

*A path is tangent-continuous.* A sharp corner in a swept path is not a part: real
pipe bends, real extrusions round the corner at a radius, and that radius is a
dimension on the drawing. Asking the kernel to "handle the transition" means asking
it to invent one of three answers — and an invented radius is exactly what ADR-026
refuses to let a blend do. So a corner is refused, and the document states the arc.

*The profile stands at the start of the path, across it.* The profile's plane must
contain the path's first point and be perpendicular to the direction the path leaves
it. Anything else is a skewed sweep whose cross-section is not the one drawn, and the
kernel does it silently.

None of those three is checked here. They are geometry, and this module reads a
document: the engine checks them against the coordinates the document states, in front
of the kernel, the way sketch closure has been checked since POSTMVP-006.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from .base import (
    FeatureResult,
    FeatureType,
    Id,
    Provenance,
    ResultRef,
    StrictModel,
)
from .sketch import BasePlaneName, PathSegment, Sketch


class SweepPath(StrictModel):
    """Where the profile goes, as a chain of lines and arcs in one plane.

    Planar, and on a base plane. A path that left its plane would be the general 3D
    curve of P4.3, which needs a way to say where a point is in space that CAD-IR does
    not have yet — and a planar path is what a drawing gives: a centre line in an
    elevation, with the bend radii dimensioned on it.

    The segments are the same lines and arcs a sketch contour is spelled out with, and
    for the same reason (ADR-020): endpoints that have to *match* rather than angles
    that have to be inferred.
    """

    id: Id
    plane: BasePlaneName
    segments: Annotated[list[PathSegment], Field(min_length=1, max_length=200)]


class SweepInputs(StrictModel):
    """A profile and the path it travels.

    No `distance`: how far the material goes is the length of the path, which the
    document already states segment by segment. A second way to say it would be a
    second thing that can disagree.
    """

    sketch: Sketch
    path: SweepPath
    source_body: ResultRef | None = None
    new_body: bool = False

    @model_validator(mode="after")
    def validate_body(self) -> "SweepInputs":
        if self.new_body and self.source_body is not None:
            raise ValueError(
                "a feature either starts a new body or adds to an existing one, not both"
            )
        return self


class CutSweepInputs(StrictModel):
    """The same, removing material: a groove that follows a path.

    There is no `through_all`. A swept cut removes exactly the volume the profile
    sweeps out, and "through all" has no meaning for a tool that is already a closed
    solid of stated size — unlike an extruded cut, whose depth is otherwise unbounded.
    """

    sketch: Sketch
    path: SweepPath
    source_body: ResultRef | None = None


class SolidSweepFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.SOLID_SWEEP]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(max_length=8)] = Field(default_factory=list)
    inputs: SweepInputs
    provenance: Provenance | None = None


class CutSweepFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.CUT_SWEEP]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(max_length=8)] = Field(default_factory=list)
    inputs: CutSweepInputs
    provenance: Provenance | None = None


SweepFeature = Union[SolidSweepFeature, CutSweepFeature]


__all__ = [
    "CutSweepFeature",
    "CutSweepInputs",
    "SolidSweepFeature",
    "SweepFeature",
    "SweepInputs",
    "SweepPath",
]
