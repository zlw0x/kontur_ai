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

from pydantic import BaseModel, ConfigDict, Field


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
