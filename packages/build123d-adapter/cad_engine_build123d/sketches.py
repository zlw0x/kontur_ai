"""Turn a CAD-IR sketch into a build123d face.

A sketch in CAD-IR is one outer contour and any number of islands, all with
explicit coordinates (ADR-020). That maps onto a face with holes, which is what
extrude wants — so this module's whole job is contour to wire, wire to face,
face minus islands.

**Nothing here interprets anything the AI wrote as code.** The document is data:
it names shapes from a fixed vocabulary, and each name has a hand-written branch
below. There is no `eval`, no `exec`, and no path by which a string in a document
becomes a call. ADR-023 states the rule; this file is where it would be most
tempting to break, because the engine is a Python library and the document is
almost a program.
"""

from __future__ import annotations

import math

from build123d import AngularDirection, Edge, Face, Plane, Vector, Wire
from cad_ir.sketch import (
    ArcSegment,
    CircleContour,
    LineSegment,
    PathContour,
    RectangleContour,
    RegularPolygonContour,
    SlotContour,
    Sweep,
)

from .errors import CadEngineError, unsupported

#: How far apart two points may be and still count as the same point.
#:
#: A contour is closed when each segment's end is the next one's start. The
#: document states coordinates to a few decimal places, so an exact comparison
#: would reject contours that are closed in every sense that matters. A micron is
#: far below anything a drawing means and far above the rounding.
CLOSURE_TOLERANCE_MM = 1e-6


def _point(value, params) -> tuple[float, float]:
    """A CAD-IR `Point2` as a pair of numbers.

    Its two coordinates are scalars, and a scalar may be a parameter reference:
    a hole whose centre moves with a plate's width is exactly what parameters
    are for. Resolving them here rather than at the call sites is what keeps
    every shape below from having to remember.
    """
    return (
        params.resolve(value[0], "x coordinate"),
        params.resolve(value[1], "y coordinate"),
    )


def contour_wire(contour, params) -> Wire:
    """One closed contour as a wire, in sketch coordinates."""
    if isinstance(contour, CircleContour):
        centre = _point(contour.center, params)
        radius = params.resolve(contour.radius, "circle radius")
        return Wire([Edge.make_circle(radius, Plane(origin=(centre[0], centre[1], 0)))])

    if isinstance(contour, RectangleContour):
        return _polygon_wire(_rectangle_points(contour, params))

    if isinstance(contour, RegularPolygonContour):
        return _polygon_wire(_regular_polygon_points(contour, params))

    if isinstance(contour, SlotContour):
        return _slot_wire(contour, params)

    if isinstance(contour, PathContour):
        return _path_wire(contour, params)

    raise unsupported(f"This engine cannot draw a {type(contour).__name__}.")


#: How much area an island has to remove to count as being inside the profile.
#:
#: A square micron. Small enough that a genuine hole always clears it, large enough that
#: the kernel's arithmetic on a boolean cannot fake it.
ISLAND_AREA_TOLERANCE_MM2 = 1e-6


def sketch_face(outer, inner: list, params) -> Face:
    """The outer contour with its islands removed.

    Islands are subtracted rather than passed as inner wires so that an island
    which is not actually inside the profile fails here, loudly, instead of
    producing a face whose validity depends on the kernel's mood.
    """
    face = Face(contour_wire(outer, params))
    if not face.is_valid:
        raise CadEngineError(
            "SKETCH_INVALID", "sketch", "The outer contour does not bound a valid face."
        )
    for island in inner:
        hole = Face(contour_wire(island, params))
        if not hole.is_valid:
            raise CadEngineError(
                "SKETCH_INVALID", "sketch", "An island does not bound a valid face."
            )
        before = float(face.area)
        remaining = face - hole
        faces = remaining.faces()
        if len(faces) == 1 and float(faces[0].area) >= before - ISLAND_AREA_TOLERANCE_MM2:
            # The island removed nothing, which means it is not in the profile at all —
            # it sits beside the part. Found by the golden corpus (POSTMVP-013): the
            # region count below catches an island that swallows the profile or cuts it
            # in two, and one that misses entirely leaves exactly one region of exactly
            # the same size. So the engine built a plate with no hole in it and reported
            # success, and the only thing that would have noticed is a through-hole
            # expectation the document might not carry.
            raise CadEngineError(
                "SKETCH_ISLAND_OUTSIDE_PROFILE",
                "sketch",
                "An island removes no area from the profile, so it lies outside it. A "
                "hole beside the part is a document that means something else.",
            )
        if len(faces) != 1:
            # Zero means the island swallowed the profile; more than one means it
            # cut it in two. Either way the document did not describe a plate with
            # a hole in it, and guessing which face was meant is not this
            # engine's decision to make.
            raise CadEngineError(
                "SKETCH_INVALID",
                "sketch",
                f"An island leaves {len(faces)} regions rather than one; it must lie "
                "wholly inside the profile.",
            )
        face = faces[0]
    return face


# ---------------------------------------------------------------------------
# The shapes
# ---------------------------------------------------------------------------


def _rectangle_points(contour: RectangleContour, params) -> list[tuple[float, float]]:
    cx, cy = _point(contour.center, params)
    half_w = params.resolve(contour.width, "rectangle width") / 2
    half_h = params.resolve(contour.height, "rectangle height") / 2
    corners = [(-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)]
    return [_rotated(point, contour.rotation_deg, (cx, cy), params) for point in corners]


def _regular_polygon_points(contour: RegularPolygonContour, params) -> list[tuple[float, float]]:
    cx, cy = _point(contour.center, params)
    radius = params.resolve(contour.circumradius, "polygon circumradius")
    step = 360.0 / contour.sides
    # First vertex on the +X axis before rotation, so a hexagon drawn twice from
    # the same document has its vertices in the same places both times.
    return [
        _rotated(
            (radius * math.cos(math.radians(index * step)),
             radius * math.sin(math.radians(index * step))),
            contour.rotation_deg,
            (cx, cy),
            params,
        )
        for index in range(contour.sides)
    ]


def _rotated(
    point: tuple[float, float],
    degrees: float,
    about: tuple[float, float],
    params,
) -> tuple[float, float]:
    angle = math.radians(params.resolve(degrees, "rotation"))
    cos, sin = math.cos(angle), math.sin(angle)
    return (
        about[0] + point[0] * cos - point[1] * sin,
        about[1] + point[0] * sin + point[1] * cos,
    )


def _polygon_wire(points: list[tuple[float, float]]) -> Wire:
    vertices = [Vector(x, y, 0) for x, y in points]
    edges = [
        Edge.make_line(vertices[index], vertices[(index + 1) % len(vertices)])
        for index in range(len(vertices))
    ]
    return Wire(edges)


def _slot_wire(contour: SlotContour, params) -> Wire:
    """A stadium: two parallel lines closed by a semicircle at each end."""
    start = Vector(*_point(contour.start, params), 0)
    end = Vector(*_point(contour.end, params), 0)
    radius = params.resolve(contour.radius, "slot radius")
    axis = end - start
    if axis.length <= CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "SKETCH_INVALID", "sketch", "A slot needs two distinct centres."
        )
    normal = Vector(-axis.Y, axis.X, 0).normalized() * radius
    edges = [
        Edge.make_line(start + normal, end + normal),
        Edge.make_three_point_arc(end + normal, end + axis.normalized() * radius, end - normal),
        Edge.make_line(end - normal, start - normal),
        Edge.make_three_point_arc(
            start - normal, start - axis.normalized() * radius, start + normal
        ),
    ]
    return Wire(edges)


def _path_wire(contour: PathContour, params) -> Wire:
    """Lines and arcs, in the order the document gives them.

    The document's own order is the contour's order. Re-deriving it by matching
    endpoints would let a document with two possible orderings build two
    different parts on two different days.
    """
    edges: list[Edge] = []
    previous_end: tuple[float, float] | None = None
    for index, segment in enumerate(contour.segments):
        start = _point(segment.start, params)
        end = _point(segment.end, params)
        if previous_end is not None and _distance(previous_end, start) > CLOSURE_TOLERANCE_MM:
            raise CadEngineError(
                "SKETCH_NOT_CLOSED",
                "sketch",
                f"Segment {index} starts at {start}, which is not where segment "
                f"{index - 1} ended, at {previous_end}. A contour is closed by its "
                "coordinates, not by the engine.",
            )
        if isinstance(segment, LineSegment):
            edges.append(Edge.make_line(Vector(*start, 0), Vector(*end, 0)))
        elif isinstance(segment, ArcSegment):
            edges.append(_arc_edge(segment, params))
        else:  # pragma: no cover - the contract's union has only these two
            raise unsupported(f"Unknown path segment {type(segment).__name__}.", "sketch")
        previous_end = end

    first = _point(contour.segments[0].start, params)
    if previous_end is None or _distance(previous_end, first) > CLOSURE_TOLERANCE_MM:
        raise CadEngineError(
            "SKETCH_NOT_CLOSED",
            "sketch",
            f"The path ends at {previous_end} and started at {first}. A profile has "
            "to close; this engine does not close it for the document.",
        )
    return Wire(edges)


def _arc_edge(segment: ArcSegment, params) -> Edge:
    """An arc from its endpoints, centre and direction.

    Built from the centre and two angles rather than from the endpoints and a
    radius: two arcs share every endpoint and centre and differ only in which way
    round they go, and `sweep` is the only thing that separates them.
    """
    centre = _point(segment.center, params)
    start = _point(segment.start, params)
    end = _point(segment.end, params)
    radius = _distance(centre, start)
    if radius <= CLOSURE_TOLERANCE_MM:
        raise CadEngineError("SKETCH_INVALID", "sketch", "An arc has no radius.")
    if abs(_distance(centre, end) - radius) > 1e-4:
        raise CadEngineError(
            "SKETCH_INVALID",
            "sketch",
            "An arc's endpoints are different distances from its centre, so the "
            "document does not describe a circular arc.",
        )
    start_angle = math.degrees(math.atan2(start[1] - centre[1], start[0] - centre[0]))
    end_angle = math.degrees(math.atan2(end[1] - centre[1], end[0] - centre[0]))
    # The direction is the document's, not an inference from which angle is
    # larger: an arc from 350 degrees to 10 degrees is a 20-degree arc one way
    # round and a 340-degree arc the other, and both are legal contours.
    direction = (
        AngularDirection.COUNTER_CLOCKWISE
        if segment.sweep is Sweep.COUNTERCLOCKWISE
        else AngularDirection.CLOCKWISE
    )
    return Edge.make_circle(
        radius,
        Plane(origin=(centre[0], centre[1], 0)),
        start_angle=start_angle,
        end_angle=end_angle,
        angular_direction=direction,
    )


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


__all__ = ["contour_wire", "sketch_face", "CLOSURE_TOLERANCE_MM"]
