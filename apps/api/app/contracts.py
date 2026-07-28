"""Versioned API and worker-protocol DTOs.

These models are deliberately data-only.  They form the boundary between the
public API, the local worker, and the later persistence layer; no worker or
client can mutate an order by sending a raw status value.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


API_VERSION = "v1"
WORKER_PROTOCOL_VERSION = "1.0"
RESOURCE_LEDGER_SCHEMA_VERSION = "1.0"
PRICING_PROFILE_SCHEMA_VERSION = "1.0"
CAPABILITY_MANIFEST_SCHEMA_VERSION = "1.0"
COST_FORMULA_VERSION = "1.0"


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
    LEDGER_EVENT_CONFLICT = "LEDGER_EVENT_CONFLICT"
    CODEX_MODEL_MISMATCH = "CODEX_MODEL_MISMATCH"
    CAPABILITY_NOT_SUPPORTED = "CAPABILITY_NOT_SUPPORTED"
    COST_SNAPSHOT_IMMUTABLE = "COST_SNAPSHOT_IMMUTABLE"
    PRICING_PROFILE_UNKNOWN = "PRICING_PROFILE_UNKNOWN"
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
    # Optional so a protocol-1.0 worker built before the capability registry
    # still authenticates and heartbeats. It simply will not be offered a job
    # that declares capability requirements.
    capability_manifest: WorkerCapabilityManifest | None = None


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
    capability_manifest: WorkerCapabilityManifest | None = None


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
    #: How the stored canonical document relates to what was submitted:
    #: both versions, both hashes and the normalizer version.
    lineage: dict[str, str] = Field(default_factory=dict)


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


# --------------------------------------------------------------------------
# Resource ledger (POSTMVP-001)
#
# The worker measures; it never prices.  Every counter is optional because an
# unavailable metric must stay null rather than be invented, and every present
# counter is non-negative so a malformed worker cannot inflate a job's cost.
# --------------------------------------------------------------------------

Count = Annotated[int, Field(ge=0)]
Millis = Annotated[int, Field(ge=0)]
Bytes = Annotated[int, Field(ge=0)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=4)]
Rate = Annotated[Decimal, Field(ge=0)]
Ratio = Annotated[Decimal, Field(ge=0, le=1)]


class ResourceEventType(StrEnum):
    AI_RUN = "AI_RUN"
    PROCESS_RUN = "PROCESS_RUN"
    CAD_SESSION = "CAD_SESSION"
    CAD_OPERATION = "CAD_OPERATION"
    CAD_REBUILD = "CAD_REBUILD"
    REPAIR_ITERATION = "REPAIR_ITERATION"
    EXPORT = "EXPORT"
    VALIDATION = "VALIDATION"
    PREVIEW_RENDER = "PREVIEW_RENDER"
    TRANSFER = "TRANSFER"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    WARNING = "WARNING"


class ResourceStage(StrEnum):
    IMAGE_PREPROCESSING = "IMAGE_PREPROCESSING"
    DRAWING_ANALYSIS = "DRAWING_ANALYSIS"
    CLARIFICATION = "CLARIFICATION"
    CAD_PLANNING = "CAD_PLANNING"
    CAD_IR_COMPILATION = "CAD_IR_COMPILATION"
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    SEMANTIC_VALIDATION = "SEMANTIC_VALIDATION"
    KOMPAS_STARTUP = "KOMPAS_STARTUP"
    DOCUMENT_BUILD = "DOCUMENT_BUILD"
    FEATURE_BUILD = "FEATURE_BUILD"
    REBUILD = "REBUILD"
    EXPORT = "EXPORT"
    GEOMETRY_VALIDATION = "GEOMETRY_VALIDATION"
    PREVIEW = "PREVIEW"
    ARTIFACT_UPLOAD = "ARTIFACT_UPLOAD"
    CLEANUP = "CLEANUP"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class AgentRole(StrEnum):
    DRAWING_EXTRACTION = "DRAWING_EXTRACTION"
    GEOMETRY_REASONING = "GEOMETRY_REASONING"
    CLARIFICATION = "CLARIFICATION"
    CAD_PLANNING = "CAD_PLANNING"
    CAD_IR_COMPILATION = "CAD_IR_COMPILATION"
    REPAIR = "REPAIR"
    FINAL_AUDIT = "FINAL_AUDIT"


class ReasoningEffort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ServiceTier(StrEnum):
    STANDARD = "standard"
    FAST = "fast"


class TokenSource(StrEnum):
    """How token counts were obtained; never guess, mark what was measured."""

    STRUCTURED = "STRUCTURED"
    SUMMARY = "SUMMARY"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class ModelObservationStatus(StrEnum):
    """How much is actually known about which model served a run."""

    UNKNOWN = "UNKNOWN"
    EXPLICIT_NOT_REPORTED = "EXPLICIT_NOT_REPORTED"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"


#: Statuses whose model attribution may be used for pricing. A MISMATCH is not
#: resolved in favour of either model, and an UNKNOWN never had one.
BILLABLE_MODEL_STATUSES = frozenset(
    {ModelObservationStatus.VERIFIED, ModelObservationStatus.EXPLICIT_NOT_REPORTED}
)


class AiUsage(StrictModel):
    """What was asked of Codex, what came back, and how much is confirmed.

    `requested_model` and `observed_model` are deliberately separate. Collapsed
    into one field, "we asked for Terra" becomes indistinguishable from "Terra
    is what ran", and only the second justifies charging Terra's weight.
    """

    requested_model: Annotated[str | None, Field(max_length=100)] = None
    observed_model: Annotated[str | None, Field(max_length=100)] = None
    requested_reasoning_effort: ReasoningEffort | None = None
    observed_reasoning_effort: ReasoningEffort | None = None
    model_observation_status: ModelObservationStatus = ModelObservationStatus.UNKNOWN
    routing_profile_version: Annotated[str | None, Field(max_length=50)] = None
    routing_rule_id: Annotated[str | None, Field(max_length=100)] = None
    service_tier: ServiceTier = ServiceTier.STANDARD
    cli_version: Annotated[str | None, Field(max_length=50)] = None
    prompt_version: Annotated[str | None, Field(max_length=50)] = None
    prompt_bundle_sha256: Annotated[str | None, Field(max_length=64)] = None
    provenance_sha256: Annotated[str | None, Field(max_length=64)] = None
    thread_id: Annotated[str | None, Field(max_length=100)] = None
    token_source: TokenSource = TokenSource.UNKNOWN
    input_tokens: Count | None = None
    cached_input_tokens: Count | None = None
    output_tokens: Count | None = None
    reasoning_tokens: Count | None = None
    total_tokens: Count | None = None

    @property
    def token_count_estimated(self) -> bool:
        return self.token_source is TokenSource.ESTIMATED

    @property
    def billable_model(self) -> str | None:
        """The model a cost may be attributed to, or None when unverifiable.

        Never falls back to a CLI default. Whatever the documentation says
        today, that default is external behaviour that can change without
        notice, and back-filling it would put a guess into a price.
        """
        if self.model_observation_status is ModelObservationStatus.VERIFIED:
            return self.observed_model
        if self.model_observation_status is ModelObservationStatus.EXPLICIT_NOT_REPORTED:
            return self.requested_model
        return None

    @model_validator(mode="after")
    def validate_observation_consistency(self) -> "AiUsage":
        status = self.model_observation_status
        if status is ModelObservationStatus.UNKNOWN:
            if self.requested_model is not None:
                raise ValueError("a requested model cannot be reported as UNKNOWN")
        elif self.requested_model is None:
            raise ValueError(f"{status} requires a requested_model")
        if status is ModelObservationStatus.VERIFIED and self.observed_model is None:
            raise ValueError("VERIFIED requires an observed_model")
        if status is ModelObservationStatus.MISMATCH and self.observed_model is None:
            raise ValueError("MISMATCH requires the observed_model that disagreed")
        if (
            status is ModelObservationStatus.EXPLICIT_NOT_REPORTED
            and self.observed_model is not None
        ):
            raise ValueError("EXPLICIT_NOT_REPORTED means the CLI reported no model")
        return self

    @model_validator(mode="after")
    def validate_token_shape(self) -> "AiUsage":
        if self.token_source is TokenSource.UNKNOWN and any(
            value is not None
            for value in (self.input_tokens, self.output_tokens, self.reasoning_tokens, self.total_tokens)
        ):
            raise ValueError("token counts require a token_source that is not UNKNOWN")
        if self.cached_input_tokens is not None and self.input_tokens is not None:
            if self.cached_input_tokens > self.input_tokens:
                raise ValueError("cached_input_tokens cannot exceed input_tokens")
        return self


class ProcessUsage(StrictModel):
    cpu_user_ms: Millis | None = None
    cpu_system_ms: Millis | None = None
    peak_memory_bytes: Bytes | None = None
    bytes_read: Bytes | None = None
    bytes_written: Bytes | None = None
    exit_code: int | None = None
    termination_reason: Annotated[str | None, Field(max_length=50)] = None
    retry_number: Count = 0


class CadUsage(StrictModel):
    operation_code: Annotated[str | None, Field(max_length=64)] = None
    operation_count: Count | None = None
    failed_feature_count: Count | None = None
    session_reuse_count: Count | None = None
    forced_termination: bool = False
    result_bytes: Bytes | None = None


EVENT_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9:._\-]{0,199}$"


class ResourceEvent(StrictModel):
    """One immutable measurement. `event_key` is the idempotency identity."""

    event_key: Annotated[str, Field(pattern=EVENT_KEY_PATTERN)]
    event_type: ResourceEventType
    stage: ResourceStage
    attempt_no: Annotated[int, Field(ge=1)] = 1
    agent_role: AgentRole | None = None
    started_at: datetime
    finished_at: datetime | None = None
    wall_ms: Millis | None = None
    success: bool
    failure_code: Annotated[str | None, Field(max_length=64)] = None
    ai: AiUsage | None = None
    process: ProcessUsage | None = None
    cad: CadUsage | None = None
    storage_byte_seconds: Annotated[Decimal | None, Field(ge=0)] = None
    human_minutes: Annotated[Decimal | None, Field(ge=0)] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_interval(self) -> "ResourceEvent":
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.success and self.failure_code is not None:
            raise ValueError("a successful event must not carry a failure_code")
        if self.ai is not None and self.event_type is not ResourceEventType.AI_RUN:
            raise ValueError("ai usage is only valid on an AI_RUN event")
        return self


class ResourceEventBatch(StrictModel):
    schema_version: Literal["1.0"] = RESOURCE_LEDGER_SCHEMA_VERSION
    job_id: UUID
    events: list[ResourceEvent] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_unique_keys(self) -> "ResourceEventBatch":
        keys = [event.event_key for event in self.events]
        if len(set(keys)) != len(keys):
            raise ValueError("event_key must be unique inside a batch")
        return self

    @model_validator(mode="after")
    def validate_model_provenance(self) -> "ResourceEventBatch":
        """Reject an AI run that does not say which model it asked for.

        Enforced on ingestion rather than on the model itself, so rows written
        before the routing profile existed still load. A new run without a
        named model is a worker that skipped routing, and its cost could never
        be attributed to anything.
        """
        unattributed = [
            event.event_key
            for event in self.events
            if event.event_type is ResourceEventType.AI_RUN
            and (event.ai is None or event.ai.requested_model is None)
        ]
        if unattributed:
            raise ValueError(
                "an AI run must record the model it requested: " + ", ".join(unattributed[:5])
            )
        return self


class ResourceEventBatchAck(StrictModel):
    job_id: UUID
    accepted: Count
    duplicates: Count


class JobIterationCounters(StrictModel):
    """Derived from the ledger; never reported directly by the worker."""

    analysis_runs: Count = 0
    clarification_cycles: Count = 0
    planning_runs: Count = 0
    cad_ir_generation_runs: Count = 0
    schema_repair_runs: Count = 0
    cad_build_attempts: Count = 0
    cad_feature_failures: Count = 0
    geometry_validation_runs: Count = 0
    repair_runs: Count = 0
    export_attempts: Count = 0
    human_review_minutes: Annotated[Decimal, Field(ge=0)] = Decimal(0)


# --------------------------------------------------------------------------
# Pricing profile (POSTMVP-002)
#
# Every rate lives here.  No rate, weight, tariff or margin may be hardcoded
# in the cost engine: a profile version is the only way a number enters a
# calculation, which is what makes a snapshot reproducible.
# --------------------------------------------------------------------------


class JobClass(StrEnum):
    AUTO_SIMPLE = "AUTO_SIMPLE"
    AUTO_STANDARD = "AUTO_STANDARD"
    AUTO_ADVANCED = "AUTO_ADVANCED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AiUsageWeights(StrictModel):
    cached_token: Rate
    output_token: Rate
    reasoning_token: Rate
    models: dict[str, Rate] = Field(default_factory=dict)
    default_model: Rate = Decimal(1)
    reasoning: dict[ReasoningEffort, Rate] = Field(default_factory=dict)
    service_tier: dict[ServiceTier, Rate] = Field(default_factory=dict)


class SubscriptionAllocation(StrictModel):
    """`ai_pool_amount / period_units` is the price of one internal AI unit.

    `period_units` is supplied by the caller from completed jobs in the
    period, so the engine stays a pure function of its arguments.
    """

    ai_pool_amount: Money
    period_units: Annotated[Decimal, Field(gt=0)]


class ShadowPrices(StrictModel):
    """API-equivalent prices. Not a bill; an estimate of a future migration."""

    input_per_million: Rate
    cached_input_per_million: Rate
    output_per_million: Rate


class WorkerRates(StrictModel):
    worker_hour_cost: Rate
    cad_license_hour_cost: Rate


class InfrastructureRates(StrictModel):
    vps_cost_per_job: Rate
    source_gb_day: Rate = Decimal(0)
    result_gb_day: Rate = Decimal(0)
    backup_gb_day: Rate = Decimal(0)
    egress_gb: Rate = Decimal(0)


class HumanRates(StrictModel):
    review_minute_cost: Rate


class PaymentRates(StrictModel):
    percent: Ratio = Decimal(0)
    fixed: Money = Decimal(0)


class ComplexityFees(StrictModel):
    included_analysis_runs: Count = 0
    analysis_retry_fee: Rate = Decimal(0)
    included_cad_attempts: Count = 0
    cad_retry_fee: Rate = Decimal(0)
    included_repair_runs: Count = 0
    repair_fee: Rate = Decimal(0)
    feature_point_price: Rate = Decimal(0)


class MarginPolicy(StrictModel):
    target_gross_margin: Annotated[Decimal, Field(ge=0, lt=1)]
    rounding_step: Annotated[Decimal, Field(gt=0)]
    minimum_price: dict[JobClass, Money] = Field(default_factory=dict)
    risk_percent: dict[JobClass, Rate] = Field(default_factory=dict)


class PricingConfig(StrictModel):
    ai_usage_weights: AiUsageWeights
    shadow_prices: ShadowPrices
    worker: WorkerRates
    infrastructure: InfrastructureRates
    human: HumanRates
    payment: PaymentRates
    complexity: ComplexityFees
    margin: MarginPolicy


class PricingProfile(StrictModel):
    schema_version: Literal["1.0"] = PRICING_PROFILE_SCHEMA_VERSION
    code: Annotated[str, Field(min_length=1, max_length=50)]
    version: Annotated[int, Field(ge=1)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    valid_from: datetime
    valid_to: datetime | None = None
    config: PricingConfig

    @model_validator(mode="after")
    def validate_validity_window(self) -> "PricingProfile":
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class AiCostStatus(StrEnum):
    """Whether a job's AI cost can be attributed to the models that served it."""

    ATTRIBUTED = "ATTRIBUTED"
    PARTIAL = "PARTIAL"
    UNVERIFIABLE = "UNVERIFIABLE"


class CostInputs(StrictModel):
    """Everything a cost calculation needs that is not in the ledger.

    Kept explicit so `calculate_cost` stays a pure function: period totals and
    the job class come from outside the job and must be passed in, never read
    from a database or a clock inside the engine.
    """

    job_class: JobClass
    subscription: SubscriptionAllocation
    advanced_feature_points: Annotated[Decimal, Field(ge=0)] = Decimal(0)


class JobCostBreakdown(StrictModel):
    formula_version: Literal["1.0"] = COST_FORMULA_VERSION
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    pricing_profile_code: str
    pricing_profile_version: int
    job_class: JobClass

    job_ai_units: Annotated[Decimal, Field(ge=0)]
    ai_allocated_cost: Money
    ai_shadow_cost: Money
    worker_cost: Money
    cad_license_cost: Money
    vps_cost: Money
    storage_cost: Money
    human_cost: Money
    payment_cost: Money
    resource_cost: Money

    complexity_surcharge: Money
    risk_reserve: Money
    margin_amount: Money
    final_price: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]

    billable_worker_seconds: Annotated[Decimal, Field(ge=0)]
    counters: JobIterationCounters
    token_coverage: dict[TokenSource, Count] = Field(default_factory=dict)
    #: How confidently each AI run's model could be identified. Carried into
    #: the snapshot so a reviewer can see what the AI figure rests on.
    model_attribution: dict[ModelObservationStatus, Count] = Field(default_factory=dict)
    ai_cost_status: AiCostStatus = AiCostStatus.ATTRIBUTED


class CostSnapshotStatus(StrEnum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"


class JobCostSnapshot(StrictModel):
    id: UUID
    job_id: UUID
    status: CostSnapshotStatus
    pricing_profile_code: str
    pricing_profile_version: int
    breakdown: JobCostBreakdown
    calculated_at: datetime


# --------------------------------------------------------------------------
# Capability registry (POSTMVP-003)
# --------------------------------------------------------------------------


class CapabilityStatus(StrEnum):
    UNSUPPORTED = "unsupported"
    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"
    DISABLED = "disabled"


#: Maturity ordering. `unsupported` and `disabled` are deliberately absent:
#: they are not low rungs on this ladder, they are "no", and no requirement can
#: ever be lax enough to accept them.
CAPABILITY_MATURITY: dict[CapabilityStatus, int] = {
    CapabilityStatus.EXPERIMENTAL: 1,
    CapabilityStatus.BETA: 2,
    CapabilityStatus.STABLE: 3,
}

#: A job is only leased to a worker that declares every required capability at
#: one of these statuses.  `experimental` deliberately does not qualify: it may
#: only be reached through an explicit opt-in job, never through normal claim.
LEASABLE_CAPABILITY_STATUSES = frozenset({CapabilityStatus.BETA, CapabilityStatus.STABLE})

CAPABILITY_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$"
CAPABILITY_VERSION_PATTERN = r"^\d+(\.\d+){0,2}$"

CapabilityKey = Annotated[str, Field(pattern=CAPABILITY_KEY_PATTERN)]
CapabilityVersion = Annotated[str, Field(pattern=CAPABILITY_VERSION_PATTERN)]


def capability_version_tuple(version: str) -> tuple[int, ...]:
    """Compare versions numerically; "1.10" is newer than "1.9", not older."""
    parts = tuple(int(part) for part in version.split("."))
    return parts + (0,) * (3 - len(parts))


class CapabilityDeclaration(StrictModel):
    """What a worker says about one capability."""

    status: CapabilityStatus
    version: CapabilityVersion = "1.0"

    @model_validator(mode="before")
    @classmethod
    def accept_bare_status(cls, value: Any) -> Any:
        # A worker may declare `"solid.revolve": "stable"` and mean version
        # 1.0. Requiring the long form everywhere would break every manifest
        # the moment versions were introduced.
        if isinstance(value, str):
            return {"status": value}
        return value


class CapabilityRequirement(StrictModel):
    """What a job needs before a worker may be handed it."""

    name: CapabilityKey
    #: Lowest maturity that satisfies this requirement.
    stability: CapabilityStatus = CapabilityStatus.BETA
    min_version: CapabilityVersion = "1.0"

    @model_validator(mode="after")
    def validate_requirable_stability(self) -> "CapabilityRequirement":
        if self.stability not in CAPABILITY_MATURITY:
            raise ValueError(f"{self.stability} is not a maturity level a job can require")
        return self

    def satisfied_by(self, declared: CapabilityDeclaration | None) -> bool:
        if declared is None or declared.status not in CAPABILITY_MATURITY:
            return False
        if CAPABILITY_MATURITY[declared.status] < CAPABILITY_MATURITY[self.stability]:
            return False
        return capability_version_tuple(declared.version) >= capability_version_tuple(self.min_version)


class WorkerCapabilityManifest(StrictModel):
    schema_version: Literal["1.0"] = CAPABILITY_MANIFEST_SCHEMA_VERSION
    worker_version: Annotated[str, Field(min_length=1, max_length=50)]
    kompas_version: Annotated[str | None, Field(max_length=50)] = None
    codex_cli_version: Annotated[str | None, Field(max_length=50)] = None
    cad_ir_versions: list[Annotated[str, Field(max_length=20)]] = Field(min_length=1, max_length=20)
    capabilities: dict[CapabilityKey, CapabilityDeclaration] = Field(min_length=1, max_length=500)

    def declared(self, name: str) -> CapabilityDeclaration | None:
        return self.capabilities.get(name)

    def supports(self, required: list[str]) -> list[str]:
        """Return the required capability keys this manifest cannot serve."""
        return [
            key
            for key in required
            if not CapabilityRequirement(name=key).satisfied_by(self.capabilities.get(key))
        ]


# --------------------------------------------------------------------------
# Scheduler diagnostics (POSTMVP-003A)
#
# Claimability is computed, never stored as an order status: it changes when a
# worker heartbeats, enrols, republishes a manifest or frees capacity, none of
# which are events on the order.  A persisted field would be stale the moment
# it was written.
# --------------------------------------------------------------------------


class ClaimabilityStatus(StrEnum):
    CLAIMABLE = "claimable"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    SETTLED = "settled"


class ClaimBlockerCode(StrEnum):
    NO_ONLINE_WORKERS = "NO_ONLINE_WORKERS"
    WORKER_MANIFEST_MISSING = "WORKER_MANIFEST_MISSING"
    CAPABILITY_NOT_SUPPORTED = "CAPABILITY_NOT_SUPPORTED"
    CAPABILITY_EXPERIMENTAL_ONLY = "CAPABILITY_EXPERIMENTAL_ONLY"
    CAPABILITY_VERSION_TOO_OLD = "CAPABILITY_VERSION_TOO_OLD"
    WORKER_VERSION_INCOMPATIBLE = "WORKER_VERSION_INCOMPATIBLE"
    WORKER_LEASE_CAPACITY_EXHAUSTED = "WORKER_LEASE_CAPACITY_EXHAUSTED"
    WORKER_HEARTBEAT_STALE = "WORKER_HEARTBEAT_STALE"
    JOB_REQUIREMENTS_INVALID = "JOB_REQUIREMENTS_INVALID"


class ClaimBlocker(StrictModel):
    code: ClaimBlockerCode
    worker_id: UUID | None = None
    worker_name: Annotated[str | None, Field(max_length=100)] = None
    capability: CapabilityKey | None = None
    detail: Annotated[str | None, Field(max_length=300)] = None


class JobClaimabilityReport(StrictModel):
    job_id: UUID
    claimability: ClaimabilityStatus
    required_capabilities: list[CapabilityRequirement]
    online_workers: Count
    compatible_workers: Count
    blockers: list[ClaimBlocker]
    evaluated_at: datetime
    #: Non-technical sentence safe to show an end user.
    summary: Annotated[str, Field(max_length=300)]


# WorkerCapabilityManifest is declared after the worker protocol DTOs that
# reference it, so those two models are completed once it exists.
WorkerClaimRequest.model_rebuild()
WorkerHeartbeatRequest.model_rebuild()
