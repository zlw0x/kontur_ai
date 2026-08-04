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
    BooleanFeature,
    CadIrDocument,
    ChamferFeature,
    CutExtrudeFeature,
    CutLoftFeature,
    CutRevolveFeature,
    CutSweepFeature,
    FilletFeature,
    PatternFeature,
    ResultKind,
    ShellFeature,
    SolidExtrudeFeature,
    SolidLoftFeature,
    SolidRevolveFeature,
    SolidSweepFeature,
    instance_count,
)
from .selectors import ExactlyN
from .sketch import (
    CircleContour,
    PathContour,
    RectangleContour,
    RegularPolygonContour,
    SlotContour,
)


#: Every feature that puts a lump of material in the part, and every one that takes a
#: piece out. A reader of a drawing counts lumps and openings, not operations, so these
#: are the lists `solids` and `openings` are compared against — and a new operation that
#: is missing from them is one the claim silently stops counting.
_MAKES_MATERIAL = (
    SolidExtrudeFeature,
    SolidRevolveFeature,
    SolidSweepFeature,
    SolidLoftFeature,
)
_REMOVES_MATERIAL = (
    CutExtrudeFeature,
    CutRevolveFeature,
    CutSweepFeature,
    CutLoftFeature,
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


class BlendKind(StrEnum):
    """A rounded edge or a cut one. The two things a drawing marks on a corner."""

    FILLET = "fillet"
    CHAMFER = "chamfer"


class BlendClaim(StrictModel):
    """How many edges the drawing shows treated, and how.

    The claim's word for a blend, and it exists because the output profile started
    offering one (ADR-032). A blend changes nothing else the claim counts — the
    outline, the openings and the solid count are the same with the corners square —
    so before this a fillet the compilation stage invented, forgot or applied to the
    wrong edges was unchecked by anything the reading stage said.

    A count, never a radius: ADR-025's rule holds. How big the round is is a size, and
    a size is checked by an expectation against a number the drawing stated.
    """

    kind: BlendKind
    count: Annotated[int, Field(ge=1, le=1000)]


class OpeningClaim(StrictModel):
    kind: OpeningKind
    count: Annotated[int, Field(ge=1, le=1000)]
    #: Whether the drawing shows these going all the way through, or nothing when the
    #: reader could not tell. Added with POSTMVP-016, when the output profile started
    #: offering blind cuts: until then every opening the cycle could produce went
    #: through, and a depth could not be got wrong. Now it can, and nothing else
    #: catches it — `through_hole_count` is written by the same stage that chose the
    #: depth, so it agrees with whatever that stage decided.
    through: bool | None = None


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
    #: The id of the parameter holding the wall thickness, when the part is hollow,
    #: and nothing when it is solid or the reader could not tell.
    #:
    #: The claim's only word for a shell, and the one place it says something about
    #: how much of the part is there rather than what shape it is. It is here because
    #: a shell is the operation whose *omission* nothing else can see: an enclosure
    #: 100 × 60 × 40 with a 3 mm wall and a solid block of the same size agree on the
    #: outline, the openings, the body count and the bounding box, and differ by four
    #: times the material. Naming the parameter, rather than carrying the number,
    #: keeps the rule ADR-025 set — a claim states kinds and names, never sizes.
    wall: Id | None = None
    #: The id of the parameter holding the draft angle, when the drawing marks one, and
    #: nothing when the walls are square or the reader could not tell.
    #:
    #: The second thing the claim says about how much of the part is there rather than
    #: what shape it is, and it is here for the same reason `wall` is: a drafted
    #: extrusion and a square one agree on the outline, the openings, the solid count
    #: and — for the narrowing draft a cast part actually shows — the bounding box too.
    #: A 20 × 20 pad 10 mm tall drafted 20° holds 2 720.752 mm³ where the square one
    #: holds 4 000, and nothing else the claim counts can tell them apart.
    #:
    #: A name, never an angle, and never a direction either: which way the walls lean
    #: is the sign of the parameter's own value, and a canonical `Scalar` has no
    #: arithmetic to flip it with (ADR-033). Measured rather than assumed — see
    #: `_draft_disagreement`.
    draft: Id | None = None
    #: The rounded and chamfered edges the drawing marks, by kind and count. Empty when
    #: the part has none or the reader could not see them — silence is not a claim.
    blends: Annotated[list[BlendClaim], Field(max_length=16)] = Field(default_factory=list)
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
    repeats = _repeats(document)
    subtracted, consumed = _boolean_roles(document)
    solids = [
        feature
        for feature in document.features
        if feature.enabled
        and isinstance(feature, _MAKES_MATERIAL)
        and str(feature.id) not in consumed
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
    found.extend(_solid_count_disagreement(solids, claim, repeats))
    found.extend(_opening_disagreements(document, claim, repeats, subtracted))
    found.extend(_thickness_disagreement(solids[0], claim))
    found.extend(_wall_disagreement(document, claim))
    found.extend(_draft_disagreement(document, claim))
    found.extend(_blend_disagreements(document, claim))
    return found


def _boolean_roles(document: CadIrDocument) -> tuple[set[str], set[str]]:
    """What the booleans do to the features that built their tool bodies.

    CAD-IR 1.7 makes this the claim's problem, because with booleans "what the part is"
    can no longer be read off feature types alone. A block extruded and then *subtracted*
    from the plate is a hole on the drawing, not a lump of metal — and before this it was
    counted as a solid and its opening was counted not at all.

    Returns the feature ids whose body ends up as an opening, and the ids that are no
    longer lumps of material. A tool the document keeps is both: it cuts the target and
    survives as a body of its own.

    A `union` is deliberately absent from both sets. A rib welded on by a boolean is the
    same thing to a reader as a boss fused implicitly, and the claim has counted the
    latter as its own lump since ADR-025.
    """
    creators: dict[str, str] = {}
    for feature in document.features:
        if not feature.enabled:
            continue
        for result in feature.produces:
            if result.kind is ResultKind.SOLID_BODY:
                creators[str(result.id)] = str(feature.id)

    subtracted: set[str] = set()
    consumed: set[str] = set()
    for feature in document.features:
        if not feature.enabled or not isinstance(feature, BooleanFeature):
            continue
        operation = str(feature.inputs.op)
        for tool in feature.inputs.tools:
            creator = creators.get(str(tool.result))
            if creator is None:
                continue
            if operation == "subtract":
                subtracted.add(creator)
            if operation in ("subtract", "intersect") and not feature.inputs.keep_tools:
                consumed.add(creator)
            elif operation == "union" and not feature.inputs.keep_tools:
                # Fused in, so it is not a body any more — but it is still a lump of
                # material a reader counts, exactly like a boss.
                pass
    return subtracted, consumed


def _repeats(document: CadIrDocument) -> dict[str, int]:
    """How many times each feature's own contribution ends up in the part.

    One for a feature nothing repeats. A pattern of six makes its source happen six
    times, and a pattern of a pattern multiplies — which is how a grid is written
    (ADR-027). This is the whole reason a pattern is worth having in a contract that
    could already spell out six coordinates: the count becomes something the document
    *states*, and a claim that read six holes off the drawing can disagree with it.

    Walked in the document's own order, the same way the engine builds it, rather
    than derived from a formula. Two patterns of one source each add their instances
    to what is already there, and an outer pattern multiplies everything the inner one
    produced; a closed form for that is a second model of the build to get wrong.
    """
    counts: dict[str, int] = {}
    #: What one instance of a feature *contributes*, as leaf features and how many of
    #: each. For anything but a pattern that is itself, once.
    contents: dict[str, dict[str, int]] = {}

    for feature in document.features:
        name = str(feature.id)
        if not feature.enabled:
            continue
        if not isinstance(feature, PatternFeature):
            counts[name] = counts.get(name, 0) + 1
            contents[name] = {name: 1}
            continue

        source = contents.get(str(feature.inputs.of))
        if source is None:
            # A pattern of something disabled or undeclared. The canonical validator
            # refuses both; counting nothing here keeps this a pure function.
            continue
        instances = instance_count(feature.inputs)
        for leaf, each in source.items():
            counts[leaf] = counts.get(leaf, 0) + (instances - 1) * each
        contents[name] = {leaf: instances * each for leaf, each in source.items()}
    return counts


def _profile_of(feature):
    """The contour a feature draws, wherever it keeps it.

    Every operation but a loft has one sketch. A loft has sections, and its outline is
    the first of them — which says as much about the part as it can, because CAD-IR 1.9
    requires every section to be the same kind of contour (ADR-031). Had mixed sections
    been allowed, a claim of `circle` would have been satisfied by a solid that ends as
    a square.
    """
    sketch = getattr(feature.inputs, "sketch", None)
    if sketch is not None:
        return sketch
    sections = getattr(feature.inputs, "sections", None)
    return sections[0] if sections else None


def _profile_disagreement(base, claim: ShapeClaim) -> list[Disagreement]:
    sketch = _profile_of(base)
    if sketch is None:  # pragma: no cover - every material-making feature draws one
        return []
    outer = sketch.outer
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


def _solid_count_disagreement(
    solids: list, claim: ShapeClaim, repeats: dict[str, int]
) -> list[Disagreement]:
    """Lumps of material, patterns counted.

    Four bosses made by patterning one are four bosses on the drawing, so a reader
    who counted five lumps and a document that writes one boss and a pattern of four
    agree — and a document that patterned three would not.
    """
    built = sum(repeats.get(str(feature.id), 1) for feature in solids)
    if built == claim.solids:
        return []
    return [
        Disagreement(
            code="SOLID_COUNT",
            claimed=str(claim.solids),
            built=str(built),
            detail=(
                f"the drawing was read as {claim.solids} solid feature(s) and the "
                f"document builds {built}"
            ),
        )
    ]


def _opening_disagreements(
    document: CadIrDocument,
    claim: ShapeClaim,
    repeats: dict[str, int],
    subtracted: frozenset[str] | set[str] = frozenset(),
) -> list[Disagreement]:
    """Openings, counted by kind wherever they are built.

    An island in a base sketch and a separate cut are the same hole on a drawing,
    so both are counted. Counting only one of them would make a claim about the
    part into a claim about how the document was written.

    A patterned cut counts once per instance, for the same reason: six holes on a
    bolt circle are six holes to whoever read the drawing, whether the document spells
    out six circles or one and a pattern of six.
    """
    #: Openings by (contour type, whether it goes through). The second half is what a
    #: blind hole made checkable, and `None` is where the document does not plainly say.
    built: dict[tuple[type, bool | None], int] = {}
    for feature in document.features:
        if not feature.enabled:
            continue
        sketch = _profile_of(feature)
        if sketch is None:
            continue
        instances = repeats.get(str(feature.id), 1)
        cuts = isinstance(feature, _REMOVES_MATERIAL)
        # An island in a solid profile is a hole through the whole extrusion. An island
        # in a cut's profile is material that cut leaves behind, and how far it reaches
        # is not something this can read off the document.
        contours = [(contour, None if cuts else True) for contour in sketch.inner]
        if cuts:
            contours.append((sketch.outer, _reaches_through(feature)))
        elif str(feature.id) in subtracted:
            # A body extruded and then subtracted is a hole on the drawing. The shape
            # of the opening is the shape of the tool's own outline (ADR-028); how deep
            # it reaches is geometry rather than a word in the document, so it is left
            # unsaid.
            contours.append((sketch.outer, None))
        for contour, through in contours:
            key = (type(contour), through)
            built[key] = built.get(key, 0) + instances

    found: list[Disagreement] = []
    claimed_total = sum(item.count for item in claim.openings)
    for item in claim.openings:
        matched = sum(
            count
            for (kind, through), count in built.items()
            if issubclass(kind, _OPENING_CONTOURS[item.kind])
            and _depth_agrees(item.through, through)
        )
        if matched != item.count:
            depth = "" if item.through is None else (
                " through" if item.through else " blind"
            )
            found.append(
                Disagreement(
                    code="OPENING_COUNT",
                    claimed=f"{item.count}{depth} {item.kind}",
                    built=f"{matched}{depth} {item.kind}",
                    detail=(
                        f"the drawing was read as {item.count}{depth} {item.kind} "
                        f"opening(s) and the document builds {matched}"
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


def _reaches_through(feature) -> bool | None:
    """Whether a cut goes all the way through, as the document states it.

    Read rather than measured: `through_all` is a word in the document and a distance
    is a number in it, and neither needs geometry. A revolved cut says nothing about
    depth in these terms, so it says nothing.
    """
    if isinstance(feature, CutRevolveFeature):
        return None
    return bool(getattr(feature.inputs, "through_all", False))


def _depth_agrees(claimed: bool | None, built: bool | None) -> bool:
    """A reader who could not tell, or a document that does not say, agrees with both.

    Silence is not a claim. This check exists for the drawing that plainly shows a
    blind hole against a document that drills through — not to punish a reader for
    admitting it could not see the depth.
    """
    return claimed is None or built is None or claimed == built


def _blend_disagreements(document: CadIrDocument, claim: ShapeClaim) -> list[Disagreement]:
    """Rounded and chamfered edges, counted where the document states a count.

    A blend's count is in the document only when its selector declares one. CAD-IR 1.5
    already refuses a cardinality that could match nothing, and `exactly_n` is the one
    that says how many — which is what the output profile emits, and what makes this
    check possible at all. A blend that says `one_or_more` has not stated a number, and
    a claim cannot disagree with a number nobody wrote.
    """
    if not claim.blends:
        return []

    counted: dict[BlendKind, int] = {kind: 0 for kind in BlendKind}
    unstated: set[BlendKind] = set()
    for feature in document.features:
        if not feature.enabled:
            continue
        if isinstance(feature, FilletFeature):
            kind = BlendKind.FILLET
        elif isinstance(feature, ChamferFeature):
            kind = BlendKind.CHAMFER
        else:
            continue
        cardinality = feature.inputs.edges.cardinality
        if isinstance(cardinality, ExactlyN):
            counted[kind] += cardinality.value
        else:
            unstated.add(kind)

    found: list[Disagreement] = []
    for item in claim.blends:
        if item.kind in unstated:
            continue
        built = counted[item.kind]
        if built == item.count:
            continue
        found.append(
            Disagreement(
                code="BLEND_COUNT",
                claimed=f"{item.count} {item.kind}",
                built=f"{built} {item.kind}",
                detail=(
                    f"the drawing was read as {item.count} {item.kind}ed edge(s) and the "
                    f"document blends {built}"
                ),
            )
        )
    return found


def _wall_disagreement(document: CadIrDocument, claim: ShapeClaim) -> list[Disagreement]:
    """A part read as hollow must be hollowed by a named wall.

    Three ways to get this wrong, and the first is the one worth the check: a
    document that never shells at all. It builds, it is manifold, its bounding box is
    the drawing's, its openings are the drawing's, and it is a solid billet where the
    drawing shows a 3 mm wall.

    The other two are the same mistake `thickness` catches one level up — a wall built
    from a literal has lost the name the drawing gave it, and a wall built from the
    wrong parameter moves when something else is edited.

    Silence is not a claim, here as everywhere: a reader who did not see a wall says
    nothing, and a document that shells anyway is not contradicted. What a reader
    cannot see, a reader does not get to be wrong about.
    """
    if claim.wall is None:
        return []
    shells = [
        feature
        for feature in document.features
        if feature.enabled and isinstance(feature, ShellFeature)
    ]
    if not shells:
        return [
            Disagreement(
                code="WALL_PARAMETER",
                claimed=str(claim.wall),
                built="no shell",
                detail=(
                    f"the drawing was read as a hollow part with wall {claim.wall} and "
                    "the document builds it solid"
                ),
            )
        ]
    named = {
        str(shell.inputs.thickness.parameter)
        for shell in shells
        if isinstance(shell.inputs.thickness, ParameterRef)
    }
    if str(claim.wall) in named:
        return []
    literals = [shell for shell in shells if not isinstance(shell.inputs.thickness, ParameterRef)]
    if literals:
        return [
            Disagreement(
                code="WALL_PARAMETER",
                claimed=str(claim.wall),
                built=f"the literal {literals[0].inputs.thickness}",
                detail=(
                    f"the drawing's wall was read as parameter {claim.wall} and "
                    f"{literals[0].id} shells by a literal, so the dimension lost its name"
                ),
            )
        ]
    return [
        Disagreement(
            code="WALL_PARAMETER",
            claimed=str(claim.wall),
            built=", ".join(sorted(named)),
            detail=(
                f"the drawing's wall was read as {claim.wall} and the document shells "
                f"by {', '.join(sorted(named))}"
            ),
        )
    ]


def _drafted(document: CadIrDocument) -> list:
    """Every enabled feature whose extrusion leans, in document order.

    `taper_deg` defaults to a plain 0.0 and every other operation has none, so this is
    a list of the features that actually draft something. A reference is always counted:
    what a parameter holds is looked at separately, because a *named* zero is a
    different mistake from an unnamed angle.
    """
    return [
        feature
        for feature in document.features
        if feature.enabled
        and (
            isinstance(taper := getattr(feature.inputs, "taper_deg", 0.0), ParameterRef)
            or float(taper) != 0.0
        )
    ]


def _draft_disagreement(document: CadIrDocument, claim: ShapeClaim) -> list[Disagreement]:
    """A part read as drafted must be drafted by a named angle.

    The same three mistakes `wall` catches, and the first is again the one worth the
    check: a document that leaves the walls square. It builds, it is manifold, its
    outline is the drawing's, its openings are the drawing's, and — this is what makes
    a draft harder than a wall — **its bounding box is the drawing's too**. Measured:
    a 20 × 20 sketch extruded 10 mm with a +20° taper still spans exactly ±10 in x,
    because the taper narrows away from the sketch plane and the sketch is the widest
    section. Only the volume knows, and the volume expectation is written by the same
    stage that chose the taper.

    (A *negative* taper widens as it travels, and there the same sketch spans ±13.640 —
    so a widening draft the document invented is visible to a bounding box and a
    narrowing one the document forgot is not. The common case on a cast part is the
    invisible one.)

    Two things this deliberately does not say. Not the angle: ADR-025's rule, and a
    size is an expectation's job. Not the direction either — which way the walls lean is
    the sign of the parameter's own value, and a canonical `Scalar` is a float or a
    reference with no arithmetic between them, so the compilation cannot flip a sign it
    was given. A claimed "narrows" could therefore only ever disagree with the reading
    stage's own number, and a check that compares a stage against itself is not a check
    (ADR-018).

    What it also cannot see is *which* feature leans. A drawing that drafts a pocket and
    a document that drafts the outside wall by the right parameter agree here.
    """
    if claim.draft is None:
        return []
    tapered = _drafted(document)
    if not tapered:
        return [
            Disagreement(
                code="DRAFT_PARAMETER",
                claimed=str(claim.draft),
                built="no taper",
                detail=(
                    f"the drawing was read as drafted by {claim.draft} and the document "
                    "extrudes square"
                ),
            )
        ]
    named = {
        str(feature.inputs.taper_deg.parameter)
        for feature in tapered
        if isinstance(feature.inputs.taper_deg, ParameterRef)
    }
    if str(claim.draft) in named:
        held = next(
            (
                parameter.value
                for parameter in document.parameters
                if str(parameter.id) == str(claim.draft)
            ),
            None,
        )
        if held is not None and float(held) == 0.0:
            # A named zero: the document drafts by the right parameter and the parameter
            # says the walls are vertical. Cheap to state and it holds the whole boundary
            # together — the id and the value reach the document from the same reading,
            # and this is where the two stop agreeing.
            return [
                Disagreement(
                    code="DRAFT_PARAMETER",
                    claimed=str(claim.draft),
                    built=f"{claim.draft} = 0",
                    detail=(
                        f"the drawing was read as drafted and {claim.draft} holds 0°, so "
                        "the walls are square whatever references it"
                    ),
                )
            ]
        return []
    literals = [feature for feature in tapered if not isinstance(feature.inputs.taper_deg, ParameterRef)]
    if literals:
        return [
            Disagreement(
                code="DRAFT_PARAMETER",
                claimed=str(claim.draft),
                built=f"the literal {literals[0].inputs.taper_deg}",
                detail=(
                    f"the drawing's draft was read as parameter {claim.draft} and "
                    f"{literals[0].id} tapers by a literal, so the angle lost its name"
                ),
            )
        ]
    return [
        Disagreement(
            code="DRAFT_PARAMETER",
            claimed=str(claim.draft),
            built=", ".join(sorted(named)),
            detail=(
                f"the drawing's draft was read as {claim.draft} and the document tapers "
                f"by {', '.join(sorted(named))}"
            ),
        )
    ]


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
    "BlendClaim",
    "BlendKind",
    "Disagreement",
    "OpeningClaim",
    "OpeningKind",
    "ProfileKind",
    "ShapeClaim",
    "disagreements",
]
