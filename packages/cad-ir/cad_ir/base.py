"""The pieces every part of CAD-IR is built from.

Split out so the modules above it can form a layer rather than a cycle:
selectors describe geometry, sketches use selectors, and the document uses
sketches — all three need identifiers, scalars and result references, and none
of them should have to import the document to get them.

`canonical` re-exports everything here, so `from .canonical import Id` keeps
working and there is still one obvious place to read the document from.
"""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Annotated, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


#: Readable, stable, lower-case. Random GUIDs would make a repair prompt, a
#: log line and a diff between two versions of the same part unreadable.
ID_PATTERN = r"^[a-z][a-z0-9_.-]{1,63}$"

Id = Annotated[str, Field(pattern=ID_PATTERN)]


class FeatureType(StrEnum):
    """What the canonical version can express.

    Adding an operation here is an additive version change that comes with an
    adapter, a verifier and fixtures — not a widening of this enum on its own.

    It lives here rather than in `canonical` because an operation now gets a
    module of its own once it is bigger than a pair of fields, and such a module
    has to name its own type without importing the document that collects it.
    One enum, imported downwards, instead of a cycle or a second list of strings
    to keep in step.
    """

    SOLID_EXTRUDE = "solid.extrude"
    CUT_EXTRUDE = "cut.extrude"
    SOLID_REVOLVE = "solid.revolve"
    CUT_REVOLVE = "cut.revolve"
    DATUM_PLANE_OFFSET = "datum.plane.offset"
    FILLET = "feature.fillet"
    CHAMFER = "feature.chamfer"
    PATTERN = "feature.pattern"
    BOOLEAN = "feature.boolean"
    SHELL = "feature.shell"
    SOLID_SWEEP = "solid.sweep"
    CUT_SWEEP = "cut.sweep"
    SOLID_LOFT = "solid.loft"
    CUT_LOFT = "cut.loft"


class ResultKind(StrEnum):
    SOLID_BODY = "solid_body"
    FACE = "face"
    EDGE = "edge"
    SKETCH = "sketch"
    PLANE = "plane"


class SourceRegion(StrictModel):
    """Where on the drawing a value came from, in normalised page coordinates.

    Optional, and kept out of the geometry: it exists so a wrong dimension can
    be traced back to the mark that produced it.
    """

    page: Annotated[int, Field(ge=1)]
    region: Annotated[list[Annotated[float, Field(ge=0, le=1)]], Field(min_length=4, max_length=4)]
    label: Annotated[str | None, Field(max_length=200)] = None


class Provenance(StrictModel):
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    source: SourceRegion | None = None
    note: Annotated[str | None, Field(max_length=300)] = None


class ParameterRef(StrictModel):
    """A reference to a named parameter."""

    parameter: Id


class ScalarQuotient(StrictModel):
    """A scalar divided by a constant — `{"divide": <scalar>, "by": 2.0}`.

    Almost every mechanical drawing dimensions **diameters**, and almost every
    contour takes a **radius**. Until this existed the two could not be the same
    number: a `Scalar` was `float | ParameterRef` with no arithmetic, so a
    document that read "Ø44" off a drawing had to write `44` into a parameter and
    then write `22` — or, as one real order did, write `44` again — as a literal
    beside it.

    That order is why this is here. It declared `bushing_outer_radius: 44`, the
    *diameter* value under a radius name, extruded a circle of radius 44, and
    restated 88 in its own expectation so the check agreed. A Ø88 part, delivered,
    with every measurement green — because the number that built it and the number
    that checked it were the same copy, and the copy that came off the drawing was
    compared against nothing.
    """

    divide: "Scalar"
    #: A constant, never a parameter. One dimension divided by another is a
    #: relationship the drawing did not state, and a document that computes one is
    #: inventing geometry rather than recording it.
    by: float

    @model_validator(mode="after")
    def validate_divisor(self) -> "ScalarQuotient":
        if not isfinite(self.by) or self.by == 0:
            raise ValueError("a scalar may only be divided by a finite, non-zero constant")
        if _depth(self) > _MAX_SCALAR_DEPTH:
            raise ValueError(
                f"a scalar may not nest deeper than {_MAX_SCALAR_DEPTH} operations")
        return self


class ScalarNegation(StrictModel):
    """The same scalar, the other way — `{"negate": <scalar>}`.

    The second thing one parameter could not do: drive both sides of a symmetric
    outline. `lever-plate`'s cap radius is 15 and its profile needs y = +15 *and*
    y = −15, so one of the two had to be a literal, and a document half-driven by
    its parameters is one where changing a dimension moves half the part.
    """

    negate: "Scalar"

    @model_validator(mode="after")
    def validate_depth(self) -> "ScalarNegation":
        if _depth(self) > _MAX_SCALAR_DEPTH:
            raise ValueError(
                f"a scalar may not nest deeper than {_MAX_SCALAR_DEPTH} operations")
        return self


#: How far a scalar may be derived from the parameter underneath it.
#:
#: Three covers everything the drawing cases need — `divide(negate(p), 2)` is two —
#: with one to spare. A bound exists at all because the nodes are recursive and a
#: document is written by a model: nothing else stops a tower a thousand deep from
#: being schema-valid, and every reader of it would recurse the same way.
_MAX_SCALAR_DEPTH = 3


def _depth(value: object) -> int:
    """How many operations sit between this scalar and its numbers."""
    if isinstance(value, ScalarQuotient):
        return 1 + _depth(value.divide)
    if isinstance(value, ScalarNegation):
        return 1 + _depth(value.negate)
    return 0


#: A number, a parameter, or one of two ways of deriving one from a parameter.
#:
#: Deliberately two operations and not four. Multiplication and addition were
#: considered and left out: the cases that were *measured* are a diameter driving
#: a radius and a parameter driving a symmetric pair, and every further operation
#: is another thing to validate, another line in the prompt, and another way for a
#: document to state a relationship nobody drew.
#:
#: Structured nodes rather than the string form 0.1.0 had (`{"expr": "d / 2"}`).
#: ADR-018 removed that on purpose: a string makes the trust boundary parse text
#: written by the model, and once it does the schema guarantees nothing about what
#: is inside. These are checked by the schema itself, and there is no parser.
Scalar = Union[float, ParameterRef, ScalarQuotient, ScalarNegation]

ScalarQuotient.model_rebuild()
ScalarNegation.model_rebuild()


class FeatureResult(StrictModel):
    """Something a feature creates that a later feature may refer to.

    Naming results explicitly is what lets a later operation say "the body the
    base extrusion made" instead of "whatever the previous feature left
    behind", which stops meaning the same thing as soon as features are
    reordered.
    """

    id: Id
    kind: ResultKind


class ResultRef(StrictModel):
    result: Id
