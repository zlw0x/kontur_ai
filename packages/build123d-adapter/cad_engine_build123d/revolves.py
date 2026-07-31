"""Turn a CAD-IR revolve into an axis and a checked profile.

Separate from `adapter.py` because the interesting half of a revolve is the
refusal, and a refusal is worth testing on its own. Building one is a documented
kernel call; deciding whether the document describes a solid at all is arithmetic
this module does in the sketch's own plane, before any of it reaches OpenCascade.

The check that matters is that **the profile does not cross the axis**. A profile
straddling its axis sweeps through itself. Left to the kernel, every crossing
profile measured here — symmetric or offset, a full turn or a quarter — comes back
as `StdFail_NotDone: BRep_API: command not done`, raised from inside OpenCascade
with no code, no stage and no mention of the document. That is not a refusal a
caller can act on: it escapes the worker's typed-error contract as a crash, and it
does not say which feature was wrong or why. Touching the axis is fine and is how
a solid shaft is drawn; crossing it never is, and saying so is this module's job.

Sampled rather than reasoned about from the endpoints. An arc can begin and end
on one side of a line and bulge across it in the middle, and a check that looked
only at where segments start and stop would pass that document.
"""

from __future__ import annotations

import math

from build123d import Axis, Plane, Vector
from cad_ir.revolve import RevolveByConstructionLine, RevolveByPoints
from cad_ir.sketch import ConstructionLine

from .errors import CadEngineError, unsupported

#: How close to the axis still counts as on it.
#:
#: The same micron `sketches.py` uses to decide a contour closes, and for the
#: same reason: a drawing states a few decimal places, so an exact comparison
#: would call a shaft drawn from x = 0 a crossing on the strength of rounding.
ON_AXIS_TOLERANCE_MM = 1e-6

#: How many points along each boundary edge are tested. Ten intervals resolves
#: the bulge of any arc a drawing contains to far below the tolerance above,
#: and the cost is a few dozen multiplications per feature.
SAMPLES_PER_EDGE = 10


def axis_points(inputs, sketch, params) -> tuple[tuple[float, float], tuple[float, float]]:
    """The axis as two points in sketch coordinates.

    Both spellings end here. A construction line is looked up by name in the
    sketch it belongs to — the contract has already checked the name is one of
    that sketch's construction *lines*, so a miss at this point is a bug in this
    engine rather than a bad document, and it says so.

    Either coordinate may be a parameter, like every other coordinate in a sketch:
    an axis that moves with the part's height is what a parametric centre line is
    for.
    """

    def point(value, what):
        return (params.resolve(value[0], what), params.resolve(value[1], what))

    if isinstance(inputs.axis, RevolveByPoints):
        return _distinct(
            point(inputs.axis.axis.start, "the revolve axis start"),
            point(inputs.axis.axis.end, "the revolve axis end"),
        )
    if isinstance(inputs.axis, RevolveByConstructionLine):
        for entity in sketch.construction:
            if isinstance(entity, ConstructionLine) and entity.id == inputs.axis.entity:
                return _distinct(
                    point(entity.start, f"construction line {entity.id}"),
                    point(entity.end, f"construction line {entity.id}"),
                )
        raise CadEngineError(
            "CAD_IR_INVALID",
            "feature",
            f"The axis names {inputs.axis.entity}, which sketch {sketch.id} does not "
            "carry as a construction line.",
        )
    raise unsupported(f"Unknown revolve axis {type(inputs.axis).__name__}.", "feature")


def _distinct(start, end):
    """The two points, or a typed refusal if they are the same point.

    The contract compares the two as they are *written*, which cannot see a pair
    that are distinct in the document and coincide once their parameters resolve.
    Checked here, in sketch coordinates, rather than after the mapping into world
    space: placing a sketch is a rigid transform, so two points that coincide on
    the plane coincide off it, and checking the shorter of the two forms means the
    error names what the document said.
    """
    if math.dist(start, end) < ON_AXIS_TOLERANCE_MM:
        raise CadEngineError(
            "REVOLVE_AXIS_INVALID",
            "feature",
            "The revolve axis has no length: its two points are the same point.",
        )
    return start, end


def world_axis(plane: Plane, points) -> Axis:
    """The sketch-plane axis, placed where the sketch is.

    Two points are mapped into world space and subtracted, rather than the
    direction being mapped on its own: a direction mapped through a plane's
    location would pick up the origin's translation and point somewhere the
    document never said.
    """
    (start_u, start_v), (end_u, end_v) = points
    start = plane.from_local_coords(Vector(start_u, start_v, 0.0))
    end = plane.from_local_coords(Vector(end_u, end_v, 0.0))
    return Axis(start, end - start)


def require_profile_clear_of_axis(face, points, feature_id: str) -> None:
    """Refuse a profile that crosses its own axis.

    Works on the face in sketch coordinates, before it is placed, because that is
    where the axis is stated and where the arithmetic is two-dimensional.

    The cross product of the axis with the vector to a sampled point gives twice
    the area of the triangle between them; dividing by the axis's length turns it
    into the point's signed distance from the axis, which is what the tolerance is
    in. Without that division the same profile would pass or fail depending on how
    long a line the document happened to draw its centre line as.
    """
    (start_u, start_v), (end_u, end_v) = points
    axis_u, axis_v = end_u - start_u, end_v - start_v
    length = math.hypot(axis_u, axis_v)

    left = right = False
    for edge in face.edges():
        for step in range(SAMPLES_PER_EDGE + 1):
            point = edge.position_at(step / SAMPLES_PER_EDGE)
            side = (
                axis_u * (point.Y - start_v) - axis_v * (point.X - start_u)
            ) / length
            if side > ON_AXIS_TOLERANCE_MM:
                left = True
            elif side < -ON_AXIS_TOLERANCE_MM:
                right = True
            if left and right:
                raise CadEngineError(
                    "REVOLVE_PROFILE_CROSSES_AXIS",
                    "feature",
                    f"The profile of {feature_id} lies on both sides of its axis. A "
                    "revolved profile may touch its axis but not cross it, or the two "
                    "halves sweep through each other.",
                )


__all__ = [
    "ON_AXIS_TOLERANCE_MM",
    "axis_points",
    "require_profile_clear_of_axis",
    "world_axis",
]
