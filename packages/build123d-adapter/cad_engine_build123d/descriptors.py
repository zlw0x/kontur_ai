"""What a selector is resolved against: measurements, never handles.

Split from `topology.py`, which does the measuring and therefore needs the CAD
library. These are numbers and strings, so they belong on the side of the line
that can be imported anywhere — the same line ENGINE-MIG-002 drew in .NET, where
the neutral package targets plain net8.0 and the adapter does not.

The split is not tidiness. The matching layer is the half that decides which face
a document meant, and a test suite that needed OpenCascade installed to exercise
it would be a test suite most machines skip.

A face is described by what it is — planar or cylindrical, which way it points,
how big it is, where it sits, what it touches — because that is what a document
can name. The index a face happens to have in the kernel's list is deliberately
not part of the description: it is the thing ADR-019 exists to stop anyone
depending on.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
    #: The kernel object, carried so the adapter can sketch on what was chosen.
    #: Never read by the matching, which is why the matching needs no kernel.
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


__all__ = ["Box", "EdgeDescriptor", "FaceDescriptor"]
