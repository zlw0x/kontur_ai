"""CAD-IR: the canonical form.

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

from pydantic import Field, model_validator

from .base import (  # re-exported: this is still the one place to read the document from
    ID_PATTERN,
    FeatureResult,
    FeatureType,
    Id,
    ParameterRef,
    Provenance,
    ResultKind,
    ResultRef,
    Scalar,
    SourceRegion,
    StrictModel,
)
from .blend import (  # re-exported alongside the document
    ChamferFeature,
    ChamferInputs,
    FilletFeature,
    FilletInputs,
)
from .boolean import (  # re-exported alongside the document
    BooleanFeature,
    BooleanInputs,
    BooleanOp,
)
from .constraints import (  # re-exported alongside the document
    ConstraintKind,
    DimensionKind,
    DrivingDimension,
    SketchConstraint,
)
from .pattern import (  # re-exported alongside the document
    CircularPattern,
    LinearPattern,
    MirrorPattern,
    PatternFeature,
    PatternInputs,
    instance_count,
)
from .selectors import (  # re-exported alongside the document
    Measurement,
    SurfaceType,
)
from .revolve import (  # re-exported alongside the document
    CutRevolveFeature,
    RevolveAxis,
    RevolveAxisSpec,
    RevolveByConstructionLine,
    RevolveByPoints,
    RevolveInputs,
    SolidRevolveFeature,
)
from .shell import ShellDirection, ShellFeature, ShellInputs  # re-exported
from .sketch import DatumPlaneOffsetInputs, Sketch

CAD_IR_SCHEMA = "cad-ai/cad-ir"
CAD_IR_VERSION = "1.8"

#: Versions this build can consume. A document declaring anything else is
#: rejected before its features are read.
SUPPORTED_VERSIONS: tuple[str, ...] = ("1.8",)

#: Versions the normalizer can lift into the canonical form.
#:
#: Older versions are migratable rather than supported, so one shape reaches the
#: adapter. A document declaring an old version while using a new entity would
#: otherwise be accepted — and a document lying about its version is the start of
#: a compatibility problem, not the end of one.
MIGRATABLE_VERSIONS: tuple[str, ...] = (
    "0.1.0",
    "1.1",
    "1.2",
    "1.3",
    "1.4",
    "1.5",
    "1.6",
    "1.7",
)

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


class Direction(StrEnum):
    PLUS_X = "+X"
    MINUS_X = "-X"
    PLUS_Y = "+Y"
    MINUS_Y = "-Y"
    PLUS_Z = "+Z"
    MINUS_Z = "-Z"


class PartType(StrEnum):
    SINGLE_PART = "single_part"


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


class SolidExtrudeInputs(StrictModel):
    sketch: Sketch
    direction: Direction
    distance: Scalar
    #: Which body this joins. Nothing means the one being built — the behaviour every
    #: document before 1.7 relies on and the one a boss on a plate wants.
    source_body: ResultRef | None = None
    #: A separate lump of material rather than an addition to one. The feature must
    #: then name the body it makes, because a body nothing can name is a body no
    #: selector and no boolean can reach.
    new_body: bool = False

    @model_validator(mode="after")
    def validate_body(self) -> "SolidExtrudeInputs":
        if self.new_body and self.source_body is not None:
            raise ValueError(
                "a feature either starts a new body or adds to an existing one, not both"
            )
        return self


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


class DatumPlaneOffsetFeature(StrictModel):
    """An auxiliary plane, so a later sketch has somewhere to sit.

    A feature rather than a `reference_geometry` entry because it depends on
    other features and other features depend on it, and the dependency graph is
    the one place that is already stated and checked.
    """

    id: Id
    type: Literal[FeatureType.DATUM_PLANE_OFFSET]
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    produces: Annotated[list[FeatureResult], Field(min_length=1, max_length=1)]
    inputs: DatumPlaneOffsetInputs
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def validate_result_kind(self) -> "DatumPlaneOffsetFeature":
        if self.produces[0].kind is not ResultKind.PLANE:
            raise ValueError("a datum plane feature produces a plane")
        return self


Feature = Annotated[
    Union[
        SolidExtrudeFeature,
        CutExtrudeFeature,
        SolidRevolveFeature,
        CutRevolveFeature,
        DatumPlaneOffsetFeature,
        FilletFeature,
        ChamferFeature,
        PatternFeature,
        BooleanFeature,
        ShellFeature,
    ],
    Field(discriminator="type"),
]


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


class SurfaceFaceCountExpectation(StrictModel):
    """How many faces of one surface kind the finished solid has.

    The check a blend needs, and the reason it is worth adding a fourth
    expectation type. A fillet is invisible to every other check in the document:
    the bounding box of a plate with rounded corners is the bounding box of the
    plate, the body count is one either way, and a hole count knows nothing about
    corners. So a fillet that quietly did not happen — or happened at the wrong
    radius — passes everything, and the only thing that distinguishes it is that
    four cylindrical faces of that radius are missing from the solid.

    Stated by the document and measured off the reopened STEP, like every other
    expectation, and for the same reason (ADR-018): a count derived from the plan
    that built the geometry would agree with it about anything they both got wrong.
    """

    id: Id
    type: Literal["surface_face_count"]
    surface: SurfaceType
    #: The radius those faces must have, when it is a curved surface and the
    #: document knows it. A fillet's radius is the one number the count alone
    #: cannot check.
    radius_mm: Measurement | None = None
    value: Annotated[int, Field(ge=0, le=1000)]


Expectation = Annotated[
    Union[
        BodyCountExpectation,
        BoundingBoxExpectation,
        ThroughHoleCountExpectation,
        SurfaceFaceCountExpectation,
    ],
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
