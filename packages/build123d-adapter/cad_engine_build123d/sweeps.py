"""The path a sweep follows, and the four things about it the kernel will not check.

`sweep` is one call. Everything in this module exists because of what was measured
around it, and each measurement is a way for a document to be built into a part that
is not the one it describes.

**The path's position is ignored.** A profile at the origin swept along a path from
(30, 0, 0) comes back at the origin: OpenCascade uses the path's shape and direction
and anchors it wherever the profile is. So a document could state a path 30 mm away
and get a part 30 mm from where its own coordinates say it is. CAD-IR 1.9 answers this
by making the path **relative** — its first point is where the profile stands, so it
must be the origin of the plane it is drawn in, and there is no absolute position left
to disagree with.

**A path that is not perpendicular to the profile is worse than refused.** Sweep a
Ø16 circle along a 45° line of length 56.57 and the result is 8 042 mm³ — which is
π·8²·**40**, the axial height, not the length travelled. The kernel swept a *skewed*
prism whose true cross-section is smaller than the circle drawn. The volume is out by
1/√2, the drawing said Ø16, and nothing in the document says otherwise.

**A bend tighter than the profile builds and reports itself valid.** A Ø16 pipe round
a 4 mm bend has its inner wall pass through itself; `is_valid` is `True`, and the
volume matches Pappus to the last bit. Only the exported mesh knows — 69 open edges —
which is a torn STL reported as a mesh fault rather than as the document's mistake.

**A corner is not a part.** Real bends have a radius and the drawing dimensions it. A
kernel asked to "handle the transition" picks one of three answers, and an invented
radius is what ADR-026 refuses to let a blend do.

So: connected, starting at the origin, open, tangent-continuous, perpendicular to the
profile, and no bend tighter than the profile reaches into it. Six checks, all against
the coordinates the document states, all in front of the kernel.
"""

from __future__ import annotations

import math

from build123d import Edge, Plane, Vector, Wire
from cad_ir.canonical import SweepPath
from cad_ir.sketch import ArcSegment, LineSegment

from .errors import CadEngineError, unsupported
from .sketches import CLOSURE_TOLERANCE_MM, arc_edge, plane_distance, sketch_point

#: How far from parallel two directions may be and still count as parallel, as the
#: sine of the angle between them. 1e-6 is about 0.2 arc-seconds: far below anything a
#: drawing states and far above the noise of arithmetic on stated coordinates.
DIRECTION_TOLERANCE = 1e-6


def path_wire(path: SweepPath, params, feature_id: str) -> Wire:
    """The path as a wire in its own plane's coordinates, checked as it is built.

    Order is the document's, like a contour's (ADR-020). Re-deriving it by matching
    endpoints would let a document with two possible orderings build two different
    parts on two different days.
    """
    segments = path.segments
    first = sketch_point(segments[0].start, params)
    if plane_distance(first, (0.0, 0.0)) > CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "SWEEP_PATH_NOT_AT_ORIGIN",
            "feature",
            f"The path of {feature_id} starts at {first}. A sweep path is stated from "
            "the profile, so it starts at the origin of its plane: the kernel anchors "
            "the sweep at the profile whatever the path's coordinates say, and a path "
            "that started elsewhere would put the part somewhere its own numbers deny.",
        )

    edges: list[Edge] = []
    previous_end: tuple[float, float] | None = None
    for index, segment in enumerate(segments):
        start = sketch_point(segment.start, params)
        end = sketch_point(segment.end, params)
        if previous_end is not None and plane_distance(previous_end, start) > CLOSURE_TOLERANCE_MM:
            raise CadEngineError(
                "SWEEP_PATH_DISCONNECTED",
                "feature",
                f"Segment {index} of {feature_id}'s path starts at {start}, which is "
                f"not where segment {index - 1} ended, at {previous_end}.",
            )
        if isinstance(segment, LineSegment):
            edges.append(Edge.make_line(Vector(*start, 0), Vector(*end, 0)))
        elif isinstance(segment, ArcSegment):
            edges.append(arc_edge(segment, params))
        else:  # pragma: no cover - the contract's union has only these two
            raise unsupported(f"Unknown path segment {type(segment).__name__}.", "feature")
        previous_end = end

    if plane_distance(previous_end, first) <= CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "SWEEP_PATH_CLOSED",
            "feature",
            f"The path of {feature_id} ends where it began. A closed path meets itself "
            "at a seam the document does not describe; a profile taken all the way "
            "round is a revolve, which states its axis.",
        )

    _require_tangent(segments, params, feature_id)
    return Wire(edges)


def _require_tangent(segments, params, feature_id: str) -> None:
    """Every join carries on in the direction it arrived.

    Checked from the stated coordinates rather than from the built edges: a tangent is
    arithmetic on the numbers in the document, and asking the kernel would mean asking
    it after it had already decided what to do with the corner.
    """
    for index in range(1, len(segments)):
        leaving = _direction_at(segments[index - 1], params, at_end=True)
        arriving = _direction_at(segments[index], params, at_end=False)
        cross = leaving[0] * arriving[1] - leaving[1] * arriving[0]
        dot = leaving[0] * arriving[0] + leaving[1] * arriving[1]
        if abs(cross) > DIRECTION_TOLERANCE or dot <= 0:
            angle = math.degrees(math.atan2(cross, dot))
            raise CadEngineError(
                "SWEEP_PATH_NOT_TANGENT",
                "feature",
                f"The path of {feature_id} turns {angle:.3f}° at the join between "
                f"segments {index - 1} and {index}. A swept path carries on in the "
                "direction it arrived; a bend is an arc of a radius the drawing gives, "
                "not a corner for the kernel to round however it likes.",
            )


def _direction_at(segment, params, at_end: bool) -> tuple[float, float]:
    """The unit direction of travel at one end of a segment, in plane coordinates."""
    start = sketch_point(segment.start, params)
    end = sketch_point(segment.end, params)
    if isinstance(segment, LineSegment):
        return _unit((end[0] - start[0], end[1] - start[1]))

    centre = sketch_point(segment.center, params)
    at = end if at_end else start
    radial = (at[0] - centre[0], at[1] - centre[1])
    # A counterclockwise arc travels 90° left of its radius; a clockwise one, right.
    if str(segment.sweep) == "ccw":
        return _unit((-radial[1], radial[0]))
    return _unit((radial[1], -radial[0]))


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(*vector)
    if length <= CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "SWEEP_PATH_DISCONNECTED", "feature", "A path segment has no length."
        )
    return (vector[0] / length, vector[1] / length)


def require_profile_across_path(
    profile_plane: Plane, path_plane: Plane, path: SweepPath, params, feature_id: str
) -> None:
    """The profile stands across the path, not along it or at an angle to it.

    The measurement this exists for: a Ø16 circle swept along a 45° line comes back
    with the volume of a 40 mm-tall prism rather than a 56.57 mm-long one, because the
    kernel swept the profile's *projection*. The part is a plausible solid of the wrong
    size and the drawing's diameter is nowhere in it.
    """
    local = _direction_at(path.segments[0], params, at_end=False)
    heading = (path_plane.x_dir * local[0] + path_plane.y_dir * local[1]).normalized()
    normal = profile_plane.z_dir.normalized()
    if heading.cross(normal).length > DIRECTION_TOLERANCE:
        angle = math.degrees(math.asin(min(1.0, heading.cross(normal).length)))
        raise CadEngineError(
            "SWEEP_PROFILE_NOT_PERPENDICULAR",
            "feature",
            f"The path of {feature_id} leaves its profile at {90 - angle:.3f}° to the "
            "profile's plane. A sweep carries the profile across the path; at any other "
            "angle the kernel sweeps what the profile projects to, which is a smaller "
            "section than the one the drawing dimensions.",
        )


def require_bends_clear_the_profile(
    face, profile_plane: Plane, path_plane: Plane, path: SweepPath, params, feature_id: str
) -> None:
    """No bend turns tighter than the profile reaches into it.

    A pipe of radius 8 round a bend of radius 4 passes through itself. The kernel
    builds it, reports it valid, and gives it the volume Pappus predicts; only the
    exported mesh shows the tear. Refused here so the document is told what is wrong
    with it rather than being told its mesh is not closed.

    The direction that matters is the one pointing at the centre of the bend. It is
    perpendicular to the path and lies in the path's plane, so it lies in the profile's
    plane too — and the profile's reach along it is a bounding box in a frame where
    that direction is an axis, which OpenCascade computes exactly.
    """
    inward = _bend_normal(path_plane, path, params)
    reach = {side: _reach(face, profile_plane, inward * side) for side in (1.0, -1.0)}

    for index, segment in enumerate(path.segments):
        if not isinstance(segment, ArcSegment):
            continue
        centre = sketch_point(segment.center, params)
        start = sketch_point(segment.start, params)
        radius = plane_distance(centre, start)
        # Which side of the path the centre is on, in the same terms `reach` is keyed by.
        towards = (centre[0] - start[0], centre[1] - start[1])
        along = towards[0] * _in_plane(path_plane, inward)[0] + towards[1] * _in_plane(
            path_plane, inward
        )[1]
        side = 1.0 if along >= 0 else -1.0
        needed = reach[side]
        if radius <= needed + CLOSURE_TOLERANCE_MM:
            raise CadEngineError(
                "SWEEP_BEND_TIGHTER_THAN_PROFILE",
                "feature",
                f"Segment {index} of {feature_id}'s path bends at radius {radius:.4f} mm "
                f"while the profile reaches {needed:.4f} mm towards the centre of that "
                "bend. The inside of the sweep would pass through itself; the kernel "
                "builds it anyway and calls it valid.",
            )


def _bend_normal(path_plane: Plane, path: SweepPath, params) -> Vector:
    """The world direction perpendicular to the path, in the path's plane."""
    local = _direction_at(path.segments[0], params, at_end=False)
    heading = path_plane.x_dir * local[0] + path_plane.y_dir * local[1]
    return heading.cross(path_plane.z_dir).normalized()


def _in_plane(path_plane: Plane, world: Vector) -> tuple[float, float]:
    """A world direction back in the path plane's own coordinates."""
    return (world.dot(path_plane.x_dir), world.dot(path_plane.y_dir))


def _reach(face, profile_plane: Plane, direction: Vector) -> float:
    """How far the placed profile extends along `direction` from its plane's origin.

    Measured with an optimal bounding box in a frame whose x axis is `direction`, which
    is exact for the analytic surfaces this engine draws — a circle of radius 8 measures
    8, not 8.0001.
    """
    frame = Plane(origin=profile_plane.origin, x_dir=direction, z_dir=profile_plane.z_dir)
    return float((frame.location.inverse() * face).bounding_box().max.X)


__all__ = [
    "DIRECTION_TOLERANCE",
    "path_wire",
    "require_bends_clear_the_profile",
    "require_profile_across_path",
]
