"""The named things in a sketch that a constraint can be about.

A line, an arc and a circle are all "a curve with a direction, a couple of
defining points and possibly a radius". Flattening them here keeps the constraint
checks from branching on shape sixteen times over.

Only *named* entities take part. An id on a segment is what a constraint refers
to, and a document that constrains something it never named has said nothing —
which the resolver reports rather than guessing at.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cad_ir.sketch import (
    ArcSegment,
    CircleContour,
    ConstructionArc,
    ConstructionCircle,
    ConstructionLine,
    LineSegment,
    PathContour,
    Sketch,
)

from .errors import CadEngineError


@dataclass(frozen=True)
class Point2:
    x: float
    y: float

    def distance_to(self, other: "Point2") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass(frozen=True)
class ConstrainedEntity:
    """One named sketch entity, reduced to what a check needs."""

    id: str
    kind: str  # "line", "arc" or "circle"
    start: Point2
    end: Point2
    center: Point2 | None = None
    radius: float | None = None

    @property
    def is_curve(self) -> bool:
        return self.kind in ("line", "arc")

    @property
    def is_round(self) -> bool:
        return self.kind in ("circle", "arc")

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)

    @property
    def direction(self) -> tuple[float, float]:
        return (self.end.x - self.start.x, self.end.y - self.start.y)

    @property
    def midpoint(self) -> Point2:
        return Point2((self.start.x + self.end.x) / 2, (self.start.y + self.end.y) / 2)

    def point_at(self, which: str) -> Point2:
        """The named point of this entity.

        A circle has only a centre, so every point of it is that centre — which
        is why `concentric` between two circles reads as a coincidence of their
        centres, and why asking a straight segment for a centre is refused
        rather than answered with its midpoint.
        """
        if self.kind == "circle":
            return self.center or self.start
        if which == "start":
            return self.start
        if which == "end":
            return self.end
        if which == "center":
            if self.center is None:
                raise CadEngineError(
                    "CONSTRAINT_OPERAND_INVALID",
                    "sketch",
                    f"{self.id} is a {self.kind} and has no centre to constrain.",
                )
            return self.center
        return self.start


def named_entities(sketch: Sketch, params) -> list[ConstrainedEntity]:
    """Every entity in the sketch that carries an id.

    Construction geometry counts. A centre line is drawn to be constrained
    against and is invisible in the finished part; leaving it out would make the
    commonest use of construction geometry unexpressible.
    """
    found: list[ConstrainedEntity] = []
    for contour in [sketch.outer, *sketch.inner]:
        found.extend(_from_contour(contour, params))
    for entity in sketch.construction:
        found.extend(_from_construction(entity, params))

    seen: set[str] = set()
    for entity in found:
        if entity.id in seen:
            raise CadEngineError(
                "SKETCH_ENTITY_DUPLICATE",
                "sketch",
                f"Two sketch entities are named {entity.id}, so a constraint on it "
                "means two things.",
            )
        seen.add(entity.id)
    return found


def _point(value, params) -> Point2:
    return Point2(
        params.resolve(value[0], "x coordinate"),
        params.resolve(value[1], "y coordinate"),
    )


def _from_contour(contour, params) -> list[ConstrainedEntity]:
    if isinstance(contour, CircleContour):
        if contour.id is None:
            return []
        centre = _point(contour.center, params)
        radius = params.resolve(contour.radius, "circle radius")
        return [ConstrainedEntity(str(contour.id), "circle", centre, centre, centre, radius)]

    if isinstance(contour, PathContour):
        entities: list[ConstrainedEntity] = []
        for segment in contour.segments:
            if segment.id is None:
                # Unnamed segments are geometry, not vocabulary. They build the
                # profile and nothing can refer to them, which is the document
                # saying it has nothing to assert about them.
                continue
            entities.append(_from_segment(str(segment.id), segment, params))
        return entities

    # A rectangle, slot or polygon is one shape with one id, and its sides are
    # not separately nameable. Constraining "the top edge of a rectangle" would
    # need the expansion this engine deliberately does not expose: the document
    # writes a path when it wants to name sides.
    return []


def _from_segment(entity_id: str, segment, params) -> ConstrainedEntity:
    start = _point(segment.start, params)
    end = _point(segment.end, params)
    if isinstance(segment, LineSegment):
        return ConstrainedEntity(entity_id, "line", start, end)
    if isinstance(segment, ArcSegment):
        centre = _point(segment.center, params)
        return ConstrainedEntity(
            entity_id, "arc", start, end, centre, centre.distance_to(start)
        )
    raise CadEngineError(
        "SKETCH_INVALID", "sketch", f"Unknown segment {type(segment).__name__}."
    )


def _from_construction(entity, params) -> list[ConstrainedEntity]:
    if entity.id is None:
        return []
    entity_id = str(entity.id)
    if isinstance(entity, ConstructionLine):
        return [
            ConstrainedEntity(
                entity_id, "line", _point(entity.start, params), _point(entity.end, params)
            )
        ]
    if isinstance(entity, ConstructionCircle):
        centre = _point(entity.center, params)
        radius = params.resolve(entity.radius, "construction circle radius")
        return [ConstrainedEntity(entity_id, "circle", centre, centre, centre, radius)]
    if isinstance(entity, ConstructionArc):
        centre = _point(entity.center, params)
        start = _point(entity.start, params)
        return [
            ConstrainedEntity(
                entity_id,
                "arc",
                start,
                _point(entity.end, params),
                centre,
                centre.distance_to(start),
            )
        ]
    # A construction point has no direction and no radius; it is a place, and
    # nothing in the constraint vocabulary asserts anything about one on its own.
    return []


__all__ = ["ConstrainedEntity", "Point2", "named_entities"]
