import asyncio
import contextlib
import shutil
from pathlib import Path
import logging
import json
import hashlib
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from cad_ir import CadIrValidationError
from cad_ir.canonical import CAD_IR_VERSION, DocumentMetadata
from cad_ir.normalizer import normalize as normalize_cad_ir

from .accounts import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    AccountService,
    AuthenticationFailed,
    EmailAlreadyRegistered,
    InMemoryAccountRepository,
    Principal,
    Role,
    SessionRecord,
    SqlAccountRepository,
    may_see_order,
)
from .accounts.limits import OrderQuota, QuotaExceeded, check_order_quota
from .accounts.passwords import WeakPassword
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
    JobFailureAck,
    JobFailureRequest,
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
    ClarificationAnswer,
    CreateUserRequest,
    CreateUserResponse,
    OrderQueuePage,
    OrderReviewRecord,
    OrderReviewRequest,
    OrderSummary,
    RegisterRequest,
    ReviewDecisionName,
    SessionResponse,
    SignInRequest,
    UserRole,
)
from .input.quarantine import InputRejected, Quarantine
from .input.sanitizer import Sanitizer, SanitizerUnavailable
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
from .orders.progress import order_status
from .orders.repository import InMemoryOrderRepository, SqlOrderRepository
from .orders.review import ReviewDecision
from .orders.state_machine import (
    OrderRecord,
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


def build_order_repository():
    """Same switch as the worker protocol, deliberately: one setting, not two.

    `memory` is what the isolated API tests run on. Everything else keeps orders in
    PostgreSQL, which is the whole point — they were in a dictionary in this module
    until 0008, so a restart lost every order in flight and a second API process
    never saw the first one's.
    """
    if settings.worker_repository_mode == "memory":
        return InMemoryOrderRepository()
    _, sessions = create_session_factory(settings.database_url)
    return SqlOrderRepository(sessions)


def build_account_repository():
    """Same switch again. Three stores, one setting, and no third answer.

    The in-memory one is not a stub: it raises the same `IntegrityError` on a
    duplicate address that the UNIQUE constraint does, so a test cannot pass by
    being run against the more forgiving of the two.
    """
    if settings.worker_repository_mode == "memory":
        return InMemoryAccountRepository()
    _, sessions = create_session_factory(settings.database_url)
    return SqlAccountRepository(sessions)


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


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Run the reaper while the API is up.

    On a timer rather than on each claim, because the failure it exists for is the
    one where **nothing is claiming**: a worker that died on its last attempt leaves
    a job leased, unclaimable and un-failed, and the only other party that could
    have reported it is the process that died. A queue that looks broken is exactly
    when no worker is polling to trigger a sweep.

    Failures are logged and swallowed. A reaper that takes the API down with it
    would turn a stuck job into an outage, and the next pass is thirty seconds away.
    """
    task = None
    if settings.reaper_interval_seconds > 0:
        task = asyncio.create_task(_reap_forever(settings.reaper_interval_seconds))
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def _reap_forever(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            outcome = await asyncio.to_thread(worker_protocol.reap)
        except Exception as error:  # noqa: BLE001 - a sweep must not end the API
            logging.getLogger("cad_ai.reaper").warning("reap failed: %s", error)
            continue
        if outcome.moved:
            # Only when something moved. A quiet queue should be quiet in the log,
            # or the one line that matters is buried under a thousand that do not.
            logging.getLogger("cad_ai.reaper").info(
                "reaped: requeued=%d failed=%d resumed=%d",
                outcome.requeued, outcome.failed, outcome.resumed,
            )


app = FastAPI(
    title="CAD AI Service API",
    version="1.0.0",
    responses={409: {"model": ProblemDetails, "description": "Conflict"}},
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([
        settings.web_origin,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])),
    # Cookies now carry the session, and a browser sends none cross-origin unless
    # this is on. The origin list stays explicit — `allow_credentials` with `*` is
    # refused by every browser, and rightly, because it would let any page on the
    # internet make authenticated requests on a signed-in user's behalf.
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "x-manual-api-token", "x-request-id", CSRF_HEADER],
)
worker_protocol = build_worker_protocol()
resource_ledger = build_resource_ledger()
artifact_store = LocalArtifactStore(settings.artifact_store_root, settings.max_artifact_bytes)
#: Uploads nothing else can read, and the program that cleans them. Kept apart from
#: the artifact store on purpose: that is what the worker downloads from, and a raw
#: upload must never be in it.
quarantine = Quarantine(Path(settings.artifact_store_root).parent / "quarantine")
sanitizer = Sanitizer(
    image=settings.sanitizer_image or None,
    # A decoder with no kernel ceilings is a laptop's convenience, and it stops at
    # the laptop. Outside `local` an operator has a container to configure, so the
    # service refuses to start decoding rather than quietly doing it unconfined —
    # the same shape as `reject_development_secrets_outside_local`.
    allow_unconfined_process=settings.environment.lower() == "local",
)
orders = build_order_repository()
accounts = AccountService(build_account_repository())
#: What one customer may have in flight and start in a day.
#:
#: Not per IP: that belongs to the reverse proxy (P1-6), which is the only thing
#: that sees an address it can trust. What the application can bound exactly —
#: because it owns the rows — is what a known account consumes, and with one worker
#: behind the pilot that is the limit that actually protects everybody else.
order_quota = OrderQuota()


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
    body: TransitionOrderRequest,
    request: Request,
) -> OrderSnapshot:
    principal = require_principal(request)
    order = orders.get(order_id)
    if order is None or not may_see_order(principal, order.owner_id):
        raise HTTPException(status_code=404, detail="order was not found")
    if not principal.is_staff and body.target_status not in CUSTOMER_TRANSITIONS:
        # A customer owns their order and may give it up; they do not get to declare
        # it READY, or send it to manual review, or move it into a stage the pipeline
        # is supposed to reach on its own. Whitelisted rather than blacklisted: a new
        # status added to `OrderStatus` is then unreachable by a customer until
        # somebody decides otherwise, which is the direction a default should fail in.
        raise HTTPException(status_code=403, detail="a customer may only cancel an order")
    updated, _ = orders.transition(
        order_id,
        target=body.target_status,
        expected_version=body.expected_version,
        reason=body.reason,
    )
    return OrderSnapshot(
        id=updated.id,
        status=updated.status,
        version=updated.version,
        updated_at=updated.updated_at,
    )


def _answer_matches(question: dict, answer: ClarificationAnswer) -> str | None:
    """Is this the shape of answer the question asked for? The reason, or None.

    The question is the authority, not the contract: `ClarificationAnswer` allows
    a number or a choice, and which one is right is a property of what was asked.
    Checking here rather than in the model is what lets the reading stage decide,
    and is why the page can render a field that fits.

    A question written before `answer_kind` existed is treated as a number, which
    is what every such question was. An in-flight order does not become
    unanswerable because a new build shipped.
    """
    kind = question.get("answer_kind", "number")
    if kind == "number":
        if not isinstance(answer.value, float):
            return f"question {question['id']} asks for a dimension in millimetres"
        return None
    if kind == "choice":
        choices = question.get("choices") or []
        if not isinstance(answer.value, str):
            return f"question {question['id']} asks for one of the answers offered"
        if answer.value not in choices:
            # Not a free-text field. Accepting anything would put text nobody
            # offered into the prompt of the next round.
            return f"question {question['id']} was not offered the answer {answer.value!r}"
        return None
    return f"question {question['id']} declares an answer kind this build cannot read"


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


# --- who is asking -------------------------------------------------------------
#
# Two credentials reach these handlers and they are not equals.
#
# A **session cookie** is a person: it names a user, so an order they create is
# theirs and an order somebody else created is not visible to them.
#
# The **manual API token** is not a person. It is `MANUAL_API_TOKEN`, and this
# service's standing rule is that it stays a diagnostic operator key and never
# becomes a client authorization. Giving it the operator role rather than some
# phantom customer's is what keeps that true: it can look at everything, the way an
# operator can, and it owns nothing, so nothing created with it becomes an order
# belonging to a user who does not exist.

#: Methods that cannot change anything, and so cannot be worth forging.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: The only status a customer may move their own order to.
#:
#: A whitelist rather than a list of forbidden ones, so that a status added to
#: `OrderStatus` later is unreachable by a customer until somebody decides
#: otherwise. `EXPIRED` is not here on purpose: expiry is something the service
#: observes about an order, not something its owner announces.
CUSTOMER_TRANSITIONS = frozenset({OrderStatus.CANCELLED})


def _identify(request: Request) -> tuple[Principal, SessionRecord | None] | None:
    session_token = request.cookies.get(SESSION_COOKIE)
    if session_token:
        resolved = accounts.resolve(session_token)
        if resolved is not None:
            return resolved
        # A cookie that no longer resolves falls through rather than refusing here.
        # An expired session plus a valid operator token is a request an operator
        # should be able to make, and the alternative is a 401 they cannot explain
        # without being told to clear their cookies.
    manual = request.headers.get("x-manual-api-token")
    if manual and secrets.compare_digest(manual, settings.manual_api_token):
        return Principal(role=Role.OPERATOR), None
    return None


def require_principal(request: Request) -> Principal:
    """Who is asking, refusing if nobody, and checking CSRF when it can apply.

    CSRF is checked **only for a cookie**, and that is not laziness. The attack is
    a page on another origin causing the browser to send a request the user did not
    intend, and the browser attaches cookies to such a request by itself. It does
    not attach an `x-manual-api-token` header, because setting a custom header
    cross-origin requires a preflight the API answers only for its own origins.
    A credential that has to be typed in cannot be sent by accident.
    """
    identified = _identify(request)
    if identified is None:
        raise HTTPException(status_code=401, detail="sign in to continue")
    principal, session = identified
    if principal.from_cookie and request.method.upper() not in SAFE_METHODS:
        if session is None or not accounts.csrf_matches(session, request.headers.get(CSRF_HEADER)):
            raise HTTPException(status_code=403, detail="CSRF token is missing or wrong")
    return principal


def require_staff(request: Request) -> Principal:
    principal = require_principal(request)
    if not principal.is_staff:
        # 404 rather than 403 on the operator surface, for the same reason an order
        # somebody does not own is a 404: a 403 confirms that the endpoint is there
        # and worth attacking, which is the one thing it need not say.
        raise HTTPException(status_code=404, detail="not found")
    return principal


def visible_order(order_id: uuid.UUID, principal: Principal) -> OrderRecord:
    """An order this principal may see, or a 404.

    **404 and not 403.** A 403 answers the question "does this order exist?" for
    anybody willing to guess an id, and the existence of an order is itself
    information about somebody else's business. The two answers are deliberately
    the same and deliberately indistinguishable.
    """
    order = _drawing_order(order_id)
    if not may_see_order(principal, order.owner_id):
        raise HTTPException(status_code=404, detail="drawing order was not found")
    return order


def visible_job_order(job_id: uuid.UUID, principal: Principal):
    """The same rule, reached from a job id instead of an order id.

    The artifact endpoints are keyed by job, and a customer downloading their own
    STEP file goes through them — so "the manual API is for operators" cannot mean
    "only operators may download". What it means is that the job's order decides,
    and this is the one translation from one to the other.
    """
    job = worker_protocol.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job was not found")
    if principal.is_staff:
        return job
    order = orders.get(job.order_id)
    if order is None or not may_see_order(principal, order.owner_id):
        raise HTTPException(status_code=404, detail="job was not found")
    return job


def _set_session_cookies(response: Response, issued) -> None:
    max_age = int(accounts.lifetime.total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        # The three that matter, and each one is doing something:
        # `httponly` keeps the token out of reach of any script on the page, so an
        # XSS bug steals nothing durable; `secure` stops it travelling over plain
        # HTTP; `samesite=lax` means the browser does not attach it to a
        # cross-site POST, which removes most of CSRF before the token below is
        # even consulted. Lax rather than Strict so that following a link into the
        # site from an email does not land on a signed-out page.
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        # Readable on purpose: the client has to copy it into a header, and a
        # header is the thing a cross-origin page cannot set. `httponly` here would
        # break the mechanism it is meant to protect.
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def _session_response(issued) -> SessionResponse:
    return SessionResponse(
        user_id=issued.user.id,
        email=issued.user.email,
        role=UserRole(issued.user.role.value),
        csrf_token=issued.csrf_token,
        expires_at=issued.session.expires_at,
    )


@app.post("/api/v1/auth/register", response_model=SessionResponse, status_code=201)
def register_account(request: RegisterRequest, response: Response) -> SessionResponse:
    """A customer account, and signed in straight away.

    Only ever a customer. An operator account is made by an admin through
    `/api/v1/admin/users`, because a public form that can hand out the role which
    reads everybody's drawings is not a form, it is a door.
    """
    try:
        user, _ = accounts.register(request.email, request.password, Role.CUSTOMER)
    except EmailAlreadyRegistered:
        # The one place the service admits an address is known. A registration form
        # cannot hide it and still work; sign-in can, and does.
        raise HTTPException(status_code=409, detail="this address is already registered") from None
    except WeakPassword as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from None
    issued = accounts.issue(user)
    _set_session_cookies(response, issued)
    return _session_response(issued)


@app.post("/api/v1/auth/sign-in", response_model=SessionResponse)
def sign_in(request: SignInRequest, response: Response) -> SessionResponse:
    try:
        issued = accounts.sign_in(request.email, request.password, request.totp)
    except AuthenticationFailed:
        # One refusal for unknown address, wrong password, disabled account and
        # missing second factor. Anything else is a form that tells a stranger which
        # addresses have accounts here, and the drawings behind those accounts are
        # somebody's commercial secret.
        raise HTTPException(status_code=401, detail="email or password is wrong") from None
    _set_session_cookies(response, issued)
    return _session_response(issued)


@app.post("/api/v1/auth/sign-out", status_code=204)
def sign_out(request: Request, response: Response) -> None:
    identified = _identify(request)
    if identified is not None and identified[0].session_id is not None:
        accounts.sign_out(identified[0].session_id)
    # Cleared whatever happened, so a browser holding a session this server has
    # never heard of does not keep presenting it.
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@app.get("/api/v1/auth/me", response_model=SessionResponse)
def current_account(request: Request, response: Response) -> SessionResponse:
    """Who the cookie says you are, and a fresh CSRF token to go with it.

    A page reloaded after the CSRF token was only ever held in memory has to be able
    to get it back without signing in again, and this is that. It is a GET, so it is
    not itself CSRF-protected — and it need not be, because it changes nothing and
    a cross-origin page cannot read the reply.
    """
    identified = _identify(request)
    if identified is None:
        raise HTTPException(status_code=401, detail="sign in to continue")
    principal, session = identified
    if session is None or principal.user_id is None:
        # The manual operator key. It authenticates but it is not an account, and
        # answering with an invented user would be the exact confusion this service
        # keeps that token out of.
        raise HTTPException(status_code=404, detail="the manual API token is not an account")
    user = accounts.repository.user(principal.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="sign in to continue")
    # Re-issued from the session's own secret would be ideal; the stored value is a
    # hash, so what is returned is a new token. Rotating on a page load closes the
    # window where an old one is still accepted.
    #
    # **And the cookie is rewritten with it**, which it was not, and that omission
    # broke every write a page made after anything called this a second time. The
    # rotation overwrote the hash the session compares against while the browser kept
    # the value from sign-in, so the token the client had — in a cookie or in memory
    # — was one the server had already stopped accepting. Measured: upload 201, call
    # `/auth/me`, upload 403. A reload, a second tab or an effect that runs twice was
    # enough. The cookie is the client's only durable copy, so re-issuing without
    # updating it hands out a credential and revokes it in the same breath.
    issued = _reissued_csrf(session)
    response.set_cookie(
        CSRF_COOKIE,
        issued,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=int(accounts.lifetime.total_seconds()),
        path="/",
    )
    return SessionResponse(
        user_id=user.id,
        email=user.email,
        role=UserRole(user.role.value),
        csrf_token=issued,
        expires_at=session.expires_at,
    )


def _reissued_csrf(session: SessionRecord) -> str:
    """A CSRF token this session will accept, without touching the session token.

    Stored as a hash, so the original cannot be handed back — a new one is minted
    and written over the old. The session cookie is untouched, so the browser stays
    signed in; only the value the header must carry changes.
    """
    token = secrets.token_urlsafe(32)
    accounts.repository.rotate_csrf(session.id, hashlib.sha256(token.encode()).hexdigest())
    return token


def _summary(order: OrderRecord) -> OrderSummary:
    return OrderSummary(
        order_id=order.id,
        status=order.status,
        version=order.version,
        owner_id=order.owner_id,
        latest_job_id=order.latest_job_id,
        clarification_round=order.clarification_round,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@app.get("/api/v1/operator/orders", response_model=OrderQueuePage)
def review_queue(request: Request, limit: int = 25, offset: int = 0) -> OrderQueuePage:
    """What is waiting for a person, oldest first.

    A query on `orders.status` and its index, which is why the hold is a *stored*
    `MANUAL_REVIEW` rather than something derived on the way out: a derived one
    would make this a scan of every order looking for the ones with artifacts.
    """
    require_staff(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    held, total = orders.waiting_for_review(limit=limit, offset=offset)
    return OrderQueuePage(
        orders=[_summary(order) for order in held],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/operator/orders/{order_id}/reviews", response_model=list[OrderReviewRecord])
def order_reviews(order_id: uuid.UUID, request: Request) -> list[OrderReviewRecord]:
    require_staff(request)
    return [
        OrderReviewRecord(
            id=review.id,
            order_id=review.order_id,
            reviewer_id=review.reviewer_id,
            decision=ReviewDecisionName(review.decision.value),
            reason=review.reason,
            order_version_before=review.order_version_before,
            order_status_after=review.order_status_after,
            created_at=review.created_at,
        )
        for review in orders.reviews_of(order_id)
    ]


@app.post("/api/v1/operator/orders/{order_id}/review", response_model=OrderSnapshot)
def review_order(
    order_id: uuid.UUID, body: OrderReviewRequest, request: Request
) -> OrderSnapshot:
    """An operator's decision, and the audit row that explains it.

    The two are written in one transaction by the repository. Not out of neatness:
    an order that became `READY` with no row saying who approved it is
    indistinguishable from one the pipeline released by itself, which is the exact
    thing `automatic_acceptance = False` exists to prevent.
    """
    principal = require_staff(request)
    decision = ReviewDecision(body.decision.value)
    if decision is not ReviewDecision.APPROVE and not (body.reason or "").strip():
        # "No" with no reason is not a decision anybody can act on, and a request
        # for changes with no note re-runs identical inputs and gets an identical
        # answer — a button that appears to do something.
        raise HTTPException(
            status_code=422, detail="a rejection or a request for changes needs a reason"
        )
    if orders.get(order_id) is None:
        raise HTTPException(status_code=404, detail="order was not found")
    updated, _ = orders.review(
        order_id,
        decision=decision,
        expected_version=body.expected_version,
        reviewer_id=principal.user_id,
        reason=(body.reason or "").strip() or None,
    )
    if decision is ReviewDecision.REQUEST_CHANGES:
        _restart_reading(updated, note=(body.reason or "").strip())
    return OrderSnapshot(
        id=updated.id,
        status=updated.status,
        version=updated.version,
        updated_at=updated.updated_at,
    )


def _restart_reading(order: OrderRecord, *, note: str) -> None:
    """Send the drawing back through the reading stage with the operator's note.

    A round, the same shape as the one an answered question produces: a new job, a
    new directory, the page copied from `source_job_id`, and the previous reading
    carried across so the model is not starting from nothing. What is new is the
    note, written as a job input the worker hands to the reading agent — without it
    this would re-run identical inputs and produce an identical document.

    Best-effort about the *prior reading* and not about the note: an order whose
    analysis cannot be found still proceeds by reading the drawing again, which is
    what a clarification round already does.
    """
    if order.source_job_id is None:
        logger.info(json.dumps({
            "event": "review_restart_skipped",
            "order_id": str(order.id),
            "reason": "the order has no drawing to read again",
        }))
        return
    job_id = uuid.uuid4()
    source = artifact_store.drawing(order.source_job_id)
    stored = artifact_store.put_drawing(
        job_id, source.path.read_bytes(), source.path.suffix.lower()
    )
    artifact_store.put_operator_note(job_id, {
        "schema_version": "0.1.0",
        "note": note,
    })
    try:
        artifact_store.put_prior_analysis(
            job_id,
            artifact_store.artifact(order.latest_job_id, "DRAWING_ANALYSIS").path.read_bytes(),
        )
    except ArtifactIntegrityError:
        pass
    round_number = order.clarification_round + 1
    worker_protocol.enqueue(Job(
        job_id,
        order.id,
        JobType.ANALYZE_DRAWING,
        "sha256:" + hashlib.sha256(
            f"{order.id}:{stored.sha256}:{round_number}:review:{note}".encode()
        ).hexdigest(),
        {WorkerCapability.AI_DRAWING, WorkerCapability.CAD_BUILD},
        CAD_IR_VERSION,
        required_capability_keys(JobType.ANALYZE_DRAWING),
    ))
    # After the job is enqueued, for the reason `answer_drawing_questions` gives:
    # a round recorded against a job that was never queued is an order pointing at
    # nothing, and the page would poll it forever.
    orders.record_round(order.id, latest_job_id=job_id, clarification_round=round_number)


@app.post("/api/v1/admin/users", response_model=CreateUserResponse, status_code=201)
def create_user(request: Request, body: CreateUserRequest) -> CreateUserResponse:
    principal = require_principal(request)
    if principal.role is not Role.ADMIN:
        raise HTTPException(status_code=404, detail="not found")
    try:
        user, secret = accounts.register(body.email, body.password, Role(body.role.value))
    except EmailAlreadyRegistered:
        raise HTTPException(status_code=409, detail="this address is already registered") from None
    except WeakPassword as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from None
    return CreateUserResponse(
        user_id=user.id,
        email=user.email,
        role=UserRole(user.role.value),
        # Shown once. It is stored to verify against, not to display, which is the
        # property an authenticator app depends on.
        totp_secret=secret,
    )


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
        request.codex,
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
        request.codex,
    )
    job = worker_protocol.claim(worker) if request.available_slots else None
    if job is None:
        return WorkerClaimResponse(protocol_version="1.0", job=None, retry_after_seconds=5)
    return WorkerClaimResponse(protocol_version="1.0", job={
        "job_id": job.id, "order_id": job.order_id, "job_type": job.job_type, "attempt": job.attempt,
        # The worker needs to know when it is holding the last permitted attempt.
        # Without it, "there will be no retry after this one" has to be a number
        # written down on both sides, and two copies of a bound is how one of them
        # drifts. A worker that knows says FAILED instead of letting the lease
        # lapse into a job nobody will pick up again.
        "max_attempts": job.max_attempts,
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
    body: ManualCadJobRequest,
    request: Request,
) -> ManualCadJobResponse:
    # Staff only, and this is the endpoint the manual token is *for*: handing a
    # CAD-IR document straight to a worker bypasses the reading stage, the shape
    # claim and every check that stands between a drawing and a part. A customer
    # has no business here; an operator diagnosing the engine has nothing else.
    principal = require_staff(request)
    # A submission may still be written against 0.1.0. It is lifted into the
    # canonical form here so the worker only ever sees one shape, and the
    # lineage records both ends of that translation.
    started = time.perf_counter()
    try:
        normalized = normalize_cad_ir(
            body.cad_ir,
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
    orders.create(
        order_id,
        OrderStatus.WAITING_FOR_LOCAL_WORKER,
        latest_job_id=job_id,
        owner_id=principal.user_id,
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
) -> DrawingJobResponse:
    principal = require_principal(request)
    _within_quota(principal)
    # Quarantine, sanitize, then store — and never the upload itself. The addendum's
    # central invariant is that the worker, Codex and the browser see only cleaned
    # pages, and what stood here read the whole body into memory with `request.body()`
    # and wrote the raw file straight into the job directory the worker downloads.
    declared = request.headers.get("content-length")
    try:
        held = await quarantine.accept(
            request.stream(),
            content_type,
            int(declared) if declared and declared.isdigit() else None,
        )
    except InputRejected as refused:
        raise HTTPException(status_code=refused.status_code,
                            detail=refused.message) from refused

    order_id, job_id = uuid.uuid4(), uuid.uuid4()
    try:
        page = sanitizer.sanitize(held, quarantine.root / f"{held.file_id}-out")
    except InputRejected as refused:
        raise HTTPException(status_code=refused.status_code,
                            detail=refused.message) from refused
    except SanitizerUnavailable as broken:
        # The machine, not the drawing. A 503 says "come back", a 422 would tell a
        # customer their file is malformed because an operator has not installed a
        # decoder — and the service would say it again every time.
        logger.error("sanitizer unavailable: %s", broken)
        raise HTTPException(
            status_code=503, detail="The drawing service is temporarily unavailable."
        ) from broken
    finally:
        # §5: the raw upload goes as soon as processing ends. Nothing downstream can
        # reach quarantine, so what is left here is only a window — and a window is
        # worth closing.
        quarantine.discard(held.file_id)
        shutil.rmtree(quarantine.root / f"{held.file_id}-out", ignore_errors=True)

    stored = artifact_store.put_drawing(job_id, page.png, ".png")
    artifact_store.put_input_manifest(job_id, page.manifest())
    # One row, and no longer also a JSON file beside the artifacts. The file was
    # what kept the drawing cycle alive across a restart while the order itself sat
    # in a dictionary; the row does that with transactions and a version behind it.
    orders.create(
        order_id,
        OrderStatus.WAITING_FOR_LOCAL_WORKER,
        latest_job_id=job_id,
        source_job_id=job_id,
        # None when the manual operator key made this, which is correct rather than
        # a gap: that token is not a person, and inventing an owner for it would put
        # a phantom user in the column the ownership rule reads.
        owner_id=principal.user_id,
    )
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


def _within_quota(principal: Principal) -> None:
    """Refuse an order that would put this customer over their limits.

    Before the upload is read, not after: the point of a quota is not to spend the
    decode and the model call and then decline.

    Staff are exempt, and the manual operator key with them. An operator diagnosing
    the engine is not the load this protects against, and `MANUAL_API_TOKEN` owns no
    orders at all — there is nothing to count.
    """
    if principal.is_staff or principal.user_id is None:
        return
    started, in_flight = orders.quota_counts(principal.user_id)
    try:
        check_order_quota(
            started_in_window=started,
            in_flight=in_flight,
            quota=order_quota,
            now=datetime.now(timezone.utc),
        )
    except QuotaExceeded as over:
        # 429 with `Retry-After`, unlike the sign-in lockout, because the caller is
        # already authenticated: there is nothing left for a rate-limit answer to
        # disclose, and a refusal that does not say when to come back is one a client
        # can only answer by polling.
        raise HTTPException(
            status_code=429,
            detail=over.message,
            headers={"Retry-After": str(over.retry_after_seconds)},
        ) from over


def _drawing_order(order_id: uuid.UUID) -> OrderRecord:
    """The order's row, adopting one written before the table existed.

    Until 0008 the drawing cycle's tracking was a JSON file in the artifact store —
    a database with no transactions and no constraints, which is why it is gone.
    Orders created before the migration have only that file, and deleting the read
    would strand every one of them. So it is read once, a row is written from it,
    and every later request takes the row. The same order migration 0006 used: the
    rows come first, the name goes second.
    """
    order = orders.get(order_id)
    if order is not None:
        return order
    try:
        tracking = artifact_store.drawing_tracking(order_id)
    except ArtifactIntegrityError:
        raise HTTPException(status_code=404, detail="drawing order was not found") from None
    try:
        adopted = orders.create(
            order_id,
            OrderStatus.WAITING_FOR_LOCAL_WORKER,
            latest_job_id=tracking["latest_job_id"],
            source_job_id=tracking["source_job_id"],
        )
    except IntegrityError:
        # Two polls of the same pre-0008 order arriving together. The page polls
        # every three seconds, so this is not hypothetical; the second insert loses
        # to the primary key and reads what the first one wrote.
        existing = orders.get(order_id)
        if existing is None:
            raise
        return existing
    if tracking["round"]:
        adopted = orders.record_round(
            order_id,
            latest_job_id=tracking["latest_job_id"],
            clarification_round=tracking["round"],
        )
    return adopted


@app.get("/api/v1/drawing-jobs/{order_id}")
def get_drawing_job(order_id: uuid.UUID, request: Request) -> dict:
    order = visible_order(order_id, require_principal(request))
    job_id = order.latest_job_id
    job = worker_protocol.get_job(job_id)
    if job is None:
        # The tracking file outlived the job row. A 500 here told the customer
        # nothing and told us it was our fault, which is only half true.
        raise HTTPException(status_code=404, detail="drawing order was not found")
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
    # One vocabulary, computed in one place. What stood here answered with
    # `OrderStatus` on two branches and `JobStatus` on the third, so which set of
    # words a customer got depended on which branch fired.
    status = order_status(order, job, has_model=has_model, has_questions=bool(questions))
    # Only while the order is genuinely waiting on the scheduler. Once it is
    # ready, failed, paused, or the user has been asked something, the ball is not
    # here — and a paused order least of all: the scheduler's summary would say no
    # worker has capacity, which is true and is not the reason.
    settled = {
        OrderStatus.READY,
        OrderStatus.WAITING_FOR_USER_ANSWERS,
        OrderStatus.FAILED,
        OrderStatus.PAUSED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
        OrderStatus.MANUAL_REVIEW,
    }
    waiting_reason = (
        scheduler_diagnostics().report(job).summary if status not in settled else None
    )
    stopped = status in (OrderStatus.FAILED, OrderStatus.PAUSED)
    return {
        "order_id": str(order_id),
        "job_id": str(job_id),
        "status": status.value,
        "waiting_reason": waiting_reason,
        # Present on a failure and on a pause, and safe to show: the worker sends a
        # typed code and text it has already stripped of paths and hosts. A FAILED
        # with no reason would be barely better than the silence it replaces, and a
        # PAUSED with no reason would be worse — it would read as a stall.
        "failure_code": job.failure_code if stopped else None,
        "failure_message": job.failure_message if stopped else None,
        # When the service expects to try again. Only on a pause, because it is the
        # only state where anybody knows.
        "retry_after": (
            job.retry_after.isoformat()
            if status == OrderStatus.PAUSED and job.retry_after
            else None
        ),
        "round": order.clarification_round,
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
    body: DrawingAnswersRequest,
    request: Request,
) -> DrawingJobResponse:
    order = visible_order(order_id, require_principal(request))
    prior_job_id = order.latest_job_id
    try:
        question_document = json.loads(
            artifact_store.artifact(prior_job_id, "CLARIFICATION_QUESTIONS").path.read_text(encoding="utf-8")
        )
    except (ArtifactIntegrityError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=409, detail="order is not waiting for answers") from error
    asked = {item["id"]: item for item in question_document.get("questions", [])}
    supplied_ids = {item.question_id for item in body.answers}
    if supplied_ids != set(asked):
        raise HTTPException(status_code=422, detail="answers must match the current question set")
    for answer in body.answers:
        problem = _answer_matches(asked[answer.question_id], answer)
        if problem is not None:
            raise HTTPException(status_code=422, detail=problem)
    if order.clarification_round >= 3:
        raise HTTPException(status_code=409, detail="clarification round limit reached")
    job_id = uuid.uuid4()
    source = artifact_store.drawing(order.source_job_id)
    stored = artifact_store.put_drawing(job_id, source.path.read_bytes(), source.path.suffix.lower())
    artifact_store.put_answers(job_id, {
        "schema_version": "0.1.0",
        "answers": [item.model_dump() for item in body.answers],
    })
    # The reading that produced these questions travels with the answers.
    #
    # A round is a new job with a new directory, so without this the worker has
    # nothing but the drawing and reads it again: a second vision call on every
    # round, and — worse — a *fresh* set of question ids. The answers already sent
    # are keyed by the old ones, so what reaches the compiling agent is a set of
    # values referring to questions that no longer exist.
    #
    # Best-effort: an order whose analysis cannot be found still proceeds by
    # re-reading, which is what it did before this existed.
    try:
        artifact_store.put_prior_analysis(
            job_id,
            artifact_store.artifact(prior_job_id, "DRAWING_ANALYSIS").path.read_bytes(),
        )
    except ArtifactIntegrityError:
        pass
    round_number = order.clarification_round + 1
    worker_protocol.enqueue(Job(
        job_id,
        order_id,
        JobType.ANALYZE_DRAWING,
        "sha256:" + hashlib.sha256(
            f"{order_id}:{stored.sha256}:{round_number}:{body.model_dump_json()}".encode()
        ).hexdigest(),
        {WorkerCapability.AI_DRAWING, WorkerCapability.CAD_BUILD},
        CAD_IR_VERSION,
        required_capability_keys(JobType.ANALYZE_DRAWING),
    ))
    # After the job is enqueued, not before: a round recorded against a job that was
    # never queued is an order pointing at nothing, and the page would poll it
    # forever. This way the worst case is a queued job the order has not caught up
    # to, which the next request fixes.
    orders.record_round(order_id, latest_job_id=job_id, clarification_round=round_number)
    return DrawingJobResponse(
        order_id=order_id,
        job_id=job_id,
        status="WAITING_FOR_LOCAL_WORKER",
        drawing_sha256=stored.sha256,
    )


@app.get("/api/v1/manual/cad-jobs/{job_id}")
def get_manual_cad_job(job_id: uuid.UUID, request: Request) -> dict:
    job = visible_job_order(job_id, require_principal(request))
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
def get_job_claimability(job_id: uuid.UUID, request: Request) -> JobClaimabilityReport:
    """Explain whether a job can currently be leased, and if not, why.

    Read-only and outside the claim transaction: diagnosing a job must never
    be able to change whether it is picked up.
    """
    job = visible_job_order(job_id, require_principal(request))
    return scheduler_diagnostics().report(job)


@app.get("/api/v1/manual/cad-jobs/{job_id}/artifacts/{artifact_type}")
def download_manual_artifact(
    job_id: uuid.UUID,
    artifact_type: str,
    request: Request,
) -> FileResponse:
    # The customer's own download goes through here — the page fetches STEP and STL
    # from this path — so "the manual API is for operators" cannot mean "only
    # operators may download". What it means is that the job's *order* decides, and
    # `visible_job_order` is the single translation from one to the other.
    job = visible_job_order(job_id, require_principal(request))
    if job.status.value != "COMPLETED":
        raise HTTPException(status_code=404, detail="completed artifact was not found")
    try:
        stored = artifact_store.artifact(job_id, artifact_type)
    except ArtifactIntegrityError as error:
        raise HTTPException(status_code=404, detail="artifact was not found") from error
    media_types = {
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
        prior = artifact_store.prior_analysis(job_id)
        if prior is not None:
            inputs.append({
                "kind": "prior_analysis",
                "download_url": str(request.url_for("download_job_input", job_id=job_id, input_kind="prior-analysis")),
                "sha256": prior.sha256,
                "size_bytes": prior.size_bytes,
                "local_name": "drawing-analysis.json",
            })
        answers = artifact_store.answers(job_id)
        if answers is not None:
            inputs.append({
                "kind": "user_answers",
                "download_url": str(request.url_for("download_job_input", job_id=job_id, input_kind="user-answers")),
                "sha256": answers.sha256,
                "size_bytes": answers.size_bytes,
                "local_name": "user-answers.json",
            })
        note = artifact_store.operator_note(job_id)
        if note is not None:
            inputs.append({
                "kind": "operator_note",
                "download_url": str(request.url_for("download_job_input", job_id=job_id, input_kind="operator-note")),
                "sha256": note.sha256,
                "size_bytes": note.size_bytes,
                "local_name": "operator-note.json",
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
    elif input_kind == "prior-analysis":
        source = artifact_store.prior_analysis(job_id)
        media_type = "application/json"
    elif input_kind == "operator-note":
        source = artifact_store.operator_note(job_id)
        if source is None:
            raise HTTPException(status_code=404, detail="no operator note was left")
        media_type = "application/json"
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


@app.post("/api/v1/workers/jobs/{job_id}/fail", response_model=JobFailureAck)
def fail_job(job_id: uuid.UUID, request: JobFailureRequest, authorization: str | None = Header(default=None)) -> JobFailureAck:
    """A worker reporting that it has stopped trying, and why.

    The counterpart to `complete`, and it did not exist. A build that failed
    raised out of the worker's job handler, was swallowed into a backoff, lost its
    lease, and came back round to be tried again — up to `max_attempts` and then
    never again, sitting in PENDING for the rest of time. From the customer's page
    that is "waiting to start", forever, with no way to tell it from a queue with
    no worker on it.

    Retrying stays the first answer. This is the *end* of retrying: the worker
    sends it once it has decided the next attempt would fail the same way, using
    the split it already makes between a failure about the document and one about
    the machine.

    A `retry_after` turns it into a **pause** instead. Some machine failures state
    a date — an exhausted Codex quota returns on one — and such a job is neither
    failed nor waiting for a worker: it will build, and no worker today can build
    it. The job goes to `PAUSED` and the reaper returns it when the time comes.
    A date already past is honoured the same way and swept on the next pass, which
    is one line less than special-casing it here.
    """
    if request.job_id != job_id:
        raise HTTPException(status_code=400, detail="job_id path/body mismatch")
    worker = authenticated_bearer(authorization)
    job = worker_protocol.fail(
        worker, job_id, request.code, request.message, request.retry_after
    )
    return JobFailureAck(job_id=job_id, status=job.status, retry_after=job.retry_after)


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
    if not missing_model:
        _hold_for_review(job.order_id)
    return JobCompletionAck(job_id=job_id, idempotent_replay=replay)


def _hold_for_review(order_id: uuid.UUID) -> None:
    """The finished build stops here unless the operator has said it need not.

    This is the same point that decides `has_model` — a job that delivered every
    artifact a model owes — rather than a second rule somewhere else that has to be
    kept in step with it. `pipeline_status` still turns `has_model` into `READY`;
    what changes is that the order now carries a *stored* `MANUAL_REVIEW`, which
    outranks it, and which is also what makes the queue a query on
    `ix_orders_status` rather than a scan looking for orders with artifacts.

    Failures are swallowed on purpose. The worker did its work and uploaded its
    files, and answering it with a 500 because the order could not be moved would
    make it retry a build that has already succeeded. The two ways this legitimately
    does nothing are an order already decided — cancelled while the build ran, which
    ADR-036 says stays cancelled — and an order created before there was a row.
    """
    if settings.automatic_acceptance:
        return
    order = orders.get(order_id)
    if order is None:
        return
    try:
        orders.transition(
            order_id,
            target=OrderStatus.MANUAL_REVIEW,
            expected_version=order.version,
            reason="a finished build waits for an operator",
        )
    except OrderTransitionError as refused:
        logger.info(
            json.dumps({
                "event": "review_hold_skipped",
                "order_id": str(order_id),
                "status": order.status.value,
                "reason": type(refused).__name__,
            })
        )


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
