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
    """A reference to a named parameter, the only indirection CAD-IR allows."""

    parameter: Id


class ScaledParameterRef(StrictModel):
    """A parameter multiplied by a constant: a diameter driving a radius.

    **Not yet part of `Scalar`, and deliberately so** — adding it is a CAD-IR
    version. It is here, with a resolver in the engine and tests for both, because
    the design was decided by measurement and the arithmetic is worth proving
    before the version that carries it. `docs/TASK-POSTMVP-scalar-arithmetic.md`
    has the argument and what wiring costs.

    The problem it exists for was found by a real run
    (`docs/acceptance/POSTMVP-016-runs-2-6-*`): a flange document carried
    `outer_diameter: 80` cited to the Ø80 callout, drew a literal `radius: 40`, and
    restated 80 in its expectation. Change the parameter to 100 and the part stays
    Ø80 — every check passes, because the copy with the best provenance is the one
    nothing reads. A `Scalar` of `float | ParameterRef` gives a diameter nowhere to
    go: it can drive a magnitude and not a half of one, so the parameter is unused
    because the contract has no way to use it.

    One node rather than an expression, and that is the whole design. A free-text
    `{"expr": "outer_diameter / 2"}` — which CAD-IR 0.1.0 had, and whose parser is
    still in `cad_ir.expression` — cannot be canonical: `"d/2"` and `"d / 2"` are
    the same part with two byte-stable hashes, and ADR-018 traded expressions away
    for exactly that reason. A scaled reference has one spelling per part, needs no
    parser, and covers every case the runs turned up: a diameter driving a radius
    (`times: 0.5`) and one parameter driving both sides of a symmetric outline
    (`times: -1`).
    """

    parameter: Id
    #: Bounded because an unbounded factor turns a 40 mm plate into a kilometre of
    #: one, and the bound is the same 1e6 the expression evaluator has always used
    #: for its result.
    times: Annotated[float, Field(gt=-1_000_000.0, lt=1_000_000.0)]

    @model_validator(mode="after")
    def validate_factor(self) -> "ScaledParameterRef":
        if self.times == 1.0:
            # A plain `ParameterRef` already says this, and two spellings of one part
            # is what canonical form exists to prevent (ADR-018).
            raise ValueError("a factor of 1 is a plain parameter reference; use one")
        if self.times == 0.0:
            # Zero drives nothing, which is the defect this form was added to fix.
            raise ValueError("a factor of 0 is the literal 0 wearing a parameter's name")
        return self


#: Not `ScaledParameterRef` yet: see that class, and
#: `docs/TASK-POSTMVP-scalar-arithmetic.md`.
Scalar = Union[float, ParameterRef]


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
