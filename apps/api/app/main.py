import logging
import json
import hashlib
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from cad_ir import CadIrValidationError
from cad_ir.canonical import CAD_IR_VERSION, DocumentMetadata
from cad_ir.normalizer import normalize as normalize_cad_ir

from .config import settings
from .database import Base, create_session_factory
from .ledger.service import LedgerError, ResourceLedgerService
from .contracts import (
    API_VERSION,
    JobClaimabilityReport,
    ResourceEvent,
    ResourceEventBatch,
    ResourceEventType,
    ResourceStage,
    ResourceEventBatchAck,
    WorkerClaimRequest,
    WorkerClaimResponse,
    JobCompletionAck,
    JobCompletionRequest,
    JobHeartbeatRequest,
    WorkerHeartbeatRequest,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    ArtifactUploadResponse,
    ManualCadJobRequest,
    ManualCadJobResponse,
    OrderSnapshot,
    ProblemDetails,
    TransitionOrderRequest,
    DrawingJobResponse,
    DrawingAnswersRequest,
)
from .workers.artifact_store import ArtifactIntegrityError, LocalArtifactStore
from .workers.capabilities import required_capability_keys
from .workers.diagnostics import SchedulerDiagnostics
from .workers.protocol import (
    InMemoryWorkerRepository,
    Job,
    WorkerProtocolError,
    WorkerProtocolService,
)
from .contracts import JobType, OrderStatus, WorkerCapability
from .orders.state_machine import (
    OrderRecord,
    OrderStateService,
    OrderTransitionError,
)
from .workers.sql_protocol import SqlWorkerProtocolService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("cad-ai-api")

#: The files a finished build owes a customer (ADR-023, `AGENTS.md` rule 11).
#:
#: Named here rather than derived from the worker's manifest because these are a
#: statement about the *product*, not about an engine: STEP is the exact geometry
#: a customer takes into any CAD system and STL is the mesh. That is the whole
#: difference from what stood here until ENGINE-MIG-008, which was `M3D` — a
#: KOMPAS-native format, written into the definition of a finished job, which no
#: engine has produced since the migration and which therefore made every
#: `BUILD_CAD` completion fail with 409.
DELIVERED_MODEL_ARTIFACTS: tuple[str, ...] = ("STEP", "STL")

def build_worker_protocol():
    if settings.worker_repository_mode == "memory":
        return WorkerProtocolService(InMemoryWorkerRepository(), settings.worker_enrollment_token)
    _, sessions = create_session_factory(settings.database_url)
    return SqlWorkerProtocolService(sessions, settings.worker_enrollment_token)


def build_resource_ledger():
    """The ledger is always SQL-backed; `memory` mode gets a disposable one.

    Measurements must survive an API restart in production, and the isolated
    API tests still need real UNIQUE-constraint behaviour rather than a fake.
    """
    if settings.worker_repository_mode == "memory":
        engine, sessions = create_session_factory("sqlite://")
        Base.metadata.create_all(engine)
        return ResourceLedgerService(sessions)
    _, sessions = create_session_factory(settings.database_url)
    return ResourceLedgerService(sessions)


app = FastAPI(
    title="CAD AI Service API",
    version="1.0.0",
    responses={409: {"model": ProblemDetails, "description": "Conflict"}},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([
        settings.web_origin,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "x-manual-api-token", "x-request-id"],
)
worker_protocol = build_worker_protocol()
resource_ledger = build_resource_ledger()
artifact_store = LocalArtifactStore(settings.artifact_store_root, settings.max_artifact_bytes)
order_state_service = OrderStateService()
order_records: dict[uuid.UUID, OrderRecord] = {}
drawing_orders: dict[uuid.UUID, dict] = {}


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logger.info(json.dumps({"event": "http_request", "request_id": request_id, "method": request.method, "path": request.url.path, "status": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 2)}))
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@app.get("/api/v1/health")
def api_health() -> dict[str, str]:
    return health()


@app.post("/api/v1/orders/{order_id}/transition", response_model=OrderSnapshot)
def transition_order(
    order_id: uuid.UUID,
    request: TransitionOrderRequest,
    x_manual_api_token: str | None = Header(default=None),
) -> OrderSnapshot:
    authenticated_manual_api(x_manual_api_token)
    order = order_records.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order was not found")
    updated, _ = order_state_service.transition(
        order,
        target=request.target_status,
        expected_version=request.expected_version,
        reason=request.reason,
    )
    order_records[order_id] = updated
    return OrderSnapshot(
        id=updated.id,
        status=updated.status,
        version=updated.version,
        updated_at=updated.updated_at,
    )


def scheduler_diagnostics() -> SchedulerDiagnostics:
    """Built per call so it always reads the protocol currently in use.

    Holding a module-level instance would pin the protocol captured at import
    time, which silently diverges whenever it is replaced.
    """
    return SchedulerDiagnostics(worker_protocol)


def authenticated_worker(worker_id, authorization: str | None):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="worker credential is required")
    return worker_protocol.authenticate(worker_id, authorization.removeprefix("Bearer "))


def authenticated_bearer(authorization: str | None):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="worker credential is required")
    return worker_protocol.authenticate_credential(authorization.removeprefix("Bearer "))


def authenticated_manual_api(token: str | None) -> None:
    if token is None or not secrets.compare_digest(token, settings.manual_api_token):
        raise HTTPException(status_code=401, detail="manual API token is required")


@app.post("/api/v1/workers/register", response_model=WorkerRegistrationResponse, status_code=201)
def register_worker(request: WorkerRegistrationRequest) -> WorkerRegistrationResponse:
    worker, credential = worker_protocol.register(
        enrollment_token=request.enrollment_token, worker_name=request.worker_name, app_version=request.app_version
    )
    return WorkerRegistrationResponse(worker_id=worker.id, credential=credential)


@app.post("/api/v1/workers/heartbeat", status_code=204)
def worker_heartbeat(request: WorkerHeartbeatRequest, authorization: str | None = Header(default=None)) -> None:
    worker = authenticated_worker(request.worker_id, authorization)
    worker_protocol.heartbeat(
        worker,
        request.capabilities,
        request.supported_cad_ir,
        request.available_slots,
        request.capability_manifest,
    )


@app.post("/api/v1/workers/claim", response_model=WorkerClaimResponse)
def claim_worker_job(request: WorkerClaimRequest, authorization: str | None = Header(default=None)) -> WorkerClaimResponse:
    worker = authenticated_worker(request.worker_id, authorization)
    worker_protocol.heartbeat(
        worker,
        request.capabilities,
        request.supported_cad_ir,
        request.available_slots,
        request.capability_manifest,
    )
    job = worker_protocol.claim(worker) if request.available_slots else None
    if job is None:
        return WorkerClaimResponse(protocol_version="1.0", job=None, retry_after_seconds=5)
    return WorkerClaimResponse(protocol_version="1.0", job={
        "job_id": job.id, "order_id": job.order_id, "job_type": job.job_type, "attempt": job.attempt,
        "idempotency_key": job.idempotency_key, "lease_expires_at": job.lease_expires_at,
        "manifest_url": f"/api/v1/workers/jobs/{job.id}/manifest",
        "required_output_schema": f"cad-ir/{job.required_cad_ir}",
        "policy": {"model_route": "not-applicable", "max_runtime_seconds": 900},
    })


@app.post("/api/v1/workers/jobs/{job_id}/heartbeat", status_code=204)
def renew_job_lease(job_id: uuid.UUID, request: JobHeartbeatRequest, authorization: str | None = Header(default=None)) -> None:
    if request.job_id != job_id:
        raise HTTPException(status_code=400, detail="job_id path/body mismatch")
    worker = authenticated_bearer(authorization)
    worker_protocol.renew_lease(worker, job_id)


@app.post("/api/v1/manual/cad-jobs", response_model=ManualCadJobResponse, status_code=201)
def create_manual_cad_job(
    request: ManualCadJobRequest,
    x_manual_api_token: str | None = Header(default=None),
) -> ManualCadJobResponse:
    authenticated_manual_api(x_manual_api_token)
    # A submission may still be written against 0.1.0. It is lifted into the
    # canonical form here so the worker only ever sees one shape, and the
    # lineage records both ends of that translation.
    started = time.perf_counter()
    try:
        normalized = normalize_cad_ir(
            request.cad_ir,
            metadata=DocumentMetadata(generator="manual-api", generator_version=API_VERSION),
        )
    except CadIrValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CAD_IR_INVALID",
                "issues": [
                    {"code": issue.code, "path": issue.path, "message": issue.message}
                    for issue in error.issues[:50]
                ],
            },
        ) from error
    normalization_ms = (time.perf_counter() - started) * 1000
    order_id, job_id = uuid.uuid4(), uuid.uuid4()
    order_records[order_id] = OrderRecord(
        order_id,
        OrderStatus.WAITING_FOR_LOCAL_WORKER,
        0,
        datetime.now(timezone.utc),
    )
    stored = artifact_store.put_cad_ir(job_id, json.loads(normalized.canonical_json))
    idempotency_key = "sha256:" + hashlib.sha256(
        f"{order_id}:{stored.sha256}".encode()
    ).hexdigest()
    worker_protocol.enqueue(
        Job(
            job_id,
            order_id,
            JobType.BUILD_CAD,
            idempotency_key,
            {WorkerCapability.CAD_BUILD},
            normalized.document.schema_version,
            required_capability_keys(JobType.BUILD_CAD),
        )
    )
    _record_normalization(job_id, normalized, normalization_ms)
    return ManualCadJobResponse(
        order_id=order_id,
        job_id=job_id,
        status="WAITING_FOR_LOCAL_WORKER",
        cad_ir_sha256=stored.sha256,
        lineage=normalized.lineage.as_dict(),
    )


def _record_normalization(job_id: uuid.UUID, normalized, elapsed_ms: float) -> None:
    """Normalisation is machine time spent on the job, so it goes in the ledger.

    Recorded in-process rather than through the worker endpoint: no worker
    holds a lease at this point, and the work happened here.
    """
    finished = datetime.now(timezone.utc)
    try:
        resource_ledger.record(
            job_id,
            [
                ResourceEvent(
                    event_key=f"job:{job_id}:attempt:1:normalize:cad_ir",
                    event_type=ResourceEventType.PROCESS_RUN,
                    stage=ResourceStage.SCHEMA_VALIDATION,
                    started_at=finished - timedelta(milliseconds=elapsed_ms),
                    finished_at=finished,
                    wall_ms=int(elapsed_ms),
                    success=True,
                    metadata=normalized.lineage.as_dict(),
                )
            ],
        )
    except Exception:
        # Deliberately broad. By this point the CAD-IR is stored and the job is
        # queued; losing an accounting row is strictly better than failing a
        # request that has already had its effect. A database outage lands here
        # as readily as a rejected event, and both are logged rather than
        # raised.
        logger.exception("failed to record CAD-IR normalization")


@app.post("/api/v1/drawing-jobs", response_model=DrawingJobResponse, status_code=201)
async def create_drawing_job(
    request: Request,
    content_type: str | None = Header(default=None),
    x_manual_api_token: str | None = Header(default=None),
) -> DrawingJobResponse:
    authenticated_manual_api(x_manual_api_token)
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    extension = { "image/png": ".png", "image/jpeg": ".jpg" }.get(normalized_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="drawing must be PNG or JPEG")
    payload = await request.body()
    if not (
        (extension == ".png" and payload.startswith(b"\x89PNG\r\n\x1a\n"))
        or (extension == ".jpg" and payload.startswith(b"\xff\xd8"))
    ):
        raise HTTPException(status_code=422, detail="drawing content does not match content type")
    order_id, job_id = uuid.uuid4(), uuid.uuid4()
    stored = artifact_store.put_drawing(job_id, payload, extension)
    order_records[order_id] = OrderRecord(
        order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER, 0, datetime.now(timezone.utc)
    )
    drawing_orders[order_id] = {"latest_job_id": job_id, "source_job_id": job_id, "round": 0}
    artifact_store.put_drawing_tracking(order_id, job_id, job_id, 0)
    worker_protocol.enqueue(Job(
        job_id,
        order_id,
        JobType.ANALYZE_DRAWING,
        "sha256:" + hashlib.sha256(f"{order_id}:{stored.sha256}:0".encode()).hexdigest(),
        {WorkerCapability.AI_DRAWING, WorkerCapability.CAD_BUILD},
        CAD_IR_VERSION,
        required_capability_keys(JobType.ANALYZE_DRAWING),
    ))
    return DrawingJobResponse(
        order_id=order_id,
        job_id=job_id,
        status="WAITING_FOR_LOCAL_WORKER",
        drawing_sha256=stored.sha256,
    )


@app.get("/api/v1/drawing-jobs/{order_id}")
def get_drawing_job(
    order_id: uuid.UUID,
    x_manual_api_token: str | None = Header(default=None),
) -> dict:
    authenticated_manual_api(x_manual_api_token)
    tracking = drawing_orders.get(order_id)
    if tracking is None:
        try:
            tracking = artifact_store.drawing_tracking(order_id)
            drawing_orders[order_id] = tracking
        except ArtifactIntegrityError:
            pass
    if tracking is None:
        raise HTTPException(status_code=404, detail="drawing order was not found")
    job_id = tracking["latest_job_id"]
    job = worker_protocol.get_job(job_id)
    artifacts = worker_protocol.get_artifacts(job_id)
    questions = []
    if any(item["type"].upper() == "CLARIFICATION_QUESTIONS" for item in artifacts):
        try:
            questions = json.loads(
                artifact_store.artifact(job_id, "CLARIFICATION_QUESTIONS").path.read_text(encoding="utf-8")
            ).get("questions", [])
        except (ArtifactIntegrityError, json.JSONDecodeError):
            questions = []
    present = {item["type"].upper() for item in artifacts}
    has_model = all(kind in present for kind in DELIVERED_MODEL_ARTIFACTS)
    status = (
        "READY" if has_model
        else "WAITING_FOR_USER_ANSWERS" if questions
        else job.status.value
    )
    # Only while the order is genuinely waiting on the scheduler. Once it is
    # ready or the user has been asked something, the ball is not here.
    waiting_reason = (
        scheduler_diagnostics().report(job).summary
        if status not in ("READY", "WAITING_FOR_USER_ANSWERS")
        else None
    )
    return {
        "order_id": str(order_id),
        "job_id": str(job_id),
        "status": status,
        "waiting_reason": waiting_reason,
        "round": tracking["round"],
        "questions": questions,
        "artifacts": [
            {
                **artifact,
                "download_url": f"/api/v1/manual/cad-jobs/{job_id}/artifacts/{artifact['type']}",
            }
            for artifact in artifacts
        ],
    }


@app.post("/api/v1/drawing-jobs/{order_id}/answers", response_model=DrawingJobResponse, status_code=201)
def answer_drawing_questions(
    order_id: uuid.UUID,
    request: DrawingAnswersRequest,
    x_manual_api_token: str | None = Header(default=None),
) -> DrawingJobResponse:
    authenticated_manual_api(x_manual_api_token)
    tracking = drawing_orders.get(order_id)
    if tracking is None:
        try:
            tracking = artifact_store.drawing_tracking(order_id)
            drawing_orders[order_id] = tracking
        except ArtifactIntegrityError:
            pass
    if tracking is None:
        raise HTTPException(status_code=404, detail="drawing order was not found")
    prior_job_id = tracking["latest_job_id"]
    try:
        question_document = json.loads(
            artifact_store.artifact(prior_job_id, "CLARIFICATION_QUESTIONS").path.read_text(encoding="utf-8")
        )
    except (ArtifactIntegrityError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=409, detail="order is not waiting for answers") from error
    expected_ids = {item["id"] for item in question_document.get("questions", [])}
    supplied_ids = {item.question_id for item in request.answers}
    if supplied_ids != expected_ids:
        raise HTTPException(status_code=422, detail="answers must match the current question set")
    if tracking["round"] >= 3:
        raise HTTPException(status_code=409, detail="clarification round limit reached")
    job_id = uuid.uuid4()
    source = artifact_store.drawing(tracking["source_job_id"])
    stored = artifact_store.put_drawing(job_id, source.path.read_bytes(), source.path.suffix.lower())
    artifact_store.put_answers(job_id, {
        "schema_version": "0.1.0",
        "answers": [item.model_dump() for item in request.answers],
    })
    round_number = tracking["round"] + 1
    worker_protocol.enqueue(Job(
        job_id,
        order_id,
        JobType.ANALYZE_DRAWING,
        "sha256:" + hashlib.sha256(
            f"{order_id}:{stored.sha256}:{round_number}:{request.model_dump_json()}".encode()
        ).hexdigest(),
        {WorkerCapability.AI_DRAWING, WorkerCapability.CAD_BUILD},
        CAD_IR_VERSION,
        required_capability_keys(JobType.ANALYZE_DRAWING),
    ))
    tracking.update(latest_job_id=job_id, round=round_number)
    artifact_store.put_drawing_tracking(
        order_id,
        tracking["latest_job_id"],
        tracking["source_job_id"],
        tracking["round"],
    )
    return DrawingJobResponse(
        order_id=order_id,
        job_id=job_id,
        status="WAITING_FOR_LOCAL_WORKER",
        drawing_sha256=stored.sha256,
    )


@app.get("/api/v1/manual/cad-jobs/{job_id}")
def get_manual_cad_job(
    job_id: uuid.UUID,
    x_manual_api_token: str | None = Header(default=None),
) -> dict:
    authenticated_manual_api(x_manual_api_token)
    job = worker_protocol.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job was not found")
    artifacts = worker_protocol.get_artifacts(job_id)
    return {
        "job_id": str(job.id),
        "order_id": str(job.order_id),
        "status": job.status.value,
        "attempt": job.attempt,
        "artifacts": [
            {
                **artifact,
                "download_url": f"/api/v1/manual/cad-jobs/{job_id}/artifacts/{artifact['type']}",
            }
            for artifact in artifacts
        ],
    }


@app.get(
    "/api/v1/manual/cad-jobs/{job_id}/claimability",
    response_model=JobClaimabilityReport,
)
def get_job_claimability(
    job_id: uuid.UUID,
    x_manual_api_token: str | None = Header(default=None),
) -> JobClaimabilityReport:
    """Explain whether a job can currently be leased, and if not, why.

    Read-only and outside the claim transaction: diagnosing a job must never
    be able to change whether it is picked up.
    """
    authenticated_manual_api(x_manual_api_token)
    job = worker_protocol.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job was not found")
    return scheduler_diagnostics().report(job)


@app.get("/api/v1/manual/cad-jobs/{job_id}/artifacts/{artifact_type}")
def download_manual_artifact(
    job_id: uuid.UUID,
    artifact_type: str,
    x_manual_api_token: str | None = Header(default=None),
) -> FileResponse:
    authenticated_manual_api(x_manual_api_token)
    job = worker_protocol.get_job(job_id)
    if job is None or job.status.value != "COMPLETED":
        raise HTTPException(status_code=404, detail="completed artifact was not found")
    try:
        stored = artifact_store.artifact(job_id, artifact_type)
    except ArtifactIntegrityError as error:
        raise HTTPException(status_code=404, detail="artifact was not found") from error
    media_types = {
        # Kept although nothing produces one any more: artifacts are files and
        # are served as written, so an order completed before ENGINE-MIG-008
        # still downloads everything it was delivered.
        "M3D": "application/octet-stream",
        "STEP": "model/step",
        "STL": "model/stl",
        "PREVIEW": "image/png",
        "VALIDATION_REPORT": "application/json",
    }
    return FileResponse(
        stored.path,
        media_type=media_types.get(artifact_type.upper(), "application/octet-stream"),
        filename=stored.path.name,
    )


@app.get("/api/v1/workers/jobs/{job_id}/manifest", name="worker_job_manifest")
def get_job_manifest(
    job_id: uuid.UUID,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    worker = authenticated_bearer(authorization)
    job = worker_protocol.get_owned_active_job(worker, job_id)
    if job.job_type == JobType.ANALYZE_DRAWING:
        source = artifact_store.drawing(job_id)
        inputs = [{
            "kind": "drawing",
            "download_url": str(request.url_for("download_job_input", job_id=job_id, input_kind="drawing")),
            "sha256": source.sha256,
            "size_bytes": source.size_bytes,
            "local_name": f"page-001{source.path.suffix.lower()}",
        }]
        answers = artifact_store.answers(job_id)
        if answers is not None:
            inputs.append({
                "kind": "user_answers",
                "download_url": str(request.url_for("download_job_input", job_id=job_id, input_kind="user-answers")),
                "sha256": answers.sha256,
                "size_bytes": answers.size_bytes,
                "local_name": "user-answers.json",
            })
    else:
        source = artifact_store.cad_ir(job_id)
        inputs = [{
            "kind": "cad_ir",
            "download_url": str(request.url_for("download_job_cad_ir", job_id=job_id)),
            "sha256": source.sha256,
            "size_bytes": source.size_bytes,
            "local_name": "cad-ir.json",
        }]
    return {
        "manifest_version": "1.0",
        "job_id": str(job_id),
        "order_id": str(job.order_id),
        "cad_ir_version": job.required_cad_ir,
        "inputs": inputs,
        "artifact_upload_url_template": str(
            request.url_for("upload_job_artifact", job_id=job_id, artifact_type="{artifact_type}")
        ).replace("%7Bartifact_type%7D", "{artifact_type}"),
    }


@app.get("/api/v1/workers/jobs/{job_id}/input/{input_kind}", name="download_job_input")
def download_job_input(
    job_id: uuid.UUID,
    input_kind: str,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    worker = authenticated_bearer(authorization)
    worker_protocol.get_owned_active_job(worker, job_id)
    if input_kind == "drawing":
        source = artifact_store.drawing(job_id)
        media_type = "image/png" if source.path.suffix.lower() == ".png" else "image/jpeg"
    elif input_kind == "user-answers":
        source = artifact_store.answers(job_id)
        if source is None:
            raise HTTPException(status_code=404, detail="answers were not found")
        media_type = "application/json"
    elif input_kind == "cad-ir":
        source = artifact_store.cad_ir(job_id)
        media_type = "application/json"
    else:
        raise HTTPException(status_code=404, detail="input was not found")
    return FileResponse(source.path, media_type=media_type, filename=source.path.name)


@app.get("/api/v1/workers/jobs/{job_id}/input/cad-ir", name="download_job_cad_ir")
def download_job_cad_ir(
    job_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    worker = authenticated_bearer(authorization)
    worker_protocol.get_owned_active_job(worker, job_id)
    source = artifact_store.cad_ir(job_id)
    return FileResponse(source.path, media_type="application/json", filename="cad-ir.json")


@app.put(
    "/api/v1/workers/jobs/{job_id}/artifacts/{artifact_type}",
    name="upload_job_artifact",
    response_model=ArtifactUploadResponse,
)
async def upload_job_artifact(
    job_id: uuid.UUID,
    artifact_type: str,
    request: Request,
    x_content_sha256: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> ArtifactUploadResponse:
    worker = authenticated_bearer(authorization)
    worker_protocol.get_owned_active_job(worker, job_id)
    if x_content_sha256 is None:
        raise HTTPException(status_code=400, detail="x-content-sha256 is required")
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_artifact_bytes:
        raise HTTPException(status_code=413, detail="artifact is too large")
    payload = await request.body()
    try:
        stored = artifact_store.put_artifact(job_id, artifact_type, payload, x_content_sha256)
    except ArtifactIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ArtifactUploadResponse(
        type=artifact_type.upper(),
        object_key=stored.object_key,
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
    )


@app.post(
    "/api/v1/workers/jobs/{job_id}/resource-events",
    response_model=ResourceEventBatchAck,
    status_code=202,
)
def record_resource_events(
    job_id: uuid.UUID,
    request: ResourceEventBatch,
    authorization: str | None = Header(default=None),
) -> ResourceEventBatchAck:
    """Append measured resources for a job the caller currently holds.

    Scoped to the active lease: only the worker actually running the job can
    say what it consumed, and a batch that arrives after the lease moved on
    belongs to a superseded attempt.
    """
    if request.job_id != job_id:
        raise HTTPException(status_code=400, detail="job_id path/body mismatch")
    worker = authenticated_bearer(authorization)
    worker_protocol.get_owned_active_job(worker, job_id)
    accepted, duplicates = resource_ledger.record(job_id, request.events)
    return ResourceEventBatchAck(job_id=job_id, accepted=accepted, duplicates=duplicates)


@app.post("/api/v1/workers/jobs/{job_id}/complete", response_model=JobCompletionAck)
def complete_job(job_id: uuid.UUID, request: JobCompletionRequest, authorization: str | None = Header(default=None)) -> JobCompletionAck:
    if request.job_id != job_id:
        raise HTTPException(status_code=400, detail="job_id path/body mismatch")
    worker = authenticated_bearer(authorization)
    job = worker_protocol.get_job(job_id)
    artifact_types = {artifact.type.upper() for artifact in request.artifacts}
    if job is None:
        raise HTTPException(status_code=404, detail="job was not found")
    missing_model = [kind for kind in DELIVERED_MODEL_ARTIFACTS if kind not in artifact_types]
    if job.job_type == JobType.BUILD_CAD and missing_model:
        raise HTTPException(
            status_code=409,
            detail=f"a completed build owes {', '.join(missing_model)}",
        )
    # A drawing job either produced the model or stopped to ask something. Both
    # are finished work; only silence is not.
    if job.job_type == JobType.ANALYZE_DRAWING and not (
        not missing_model or
        {"DRAWING_ANALYSIS", "CLARIFICATION_QUESTIONS"}.issubset(artifact_types)
    ):
        raise HTTPException(status_code=409, detail="drawing analysis artifacts are required")
    try:
        for artifact in request.artifacts:
            artifact_store.verify_completion(job_id, artifact.model_dump())
    except ArtifactIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    replay = worker_protocol.complete_with_artifacts(
        worker, job_id, request.idempotency_key, [artifact.model_dump() for artifact in request.artifacts]
    )
    return JobCompletionAck(job_id=job_id, idempotent_replay=replay)


@app.exception_handler(Exception)
async def safe_exception_handler(request: Request, exc: Exception):
    request_id = request.headers.get("x-request-id", "unknown")
    logger.exception("unhandled request error", extra={"request_id": request_id})
    return JSONResponse(status_code=500, content={"type": "about:blank", "title": "Internal Server Error", "status": 500, "request_id": request_id})


@app.exception_handler(WorkerProtocolError)
async def worker_protocol_exception(request: Request, exc: WorkerProtocolError):
    status = 401 if exc.code.value in {"WORKER_AUTH_FAILED", "ENROLLMENT_REJECTED"} else 409
    return JSONResponse(status_code=status, content={"type": "about:blank", "title": "Worker protocol rejected", "status": status, "code": exc.code, "request_id": request.headers.get("x-request-id", "unknown")})


@app.exception_handler(LedgerError)
async def ledger_exception(request: Request, exc: LedgerError):
    return JSONResponse(
        status_code=409,
        content={
            "type": "about:blank",
            "title": "Resource ledger rejected the batch",
            "status": 409,
            "code": exc.code,
            "request_id": request.headers.get("x-request-id", "unknown"),
        },
    )


@app.exception_handler(OrderTransitionError)
async def order_transition_exception(request: Request, exc: OrderTransitionError):
    return JSONResponse(
        status_code=409,
        content={
            "type": "about:blank",
            "title": "Order transition rejected",
            "status": 409,
            "code": exc.code,
            "request_id": request.headers.get("x-request-id", "unknown"),
        },
    )
