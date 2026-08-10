"""How far an extrusion travels when the drawing named a face instead of a number.

The whole of CAD-IR 1.13 on this side is one division. Given a profile on a plane
with origin `o` travelling along unit `d`, and a planar face with normal `n` through
a point `p`:

    reach = ((p - o) · n) / (d · n)

Then the engine extrudes by `reach` — the operation it has performed since
ENGINE-MIG-003, with its existing post-checks and its existing determinism. The
kernel's own `Solid.extrude_until` is not called from anywhere in this repository,
and `docs/TASK-POSTMVP-P3-2-up-to-a-face.md` is why: of sixteen measured cases two
are correct, three raise, and three succeed and return the wrong part. The worst is a
profile inside the material, which comes back as one valid solid reaching
`5 + sqrt(40² + 40² + 10²) = 62.45` — the trial extrusion's own length, and nothing
to do with the drawing.

**What this buys is a number.** Every over-driven operation before this was caught by
comparing the result against something the document stated; `until` states nothing,
so a document using it cannot be checked by construction. A computed reach is a
number the manifest can record, the corpus can state in closed form, and an
expectation can measure against.

Measured against the kernel where the kernel is right — a boss to the underside of a
plate 20 mm up — the two agree to `0.000e+00`.
"""

from __future__ import annotations

from cad_ir.until_face import PARALLEL_TOLERANCE

from .errors import CadEngineError
from .selectors import require_one, resolve_faces
from .topology import read_faces

#: How near zero a reach may be before it is refused, in mm.
#:
#: Not an equality: the reach is a quotient of dot products of kernel-produced
#: vectors, so exact zero is not a value that reliably appears. What this catches is
#: the geometry `Solid.extrude_until` raises `Extrusion is None` on — a profile
#: sitting *on* the face it is told to stop at — which is a document saying "extrude
#: to where you already are".
_ZERO_REACH_MM = 1e-9


def reach_to_face(feature, part, plane, sense: float) -> float:
    """The distance from this feature's sketch plane to the face it names.

    `sense` is the ±1 the caller already computed from `direction`, so the travel
    here is the same vector the extrusion will use rather than a second reading of
    the document.

    Four refusals, each of which is a measured case from the investigation rather
    than a defensive check:

    `UNTIL_FACE_NOT_PLANAR` — a cylinder has no single plane to reach, and "the
    nearest point of it" is a distance the drawing did not give.

    `UNTIL_FACE_PARALLEL` — travel along the face's own plane never meets it. The
    kernel's answer here is a `ValueError` about a null shape, which reads like a
    broken document rather than an impossible one.

    `UNTIL_FACE_BEHIND` — the face is behind the profile along `direction`. The
    kernel's answer is to reverse, which is a second way to state a direction the
    document already states; refusing is the one that keeps `direction` meaning what
    it says.

    `UNTIL_FACE_COINCIDENT` — the profile is already on the face. This is the
    geometry that made the original investigation think `extrude_until` was broken in
    general, and it is one document rather than a general failure.
    """
    if part is None:
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET",
            "feature",
            f"{feature.id} stops at a face, but nothing has been built to have faces.",
        )
    selector = feature.inputs.until_face
    face = require_one(resolve_faces(selector, read_faces(part)), selector).handle

    normal = _plane_normal(face, feature)
    travel = plane.z_dir * sense
    along = _dot(travel, normal)
    if abs(along) < PARALLEL_TOLERANCE:
        raise CadEngineError(
            "UNTIL_FACE_PARALLEL",
            "feature",
            f"{feature.id} travels along the plane of the face it names, so there is "
            "no point at which it would stop.",
        )

    origin, point = plane.origin, face.center()
    offset = (point.X - origin.X, point.Y - origin.Y, point.Z - origin.Z)
    reach = (offset[0] * normal[0] + offset[1] * normal[1] + offset[2] * normal[2]) / along

    if abs(reach) < _ZERO_REACH_MM:
        raise CadEngineError(
            "UNTIL_FACE_COINCIDENT",
            "feature",
            f"{feature.id} starts on the face it stops at, so it has nowhere to go.",
        )
    if reach < 0:
        raise CadEngineError(
            "UNTIL_FACE_BEHIND",
            "feature",
            f"{feature.id} names a face behind its own direction of travel; reversing "
            "it here would contradict the direction the document states.",
        )
    return reach


def _plane_normal(face, feature) -> tuple[float, float, float]:
    """The face's own normal, refusing anything that has more than one.

    `geom_type` is what build123d 0.11.1 calls it, and `GeomType.PLANE` is the only
    value accepted: a cylinder, a cone or a spline surface each have a normal that
    depends where on them you ask, and a reach computed at one point of it is a
    length the drawing did not state.
    """
    kind = getattr(face, "geom_type", None)
    if kind is None or getattr(kind, "name", str(kind)).upper() not in ("PLANE", "PLANAR"):
        raise CadEngineError(
            "UNTIL_FACE_NOT_PLANAR",
            "feature",
            f"{feature.id} stops at a {getattr(kind, 'name', kind)} face; only a planar "
            "one has a single distance to reach.",
        )
    direction = face.center_location.z_axis.direction
    return (float(direction.X), float(direction.Y), float(direction.Z))


def _dot(vector, normal: tuple[float, float, float]) -> float:
    return (
        float(vector.X) * normal[0]
        + float(vector.Y) * normal[1]
        + float(vector.Z) * normal[2]
    )


__all__ = ["reach_to_face"]
