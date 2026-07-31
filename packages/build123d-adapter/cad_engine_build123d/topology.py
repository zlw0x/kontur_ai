"""Measure a built part into descriptors a selector can be resolved against.

The other half of selector resolution. This half touches the kernel; the matching
in `selectors.py` works on the descriptors alone, which is what makes it testable
without a CAD library and what kept the same split honest under KOMPAS.

Descriptors are *measurements*, never handles. A face is described by what it is
— planar or cylindrical, which way it points, how big it is, where it sits, what
it touches — because that is what a document can name. The index a face happens
to have in the kernel's list is deliberately not part of the description: it is
the thing ADR-019 exists to stop anyone depending on.
"""

from __future__ import annotations

from build123d import CenterOf, GeomType

from .descriptors import Box, EdgeDescriptor, FaceDescriptor

#: How the kernel's surface kinds map onto the vocabulary a document may use.
#: Everything the contract has no word for is `other`, which a document can still
#: select on but cannot mistake for something it is not.
_SURFACES = {
    GeomType.PLANE: "planar",
    GeomType.CYLINDER: "cylindrical",
    GeomType.CONE: "conical",
    GeomType.SPHERE: "spherical",
    GeomType.TORUS: "toroidal",
}

_CURVES = {
    GeomType.LINE: "line",
    GeomType.CIRCLE: "circle",
    GeomType.ELLIPSE: "ellipse",
    GeomType.BSPLINE: "spline",
    GeomType.BEZIER: "spline",
}


def read_faces(part) -> list[FaceDescriptor]:
    """Every face of the part, measured.

    Ids are positional strings — `face.0`, `face.1` — and are for the trace and
    for error messages only. Nothing resolves by them, which is why they may be
    positional at all: they name a row in a report, not a piece of geometry.
    """
    faces = list(part.faces())
    described: list[FaceDescriptor] = []
    for index, face in enumerate(faces):
        described.append(
            FaceDescriptor(
                id=f"face.{index}",
                surface_type=_SURFACES.get(face.geom_type, "other"),
                area_mm2=float(face.area),
                centroid=_centre(face),
                bounds=_box(face),
                normal=_normal_of(face),
                radius_mm=_radius_of(face),
                adjacent_surface_types=_neighbour_surfaces(face, faces),
                adjacent_face_count=len(_neighbours(face, faces)),
                handle=face,
            )
        )
    return described


def read_edges(part) -> list[EdgeDescriptor]:
    faces = list(part.faces())
    described: list[EdgeDescriptor] = []
    for index, edge in enumerate(part.edges()):
        touching = [face for face in faces if _shares_edge(face, edge)]
        described.append(
            EdgeDescriptor(
                id=f"edge.{index}",
                curve_type=_CURVES.get(edge.geom_type, "other"),
                length_mm=float(edge.length),
                centroid=_centre(edge),
                bounds=_box(edge),
                direction=_direction_of(edge),
                radius_mm=_radius_of(edge),
                adjacent_surface_types=tuple(
                    sorted({_SURFACES.get(face.geom_type, "other") for face in touching})
                ),
                adjacent_face_count=len(touching),
                convexity=_convexity_of(edge, touching),
                handle=edge,
            )
        )
    return described


# ---------------------------------------------------------------------------
# Convexity
# ---------------------------------------------------------------------------

#: How far off the edge to step when deciding which way a face extends.
#:
#: Big enough that the kernel's own distance queries are not answering noise, small
#: enough that a curved face's chord still sits nearer its own surface than the
#: other candidate. A millimetre would fail on a 0.5 mm fillet; a nanometre would
#: fail on arithmetic.
_PROBE_MM = 1e-3

#: Below this, the two faces meet smoothly and the edge is neither convex nor
#: concave.
_FLAT = 1e-6


def _convexity_of(edge, touching: list) -> str | None:
    """Convex, concave, tangent — or nothing where the question does not apply.

    A fillet rounds a convex edge and a concave one is the root of a boss, so a
    document that cannot tell them apart cannot say which of the two it means. The
    predicate has been in the contract since ADR-019 and was, until now, silently
    ignored by the resolver — which is worse than not having it: a selector stating
    `convexity` matched on its other predicates alone and quietly took both.

    The test is the dihedral angle measured through the material, and it is done
    with directions rather than by classifying a probe point as inside or outside.
    That was the first attempt and it cannot work: for both a convex and a concave
    edge the outward normals sum to a direction pointing out of the solid, so a
    point along that bisector is outside either way. What does distinguish them is
    where each face *goes* from the edge — `u1 · n2` is negative when the faces fold
    away from each other and positive when they fold towards each other.

    Verified against known geometry rather than reasoned about alone: a box's twelve
    edges are convex, the rim of a hole is convex (it is a sharp outside corner, and
    the surprise is only in the word), the root where a boss meets a plate is
    concave, and the seam of a cylinder has one face and no answer.
    """
    if len(touching) != 2:
        # A seam has one face, and a non-manifold edge with three is not something
        # to have an opinion about.
        return None
    point = edge.position_at(0.5)
    tangent = _unit(edge.tangent_at(0.5))
    if tangent is None:
        return None

    first = _away_from_edge(touching[0], point, tangent)
    second = _away_from_edge(touching[1], point, tangent)
    if first is None or second is None:
        return None
    (into_first, _) = first
    (_, normal_second) = second

    folded = _dot(into_first, normal_second)
    if folded < -_FLAT:
        return "convex"
    if folded > _FLAT:
        return "concave"
    return "tangent"


def _away_from_edge(face, point, tangent):
    """Which way this face extends from the edge, and its outward normal there.

    The direction is `normal × tangent` up to a sign, and the sign is settled by
    asking the kernel: of the two candidate points a hair to either side, the one
    lying on this face is the one in the direction the face extends. A face is
    bounded, so the point on the far side of the edge is a probe-length away from it
    even though it sits on the same underlying surface.
    """
    normal = _unit(face.normal_at(point))
    if normal is None:
        return None
    across = _unit(_cross(normal, tangent))
    if across is None:
        return None
    forward = _step(point, across, _PROBE_MM)
    backward = _step(point, across, -_PROBE_MM)
    try:
        if face.distance_to(forward) <= face.distance_to(backward):
            return across, normal
    except Exception:  # noqa: BLE001 - the kernel's refusals are opaque
        return None
    return (-across[0], -across[1], -across[2]), normal


def _step(point, direction, amount: float) -> tuple[float, float, float]:
    return (
        float(point.X) + amount * direction[0],
        float(point.Y) + amount * direction[1],
        float(point.Z) + amount * direction[2],
    )


def _unit(vector) -> tuple[float, float, float] | None:
    values = vector if isinstance(vector, tuple) else (vector.X, vector.Y, vector.Z)
    length = sum(float(value) ** 2 for value in values) ** 0.5
    if length < _FLAT:
        return None
    return tuple(float(value) / length for value in values)


def _cross(left, right) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _dot(left, right) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def _xyz(vector) -> tuple[float, float, float]:
    return (float(vector.X), float(vector.Y), float(vector.Z))


def _centre(shape) -> tuple[float, float, float]:
    """The centre a document means, which is not the one `center()` returns.

    build123d's default is `CenterOf.GEOMETRY`: the point at the middle of the
    surface's own parameter domain. For a planar face that is the centroid, and for
    anything curved it is a point *on* the surface — the centre of a Ø6 hole at
    x = 10 came back as x = 7, and the circular edge round its mouth as x = 7 too.

    A document saying "the face centred on x = 10" means the axis of that hole. So the
    centre of mass is what a `position.center_along` predicate is resolved against.
    Measured rather than assumed, and the reason this has a name of its own: with
    `GEOMETRY` every centre predicate on a curved face is off by a radius, which is
    not a failure — it is a selector matching something else.
    """
    try:
        return _xyz(shape.center(CenterOf.MASS))
    except Exception:  # noqa: BLE001 - a degenerate shape has no centre of mass
        return _xyz(shape.center())


def _box(shape) -> Box:
    bounds = shape.bounding_box()
    return Box(_xyz(bounds.min), _xyz(bounds.max))


def _normal_of(face) -> tuple[float, float, float] | None:
    """The outward normal at the face's centre, or nothing.

    Nothing rather than a guess: a face whose normal cannot be taken is one no
    normal predicate can honestly match, and inventing a direction for it would
    make a selector pick it for a reason that is not true of it.
    """
    try:
        return _xyz(face.normal_at())
    except Exception:  # noqa: BLE001 - the kernel's refusals are opaque
        return None


def _radius_of(shape) -> float | None:
    try:
        radius = shape.radius
    except Exception:  # noqa: BLE001 - not every surface or curve has one
        return None
    return None if radius is None else float(radius)


def _direction_of(edge) -> tuple[float, float, float] | None:
    try:
        return _xyz(edge.tangent_at(0.0))
    except Exception:  # noqa: BLE001
        return None


def _neighbours(face, faces) -> list:
    """The faces that share an edge with this one."""
    own = {_edge_key(edge) for edge in face.edges()}
    return [
        other
        for other in faces
        if other is not face and any(_edge_key(edge) in own for edge in other.edges())
    ]


def _neighbour_surfaces(face, faces) -> tuple[str, ...]:
    return tuple(
        sorted({_SURFACES.get(other.geom_type, "other") for other in _neighbours(face, faces)})
    )


def _shares_edge(face, edge) -> bool:
    key = _edge_key(edge)
    return any(_edge_key(item) == key for item in face.edges())


def _edge_key(edge) -> tuple:
    """An edge's identity, by where it is rather than by object identity.

    Two `Edge` wrappers around the same underlying curve are different Python
    objects, so adjacency has to be decided geometrically. Rounded to a micron:
    finer would make two genuinely coincident edges look different because of
    arithmetic, coarser would merge edges a millimetre apart.
    """
    start = edge.position_at(0.0)
    end = edge.position_at(1.0)
    ends = sorted(
        [
            (round(start.X, 6), round(start.Y, 6), round(start.Z, 6)),
            (round(end.X, 6), round(end.Y, 6), round(end.Z, 6)),
        ]
    )
    return (round(float(edge.length), 6), ends[0], ends[1])


__all__ = ["read_edges", "read_faces"]
