"""Reopen what was written and measure it.

A successful export is not evidence that the model is right. The kernel can
write a file it cannot read back, a boolean can leave two bodies where the
document expected one, and a mesh can be exported at a tolerance that no longer
describes the solid it came from. So the files are reopened by a reader that did
not build them, and everything the document claimed is measured again.

The verifier deliberately does **not** derive its expectations from the build. A
check that computed what to expect from the same plan that produced the geometry
would be satisfied by construction, and a verifier that cannot disagree is not
verifying (ADR-018). Expectations come from the document's own `expectations`
array.

The report is internal. It is how the service knows a model is right; it is not
a file a customer receives (ADR-023).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CadEngineError

#: How far a mesh may sit inside the solid it was tessellated from.
#:
#: A triangulation of a curved surface is inscribed: every chord cuts the corner.
#: So a mesh bounding box is never larger than the solid's and may be smaller by
#: up to the sagitta of the coarsest chord. Comparing them symmetrically would
#: fail every part with a hole in it for a reason that is about tessellation
#: rather than about the model — a lesson from the KOMPAS acceptance runs, where
#: an 80 mm part measured 79.898 in its mesh.
MESH_CHORD_TOLERANCE_MM = 0.05

#: Limits on what may be handed to a browser or a printer. A mesh past these is
#: not a better model, it is a download nobody can open.
MAX_TRIANGLES = 2_000_000
MAX_STL_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class MeshFacts:
    triangles: int
    vertices: int
    degenerate: int
    open_edges: int
    inconsistent_normals: int
    bounds: tuple[float, float, float]
    genus: int = 0


@dataclass(frozen=True)
class VerificationReport:
    valid: bool
    checks: tuple[Check, ...] = field(default_factory=tuple)
    mesh: MeshFacts | None = None

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "checks": [
                {"name": item.name, "passed": item.passed, "detail": item.detail}
                for item in self.checks
            ],
            "mesh": None
            if self.mesh is None
            else {
                "triangle_count": self.mesh.triangles,
                "vertex_count": self.mesh.vertices,
                "degenerate_triangle_count": self.mesh.degenerate,
                "open_or_non_manifold_edge_count": self.mesh.open_edges,
                "inconsistent_normal_count": self.mesh.inconsistent_normals,
                "bounding_box": list(self.mesh.bounds),
                "genus": self.mesh.genus,
            },
        }


@dataclass(frozen=True)
class SurfaceFaceCount:
    """How many faces of one surface kind the document says the solid has."""

    id: str
    surface: str
    count: int
    radius_mm: float | None = None
    radius_tolerance_mm: float = 0.0


@dataclass(frozen=True)
class Expectations:
    """What the document said the finished solid must be."""

    size_mm: tuple[float, float, float] | None = None
    tolerance_mm: float = 0.05
    body_count: int | None = None
    through_hole_count: int | None = None
    surface_face_counts: tuple[SurfaceFaceCount, ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, document) -> "Expectations":
        size = None
        tolerance = 0.05
        bodies = None
        holes = None
        surfaces: list[SurfaceFaceCount] = []
        for item in document.expectations:
            kind = str(getattr(item, "type", ""))
            if kind == "bounding_box":
                size = (float(item.size_mm.x), float(item.size_mm.y), float(item.size_mm.z))
                tolerance = float(item.tolerance_mm)
            elif kind == "body_count":
                bodies = int(item.value)
            elif kind == "through_hole_count":
                holes = int(item.value)
            elif kind == "surface_face_count":
                surfaces.append(
                    SurfaceFaceCount(
                        id=str(item.id),
                        surface=str(item.surface),
                        count=int(item.value),
                        radius_mm=None if item.radius_mm is None else float(item.radius_mm.value),
                        radius_tolerance_mm=(
                            0.0 if item.radius_mm is None else float(item.radius_mm.tolerance)
                        ),
                    )
                )
        return cls(size, tolerance, bodies, holes, tuple(surfaces))


def verify(step_path: Path, stl_path: Path, expectations: Expectations) -> VerificationReport:
    """Reopen both files and check everything the document claimed."""
    checks: list[Check] = []
    solid, step_bounds = _read_step(step_path, expectations, checks)
    mesh = _read_stl(stl_path, checks, expectations)
    if mesh is not None and step_bounds is not None:
        _compare_bounds(step_bounds, mesh.bounds, checks)
    return VerificationReport(
        valid=all(item.passed for item in checks), checks=tuple(checks), mesh=mesh
    )


# ---------------------------------------------------------------------------
# STEP
# ---------------------------------------------------------------------------


def _read_step(path: Path, expectations: Expectations, checks: list[Check]):
    from build123d import import_step

    if not path.is_file() or path.stat().st_size == 0:
        checks.append(Check("step_readable", False, "The STEP file is missing or empty."))
        return None, None
    try:
        shape = import_step(str(path))
    except Exception as error:  # noqa: BLE001 - the kernel's failures are opaque
        checks.append(Check("step_readable", False, f"The STEP file will not reopen: {error}"))
        return None, None
    checks.append(Check("step_readable", True, f"{path.stat().st_size} bytes reopened."))

    solids = list(shape.solids())
    checks.append(
        Check("step_has_solid", bool(solids), f"{len(solids)} solid bodies found.")
    )
    if not solids:
        return None, None

    # `is_valid` is the kernel's own opinion of the shape it just read back, and
    # it is worth asking precisely because it did not build it.
    valid = bool(getattr(shape, "is_valid", True))
    checks.append(Check("step_shape_valid", valid, "The kernel accepts the reopened shape."))

    volume = float(shape.volume)
    checks.append(
        Check("positive_volume", volume > 0, f"{volume:.4f} mm3.")
    )
    empty = [index for index, solid in enumerate(solids) if float(solid.volume) <= 0]
    checks.append(
        Check(
            "no_degenerate_solids",
            not empty,
            f"{len(empty)} solids enclose no volume." if empty else "Every solid encloses volume.",
        )
    )

    if expectations.body_count is not None:
        checks.append(
            Check(
                "solid_body_count",
                len(solids) == expectations.body_count,
                f"expected {expectations.body_count}, measured {len(solids)}.",
            )
        )

    for wanted in expectations.surface_face_counts:
        checks.append(_surface_face_check(shape, wanted))

    box = shape.bounding_box()
    bounds = (float(box.size.X), float(box.size.Y), float(box.size.Z))
    if expectations.size_mm is not None:
        # Sorted, because a bounding box is a set of three extents and which axis
        # a document called "x" is a statement about its own frame, not about the
        # part. A plate rotated 90 degrees in the document is the same plate.
        want = sorted(expectations.size_mm)
        got = sorted(bounds)
        within = all(
            abs(a - b) <= expectations.tolerance_mm for a, b in zip(want, got, strict=True)
        )
        checks.append(
            Check(
                "bounding_box",
                within,
                f"expected {_round(expectations.size_mm)}, measured {_round(bounds)}.",
            )
        )

    return shape, bounds


def _surface_face_check(shape, wanted: SurfaceFaceCount) -> Check:
    """Count the faces of one surface kind in the reopened solid.

    The only check that can see a fillet. Nothing else in a document notices one:
    the bounding box of a plate with rounded corners is the bounding box of the
    plate, the body count is one either way, and a hole count knows nothing about
    corners. So a fillet that silently did not happen, or happened at 2 mm where
    the drawing said 3, passes everything — except that the cylindrical faces it
    should have left behind are missing.

    Read from the file rather than from the build, like every other expectation.
    The surface kinds are the contract's own words (`SurfaceType`), mapped here from
    the kernel's, so a document and a report use one vocabulary.
    """
    from build123d import GeomType

    kinds = {
        "planar": GeomType.PLANE,
        "cylindrical": GeomType.CYLINDER,
        "conical": GeomType.CONE,
        "spherical": GeomType.SPHERE,
        "toroidal": GeomType.TORUS,
    }
    geom = kinds.get(wanted.surface)
    if geom is None:  # pragma: no cover - SurfaceType is closed
        return Check(f"surface_face_count[{wanted.id}]", False, f"unknown surface {wanted.surface}.")

    matching = [face for face in shape.faces() if face.geom_type == geom]
    described = f"{wanted.surface} faces"
    if wanted.radius_mm is not None:
        matching = [
            face
            for face in matching
            if _radius(face) is not None
            and abs(_radius(face) - wanted.radius_mm) <= wanted.radius_tolerance_mm
        ]
        described += f" of radius {wanted.radius_mm}"
    return Check(
        f"surface_face_count[{wanted.id}]",
        len(matching) == wanted.count,
        f"expected {wanted.count} {described}, measured {len(matching)}.",
    )


def _radius(face) -> float | None:
    try:
        radius = face.radius
    except Exception:  # noqa: BLE001 - not every surface has one
        return None
    return None if radius is None else float(radius)


# ---------------------------------------------------------------------------
# STL
# ---------------------------------------------------------------------------


def _read_stl(path: Path, checks: list[Check], expectations: Expectations) -> MeshFacts | None:
    """Parse the mesh with a reader that did not write it.

    Deliberately not the CAD library's importer. The point is to check the file
    as a file — a reader that shares code with the writer agrees with it about
    anything they both get wrong.
    """
    if not path.is_file() or path.stat().st_size == 0:
        checks.append(Check("stl_readable", False, "The STL file is missing or empty."))
        return None
    size = path.stat().st_size
    if size > MAX_STL_BYTES:
        checks.append(Check("stl_size", False, f"{size} bytes exceeds the limit."))
        return None

    try:
        triangles = _parse_stl(path.read_bytes())
    except ValueError as error:
        checks.append(Check("stl_structure", False, str(error)))
        return None
    checks.append(Check("stl_structure", True, f"{len(triangles)} complete triangles parsed."))

    if len(triangles) > MAX_TRIANGLES:
        checks.append(
            Check("stl_triangle_count", False, f"{len(triangles)} exceeds the limit.")
        )
    else:
        checks.append(
            Check("stl_triangle_count", True, f"{len(triangles)} triangles.")
        )

    degenerate = sum(1 for triangle in triangles if not _is_finite_and_real(triangle))
    checks.append(
        Check(
            "finite_non_degenerate_triangles",
            degenerate == 0,
            f"{degenerate} degenerate or non-finite triangles.",
        )
    )

    open_edges, inconsistent = _edge_facts(triangles)
    checks.append(
        Check(
            "closed_manifold_mesh",
            open_edges == 0,
            f"{open_edges} edges do not have exactly two incident triangles.",
        )
    )
    checks.append(
        Check(
            "consistent_normals",
            inconsistent == 0,
            f"{inconsistent} edges are traversed the same way by both their triangles.",
        )
    )

    points = [point for triangle in triangles for point in triangle]
    vertices = len({_vertex_key(point) for point in points})
    bounds = _extent(points)
    genus = _genus(triangles, vertices)
    if expectations.through_hole_count is not None:
        checks.append(
            Check(
                "through_hole_count",
                genus == expectations.through_hole_count,
                f"expected {expectations.through_hole_count}, mesh-derived genus {genus}.",
            )
        )
    return MeshFacts(
        len(triangles), vertices, degenerate, open_edges, inconsistent, bounds, genus
    )


def _genus(triangles: list[tuple], vertices: int) -> int:
    """How many holes go all the way through, by Euler's formula on the mesh.

    V - E + F = 2c - 2g for a closed orientable surface of `c` components, so the
    genus counts the handles — which for a plate is exactly the number of through
    holes. Counted on the triangulation rather than on the B-rep on purpose: a B-rep
    counts a full circle as one edge with one vertex and adds a seam to the cylinder,
    so Euler's formula over faces and edges gives 0 for a plate that plainly has a
    hole in it. That was measured here, not assumed — the first version of this
    check read genus 0 for a one-hole plate and -1 for a two-hole one.

    The component count is not decoration either. Multi-body parts arrived with
    CAD-IR 1.7, and with `c` assumed to be 1 two solid lumps with no holes in them
    came out as genus −1: a part the document said had no through holes reported a
    negative number of them.

    Derived rather than counted from cylindrical faces, because a blind hole and
    a through hole both have one cylinder and only one of them is a handle.
    """
    edges = {
        tuple(sorted((_vertex_key(triangle[index]), _vertex_key(triangle[(index + 1) % 3]))))
        for triangle in triangles
        for index in range(3)
    }
    characteristic = vertices - len(edges) + len(triangles)
    return (2 * _components(triangles) - characteristic) // 2


def _components(triangles: list[tuple]) -> int:
    """How many separate closed surfaces the mesh describes.

    Union-find over the triangles' vertices: two triangles sharing a vertex are on the
    same surface. A part of two disjoint bodies is two components, and Euler's formula
    needs to know.
    """
    parent: dict[tuple, tuple] = {}

    def find(key: tuple) -> tuple:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: tuple, right: tuple) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[left] = right

    for triangle in triangles:
        keys = [_vertex_key(point) for point in triangle]
        union(keys[0], keys[1])
        union(keys[1], keys[2])
    return len({find(key) for key in parent}) or 1


def _parse_stl(payload: bytes) -> list[tuple]:
    """Binary or ASCII, whichever it is, with the length checked either way."""
    text_like = payload[:5].lower() == b"solid" and b"facet" in payload[:1024]
    return _parse_ascii(payload) if text_like else _parse_binary(payload)


def _parse_binary(payload: bytes) -> list[tuple]:
    if len(payload) < 84:
        raise ValueError("The STL file is shorter than a binary header.")
    count = struct.unpack_from("<I", payload, 80)[0]
    expected = 84 + count * 50
    if len(payload) != expected:
        raise ValueError(
            f"The header declares {count} triangles, which needs {expected} bytes; "
            f"the file has {len(payload)}."
        )
    triangles = []
    for index in range(count):
        offset = 84 + index * 50
        values = struct.unpack_from("<12f", payload, offset)
        triangles.append(
            (values[3:6], values[6:9], values[9:12])
        )
    return triangles


def _parse_ascii(payload: bytes) -> list[tuple]:
    triangles: list[tuple] = []
    current: list[tuple[float, float, float]] = []
    for line in payload.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("vertex"):
            continue
        parts = stripped.split()
        if len(parts) != 4:
            raise ValueError(f"A vertex line has {len(parts) - 1} coordinates.")
        current.append(tuple(float(value) for value in parts[1:]))
        if len(current) == 3:
            triangles.append(tuple(current))
            current = []
    if current:
        raise ValueError("The file ends part-way through a triangle.")
    if not triangles:
        raise ValueError("The file contains no triangles.")
    return triangles


def _is_finite_and_real(triangle) -> bool:
    points = [coordinate for point in triangle for coordinate in point]
    if not all(math.isfinite(value) for value in points):
        return False
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    cross = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    return math.hypot(*cross) > 1e-12


def _edge_facts(triangles: list[tuple]) -> tuple[int, int]:
    """How many edges are not shared by exactly two triangles, and how many are
    shared the wrong way round.

    A closed surface has every edge in exactly two triangles, traversed once in
    each direction. An edge traversed the same way twice means the two triangles
    disagree about which side is out, which is what a printer sees as a hole.
    """
    directed: dict[tuple, int] = {}
    for triangle in triangles:
        keys = [_vertex_key(point) for point in triangle]
        for index in range(3):
            edge = (keys[index], keys[(index + 1) % 3])
            directed[edge] = directed.get(edge, 0) + 1

    open_edges = 0
    inconsistent = 0
    seen: set[tuple] = set()
    for edge, count in directed.items():
        undirected = tuple(sorted(edge))
        if undirected in seen:
            continue
        seen.add(undirected)
        forward = directed.get(edge, 0)
        backward = directed.get((edge[1], edge[0]), 0)
        if forward + backward != 2:
            open_edges += 1
        elif forward == 2 or backward == 2:
            inconsistent += 1
    return open_edges, inconsistent


def _vertex_key(point) -> tuple:
    return (round(point[0], 6), round(point[1], 6), round(point[2], 6))


def _extent(points: list) -> tuple[float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def _compare_bounds(step_bounds, mesh_bounds, checks: list[Check]) -> None:
    """The mesh must describe the same part as the solid, allowing for chords.

    Asymmetric on purpose: a mesh may be smaller than its solid by the sagitta of
    a chord and may never be larger. A symmetric comparison would either fail
    every curved part or accept a mesh that overshoots, and overshooting is the
    direction that means something went wrong.
    """
    worst = max(step - mesh for step, mesh in zip(step_bounds, mesh_bounds, strict=True))
    overshoot = max(mesh - step for step, mesh in zip(step_bounds, mesh_bounds, strict=True))
    within = worst <= MESH_CHORD_TOLERANCE_MM and overshoot <= 1e-6
    checks.append(
        Check(
            "mesh_matches_solid",
            within,
            f"STEP {_round(step_bounds)} against STL {_round(mesh_bounds)}; the mesh sits "
            f"{worst:.4f} mm inside and {overshoot:.4f} mm outside.",
        )
    )


def _round(values) -> list:
    return [round(float(value), 4) for value in values]


__all__ = [
    "Check",
    "Expectations",
    "MESH_CHORD_TOLERANCE_MM",
    "MeshFacts",
    "SurfaceFaceCount",
    "VerificationReport",
    "verify",
]
