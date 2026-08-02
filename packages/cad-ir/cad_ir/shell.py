"""CAD-IR 1.8: shell — the operation that decides how much of the part is there.

Every operation so far answers "what shape is it?". A shell answers a different
question: the outline is the same, the openings are the same, the body count is the
same, and what changed is that the inside is gone. An enclosure 100 × 60 × 40 with a
3 mm wall and a solid block 100 × 60 × 40 are the same part to every check that
measures the outside, and they differ by a factor of four in material.

That makes a shell the operation whose *omission* is hardest to see, so two things
are decided here rather than left to the kernel.

*A shell must name at least one face to remove.* `all` and `zero_or_one` are refused,
the same rule an edge blend has had since CAD-IR 1.5 and for a sharper reason. It is
not that a shell of nothing is a no-op: `offset` with no openings is a different
operation entirely — it shrinks the solid — so a selector that matched nothing does
not leave the part alone, it silently replaces it with a smaller one. What the
document meant to be a hollow box comes back as a solid box 6 mm smaller in every
direction.

*A shell says which way the wall grows.* `inward` keeps the outside the drawing
dimensions and eats into the part; `outward` keeps the *inside* and grows past the
original surface, which is what a drawing of a pipe around a bore means. They are
different parts, the difference is invisible in the document unless it is stated, and
the kernel's own answer is a sign on a number.

What is deliberately absent is a wall that straddles the surface — "both", in the
roadmap's words. OpenCascade's solid offset has no such mode, and building one out of
two offsets would put a size in the document that no drawing states: a 3 mm wall
centred on the outline is a 1.5 mm change to a dimension somebody measured.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import (
    FeatureResult,
    FeatureType,
    Id,
    ParameterRef,
    Provenance,
    Scalar,
    StrictModel,
)
from .selectors import Cardinality, ExactlyN, FaceSelector


class ShellDirection(StrEnum):
    """Which side of the original surface the wall is on.

    `inward` is what "shell this part" means in every CAD system: the outer size is
    the size on the drawing and the material is removed from inside. `outward` is the
    other reading — the surface that exists becomes the cavity — and it changes the
    part's overall size, which is why it cannot be a detail the document leaves out.
    """

    INWARD = "inward"
    OUTWARD = "outward"


#: The cardinalities a shell's opening selector may declare.
#:
#: `exactly_n` is allowed too, and handled separately for the same reason as in
#: `blend`: it is a model rather than a member of the enum.
SHELL_CARDINALITIES: tuple[Cardinality, ...] = (
    Cardinality.EXACTLY_ONE,
    Cardinality.ONE_OR_MORE,
)


def _require_countable_faces(selector: FaceSelector) -> None:
    """A shell's selector must be unable to match nothing.

    An edge blend refuses the same two cardinalities because blending zero edges is a
    feature that silently does not happen. A shell of zero faces is worse than that:
    the kernel is still asked to offset the solid, and an offset with nothing open is
    the *shrink* operation. The document says "hollow this box, open at the top" and a
    selector that matched no top produces a solid box, smaller than the drawing, that
    passes a body count and a hole count and fails only a bounding box somebody
    remembered to state.
    """
    cardinality = selector.cardinality
    if isinstance(cardinality, ExactlyN):
        if cardinality.value < 1:
            raise ValueError(
                f"selector {selector.id} opens exactly 0 faces; a shell with nothing "
                "open is a solid that has been shrunk, not a hollow part"
            )
        return
    if cardinality not in SHELL_CARDINALITIES:
        raise ValueError(
            f"selector {selector.id} declares {cardinality}, which allows matching no "
            "faces at all; a shell must declare exactly_one, one_or_more or exactly_n "
            "so that opening nothing is a failure rather than a shrunken solid"
        )


class ShellInputs(StrictModel):
    """A wall of `thickness`, with the faces a selector names removed.

    There is no `source_body`: the selector's `from_result` already says whose faces
    these are, and a second way to say it is a second thing that can disagree — the
    same reasoning as a blend's.
    """

    #: The faces removed to open the part. Not the faces kept: a drawing of an
    #: enclosure names the open side, and listing the other five would be five more
    #: chances to name one wrong.
    faces: FaceSelector
    thickness: Scalar
    direction: ShellDirection = ShellDirection.INWARD

    @model_validator(mode="after")
    def validate_inputs(self) -> "ShellInputs":
        _require_countable_faces(self.faces)
        if isinstance(self.thickness, ParameterRef):
            # A promise about a number this module never sees. The engine resolves it
            # and checks it again in front of the kernel.
            return self
        if float(self.thickness) <= 0:
            raise ValueError("a wall thickness must be positive")
        return self


class ShellFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.SHELL]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    #: Always empty. A shell modifies the body it is given; it does not make one, and
    #: a result id here would name the body that was already there.
    produces: Annotated[list[FeatureResult], Field(max_length=0)] = Field(default_factory=list)
    inputs: ShellInputs
    provenance: Provenance | None = None


__all__ = [
    "SHELL_CARDINALITIES",
    "ShellDirection",
    "ShellFeature",
    "ShellInputs",
]
