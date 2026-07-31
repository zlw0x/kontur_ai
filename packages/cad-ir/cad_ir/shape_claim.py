"""What the part is claimed to be, stated before the document that builds it.

A drawing is read in two stages: something looks at the image and says what it
sees, and something else compiles that into CAD-IR. Until now the first stage
produced only a flat list of numbers — width, height, a radius — and the *shape*
of the part appeared for the first time inside CAD-IR. That has three costs:

- the reading stage cannot ask about shape. "Is this outline a slot or a rounded
  rectangle?" is the question a drawing most often raises, and there was no field
  to raise it in;
- nothing can disagree with the compilation. A misread outline arrives as a valid
  document, builds, passes every geometric check, and is the wrong part;
- the two prompts had to name one shape class between them, because a wider
  vocabulary would have had nowhere to land.

A shape claim is the missing statement. It says *what kinds of things the part is
made of* — the outline, how many openings and of what kind, how many solids, which
parameter is the thickness — and deliberately not where any of them are. The
coordinates stay CAD-IR's job, and there is no second geometry format to keep in
step.

**The claim is not derived from the document it checks.** That is the same rule
ADR-018 states for expectations, for the same reason: a claim computed from the
plan that produced the geometry would be satisfied by construction, and a check
that cannot fail is not a check. It comes from the stage that looked at the
drawing, and `disagreements` is where the two are compared.

Nothing here is a repair. A contradiction is reported and named; deciding what to
do about it — ask the user, try the compilation again, refuse — belongs to the
caller, which knows what it is allowed to spend.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from .base import Id, ParameterRef, StrictModel
from .canonical import (
    CadIrDocument,
    CutExtrudeFeature,
    CutRevolveFeature,
    SolidExtrudeFeature,
    SolidRevolveFeature,
)
from .sketch import (
    CircleContour,
    PathContour,
    RectangleContour,
    RegularPolygonContour,
    SlotContour,
)


class ProfileKind(StrEnum):
    """The outline of the part, in the words a drawing uses.

    One kind per contour CAD-IR can express, so a claim maps onto a document
    without a translation table that could disagree with either side.
    `closed_profile` is the general case — an outline spelled out as lines and
    arcs — and is what a reader should say when the outline is not one of the
    named shapes rather than guessing at the nearest one.
    """

    RECTANGLE = "rectangle"
    CIRCLE = "circle"
    SLOT = "slot"
    REGULAR_POLYGON = "regular_polygon"
    CLOSED_PROFILE = "closed_profile"


class OpeningKind(StrEnum):
    """A hole or a cut-out, by the shape of its opening.

    Not by how it is built. A round hole through a plate may reach the document as
    an island in the base sketch or as a separate cut, and both are the same hole
    on the drawing — so a claim that distinguished them would contradict a
    document that was right.
    """

    ROUND = "round"
    SLOT = "slot"
    RECTANGULAR = "rectangular"
    POLYGONAL = "polygonal"
    PROFILED = "profiled"


#: How an opening kind may appear in CAD-IR. A rectangular opening is a rectangle
#: contour and nothing else; a profiled one is spelled out, which a rectangle
#: could also legitimately be, so `profiled` accepts a rectangle rather than
#: calling a correct document wrong.
_OPENING_CONTOURS: dict[OpeningKind, tuple[type, ...]] = {
    OpeningKind.ROUND: (CircleContour,),
    OpeningKind.SLOT: (SlotContour,),
    OpeningKind.RECTANGULAR: (RectangleContour,),
    OpeningKind.POLYGONAL: (RegularPolygonContour,),
    OpeningKind.PROFILED: (PathContour, RectangleContour),
}

#: Which named contour each claimed profile may be built as.
#:
#: A `path` is accepted for every kind and checked separately, because a named
#: shape written the long way is still that shape: a rectangle whose four sides
#: need names for constraints reaches the document as a path, and refusing that
#: would make the claim an instruction about how to write CAD-IR rather than a
#: statement about the part.
_PROFILE_CONTOURS: dict[ProfileKind, tuple[type, ...]] = {
    ProfileKind.RECTANGLE: (RectangleContour, PathContour),
    ProfileKind.CIRCLE: (CircleContour,),
    ProfileKind.SLOT: (SlotContour, PathContour),
    ProfileKind.REGULAR_POLYGON: (RegularPolygonContour, PathContour),
    ProfileKind.CLOSED_PROFILE: (
        PathContour,
        RectangleContour,
        CircleContour,
        SlotContour,
        RegularPolygonContour,
    ),
}

#: What a spelled-out path must look like to be the named shape, as
#: (straight segments, arcs). Only the two signatures that are unambiguous: a
#: rectangle is four straight sides and a slot is two sides and two end caps.
#:
#: This is what keeps the leniency above from making the check useless. Without
#: it, "rectangle" claimed against a stadium outline written as a path would pass,
#: which is precisely the misread the claim exists to catch. A polygon is left out
#: because the claim does not say how many sides, and a claim cannot be checked
#: against a number it never stated.
_PATH_SIGNATURES: dict[ProfileKind, tuple[int, int]] = {
    ProfileKind.RECTANGLE: (4, 0),
    ProfileKind.SLOT: (2, 2),
}


class OpeningClaim(StrictModel):
    kind: OpeningKind
    count: Annotated[int, Field(ge=1, le=1000)]


class ShapeClaim(StrictModel):
    """What the reading stage says the part is.

    `thickness` is the id of the parameter the drawing's depth was recorded as,
    or nothing when the reader could not name one. Naming it is what catches a
    dimension that lost its name on the way into the document — a literal where a
    parameter was read is a part that cannot be changed later without editing
    geometry.
    """

    profile: ProfileKind
    openings: Annotated[list[OpeningClaim], Field(max_length=64)] = Field(default_factory=list)
    #: How many separate solids the part is built from. One for a plate; more for
    #: a plate with a boss on it.
    solids: Annotated[int, Field(ge=1, le=64)] = 1
    thickness: Id | None = None
    #: Free text, for a reader to say what an outline is when the vocabulary
    #: above does not name it. Never read by any check — it exists so a person
    #: reviewing a contradiction can see what was meant.
    note: Annotated[str | None, Field(max_length=500)] = None


class Disagreement(StrictModel):
    """One way the document is not the part that was claimed."""

    #: What was compared, as a stable code a repair prompt can react to.
    code: str
    claimed: str
    built: str
    detail: Annotated[str, Field(max_length=300)]


def disagreements(document: CadIrDocument, claim: ShapeClaim) -> list[Disagreement]:
    """Every way `document` contradicts `claim`. Empty when the two agree.

    Only kinds and counts are compared, never positions or sizes: the drawing
    stage does not know coordinates and the document does, so anything measured
    would be the document checking itself.
    """
    solids = [
        feature
        for feature in document.features
        if feature.enabled and isinstance(feature, (SolidExtrudeFeature, SolidRevolveFeature))
    ]
    if not solids:
        return [
            Disagreement(
                code="NO_SOLID",
                claimed=f"{claim.solids} solid",
                built="none",
                detail="the document builds no solid at all",
            )
        ]

    found: list[Disagreement] = []
    found.extend(_profile_disagreement(solids[0], claim))
    found.extend(_solid_count_disagreement(solids, claim))
    found.extend(_opening_disagreements(document, claim))
    found.extend(_thickness_disagreement(solids[0], claim))
    return found


def _profile_disagreement(base, claim: ShapeClaim) -> list[Disagreement]:
    outer = base.inputs.sketch.outer
    if not isinstance(outer, _PROFILE_CONTOURS[claim.profile]):
        return [
            Disagreement(
                code="PROFILE_KIND",
                claimed=str(claim.profile),
                built=str(outer.type),
                detail=(
                    f"the drawing was read as a {claim.profile} outline and {base.id} "
                    f"builds a {outer.type}"
                ),
            )
        ]
    signature = _PATH_SIGNATURES.get(claim.profile)
    if signature is None or not isinstance(outer, PathContour):
        return []
    arcs = sum(1 for segment in outer.segments if str(segment.type) == "arc")
    built = (len(outer.segments) - arcs, arcs)
    if built == signature:
        return []
    return [
        Disagreement(
            code="PROFILE_KIND",
            claimed=str(claim.profile),
            built=f"a contour of {built[0]} straight segment(s) and {built[1]} arc(s)",
            detail=(
                f"the drawing was read as a {claim.profile} outline, which is "
                f"{signature[0]} straight segment(s) and {signature[1]} arc(s); "
                f"{base.id} spells out {built[0]} and {built[1]}"
            ),
        )
    ]


def _solid_count_disagreement(solids: list, claim: ShapeClaim) -> list[Disagreement]:
    if len(solids) == claim.solids:
        return []
    return [
        Disagreement(
            code="SOLID_COUNT",
            claimed=str(claim.solids),
            built=str(len(solids)),
            detail=(
                f"the drawing was read as {claim.solids} solid feature(s) and the "
                f"document has {len(solids)}"
            ),
        )
    ]


def _opening_disagreements(document: CadIrDocument, claim: ShapeClaim) -> list[Disagreement]:
    """Openings, counted by kind wherever they are built.

    An island in a base sketch and a separate cut are the same hole on a drawing,
    so both are counted. Counting only one of them would make a claim about the
    part into a claim about how the document was written.
    """
    built: dict[type, int] = {}
    for feature in document.features:
        if not feature.enabled:
            continue
        sketch = getattr(feature.inputs, "sketch", None)
        if sketch is None:
            continue
        contours = list(sketch.inner)
        if isinstance(feature, (CutExtrudeFeature, CutRevolveFeature)):
            contours.append(sketch.outer)
        for contour in contours:
            built[type(contour)] = built.get(type(contour), 0) + 1

    found: list[Disagreement] = []
    claimed_total = sum(item.count for item in claim.openings)
    for item in claim.openings:
        matched = sum(
            count
            for kind, count in built.items()
            if issubclass(kind, _OPENING_CONTOURS[item.kind])
        )
        if matched != item.count:
            found.append(
                Disagreement(
                    code="OPENING_COUNT",
                    claimed=f"{item.count} {item.kind}",
                    built=f"{matched} {item.kind}",
                    detail=(
                        f"the drawing was read as {item.count} {item.kind} opening(s) "
                        f"and the document builds {matched}"
                    ),
                )
            )

    total = sum(built.values())
    if total != claimed_total and not found:
        # The kinds each matched and the total did not, which means the document
        # has openings of a kind nobody read off the drawing.
        found.append(
            Disagreement(
                code="OPENING_COUNT",
                claimed=f"{claimed_total} opening(s)",
                built=f"{total} opening(s)",
                detail="the document builds openings the drawing was not read as having",
            )
        )
    return found


def _thickness_disagreement(base, claim: ShapeClaim) -> list[Disagreement]:
    if claim.thickness is None:
        return []
    distance = getattr(base.inputs, "distance", None)
    if isinstance(distance, ParameterRef):
        if str(distance.parameter) == str(claim.thickness):
            return []
        return [
            Disagreement(
                code="THICKNESS_PARAMETER",
                claimed=str(claim.thickness),
                built=str(distance.parameter),
                detail=(
                    f"the drawing's thickness was read as {claim.thickness} and "
                    f"{base.id} extrudes by {distance.parameter}"
                ),
            )
        ]
    if distance is None:
        # A revolve has no distance. The claim naming a thickness for one is a
        # reading that does not fit the part, and saying so is more useful than
        # ignoring the field.
        return [
            Disagreement(
                code="THICKNESS_PARAMETER",
                claimed=str(claim.thickness),
                built="no extrusion distance",
                detail=f"{base.id} is not an extrusion, so it has no thickness to check",
            )
        ]
    return [
        Disagreement(
            code="THICKNESS_PARAMETER",
            claimed=str(claim.thickness),
            built=f"the literal {distance}",
            detail=(
                f"the drawing's thickness was read as parameter {claim.thickness} and "
                f"{base.id} extrudes by a literal, so the dimension lost its name"
            ),
        )
    ]


__all__ = [
    "Disagreement",
    "OpeningClaim",
    "OpeningKind",
    "ProfileKind",
    "ShapeClaim",
    "disagreements",
]
