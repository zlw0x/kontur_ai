"""The one thing a loft's sections must be that the document cannot state.

CAD-IR 1.9 checks the part of the correspondence problem that is readable: every
section is the same kind of contour with the same number of vertices, so which point
meets which is decided by the shapes rather than chosen by the kernel.

What it cannot check is *where the planes are*, because a datum plane's offset and a
face selector's result are only known once the build has run. And there is one
arrangement that has to be refused:

    loft([square on XY, smaller square on XY])   ->   a solid, no error, volume 0.0

Two sections on the same plane produce a body with no thickness. It is one solid, so a
`body_count` of 1 passes; it is closed, so the mesh check passes; and it is nothing.
"""

from __future__ import annotations

from build123d import Plane

from .errors import CadEngineError

#: How far apart two section planes have to be to be different planes, in mm.
#: A micron: below any thickness a drawing states, above the arithmetic of placing a
#: plane by an offset a parameter gave.
PLANE_SEPARATION_MM = 1e-6


def require_distinct_planes(planes: list[Plane], section_ids: list[str], feature_id: str) -> None:
    """No two sections stand in the same place.

    Compared as planes rather than as origins: two sections whose planes are parallel
    and a micron apart are a legitimate if strange part, and two whose planes coincide
    are not a part at all whatever their origins say.
    """
    for index in range(1, len(planes)):
        for earlier in range(index):
            if _same_plane(planes[earlier], planes[index]):
                raise CadEngineError(
                    "LOFT_SECTIONS_COPLANAR",
                    "feature",
                    f"Sections {section_ids[earlier]} and {section_ids[index]} of "
                    f"{feature_id} lie in the same plane. The kernel lofts them into a "
                    "solid of no thickness — one body, closed, and zero volume — rather "
                    "than refusing.",
                )


def _same_plane(left: Plane, right: Plane) -> bool:
    if left.z_dir.cross(right.z_dir).length > PLANE_SEPARATION_MM:
        return False
    return abs((right.origin - left.origin).dot(left.z_dir)) <= PLANE_SEPARATION_MM


__all__ = ["PLANE_SEPARATION_MM", "require_distinct_planes"]
