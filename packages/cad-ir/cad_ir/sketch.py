"""CAD-IR sketch geometry: contours, segments and the plane they sit on.

Version 1.1 could express two shapes on one plane, so every part the service
could build was a rectangular plate with round holes. This is the sketch as a
real object: closed contours of lines and arcs, an outer profile with islands
inside it, and a plane that may be a base plane, an auxiliary plane, or a face
named by a semantic selector.

Three boundaries are deliberate.

*Explicit coordinates only.* Nothing here is solved for, and nothing infers a
dimension. A value is a number or a named parameter. Constraints exist as of 1.3
and are *assertions* about these coordinates rather than a way of producing
them — see `constraints.py` and ADR-022.

*One level of nesting, by construction.* A sketch has one `outer` contour and a
list of `inner` ones. An island inside an island is not rejected by a
validator — it cannot be written down.

*Construction geometry is not profile geometry.* Points, and lines, arcs and
circles that only exist to be measured or constrained against, live in their
own list. No rule has to guess whether a stray line was meant to close a
contour, because a line in `construction` never was.

What this module does **not** do is check that a contour closes, that it does
not cross itself, or that an island is really inside the profile. That is
geometry, it needs the parameters resolved, and it has to run on the machine
that drives KOMPAS — so it lives in the adapter, in front of COM. See
`docs/TASK-POSTMVP-006-sketch-primitives.md`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from .base import Id, ResultRef, Scalar, StrictModel
from .constraints import ConstraintList, DimensionList
from .selectors import Cardinality, FaceSelector

#: A sketch-plane coordinate pair. Either component may be a parameter
#: reference, which is how a part stays parametric without an expression
#: language.
Point2 = Annotated[list[Scalar], Field(min_length=2, max_length=2)]


class BasePlaneName(StrEnum):
    XY = "XY"
    XZ = "XZ"
    YZ = "YZ"


class SketchOnBasePlane(StrictModel):
    on: Literal["base"]
    plane: BasePlaneName


class SketchOnDatumPlane(StrictModel):
    """A sketch on an auxiliary plane some earlier feature produced."""

    on: Literal["datum"]
    plane: ResultRef


class SketchOnFace(StrictModel):
    """A sketch on a face of the model, named by what the face means.

    The selector is resolved at build time against the model as it then is. The
    document never records which face was chosen, because a face index stops
    meaning the same thing after the next rebuild — the whole argument of
    ADR-019.
    """

    on: Literal["face"]
    face: FaceSelector

    @model_validator(mode="after")
    def validate_single_face(self) -> "SketchOnFace":
        if self.face.cardinality is not Cardinality.EXACTLY_ONE:
            # A sketch sits on one face. "One or more" would leave the build
            # picking, which is the coin toss selectors exist to prevent.
            raise ValueError("a sketch plane selector must declare exactly_one")
        return self


SketchPlaneSpec = Annotated[
    Union[SketchOnBasePlane, SketchOnDatumPlane, SketchOnFace],
    Field(discriminator="on"),
]


class Sweep(StrEnum):
    """Which way round an arc goes from its start point to its end point."""

    COUNTERCLOCKWISE = "ccw"
    CLOCKWISE = "cw"


class LineSegment(StrictModel):
    type: Literal["line"]
    start: Point2
    end: Point2
    #: Optional, and required only to be constrained. A sketch with no
    #: constraints should not have to invent a name for every side of a
    #: rectangle.
    id: Id | None = None


class ArcSegment(StrictModel):
    """An arc given by its two endpoints, its centre and a direction.

    Endpoints and centre over centre-radius-angles because it is the form that
    makes a contour verifiable: the previous segment's end has to equal this
    segment's start, and with angles that is an inference rather than a
    comparison. The adapter converts to what KOMPAS wants.

    `sweep` is not redundant with the endpoints: two arcs share every endpoint
    and centre and differ only in which way round they go.
    """

    type: Literal["arc"]
    start: Point2
    end: Point2
    center: Point2
    sweep: Sweep
    id: Id | None = None


PathSegment = Annotated[Union[LineSegment, ArcSegment], Field(discriminator="type")]


class PathContour(StrictModel):
    """A closed boundary spelled out segment by segment.

    The general form. Everything else in this module is a shape that expands
    into one of these deterministically.
    """

    type: Literal["path"]
    segments: Annotated[list[PathSegment], Field(min_length=2, max_length=400)]
    id: Id | None = None


class CircleContour(StrictModel):
    type: Literal["circle"]
    center: Point2
    radius: Scalar
    id: Id | None = None


class RectangleContour(StrictModel):
    type: Literal["rectangle"]
    center: Point2
    width: Scalar
    height: Scalar
    rotation_deg: Scalar = 0.0
    id: Id | None = None


class SlotContour(StrictModel):
    """A straight slot: two end-cap centres and the radius that rounds them."""

    type: Literal["slot"]
    start: Point2
    end: Point2
    radius: Scalar
    id: Id | None = None


class RegularPolygonContour(StrictModel):
    type: Literal["regular_polygon"]
    center: Point2
    sides: Annotated[int, Field(ge=3, le=64)]
    circumradius: Scalar
    rotation_deg: Scalar = 0.0
    id: Id | None = None


Contour = Annotated[
    Union[PathContour, CircleContour, RectangleContour, SlotContour, RegularPolygonContour],
    Field(discriminator="type"),
]


class ConstructionPoint(StrictModel):
    type: Literal["point"]
    id: Id
    at: Point2


class ConstructionLine(StrictModel):
    type: Literal["line"]
    id: Id
    start: Point2
    end: Point2


class ConstructionCircle(StrictModel):
    type: Literal["circle"]
    id: Id
    center: Point2
    radius: Scalar


class ConstructionArc(StrictModel):
    type: Literal["arc"]
    id: Id
    start: Point2
    end: Point2
    center: Point2
    sweep: Sweep


ConstructionEntity = Annotated[
    Union[ConstructionPoint, ConstructionLine, ConstructionCircle, ConstructionArc],
    Field(discriminator="type"),
]


class Sketch(StrictModel):
    id: Id
    plane: SketchPlaneSpec
    outer: Contour
    inner: Annotated[list[Contour], Field(max_length=64)] = Field(default_factory=list)
    construction: Annotated[list[ConstructionEntity], Field(max_length=64)] = Field(
        default_factory=list
    )
    constraints: ConstraintList = Field(default_factory=list)
    dimensions: DimensionList = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_names(self) -> "Sketch":
        """Every name in a sketch is unique, and every reference resolves.

        Checked here rather than in the adapter because it is about the document
        rather than about geometry: two entities with the same id make a
        constraint mean two things, and a constraint naming nothing is a
        statement about a part that does not exist.
        """
        named: set[str] = set()
        for entity in self.entities():
            identifier = getattr(entity, "id", None)
            if identifier is None:
                continue
            if identifier in named:
                raise ValueError(f"duplicate sketch entity id: {identifier}")
            named.add(identifier)

        for constraint in self.constraints:
            for role, reference in (("of", constraint.of), ("to", constraint.to),
                                    ("axis", constraint.axis)):
                if reference is not None and reference not in named:
                    raise ValueError(
                        f"constraint {constraint.id} names {reference} as its {role}, "
                        "which no sketch entity carries"
                    )
        seen_constraints: set[str] = set()
        for constraint in self.constraints:
            if constraint.id in seen_constraints:
                raise ValueError(f"duplicate constraint id: {constraint.id}")
            seen_constraints.add(constraint.id)

        seen_dimensions: set[str] = set()
        for dimension in self.dimensions:
            if dimension.id in seen_dimensions:
                raise ValueError(f"duplicate dimension id: {dimension.id}")
            seen_dimensions.add(dimension.id)
            if dimension.of not in named:
                raise ValueError(
                    f"dimension {dimension.id} measures {dimension.of}, "
                    "which no sketch entity carries"
                )
        return self

    def entities(self):
        """Everything in the sketch a constraint could name, contours first."""
        for contour in [self.outer, *self.inner]:
            yield contour
            if isinstance(contour, PathContour):
                yield from contour.segments
        yield from self.construction


class DatumPlaneOffsetInputs(StrictModel):
    """An auxiliary plane parallel to another, a stated distance away.

    Offset only. A plane at an angle or through three points is expressible in
    KOMPAS and will be added when something needs one; adding it now would mean
    three build paths with one test each.
    """

    base: Union[BasePlaneName, ResultRef]
    offset_mm: Scalar
    flip: bool = False
