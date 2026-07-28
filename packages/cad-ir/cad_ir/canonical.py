"""CAD-IR 1.1: the canonical form.

Version 0.1.0 was shaped around the one part the MVP builds. This version is
shaped around what the next few dozen operations will need, without adding any
of them: the document declares its own schema and version, features form an
explicit dependency graph, every feature says what it produces, and parameters
are typed rather than being floats with a unit string.

Three boundaries are deliberate.

*Intent, not execution.* Nothing here may name a COM object, a face or edge
index, a file path or a command. The document says what the part is; the
trusted adapter decides how KOMPAS should build it. An index that means
something today means something else after the next parameter change.

*Expectations do not drive the build.* They are what an independent verifier
checks afterwards. A build that read them could satisfy them by construction,
which would make them worthless.

*No expression language yet.* A value is a number or a reference to a
parameter. Arithmetic in a document the model writes is a second thing to
validate and a second thing to get wrong, and nothing in the supported
geometry needs it.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

CAD_IR_SCHEMA = "cad-ai/cad-ir"
CAD_IR_VERSION = "1.1"

#: Versions this build can consume. A document declaring anything else is
#: rejected before its features are read.
SUPPORTED_VERSIONS: tuple[str, ...] = ("1.1",)

#: Versions the normalizer can lift into the canonical form.
MIGRATABLE_VERSIONS: tuple[str, ...] = ("0.1.0",)

#: Readable, stable, lower-case. Random GUIDs would make a repair prompt, a
#: log line and a diff between two versions of the same part unreadable.
ID_PATTERN = r"^[a-z][a-z0-9_.-]{1,63}$"

Id = Annotated[str, Field(pattern=ID_PATTERN)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ParameterType(StrEnum):
    LENGTH = "length"
    ANGLE = "angle"
    COUNT = "count"
    RATIO = "ratio"
    BOOLEAN = "boolean"


#: Canonical units. Length is millimetres and angle is degrees in the
#: document; the adapter converts to whatever its maths needs. One internal
#: representation per quantity is the whole point.
CANONICAL_UNIT: dict[ParameterType, str | None] = {
    ParameterType.LENGTH: "mm",
    ParameterType.ANGLE: "deg",
    ParameterType.COUNT: None,
    ParameterType.RATIO: None,
    ParameterType.BOOLEAN: None,
}


class ParameterStatus(StrEnum):
    CONFIRMED = "confirmed"
    USER_CONFIRMED = "user_confirmed"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    UNRESOLVED = "unresolved"


class ResultKind(StrEnum):
    SOLID_BODY = "solid_body"
    FACE = "face"
    EDGE = "edge"
    SKETCH = "sketch"


class FeatureType(StrEnum):
    """What version 1.1 can express.

    Two entries, because the confirmed geometry is one extrusion and any
    number of cuts. Adding an operation here is an additive version change
    that comes with an adapter, a verifier and fixtures — not a widening of
    this enum on its own.
    """

    SOLID_EXTRUDE = "solid.extrude"
    CUT_EXTRUDE = "cut.extrude"


class SketchPlane(StrEnum):
    XY = "XY"
    XZ = "XZ"
    YZ = "YZ"


class Direction(StrEnum):
    PLUS_X = "+X"
    MINUS_X = "-X"
    PLUS_Y = "+Y"
    MINUS_Y = "-Y"
    PLUS_Z = "+Z"
    MINUS_Z = "-Z"


class PartType(StrEnum):
    SINGLE_PART = "single_part"


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
    """A reference to a named parameter, the only indirection 1.1 allows."""

    parameter: Id


Scalar = Union[float, ParameterRef]


class Parameter(StrictModel):
    id: Id
    type: ParameterType
    value: float
    unit: Annotated[str | None, Field(max_length=16)] = None
    name: Annotated[str | None, Field(max_length=100)] = None
    status: ParameterStatus = ParameterStatus.CONFIRMED
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def validate_unit(self) -> "Parameter":
        expected = CANONICAL_UNIT[self.type]
        if self.unit != expected:
            raise ValueError(
                f"a {self.type} parameter must carry unit {expected!r}, not {self.unit!r}"
            )
        if self.type is ParameterType.COUNT and self.value != int(self.value):
            raise ValueError("a count parameter must be a whole number")
        if self.type is ParameterType.BOOLEAN and self.value not in (0, 1):
            raise ValueError("a boolean parameter must be 0 or 1")
        return self


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


class CenterRectangle(StrictModel):
    id: Id
    type: Literal["center_rectangle"]
    center: Annotated[list[Scalar], Field(min_length=2, max_length=2)]
    width: Scalar
    height: Scalar


class Circle(StrictModel):
    id: Id
    type: Literal["circle"]
    center: Annotated[list[Scalar], Field(min_length=2, max_length=2)]
    radius: Scalar


SketchEntity = Annotated[Union[CenterRectangle, Circle], Field(discriminator="type")]


class Sketch(StrictModel):
    id: Id
    plane: SketchPlane
    entities: Annotated[list[SketchEntity], Field(min_length=1, max_length=64)]
    expected_closed_contours: Annotated[int, Field(ge=0, le=64)] = 1


class SolidExtrudeInputs(StrictModel):
    sketch: Sketch
    direction: Direction
    distance: Scalar
    source_body: ResultRef | None = None


class CutExtrudeInputs(StrictModel):
    sketch: Sketch
    direction: Direction
    through_all: bool = False
    distance: Scalar | None = None
    source_body: ResultRef | None = None

    @model_validator(mode="after")
    def validate_depth(self) -> "CutExtrudeInputs":
        if self.through_all and self.distance is not None:
            raise ValueError("a through-all cut must not also declare a distance")
        if not self.through_all and self.distance is None:
            raise ValueError("a cut must declare either through_all or a distance")
        return self


class SolidExtrudeFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.SOLID_EXTRUDE]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(max_length=64)] = Field(default_factory=list)
    inputs: SolidExtrudeInputs
    provenance: Provenance | None = None


class CutExtrudeFeature(StrictModel):
    id: Id
    type: Literal[FeatureType.CUT_EXTRUDE]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(max_length=64)] = Field(default_factory=list)
    inputs: CutExtrudeInputs
    provenance: Provenance | None = None


Feature = Annotated[Union[SolidExtrudeFeature, CutExtrudeFeature], Field(discriminator="type")]


class Size3(StrictModel):
    x: Annotated[float, Field(gt=0)]
    y: Annotated[float, Field(gt=0)]
    z: Annotated[float, Field(gt=0)]


class BodyCountExpectation(StrictModel):
    id: Id
    type: Literal["body_count"]
    value: Annotated[int, Field(ge=0, le=1000)]


class BoundingBoxExpectation(StrictModel):
    id: Id
    type: Literal["bounding_box"]
    size_mm: Size3
    tolerance_mm: Annotated[float, Field(ge=0, le=100)]


class ThroughHoleCountExpectation(StrictModel):
    id: Id
    type: Literal["through_hole_count"]
    value: Annotated[int, Field(ge=0, le=1000)]


Expectation = Annotated[
    Union[BodyCountExpectation, BoundingBoxExpectation, ThroughHoleCountExpectation],
    Field(discriminator="type"),
]


class DocumentHeader(StrictModel):
    units: Literal["mm"]
    part_type: PartType = PartType.SINGLE_PART
    coordinate_system: Literal["right_handed"] = "right_handed"
    name: Annotated[str | None, Field(max_length=100)] = None


class DocumentMetadata(StrictModel):
    """Who wrote this document, not which model wrote it.

    Model, reasoning effort and CLI version belong to the AI run that produced
    the document (ADR-017). Putting them here would change the canonical hash
    of an identical part whenever the model changed, which would make the hash
    useless for the one thing it is for.
    """

    generator: Annotated[str, Field(min_length=1, max_length=100)]
    generator_version: Annotated[str, Field(min_length=1, max_length=50)]
    prompt_version: Annotated[str | None, Field(max_length=50)] = None
    generation_attempt_id: Annotated[str | None, Field(max_length=64)] = None


class CadIrDocument(StrictModel):
    ir_schema: Literal[CAD_IR_SCHEMA] = Field(alias="schema", default=CAD_IR_SCHEMA)
    schema_version: Literal[CAD_IR_VERSION] = CAD_IR_VERSION
    document: DocumentHeader
    parameters: Annotated[list[Parameter], Field(max_length=500)] = Field(default_factory=list)
    reference_geometry: Annotated[list[dict[str, Any]], Field(max_length=0)] = Field(
        default_factory=list
    )
    features: Annotated[list[Feature], Field(min_length=1, max_length=200)]
    expectations: Annotated[list[Expectation], Field(max_length=100)] = Field(default_factory=list)
    metadata: DocumentMetadata

    def canonical_dict(self) -> dict[str, Any]:
        """The document as it is hashed and stored.

        Unset optional fields are dropped rather than serialised as null, so a
        document that omits a field and one that sets it to null are the same
        part and get the same hash.
        """
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    def canonical_json(self) -> str:
        return canonical_json(self.canonical_dict())

    def canonical_sha256(self) -> str:
        return sha256_of(self.canonical_json())


def canonical_json(value: dict[str, Any]) -> str:
    """Byte-stable JSON: sorted keys, no incidental whitespace, UTF-8.

    Two documents describing the same part must produce the same bytes, or the
    hash cannot be used to tell "this is the part we already built" from "this
    is a different part".
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def declared_version(value: dict[str, Any]) -> str | None:
    version = value.get("schema_version")
    return version if isinstance(version, str) else None
