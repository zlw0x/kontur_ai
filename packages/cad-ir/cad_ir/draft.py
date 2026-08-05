"""CAD-IR 1.12: draft — the walls a mould has to let go of, named one at a time.

`taper_deg` has drafted an extrusion since 1.10, and POSTMVP-024 measured that for a
plain boss the two are the same part to the last decimal: a 40 × 40 square drawn in
10° over 20 mm is 26 689.1761 mm³ whether the extrusion tapers or the walls are drafted
afterwards. That measurement is why this operation took three milestones to arrive —
by the rule POSTMVP-011, POSTMVP-022 and POSTMVP-024 arrived at from three directions,
**an operation earns its place in CAD-IR only when it says something composition
cannot.**

Two things `taper_deg` cannot say, both measured:

*Some walls and not others.* A taper draws in every wall its extrusion makes. Draft two
adjacent walls of that same block and the part is 29 261.6782 mm³ — closed form
`(a³ − (a − h·tanθ)³) / 3·tanθ`, exact — with the bounding box unchanged, because the
two undrafted walls still stand where the drawing put them. There is no sequence of
extrusions that produces it: a second extrusion adds material, and this removes it from
two sides of one lump.

*A body an extrusion did not make.* Draft the outer wall of a turned tube, inner Ø20,
outer Ø40, 20 tall: 18 849.5559 mm³ becomes 14 678.4446, the frustum less the bore,
exact. `taper_deg` cannot reach a revolved body at all, and a boolean's result even
less.

## What the document states, and what it must not

**The faces, by selector** (ADR-019), with a cardinality that cannot match nothing —
the rule a blend has had since ADR-026 and a shell since ADR-030. A draft that found no
walls is a feature that silently did not happen, and its failure mode is a part of
exactly the right size with vertical walls where the drawing shows a mould draft.

**The neutral face, by selector too.** The kernel takes a *plane*: the section lying in
it keeps its size and everything else moves. Which plane that is decides the part — the
same block drafted +10° about its base is 26 689.1761 mm³ and about its top is
37 974.1029, and both are valid solids of the right height. A drawing says which end
holds the dimension, so the document names the face rather than stating a coordinate.
That is ADR-026's rule for an asymmetric chamfer, which names the face its first
distance is measured from, for the same reason: the kernel's answer to "measured from
where?" would otherwise be whichever face it visited first.

**A sign, and only a sign.** Positive draws the walls *in* as they leave the neutral
face; negative lets them out. That is `taper_deg`'s rule (ADR-033) and it is deliberately
the same one: "draft" means opposite things on a boss and in a cavity, and a sign the
document cannot see is a sign somebody else chose.

## What is refused, and what the engine catches instead

A **zero** angle is refused here: it is a feature that does nothing, wearing the name of
one that does. Beyond that the contract cannot say much — whether an angle is too steep
depends on how far the faces reach, which only the kernel knows. Measured on the same
block, where the section closes at 45°: at 40° a smaller valid solid, at exactly 45° a
**pyramid that reports `is_valid` false**, and past it `Standard_ConstructionError` with
an empty message — a raw OCCT throw with no code and nothing about the document, the
same shape as the revolve's `StdFail_NotDone` (ENGINE-MIG-006). So the engine tries and
then checks, as it does for a shell and for a taper (`DRAFT_TOO_STEEP`).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import (
    FeatureResult,
    FeatureType,
    Id,
    Provenance,
    Scalar,
    StrictModel,
    stated_number,
)
from .selectors import Cardinality, ExactlyN, FaceSelector

#: How far from flat a draft may lean, the same bound `taper_deg` carries. At 90° the
#: wall lies in the neutral plane and past it the solid turns inside out.
DRAFT_LIMIT_DEG = 89.0

#: The cardinalities a draft's face selector may declare — those that cannot match
#: nothing. `exactly_n` is allowed too and handled separately, being a model rather
#: than a member of the enum.
DRAFT_CARDINALITIES: tuple[Cardinality, ...] = (
    Cardinality.EXACTLY_ONE,
    Cardinality.ONE_OR_MORE,
)


def _require_countable_faces(selector: FaceSelector) -> None:
    """A draft's selector must be unable to match nothing.

    Third operation to carry this rule and the reason is unchanged: a draft that
    treated no faces is a successful feature that did not happen, and the part it
    leaves has the drawing's dimensions with none of its draft. Nothing downstream can
    see that — a draft changes no face count, no body count and, on the faces it does
    not touch, no bounding box.
    """
    cardinality = selector.cardinality
    if isinstance(cardinality, ExactlyN):
        if cardinality.value < 1:
            raise ValueError(
                f"selector {selector.id} drafts exactly 0 faces; a draft that treats "
                "nothing is a feature that silently did not happen"
            )
        return
    if cardinality not in DRAFT_CARDINALITIES:
        raise ValueError(
            f"selector {selector.id} declares {cardinality}, which allows matching no "
            "faces at all; a draft must declare exactly_one, one_or_more or exactly_n"
        )


def _require_one_neutral_face(selector: FaceSelector) -> None:
    """Exactly one, because two faces are two planes and the engine would pick one."""
    if selector.cardinality is not Cardinality.EXACTLY_ONE:
        raise ValueError(
            f"selector {selector.id} names the neutral face and must declare "
            "exactly_one: a draft is measured from one plane"
        )


class DraftInputs(StrictModel):
    """Draw `faces` in by `angle_deg`, measured from the plane of `neutral_face`.

    There is no `source_body`, for the reason a shell and a blend have none: the
    selectors' `from_result` already says whose faces these are, and a second way to
    say it is a second thing that can disagree.
    """

    #: The walls to draw in. Named, never "all of them": the whole point of the
    #: operation is that a drawing marks some walls and not others.
    faces: FaceSelector
    #: The face whose plane holds still. Its section keeps the size the drawing gives
    #: it, and every other section moves.
    neutral_face: FaceSelector
    #: Positive draws the walls in as they leave the neutral face; negative lets them
    #: out. The same rule as `taper_deg` (ADR-033), on purpose.
    angle_deg: Scalar

    @model_validator(mode="after")
    def validate_inputs(self) -> "DraftInputs":
        _require_countable_faces(self.faces)
        _require_one_neutral_face(self.neutral_face)
        if self.faces.id == self.neutral_face.id:
            # Two selectors with one id is a document that cannot be talked about: a
            # trace naming `selector.walls` would mean either of them.
            raise ValueError("a draft's faces and its neutral face need different ids")
        angle = stated_number(self.angle_deg)
        if angle is None:
            return self
        if angle == 0:
            raise ValueError(
                "a draft of 0° leaves the walls vertical; drop the feature rather than "
                "stating one that does nothing"
            )
        if not -DRAFT_LIMIT_DEG <= angle <= DRAFT_LIMIT_DEG:
            raise ValueError(
                f"a draft is between -{DRAFT_LIMIT_DEG:g} and {DRAFT_LIMIT_DEG:g} degrees"
            )
        return self


class DraftFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.DRAFT]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    #: Always empty. A draft moves the faces of a body that is already there.
    produces: Annotated[list[FeatureResult], Field(max_length=0)] = Field(default_factory=list)
    inputs: DraftInputs
    provenance: Provenance | None = None


__all__ = [
    "DRAFT_CARDINALITIES",
    "DRAFT_LIMIT_DEG",
    "DraftFeature",
    "DraftInputs",
]
