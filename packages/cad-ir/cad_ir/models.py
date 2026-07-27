from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParameterStatus(StrEnum):
    CONFIRMED = "confirmed"
    USER_CONFIRMED = "user_confirmed"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    UNRESOLVED = "unresolved"


class FeatureType(StrEnum):
    EXTRUDE_ADD = "extrude_add"
    EXTRUDE_CUT = "extrude_cut"
    REVOLVE_ADD = "revolve_add"
    REVOLVE_CUT = "revolve_cut"
    HOLE = "hole"
    LINEAR_PATTERN = "linear_pattern"
    CIRCULAR_PATTERN = "circular_pattern"
    FILLET = "fillet"
    CHAMFER = "chamfer"
    MIRROR = "mirror"


class Part(StrictModel):
    name: str
    units: str
    body_mode: str


class Parameter(StrictModel):
    id: str
    name: str | None = None
    value: float
    unit: str
    status: ParameterStatus
    confidence: float
    source: dict[str, Any]


class Feature(StrictModel):
    id: str
    type: FeatureType
    enabled: bool
    depends_on: list[str]
    inputs: dict[str, Any]
    semantic_outputs: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class Invariant(StrictModel):
    id: str
    type: str
    expected: Any
    tolerance: float | None = None
    severity: str


class CadIrDocument(StrictModel):
    schema_version: str
    part: Part
    parameters: list[Parameter]
    features: list[Feature]
    expected_invariants: list[Invariant]
    assumptions: list[dict[str, Any]]
    unresolved: list[dict[str, Any]]
    provenance: dict[str, Any] = Field(default_factory=dict)
