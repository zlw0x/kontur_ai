"""CAD-IR 1.7: more than one body, and the booleans between them.

Until now a document described one lump of material. Every additive feature fused
into whatever had been built and every cut removed from it, so `source_body` — a
field the contract has carried since 1.1 — pointed at the only body there was and the
engine could ignore it without anyone noticing.

This version makes a body a real thing: created by name, targeted by name, and
combined by name. Three consequences are the point of the milestone.

*`from_result` starts meaning something.* A selector says which body's faces or edges
it is talking about, and with two bodies in the part that is no longer decorative.

*A boolean is an operation, not a side effect.* Fusing has always happened
implicitly, and implicit fusing is fine for a boss on a plate. It is not fine for
"subtract this tool from that body and keep the tool", which is a statement about two
named things and cannot be spelled as an ordering.

*Nothing changes for a document that says nothing.* A feature with no `new_body` and
no `source_body` still fuses into the body being built, which is what every fixture
written before 1.7 means and what the drawing pipeline emits. The new behaviour is
opt-in, because the alternative — every solid feature making its own body — would turn
every existing multi-feature part into a multi-body one.

**A boolean modifies its target and produces nothing.** The alternative, a boolean
that produced a new body id, would leave a document naming three bodies where a
person sees one, and every later selector would have to know which of the three the
part is now made of.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import (
    FeatureResult,
    FeatureType,
    Id,
    Provenance,
    ResultRef,
    StrictModel,
)


class BooleanOp(StrEnum):
    """What to do with the tools, in the words the roadmap uses (P2.6)."""

    UNION = "union"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"


class BooleanInputs(StrictModel):
    """One boolean: a target body, one or more tool bodies, and what to do.

    `keep_tools` decides whether the tools survive as bodies of their own. The default
    is that they do not, because a tool that stays behind is a second lump in the
    delivered STEP and a document should have to ask for that.
    """

    op: BooleanOp
    target: ResultRef
    tools: Annotated[list[ResultRef], Field(min_length=1, max_length=32)]
    keep_tools: bool = False

    @model_validator(mode="after")
    def validate_operands(self) -> "BooleanInputs":
        names = [item.result for item in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("a body is a tool once or not at all")
        if self.target.result in names:
            # Subtracting a body from itself is nothing; uniting it with itself is a
            # no-op that reads as an operation. Both are documents that mean something
            # else, and neither is worth guessing at.
            raise ValueError(
                f"{self.target.result} is both the target and a tool of this boolean"
            )
        return self


class BooleanFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.BOOLEAN]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    #: Always empty: the result *is* the target body, under the name it already has.
    produces: Annotated[list[FeatureResult], Field(max_length=0)] = Field(default_factory=list)
    inputs: BooleanInputs
    provenance: Provenance | None = None


__all__ = ["BooleanFeature", "BooleanInputs", "BooleanOp"]
