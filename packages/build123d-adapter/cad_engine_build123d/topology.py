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

from dataclasses import dataclass, field

from build123d import GeomType

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


@dataclass(frozen=True)
class Box:
    min: tuple[float, float, float]
    max: tuple[float, float, float]

    def min_along(self, axis: str) -> float:
        return self.min["xyz".index(axis)]

    def max_along(self, axis: str) -> float:
        return self.max["xyz".index(axis)]


@dataclass(frozen=True)
class FaceDescriptor:
    """One face, as what it is rather than as where it is in a list."""

    id: str
    surface_type: str
    area_mm2: float
    centroid: tuple[float, float, float]
    bounds: Box
    normal: tuple[float, float, float] | None = None
    radius_mm: float | None = None
    #: The surface kinds of the faces this one touches, for `adjacent`.
    adjacent_surface_types: tuple[str, ...] = field(default_factory=tuple)
    adjacent_face_count: int = 0
    handle: object | None = None


@dataclass(frozen=True)
class EdgeDescriptor:
    id: str
    curve_type: str
    length_mm: float
    centroid: tuple[float, float, float]
    bounds: Box
    direction: tuple[float, float, float] | None = None
    radius_mm: float | None = None
    adjacent_surface_types: tuple[str, ...] = field(default_factory=tuple)
    adjacent_face_count: int = 0
    handle: object | None = None


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
                centroid=_xyz(face.center()),
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
                centroid=_xyz(edge.center()),
                bounds=_box(edge),
                direction=_direction_of(edge),
                radius_mm=_radius_of(edge),
                adjacent_surface_types=tuple(
                    sorted({_SURFACES.get(face.geom_type, "other") for face in touching})
                ),
                adjacent_face_count=len(touching),
                handle=edge,
            )
        )
    return described


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def _xyz(vector) -> tuple[float, float, float]:
    return (float(vector.X), float(vector.Y), float(vector.Z))


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


__all__ = ["Box", "EdgeDescriptor", "FaceDescriptor", "read_edges", "read_faces"]
