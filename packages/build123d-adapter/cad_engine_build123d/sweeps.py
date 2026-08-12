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

from build123d import Edge, Helix, Plane, Vector, Wire
from cad_ir.canonical import SpatialArcSegment, SpatialLineSegment, SweepPath
from cad_ir.sketch import ArcSegment, LineSegment
from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer, BOPAlgo_CheckStatus

from .errors import CadEngineError, unsupported
from .sketches import CLOSURE_TOLERANCE_MM, arc_edge, plane_distance, sketch_point

#: How far from parallel two directions may be and still count as parallel, as the
#: sine of the angle between them. 1e-6 is about 0.2 arc-seconds: far below anything a
#: drawing states and far above the noise of arithmetic on stated coordinates.
DIRECTION_TOLERANCE = 1e-6


#: How much of the section may overlap the next turn before it is refused, in mm.
#:
#: Nothing: turns touching exactly is the boundary, and past it the solid passes
#: through itself. A small slack would be inventing a clearance the drawing did not
#: give, which is what ADR-026 refuses to let a blend do.
_HELIX_TOUCH_TOLERANCE_MM = 0.0


def helix_wire(path, params, feature_id: str) -> Wire:
    """A helical path, wound about the normal of the plane it is stated on.

    Five numbers and a direction, and the reason that is enough is
    `docs/TASK-POSTMVP-P4-3-a-helix-is-not-a-3d-curve.md`: Gate P4 assumed a spring
    needed a coordinate vocabulary, and the kernel needs `pitch`, `height`, `radius`
    and a hand. The plane supplies the frame, exactly as it does for a planar path.

    Measured: the wire's length is `turns · √((2πr)² + p²)` to 1e-10, so a swept
    spring has a closed-form volume by Pappus.

    **The cone angle is converted before the kernel sees it** (CAD-IR 1.15), because
    this kernel's `cone_angle` makes `pitch` a distance along the cone's *slant* while
    a drawing dimensions a pitch along the *axis*. Measured on the probe:

        cone  0 deg   z per turn 10.00000   3.00000 turns
        cone 15 deg   z per turn  9.65926   3.10583 turns
        cone 30 deg   z per turn  8.66025   3.46410 turns

    `z per turn` is `pitch · cos(cone_angle)`, so a document stating the pitch a
    drawing states would get half a turn too many at 30°, in a spring that is valid,
    plausible and matches every closed form computed *from the kernel*. Dividing here
    is the `until_face` pattern: what a division in trusted code buys is a number.
    """
    pitch = params.resolve(path.pitch, f"{feature_id} helix pitch")
    height = params.resolve(path.height, f"{feature_id} helix height")
    radius = params.resolve(path.radius, f"{feature_id} helix radius")
    cone = params.resolve(path.cone_angle, f"{feature_id} helix cone angle")
    for name, value in (("pitch", pitch), ("height", height), ("radius", radius)):
        if value <= 0:
            raise CadEngineError(
                "DIMENSION_OUT_OF_RANGE",
                "feature",
                f"A helix {name} must be positive; {feature_id} resolves it to {value:g}.",
            )
    if not -89.0 <= cone <= 89.0:
        raise CadEngineError(
            "DIMENSION_OUT_OF_RANGE",
            "feature",
            f"A helix cone angle must be between -89 and 89 degrees; {feature_id} "
            f"resolves it to {cone:g}.",
        )
    if radius + height * math.tan(math.radians(cone)) <= CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "DIMENSION_OUT_OF_RANGE",
            "feature",
            f"The cone angle of {feature_id} closes the helix onto its own axis before "
            f"the end: radius {radius:g} at the start, "
            f"{radius + height * math.tan(math.radians(cone)):g} at height {height:g}.",
        )
    return Wire(
        Helix(
            pitch=pitch / math.cos(math.radians(cone)),
            height=height,
            radius=radius,
            cone_angle=cone,
            lefthand=path.hand == "left",
        ).edges()
    )


def helix_section_plane(wire: Wire, axis: Vector) -> Plane:
    """Where a helix's section stands, with a frame this repository chose.

    `Plane(origin, z_dir=…)` leaves the in-plane frame to build123d, and build123d
    picks whichever global axis is least parallel to the normal — measured, it returned
    the projection of +X for one direction and of +Z for another. That is a heuristic
    rather than a convention, and a **round section cannot tell**, which is why 1.14
    never had to ask. A thread's flanks can: they are nothing but a direction.

    So the frame is built here from the path itself. `x` is the helix's **axis
    projected into the section plane** and `y` follows, which puts a section drawn the
    way a drawing draws one — along the screw, and radially outward for depth — where
    the drawing puts it. It cannot be exactly the axis, because the plane is
    perpendicular to a tangent that leans by the lead angle; the projection is the
    nearest thing the geometry allows, and it is stated rather than inherited.
    """
    tangent = (wire % 0).normalized()
    along = axis.normalized()
    # The axis, less whatever of it points along the path.
    in_plane = along - tangent * along.dot(tangent)
    if in_plane.length <= DIRECTION_TOLERANCE:  # pragma: no cover - a helix never does
        raise CadEngineError(
            "DIMENSION_OUT_OF_RANGE",
            "feature",
            "A helical path leaves its own plane along the axis, which no helix does.",
        )
    return Plane(origin=wire @ 0, x_dir=in_plane.normalized(), z_dir=tangent)


def require_pitch_clears_the_section(face, profile_plane: Plane, axis: Vector,
                                     pitch: float, feature_id: str) -> None:
    """A spring wound tighter than its own wire is refused before the kernel sees it.

    Measured, and it is the fifth instance of the rule ADR-033 states. A 2 mm wire on
    a 2 mm pitch overlaps its neighbouring turn by half its diameter, and the kernel
    returns one solid, calls it valid, and produces a volume that **matches Pappus** —
    because the material counted twice is exactly the material the formula counts
    twice. Nothing in the volume can see it.

    The genus cross-check of POSTMVP-020 does catch it, by disagreeing with itself
    across two exporters. But the condition is closed-form and knowable beforehand:
    turns touch when the section's extent along the axis reaches the pitch. So it is
    refused here with a number in it, the way `SWEEP_BEND_TIGHTER_THAN_PROFILE` is,
    because a refusal a repair loop can read beats a genus that came out wrong.
    """
    forward = _reach(face, profile_plane, axis)
    backward = _reach(face, profile_plane, -axis)
    extent = forward + backward
    if extent - pitch > _HELIX_TOUCH_TOLERANCE_MM:
        raise CadEngineError(
            "HELIX_PITCH_TIGHTER_THAN_SECTION",
            "feature",
            f"The path of {feature_id} advances {pitch:.4f} mm per turn while its "
            f"section spans {extent:.4f} mm along the axis. Neighbouring turns would "
            "pass through each other; the kernel builds it anyway, calls it valid, and "
            "returns a volume that agrees with Pappus because the overlap is counted "
            "twice on both sides.",
        )


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


# --- a path that leaves its plane (CAD-IR 1.15) -----------------------------------
#
# `docs/TASK-POSTMVP-P4-3-a-path-that-leaves-its-plane.md` is the argument. Everything
# below is the planar code with a third component and one extra consequence: a section
# carried round a path in space is *rotated* by the time it reaches the next bend, so
# the reach that decides whether that bend is too tight has to be measured in the
# section's own frame at that point rather than at the start.


def spatial_path_wire(path, params, feature_id: str, path_plane: Plane) -> Wire:
    """A path in space as a wire in world coordinates, checked as it is built.

    The world rather than the plane's local frame, unlike `path_wire`, because a
    spatial path's checks need world directions anyway — and building it here means
    the wire the trace records is the wire the checks ran against.

    Every rule is 1.9's: it starts at the plane's origin (ADR-031 — the kernel anchors
    a sweep at the profile whatever the path says, so a path that started elsewhere
    would put the part where its own numbers deny), it is connected, it is open, and it
    is tangent-continuous.
    """
    segments = path.segments
    points = [_spatial_point(segment.start, params, path_plane) for segment in segments]
    ends = [_spatial_point(segment.end, params, path_plane) for segment in segments]

    if (points[0] - path_plane.origin).length > CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "SWEEP_PATH_NOT_AT_ORIGIN",
            "feature",
            f"The path of {feature_id} starts at {_show(points[0])}. A sweep path is "
            "stated from the profile, so it starts at the origin of its plane: the "
            "kernel anchors the sweep at the profile whatever the path's coordinates "
            "say, and a path that started elsewhere would put the part somewhere its "
            "own numbers deny.",
        )

    edges: list[Edge] = []
    for index, segment in enumerate(segments):
        start, end = points[index], ends[index]
        if index and (start - ends[index - 1]).length > CLOSURE_TOLERANCE_MM:
            raise CadEngineError(
                "SWEEP_PATH_DISCONNECTED",
                "feature",
                f"Segment {index} of {feature_id}'s path starts at {_show(start)}, "
                f"which is not where segment {index - 1} ended, at "
                f"{_show(ends[index - 1])}.",
            )
        if isinstance(segment, SpatialLineSegment):
            if (end - start).length <= CLOSURE_TOLERANCE_MM:
                raise CadEngineError(
                    "SWEEP_PATH_DISCONNECTED",
                    "feature",
                    f"Segment {index} of {feature_id}'s path has no length.",
                )
            edges.append(Edge.make_line(start, end))
        elif isinstance(segment, SpatialArcSegment):
            edges.append(_spatial_arc(segment, params, path_plane, index, feature_id))
        else:  # pragma: no cover - the contract's union has only these two
            raise unsupported(f"Unknown path segment {type(segment).__name__}.", "feature")

    if (ends[-1] - points[0]).length <= CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "SWEEP_PATH_CLOSED",
            "feature",
            f"The path of {feature_id} ends where it began. A closed path meets itself "
            "at a seam the document does not describe; a profile taken all the way "
            "round is a revolve, which states its axis.",
        )

    _require_tangent_in_space(segments, params, path_plane, feature_id)
    return Wire(edges)


def _arc_frame(segment, params, path_plane: Plane, index: int, feature_id: str):
    """Everything a spatial arc is, checked once and shared by everything that asks.

    One function rather than three, because each of the three callers below needs the
    binormal and each would divide by zero on the same document. It was measured: a
    half-turn arc reached `require_spatial_bends_clear_the_profile` before the wire was
    built and escaped as `gp_Vec::Normalized() - vector has zero norm` — a crash where
    a refusal was written and waiting.
    """
    start = _spatial_point(segment.start, params, path_plane)
    end = _spatial_point(segment.end, params, path_plane)
    centre = _spatial_point(segment.center, params, path_plane)

    from_start, from_end = start - centre, end - centre
    radius, other = from_start.length, from_end.length
    if radius <= CLOSURE_TOLERANCE_MM or abs(radius - other) > CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "SWEEP_PATH_ARC_NOT_CIRCULAR",
            "feature",
            f"Segment {index} of {feature_id}'s path names a centre {radius:.4f} mm "
            f"from its start and {other:.4f} mm from its end. An arc has one radius, "
            "and the two distances are how a document says so.",
        )
    if from_start.cross(from_end).length <= radius * radius * DIRECTION_TOLERANCE:
        raise CadEngineError(
            "SWEEP_PATH_ARC_AMBIGUOUS",
            "feature",
            f"Segment {index} of {feature_id}'s path turns half a circle or more: its "
            "start, centre and end lie on one line, which leaves the plane the arc "
            "bends in undecided. The kernel's answer to that is a construction error "
            "with an empty message. State the bend as two arcs joined tangentially — "
            "which is what a drawing dimensions anyway.",
        )
    return start, end, centre, from_start, from_end, radius


def _spatial_arc(segment, params, path_plane: Plane, index: int, feature_id: str) -> Edge:
    """The shorter of the two arcs through `start` and `end` about `center`.

    "Shorter" is not a preference, it is the only one a tangent-continuous path can
    take: the longer arc leaves its start in the opposite direction, so it could never
    carry on the way the path arrived. That is why a spatial arc carries no `sweep`
    field where a planar one does — a planar arc is shared with sketch contours, which
    have the freedom a path does not.
    """
    start, end, centre, from_start, from_end, radius = _arc_frame(
        segment, params, path_plane, index, feature_id
    )
    # The midpoint of the shorter arc: out along the bisector of the two radii.
    bisector = (from_start.normalized() + from_end.normalized()).normalized()
    return Edge.make_three_point_arc(start, centre + bisector * radius, end)


def _require_tangent_in_space(segments, params, path_plane: Plane, feature_id: str) -> None:
    """Every join carries on in the direction it arrived, in three dimensions.

    Checked from the stated coordinates, like the planar one, and for the same reason:
    a tangent is arithmetic on the numbers in the document, and asking the kernel would
    mean asking it after it had already decided what to do with the corner.
    """
    for index in range(1, len(segments)):
        leaving = _spatial_direction(
            segments[index - 1], params, path_plane, True, index - 1, feature_id
        )
        arriving = _spatial_direction(
            segments[index], params, path_plane, False, index, feature_id
        )
        cross = leaving.cross(arriving).length
        dot = leaving.dot(arriving)
        if cross > DIRECTION_TOLERANCE or dot <= 0:
            angle = math.degrees(math.atan2(cross, dot))
            raise CadEngineError(
                "SWEEP_PATH_NOT_TANGENT",
                "feature",
                f"The path of {feature_id} turns {angle:.3f}° at the join between "
                f"segments {index - 1} and {index}. A swept path carries on in the "
                "direction it arrived; a bend is an arc of a radius the drawing gives, "
                "not a corner for the kernel to round however it likes.",
            )


def _spatial_direction(segment, params, path_plane: Plane, at_end: bool,
                       index: int = 0, feature_id: str = "") -> Vector:
    """The unit direction of travel at one end of a spatial segment, in world terms."""
    if isinstance(segment, SpatialLineSegment):
        start = _spatial_point(segment.start, params, path_plane)
        end = _spatial_point(segment.end, params, path_plane)
        return (end - start).normalized()

    _, _, _, from_start, from_end, _ = _arc_frame(
        segment, params, path_plane, index, feature_id
    )
    # The binormal of the shorter arc, and the velocity is the binormal crossed into
    # the radius — which is the same formula at both ends.
    binormal = from_start.cross(from_end).normalized()
    return binormal.cross(from_end if at_end else from_start).normalized()


def require_profile_across_spatial_path(
    profile_plane: Plane, path_plane: Plane, path, params, feature_id: str
) -> None:
    """The profile stands across a spatial path, on the same measurement as a planar one.

    Measured on the probe: a section tilted 45° to a 3D run comes back at 8487.6754
    where 12003.3857 was drawn — the kernel sweeps the section's *projection*, exactly
    as ADR-031 measured in the plane, and the ratio is the same 1/√2.
    """
    heading = _spatial_direction(path.segments[0], params, path_plane, False, 0, feature_id)
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


def require_spatial_bends_clear_the_profile(
    face, profile_plane: Plane, path_plane: Plane, path, params, feature_id: str
) -> None:
    """No bend turns tighter than the profile reaches into it — in space.

    The planar version measures the profile's reach once, because a planar path rotates
    the section about one fixed axis and the inward direction of every bend rotates with
    it: the two cancel and the reach in the section's own frame never changes. A path
    that leaves its plane has no such luck. By the time the section arrives at the third
    bend it has been turned by the two before it, and the direction pointing at that
    bend's centre is somewhere else in the section's own frame.

    So the rotation is accumulated as the path is walked — one turn about the arc's own
    binormal per bend — and the inward direction is carried **back** through it before
    the profile is measured. Within a single arc nothing more is needed: the section and
    the inward direction turn about the same binormal by the same angle, so the reach is
    constant along the bend and the value at its start is exact.
    """
    history: list[tuple[Vector, float]] = []
    for index, segment in enumerate(path.segments):
        if not isinstance(segment, SpatialArcSegment):
            continue
        _, _, _, from_start, from_end, radius = _arc_frame(
            segment, params, path_plane, index, feature_id
        )

        inward = from_start.normalized() * -1.0
        # Back through every turn taken so far, latest first: the section's frame at
        # this bend is `R` applied to its frame at the start, so a world direction is
        # `R⁻¹ · d` in the frame the profile was drawn in.
        local = inward
        for axis, angle in reversed(history):
            local = _rotated(local, axis, -angle)
        needed = _reach(face, profile_plane, local)

        if radius <= needed + CLOSURE_TOLERANCE_MM:
            raise CadEngineError(
                "SWEEP_BEND_TIGHTER_THAN_PROFILE",
                "feature",
                f"Segment {index} of {feature_id}'s path bends at radius {radius:.4f} mm "
                f"while the profile reaches {needed:.4f} mm towards the centre of that "
                "bend. The inside of the sweep would pass through itself; the kernel "
                "builds it anyway and calls it valid.",
            )

        binormal = from_start.cross(from_end).normalized()
        turn = math.atan2(from_start.cross(from_end).length, from_start.dot(from_end))
        history.append((binormal, turn))


def _rotated(vector: Vector, axis: Vector, angle: float) -> Vector:
    """Rodrigues' formula. Written out because the alternative is a Location round trip
    for what is three multiplications, and because a rotation the reader can check is
    worth more here than one hidden behind a transform."""
    cos, sin = math.cos(angle), math.sin(angle)
    return (
        vector * cos
        + axis.cross(vector) * sin
        + axis * (axis.dot(vector) * (1.0 - cos))
    )


def _spatial_point(value, params, path_plane: Plane) -> Vector:
    """A three-component path point, resolved and placed in world coordinates.

    The components are in the path plane's own frame — u along its x direction, v along
    its y, and w out of it — which is what makes `plane` mean the same thing it means
    for a planar path even though the path no longer lies in it.
    """
    u = params.resolve(value[0], "spatial path point")
    v = params.resolve(value[1], "spatial path point")
    w = params.resolve(value[2], "spatial path point")
    return path_plane.origin + path_plane.x_dir * u + path_plane.y_dir * v + path_plane.z_dir * w


def _show(point: Vector) -> str:
    return f"({float(point.X):.4f}, {float(point.Y):.4f}, {float(point.Z):.4f})"


# --- the backstop none of the closed forms could be ------------------------------


def require_no_self_intersection(solid, feature_id: str, what: str) -> None:
    """A solid that passes through itself is never the part on a drawing.

    This is the one check in this module that asks the kernel instead of the document,
    and it exists because the probe found a failure **nothing else in this service
    catches**. It has to be a *spiral*, and that is why the gap survived so long: two
    tangent bends of radius R put the outgoing and returning runs 2R apart, and the
    bend rule already requires R to clear the profile — so a U-turn's runs can never
    touch. A path that comes back alongside a part of itself that is **not its
    neighbour** can.

    Four bends of R35, a section reaching 30, a last run 25 mm from the first:

        volume  2643399.9499   valid   Pappus 2643399.9499   diff 4.657e-10
        B-rep   1 solid, 1 shell, 11 faces, genus 0
        mesh    33764 triangles, 0 open edges, 0 inconsistent normals, genus 0

    Every check passes. The genus cross-check of POSTMVP-020 — which does catch the
    self-intersecting sweep of POSTMVP-018 — agrees with itself here, because this
    surface passes through itself *smoothly*: no triangle edge is left unmatched, so
    the mesh is a closed manifold and both computations of the genus give 0. The volume
    matches its own closed form, because the material counted twice is the material the
    formula counts twice.

    Every closed-form check written for this family before it is **local**:
    `SWEEP_BEND_TIGHTER_THAN_PROFILE` looks at one bend against the profile,
    `HELIX_PITCH_TIGHTER_THAN_SECTION` at one turn against its neighbour. Two
    *different* parts of a path meeting each other is invisible to both. And the path
    above is **planar**, so this is a hole in 1.9 rather than a cost of 1.15.

    `BOPAlgo_ArgumentAnalyzer` with `SelfInterMode` answers it exactly, in
    milliseconds, with no false positive on an ordinary part:

        a plain block / a cylinder             False   0.00s
        the spiral with a section reaching 10  False   0.09s
        the spiral with a section reaching 30  True    0.18s
        tight bend R4 with a section reaching 8  True  0.03s
        the same bend with a section reaching 2  False 0.03s
        a helix of pitch 2.0 carrying a 2 mm wire  True 0.84s

    It does **not** make the two closed-form pre-checks redundant, and the difference is
    the one this repository keeps arriving at: a pre-check refuses with a number the
    repair loop can read — "bends at radius 4 while the profile reaches 8" — and this
    one can say only that it happens somewhere. The pre-checks name the mistake; this is
    the backstop for what no closed form covers.
    """
    analyzer = BOPAlgo_ArgumentAnalyzer()
    analyzer.SetShape1(solid.wrapped)
    # One question only. Every other mode this analyzer offers is about arguments to a
    # boolean operation, which is not what is being asked.
    analyzer.SelfInterMode = True
    analyzer.StopOnFirstFaulty = True
    analyzer.Perform()

    faulty = any(
        result.GetCheckStatus() == BOPAlgo_CheckStatus.BOPAlgo_SelfIntersect
        for result in analyzer.GetCheckResult()
    )
    if faulty:
        raise CadEngineError(
            "SOLID_PASSES_THROUGH_ITSELF",
            "feature",
            f"The {what} of {feature_id} passes through itself. The kernel returns one "
            "solid and reports it valid, its volume agrees with the closed form because "
            "the overlapping material is counted twice on both sides, and its mesh is a "
            "closed manifold — so nothing downstream would have said anything. Two parts "
            "of the path meet, or the section is larger than the part of the path it "
            "travels can carry.",
        )


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
    "helix_section_plane",
    "helix_wire",
    "path_wire",
    "require_bends_clear_the_profile",
    "require_no_self_intersection",
    "require_pitch_clears_the_section",
    "require_profile_across_path",
    "require_profile_across_spatial_path",
    "require_spatial_bends_clear_the_profile",
    "spatial_path_wire",
]
