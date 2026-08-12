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
    Scalar,
    StrictModel,
    stated_number,
)
from .sketch import BasePlaneName, PathSegment, Sketch

#: A point in the space a path is stated in: three components in the frame of the
#: path's own plane, the third being how far it stands out of that plane (CAD-IR 1.15).
#:
#: This is the whole of the "new coordinate vocabulary" P4.3 was said to need, and
#: `docs/TASK-POSTMVP-P4-3-a-path-that-leaves-its-plane.md` is why it is one number
#: rather than a curve library: everything else about a spatial path — the tangency,
#: the perpendicular profile, the bend clearance — is a rule CAD-IR 1.9 already states
#: and the engine already checks, with two components instead of three.
Point3 = Annotated[list[Scalar], Field(min_length=3, max_length=3)]


class SweepPath(StrictModel):
    """Where the profile goes, as a chain of lines and arcs in one plane.

    Planar, and on a base plane — which is what a drawing gives for most parts: a
    centre line in an elevation, with the bend radii dimensioned on it. A path that
    leaves its plane is `SpatialPath`, added in 1.15.

    The segments are the same lines and arcs a sketch contour is spelled out with, and
    for the same reason (ADR-020): endpoints that have to *match* rather than angles
    that have to be inferred.
    """

    id: Id
    plane: BasePlaneName
    segments: Annotated[list[PathSegment], Field(min_length=1, max_length=200)]


class SpatialLineSegment(StrictModel):
    """A straight run of a path in space (CAD-IR 1.15)."""

    type: Literal["line3"]
    start: Point3
    end: Point3
    id: Id | None = None


class SpatialArcSegment(StrictModel):
    """A bend in space, given by its two endpoints and its centre.

    The same three things a planar arc states, each with a third component — and
    **without `sweep`**, which is the one difference and it is a consequence rather
    than a decision.

    A planar `ArcSegment` needs `sweep` because it is shared with sketch contours,
    where two arcs share every endpoint and centre and differ only in which way round
    they go. A *path* has no such freedom: CAD-IR 1.9 requires it to be
    tangent-continuous, and of the two arcs through these points only the shorter one
    can continue in the direction the path arrived. So the way round is derived, and a
    second way to state it would be a second thing that can disagree.

    What that form cannot say is a half turn or more: `start`, `center` and `end`
    collinear leaves the arc's plane undefined, and the kernel's answer to it is
    `gp_Dir::Crossed() - result vector has zero norm` — an empty-message construction
    error of the kind the draft investigation found escaping as a crash. The engine
    refuses it with a reason, and a U-bend is two quarter turns joined tangentially,
    which is what the document has to state anyway because 1.9 checks the join.
    """

    type: Literal["arc3"]
    start: Point3
    end: Point3
    center: Point3
    id: Id | None = None


#: One run or one bend of a path in space.
SpatialSegment = Annotated[
    Union[SpatialLineSegment, SpatialArcSegment], Field(discriminator="type")
]


class SpatialPath(StrictModel):
    """A path that leaves the plane it is stated on (CAD-IR 1.15).

    A bent tube is the case: a drawing gives it as straight runs and bend radii across
    two views, and two of its bends lie in different planes. That is the smallest thing
    `SweepPath` cannot say.

    `plane` is the frame the coordinates are stated in and nothing more — the path no
    longer lies in it. Everything else is 1.9's rule unchanged: the path starts at that
    plane's origin (ADR-031, because the kernel anchors a sweep at the profile whatever
    the path's coordinates say), it is open, it is tangent-continuous, and it leaves the
    profile at a right angle.

    Measured, and the reason this is checkable at all: **Pappus is exact for a path in
    space.** The volume element of a tube is `(1 - u*kappa) du dv ds`, so the correction
    is the section's first moment about the path — zero when the centroid rides it. The
    torsion that is the entire difference between this and a planar path drops out of
    the volume, and the probe agrees to 1.819e-12.

    It follows that **volume cannot see the third dimension**: the run measured in the
    probe and the same lengths kept planar come back at 12003.3857 both. What sees it is
    the bounding box, which is an expectation documents already carry.
    """

    id: Id
    #: The frame the points are stated in. Its normal is the third component's
    #: direction; the profile stands on a plane perpendicular to the path's first step,
    #: exactly as for a planar path.
    plane: BasePlaneName
    segments: Annotated[list[SpatialSegment], Field(min_length=1, max_length=200)]


class HelicalPath(StrictModel):
    """A path that winds about the normal of the plane it is stated on (CAD-IR 1.14).

    `docs/TASK-POSTMVP-P4-3-a-helix-is-not-a-3d-curve.md` is why this is five numbers
    and not a coordinate vocabulary. Gate P4's table put a spring, an auger, a helical
    groove and a real thread behind P4.3 — "a new coordinate vocabulary in CAD-IR; the
    largest single piece of P4" — and the kernel says otherwise: a helix is `pitch`,
    `height`, `radius`, a hand and an axis, **not one of them a point in space.**

    The axis is the stated plane's own normal, and the helix starts at `radius` along
    that plane's x direction. That is build123d's own convention and it is the same
    move `SweepPath` already makes: a path says which plane it is drawn on, and the
    plane supplies the frame. Nothing here needs a point that CAD-IR cannot say.

    Its length is `turns · √((2πr)² + p²)`, matched by the kernel to 1e-10, so a
    swept spring has a closed-form volume by Pappus — which is what the corpus needs
    before an operation can be promoted at all.
    """

    id: Id
    #: The plane the helix winds in. Its **normal is the axis**, and its x direction
    #: is where the first turn starts.
    plane: BasePlaneName
    #: How far one turn advances along the axis.
    pitch: Scalar
    #: How far the whole helix advances. Turns are `height / pitch`, stated this way
    #: because a drawing dimensions a spring's free length rather than counting turns
    #: — and a non-integer number of turns is an ordinary spring.
    height: Scalar
    #: The distance from the axis to the path, which is where the profile stands.
    radius: Scalar
    #: Which way it winds, and it is **required**.
    #:
    #: Every other property of a part in this contract can be checked against the
    #: built solid. This one cannot: a left-hand and a right-hand helix have the same
    #: volume, the same topology and the same bounding box — measured, not assumed —
    #: so nothing downstream can catch a wrong one. A default would make the
    #: uncheckable property the one a document is allowed to leave out.
    hand: Literal["right", "left"]
    #: How far the radius opens out along the axis, in degrees (CAD-IR 1.15). Zero is
    #: a cylindrical helix and is what every document written before 1.15 means.
    #:
    #: `radius` is then the radius at the **start**, and the far end is
    #: `radius + height * tan(cone_angle)`.
    #:
    #: The engine converts before the kernel sees it, and the reason is measured: this
    #: kernel's `cone_angle` makes `pitch` a distance along the cone's **slant**, while
    #: a drawing dimensions a pitch along the **axis**. A document stating pitch 10 over
    #: height 30 at 30 deg would get 3.464 turns where it drew 3 — a valid, plausible
    #: spring with half a turn too many. So the document states what the drawing states
    #: and trusted code divides by `cos(cone_angle)`, which is the `until_face` pattern:
    #: *what a division in trusted code buys is a number.*
    cone_angle: Scalar = 0.0

    @model_validator(mode="after")
    def validate_dimensions(self) -> "HelicalPath":
        for name, value in (("pitch", self.pitch), ("height", self.height),
                            ("radius", self.radius)):
            stated = stated_number(value)
            # A named one is a promise about a number this module never sees, which
            # the engine resolves and re-checks in front of the kernel.
            if stated is not None and stated <= 0:
                raise ValueError(f"a helix {name} must be positive")
        cone = stated_number(self.cone_angle)
        # Half a right angle each way. Past 90 the "cone" turns inside out, and at 90
        # the conversion this angle exists for divides by zero.
        if cone is not None and not -89.0 <= cone <= 89.0:
            raise ValueError("a helix cone_angle must be between -89 and 89 degrees")
        return self


#: Where a profile travels: a chain of lines and arcs in a plane, the same chain in
#: space, or a helix.
#:
#: No discriminator field, and that is deliberate rather than lazy. Each pair is told
#: apart by what it declares and all three forbid extras, so exactly one of them
#: validates any given payload: a helix by its `pitch`/`height`/`radius`/`hand`, and
#: the two chains by their segments' own `type` — `line`/`arc` against `line3`/`arc3`.
#: Adding a required `kind` would have made every document written before it invalid
#: the moment the normalizer relabelled it, and the normalizer is relabel-only by
#: design (`MIGRATABLE_VERSIONS` derives `RELABEL_ONLY`).
SweepPathSpec = Union[SweepPath, SpatialPath, HelicalPath]


class SweepInputs(StrictModel):
    """A profile and the path it travels.

    No `distance`: how far the material goes is the length of the path, which the
    document already states segment by segment. A second way to say it would be a
    second thing that can disagree.
    """

    sketch: Sketch
    path: SweepPathSpec
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
    path: SweepPathSpec
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
    "HelicalPath",
    "Point3",
    "SolidSweepFeature",
    "SpatialArcSegment",
    "SpatialLineSegment",
    "SpatialPath",
    "SpatialSegment",
    "SweepFeature",
    "SweepInputs",
    "SweepPath",
    "SweepPathSpec",
]
