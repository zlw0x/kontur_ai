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
    DRAFT = "feature.draft"
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
    """A parameter divided by a constant — `{"divide": {"parameter": "d"}, "by": 2.0}`.

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

    #: A parameter, and nothing else. Not a literal — `divide(80, 2)` is the number 40
    #: with extra words — and not another node, for the reason `validate_divisor`
    #: gives: one value, one spelling.
    divide: ParameterRef
    #: A constant, never a parameter. One dimension divided by another is a
    #: relationship the drawing did not state, and a document that computes one is
    #: inventing geometry rather than recording it.
    by: float

    @model_validator(mode="after")
    def validate_divisor(self) -> "ScalarQuotient":
        """Positive, finite, and not 1 — the half of the grammar that keeps it unique.

        ADR-018 makes a document's meaning a byte-stable hash of a *unique*
        representation, and 1.11 shipped four spellings of −r/2:

            {"negate": {"divide": {"parameter": "r"}, "by": 2.0}}
            {"divide": {"negate": {"parameter": "r"}}, "by": 2.0}
            {"divide": {"parameter": "r"}, "by": -2.0}

        — three hashes, one number. And two of +r, the plain reference and a pair of
        negations that cancel. Each was legal, so the property ADR-018 traded
        expressions away to get did not actually hold.

        Closing it needs no new field, only a grammar: **a quotient divides a
        parameter by a positive constant, and a negation wraps a reference or a
        quotient.** Every value has exactly one spelling, and the depth is two by
        construction rather than by a bound anybody has to check.
        """
        if not isfinite(self.by) or self.by <= 0:
            raise ValueError(
                "a scalar is divided by a finite constant greater than zero; a "
                "negative divisor is a negation, and belongs on the outside"
            )
        if self.by == 1:
            raise ValueError("dividing by 1 is the parameter itself; reference it")
        return self


class ScalarNegation(StrictModel):
    """A parameter or a quotient, the other way — `{"negate": {"parameter": "r"}}`.

    The second thing one parameter could not do: drive both sides of a symmetric
    outline. `lever-plate`'s cap radius is 15 and its profile needs y = +15 *and*
    y = −15, so one of the two had to be a literal, and a document half-driven by
    its parameters is one where changing a dimension moves half the part.
    """

    #: A reference or a quotient. Not a literal — `negate(5)` is `-5` — and not
    #: another negation, because two cancel and the value is already sayable without
    #: either. The other half of the grammar `ScalarQuotient.validate_divisor` states.
    negate: Union[ParameterRef, ScalarQuotient]


#: The deepest a scalar can be, and it is a property of the grammar rather than a
#: bound anybody enforces: a quotient divides a *parameter*, and a negation wraps a
#: reference or a quotient, so `negate(divide(p, k))` is as far as it goes.
#:
#: 1.11 had an explicit `_MAX_SCALAR_DEPTH` because the two nodes each took a whole
#: `Scalar` and nothing else stopped a tower a thousand deep from being schema-valid.
#: With the grammar closed the check could no longer fire, and a check that cannot
#: fail is not a check.
MAX_SCALAR_DEPTH = 2


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
#:
#: And a **grammar** rather than two nodes that each take a whole `Scalar`. Written the
#: general way, 1.11 admitted four spellings of −p/2 and two of +p, so the byte-stable
#: hash ADR-018 exists for did not identify a part. Each node now takes only what keeps
#: the spelling unique, which also puts the shape of the language in the generated
#: schema instead of in a validator nobody reads.
Scalar = Union[float, ParameterRef, ScalarQuotient, ScalarNegation]


def stated_number(value: object) -> float | None:
    """The number a scalar states outright, or nothing when it depends on a parameter.

    Every range check in this contract has the same shape: a literal size can be
    checked here, and a named one is a promise about a number this module never sees,
    which the engine resolves and re-checks in front of the kernel. Each of them wrote
    that as `isinstance(value, ParameterRef)` — correct while a `Scalar` had two
    members, and wrong the moment ADR-034 gave it four.

    It was wrong in the worst available way. `float(ScalarQuotient(...))` raises
    `TypeError` from inside a pydantic validator, which is not a refusal: it escapes as
    a raw type error, reaches the caller as `SCHEMA_INVALID` with the message
    "float() argument must be a string or a real number", and the range check it was
    guarding never runs. Seven of the nine sites did this — a fillet radius, three
    chamfer sizes, a wall thickness, a pattern spacing and an extrusion taper — so a
    document that drove any of them from a diameter was refused with a Python
    diagnostic, and one that drove them from a negative one was not checked at all.

    One function so that the next member of `Scalar` cannot reintroduce it.
    """
    if isinstance(value, (ParameterRef, ScalarQuotient, ScalarNegation)):
        return None
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def parameters_of(value: object) -> frozenset[str]:
    """Every parameter a scalar reads, through whatever arithmetic sits on top of it.

    The other half of the same problem, and it belongs to the shape claim rather than
    to a range check. `thickness`, `wall` and `draft` each name the parameter the
    drawing's dimension was recorded as, and each asked whether the geometry's scalar
    *is* a `ParameterRef` with that name. A thickness written as half of a stated
    overall height is driven by the parameter and would have been reported as "the
    literal ...", telling the compiling agent to fix something it had done right.
    """
    if isinstance(value, ParameterRef):
        return frozenset({str(value.parameter)})
    if isinstance(value, ScalarQuotient):
        return parameters_of(value.divide)
    if isinstance(value, ScalarNegation):
        return parameters_of(value.negate)
    return frozenset()


def negates(value: object) -> bool:
    """Whether a scalar arrives with its sign turned over.

    One question, asked in one place: `ShapeClaim.draft` names the parameter holding a
    draft angle and deliberately says nothing about direction, because ADR-033 measured
    that a positive taper narrows away from the sketch plane whichever way the extrusion
    travels — and, at the time, because a `Scalar` had no arithmetic to flip a sign
    with. ADR-034 gave it one. `{"negate": {"parameter": "draft_angle"}}` leans the
    walls the other way while still naming the parameter the reading cited.

    One line, and it is the grammar that makes it one. While a sign could also hide in a
    negative divisor or in a pair of negations, this had to walk the tree and answer for
    three spellings; with those refused there is exactly one place a sign can be.
    """
    return isinstance(value, ScalarNegation)


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
