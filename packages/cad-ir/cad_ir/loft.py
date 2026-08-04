"""CAD-IR 1.9: loft — a solid between sections.

A sweep carries one profile along a path. A loft is the other way round: several
profiles standing where the drawing puts them, and the material is whatever runs
between them. It is how a taper, a transition and a boat-tail are drawn.

The difficulty is not the geometry, it is the **correspondence**: which point of the
first section becomes which point of the second. The kernel always has an answer and
never says what it was, so a loft from a square to a square rotated 45° is either a
prism with a twist in it or a prism with a fold, depending on which corner OpenCascade
matched to which — and both are valid solids of plausible volume.

So the rule that carries this operation is: **every section is the same kind of
contour, with the same number of vertices.** A circle to a circle, a rectangle to a
rectangle, a hexagon to a hexagon. Then correspondence is determined by the shapes
themselves rather than chosen by the kernel, and it can be checked by reading the
document rather than by inspecting the result. Gate P4 asks for exactly this and
phrases it the other way round — "ambiguous section correspondence is rejected".

Two consequences worth stating.

*A round-to-square transition is refused*, and it is a real part. It comes back when
the document can **state** the correspondence — a list of which vertex meets which —
because that is the thing the drawing knows and the kernel does not.

*The shape claim needs nothing new.* Its `profile` is the kind of contour the part is
made of, and with every section the same kind, one word covers all of them. Had mixed
sections been allowed, a claim of `circle` would have been satisfied by a solid that
ends as a square.

Islands are refused for a different reason: a section with a hole in it is two
correspondences, and the kernel is not told which hole pairs with which.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from .base import (
    FeatureResult,
    FeatureType,
    Id,
    ParameterRef,
    Provenance,
    ResultRef,
    StrictModel,
    stated_number,
)
from .sketch import PathContour, RectangleContour, RegularPolygonContour, Sketch


def _signature(contour) -> tuple:
    """What has to match between two sections for correspondence to be determined.

    The kind of contour, and — where the kind alone does not fix the number of
    vertices — how many there are. A hexagon and an octagon are both
    `regular_polygon`, and lofting one into the other is the ambiguity this exists to
    stop.
    """
    if isinstance(contour, RegularPolygonContour):
        return (type(contour).__name__, contour.sides)
    if isinstance(contour, PathContour):
        return (type(contour).__name__, len(contour.segments))
    return (type(contour).__name__,)


#: How close two angles have to be to count as the same one, in degrees. A drawing
#: states a rotation to a degree or a minute; a millidegree is arithmetic noise.
ROTATION_TOLERANCE_DEG = 1e-6


def _symmetry_deg(contour) -> float | None:
    """The smallest rotation that maps a contour's vertices onto themselves.

    `None` where the question does not arise: a circle has no vertices to pair, and a
    slot or a spelled-out path states no rotation at all — its corners are coordinates,
    and comparing two vertex sets for a hidden rotation is a different piece of work
    (it is named in `docs/GATE-P4-ANALYSIS.md`).
    """
    if isinstance(contour, RegularPolygonContour):
        return 360.0 / contour.sides
    if isinstance(contour, RectangleContour):
        # A square repeats every quarter turn; any other rectangle, every half. When
        # either side reads a parameter the two cannot be compared here, so the
        # guaranteed symmetry of *every* rectangle is used — that refuses the half turn
        # and lets a quarter through rather than refusing a document that may be correct.
        width, height = stated_number(contour.width), stated_number(contour.height)
        if width is None or height is None:
            # Equal *expressions* are equal sides, which catches a square whose two
            # sides are one parameter. Anything else falls back to the safe symmetry.
            return 90.0 if contour.width == contour.height else 180.0
        return 90.0 if abs(width - height) <= 1e-9 else 180.0
    return None


def _rotation_of(contour) -> float | None:
    """The rotation a contour states, or `None` when it states it as a name."""
    return stated_number(getattr(contour, "rotation_deg", None))


def _require_unambiguous_rotation(sections: list[Sketch]) -> None:
    """A rotation between sections must be smaller than the contour's own symmetry.

    The half of Gate P4 that ADR-031's kind-and-count rule left open, and it is
    reachable because a rotation is a number the document states.

    A 40 x 40 square lofted to another 40 x 40 square turned 90 degrees builds a
    **prism with no twist at all** — 48 000.0000 mm3, the same digits as the un-rotated
    case, one solid, valid, unremarkable topology. Nothing is wrong with the kernel: a
    square turned a quarter is the same set of points, so both readings are consistent
    with the sections as stated and it picks one. Measured at 0, 15, 45 and 90 degrees;
    only the last two are undecided, and 135 is undecided in the same way because its
    vertex set is the one at 45.

    So the stated rotation has to be the one the sections can record — inside
    `[0, symmetry)`. A drawing that means a quarter-turn twist has to say so as a twist,
    which is a different input (P4.1's `controlled twist`) and not a rotated section.
    """
    step = _symmetry_deg(sections[0].outer)
    if step is None:
        return
    first = _rotation_of(sections[0].outer)
    if first is None:
        return
    for section in sections[1:]:
        rotation = _rotation_of(section.outer)
        if rotation is None:
            continue
        turned = (rotation - first) % 360.0
        if turned < step - ROTATION_TOLERANCE_DEG:
            continue
        raise ValueError(
            f"section {section.id} is turned {turned:g} degrees from {sections[0].id}, "
            f"and this contour repeats itself every {step:g}; the sections cannot record "
            f"the difference between that and {turned % step:g} degrees, so which point "
            "meets which is the kernel's choice. State a twist as a twist, not as a "
            "rotated section"
        )


def _require_corresponding(sections: list[Sketch]) -> None:
    for index, section in enumerate(sections):
        if section.inner:
            raise ValueError(
                f"section {section.id} has {len(section.inner)} island(s); a loft "
                "between sections with holes leaves the kernel to decide which hole "
                "meets which"
            )
    _require_unambiguous_rotation(sections)
    first = _signature(sections[0].outer)
    for section in sections[1:]:
        if _signature(section.outer) != first:
            raise ValueError(
                f"section {section.id} is a {section.outer.type} where {sections[0].id} "
                f"is a {sections[0].outer.type}; a loft's sections must be the same kind "
                "of contour with the same number of vertices, so that which point meets "
                "which is decided by the shapes rather than by the kernel"
            )


class LoftInputs(StrictModel):
    """The sections, in the order the material runs through them.

    Order is the document's, not something derived from where the planes are: two
    sections on either side of a third is a shape a drawing can mean, and sorting them
    by height would silently build a different one.
    """

    sections: Annotated[list[Sketch], Field(min_length=2, max_length=16)]
    #: Straight transitions between sections rather than a smooth surface through all
    #: of them. With two sections it changes nothing; with three it is the difference
    #: between a cone-and-cone and a curve, and the drawing says which.
    ruled: bool = False
    source_body: ResultRef | None = None
    new_body: bool = False

    @model_validator(mode="after")
    def validate_inputs(self) -> "LoftInputs":
        _require_corresponding(self.sections)
        if self.new_body and self.source_body is not None:
            raise ValueError(
                "a feature either starts a new body or adds to an existing one, not both"
            )
        return self


class CutLoftInputs(StrictModel):
    """The same, removing material: a tapered pocket."""

    sections: Annotated[list[Sketch], Field(min_length=2, max_length=16)]
    ruled: bool = False
    source_body: ResultRef | None = None

    @model_validator(mode="after")
    def validate_inputs(self) -> "CutLoftInputs":
        _require_corresponding(self.sections)
        return self


class SolidLoftFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.SOLID_LOFT]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(max_length=8)] = Field(default_factory=list)
    inputs: LoftInputs
    provenance: Provenance | None = None


class CutLoftFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.CUT_LOFT]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(max_length=8)] = Field(default_factory=list)
    inputs: CutLoftInputs
    provenance: Provenance | None = None


LoftFeature = Union[SolidLoftFeature, CutLoftFeature]


__all__ = [
    "ROTATION_TOLERANCE_DEG",
    "CutLoftFeature",
    "CutLoftInputs",
    "LoftFeature",
    "LoftInputs",
    "SolidLoftFeature",
]
