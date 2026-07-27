"""Versioned API and worker-protocol DTOs.

These models are deliberately data-only.  They form the boundary between the
public API, the local worker, and the later persistence layer; no worker or
client can mutate an order by sending a raw status value.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


API_VERSION = "v1"
WORKER_PROTOCOL_VERSION = "1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderStatus(StrEnum):
    DRAFT = "DRAFT"
    UPLOADED = "UPLOADED"
    INPUT_VALIDATION = "INPUT_VALIDATION"
    WAITING_FOR_LOCAL_WORKER = "WAITING_FOR_LOCAL_WORKER"
    DRAWING_ANALYSIS = "DRAWING_ANALYSIS"
    WAITING_FOR_USER_ANSWERS = "WAITING_FOR_USER_ANSWERS"
    PLAN_READY = "PLAN_READY"
    WAITING_FOR_PLAN_APPROVAL = "WAITING_FOR_PLAN_APPROVAL"
    QUEUED_FOR_CAD = "QUEUED_FOR_CAD"
    CAD_BUILDING = "CAD_BUILDING"
    CAD_VALIDATION = "CAD_VALIDATION"
    AUTO_REPAIR = "AUTO_REPAIR"
    READY = "READY"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class JobType(StrEnum):
    ANALYZE_DRAWING = "ANALYZE_DRAWING"
    COMPILE_CAD_IR = "COMPILE_CAD_IR"
    BUILD_CAD = "BUILD_CAD"
    VALIDATE_CAD = "VALIDATE_CAD"


class WorkerCapability(StrEnum):
    AI_DRAWING = "AI_DRAWING"
    KOMPAS_BUILD = "KOMPAS_BUILD"


class ErrorCode(StrEnum):
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    ORDER_VERSION_CONFLICT = "ORDER_VERSION_CONFLICT"
    UNKNOWN_PROTOCOL_VERSION = "UNKNOWN_PROTOCOL_VERSION"
    ENROLLMENT_REJECTED = "ENROLLMENT_REJECTED"
    WORKER_AUTH_FAILED = "WORKER_AUTH_FAILED"
    UNKNOWN_ENUM_VALUE = "UNKNOWN_ENUM_VALUE"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    CONTOUR_NOT_CLOSED = "CONTOUR_NOT_CLOSED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    COMPLETED = "COMPLETED"


class OrderSnapshot(StrictModel):
    id: UUID
    status: OrderStatus
    version: Annotated[int, Field(ge=0)]
    updated_at: datetime


class TransitionOrderRequest(StrictModel):
    expected_version: Annotated[int, Field(ge=0)]
    target_status: OrderStatus
    reason: Annotated[str | None, Field(max_length=500)] = None


class ProblemDetails(StrictModel):
    type: str
    title: str
    status: int
    code: ErrorCode
    request_id: str
    detail: str | None = None


class WorkerClaimRequest(StrictModel):
    protocol_version: Literal["1.0"]
    worker_id: UUID
    capabilities: list[WorkerCapability] = Field(min_length=1)
    supported_cad_ir: list[str] = Field(min_length=1)
    available_slots: Annotated[int, Field(ge=0, le=10)]


class JobPolicy(StrictModel):
    model_route: str
    max_runtime_seconds: Annotated[int, Field(gt=0, le=3600)]


class ClaimedJob(StrictModel):
    job_id: UUID
    order_id: UUID
    job_type: JobType
    attempt: Annotated[int, Field(ge=1)]
    idempotency_key: str
    lease_expires_at: datetime
    manifest_url: str
    required_output_schema: str
    policy: JobPolicy


class WorkerClaimResponse(StrictModel):
    protocol_version: Literal["1.0"]
    job: ClaimedJob | None
    retry_after_seconds: Annotated[int | None, Field(ge=1, le=300)] = None

    @model_validator(mode="after")
    def validate_claim_shape(self) -> "WorkerClaimResponse":
        if self.job is None and self.retry_after_seconds is None:
            raise ValueError("an empty claim response requires retry_after_seconds")
        if self.job is not None and self.retry_after_seconds is not None:
            raise ValueError("a claimed job must not include retry_after_seconds")
        return self


class WorkerRegistrationRequest(StrictModel):
    enrollment_token: str = Field(min_length=32, max_length=512, repr=False)
    worker_name: str = Field(min_length=1, max_length=100)
    app_version: str = Field(min_length=1, max_length=50)


class WorkerRegistrationResponse(StrictModel):
    worker_id: UUID
    credential: str = Field(repr=False)
    protocol_version: Literal["1.0"] = WORKER_PROTOCOL_VERSION


class WorkerHeartbeatRequest(StrictModel):
    worker_id: UUID
    capabilities: list[WorkerCapability] = Field(min_length=1)
    supported_cad_ir: list[str] = Field(min_length=1)
    available_slots: int = Field(ge=0, le=10)


class JobHeartbeatRequest(StrictModel):
    job_id: UUID
    stage: OrderStatus
    progress: Annotated[float, Field(ge=0, le=1)]
    message_code: str
    safe_details: dict[str, Any] = Field(default_factory=dict)


class JobError(StrictModel):
    code: ErrorCode
    safe_message: Annotated[str, Field(min_length=1, max_length=500)]
    retryable: bool
    requires_user_input: bool
    diagnostic_fingerprint: str


class Artifact(StrictModel):
    type: str
    object_key: str
    sha256: str
    size_bytes: Annotated[int, Field(ge=0)]


class JobCompletionRequest(StrictModel):
    job_id: UUID
    idempotency_key: str
    result: dict[str, Any]
    artifacts: list[Artifact]


class JobCompletionAck(StrictModel):
    job_id: UUID
    idempotent_replay: bool


class ManualCadJobRequest(StrictModel):
    cad_ir: dict[str, Any]
    requested_formats: list[Literal["m3d", "step", "stl"]] = Field(default_factory=lambda: ["m3d"])


class ManualCadJobResponse(StrictModel):
    order_id: UUID
    job_id: UUID
    status: Literal["WAITING_FOR_LOCAL_WORKER"]
    cad_ir_sha256: str


class ArtifactUploadResponse(StrictModel):
    type: str
    object_key: str
    sha256: str
    size_bytes: int


class DrawingJobResponse(StrictModel):
    order_id: UUID
    job_id: UUID
    status: Literal["WAITING_FOR_LOCAL_WORKER"]
    drawing_sha256: str


class ClarificationAnswer(StrictModel):
    question_id: str = Field(min_length=1, max_length=100)
    value: float
    unit: Literal["mm"]


class DrawingAnswersRequest(StrictModel):
    answers: list[ClarificationAnswer] = Field(min_length=1, max_length=10)
