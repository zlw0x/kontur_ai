"""Customer-owned projects; builds still run through the trusted worker."""

from __future__ import annotations

import json
from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from cad_ir import CadIrValidationError
from cad_ir.canonical_validator import validate_canonical
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError

from app.accounts import may_see_order
from app.contracts import JobType, OrderStatus, WorkerCapability
from app.workers.artifact_store import ArtifactIntegrityError
from app.workers.capabilities import required_capability_keys
from app.workers.protocol import Job, WorkerProtocolError

from .editor import EditRefused, add_hole, edit_parameters, edit_text, enclosure
from .repository import VersionConflict

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
Dimension = Annotated[float, Field(gt=0, le=2000, allow_inf_nan=False)]
Coordinate = Annotated[float, Field(ge=-2000, le=2000, allow_inf_nan=False)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnclosureInput(StrictRequest):
    width: Dimension = 120
    height: Dimension = 80
    depth: Dimension = 40
    wall: Dimension = 3


class CreateProject(StrictRequest):
    name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
    source_order_id: UUID | None = None
    enclosure: EnclosureInput | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.source_order_id is None) == (self.enclosure is None):
            raise ValueError("Choose exactly one source: source_order_id or enclosure")
        return self


class EditBase(StrictRequest):
    expected_revision: Annotated[int, Field(ge=1, le=1000)]
    action_id: UUID


class ParameterEdit(EditBase):
    kind: Literal["parameters"]
    changes: Annotated[
        dict[str, Annotated[float, Field(allow_inf_nan=False)]],
        Field(min_length=1, max_length=30),
    ]


class HoleEdit(EditBase):
    kind: Literal["hole"]
    diameter: Dimension
    x: Coordinate
    y: Coordinate


class TextEdit(EditBase):
    kind: Literal["text"]
    text: Annotated[str, Field(min_length=1, max_length=300)]


class RestoreEdit(EditBase):
    kind: Literal["restore"]
    revision: Annotated[int, Field(ge=1, le=1000)]


Edit = Annotated[
    ParameterEdit | HoleEdit | TextEdit | RestoreEdit, Field(discriminator="kind")
]


def runtime():
    # Resolve the live services, including the stores swapped by isolated tests.
    from app import main

    return main


def visible(project_id, request):
    services = runtime()
    principal = services.require_principal(request)
    project = services.projects.get(project_id)
    owner = UUID(project.owner_id) if project and project.owner_id else None
    if project is None or not may_see_order(principal, owner):
        raise HTTPException(404, "project was not found")
    return project, principal


def ensure_build(project, version):
    """Replay a durable revision's dispatch with the same ids after an outage.

    SQL snapshots are committed before touching the worker queue. A failed
    dispatch therefore leaves an explicit, retryable version, never a lost edit
    or a second randomly named job on retry.
    """
    services = runtime()
    job_id, order_id = UUID(version.job_id), UUID(version.order_id)
    if services.worker_protocol.get_job(job_id) is not None:
        return
    if services.orders.get(order_id) is None:
        try:
            services.orders.create(
                order_id,
                OrderStatus.WAITING_FOR_LOCAL_WORKER,
                latest_job_id=job_id,
                owner_id=UUID(project.owner_id) if project.owner_id else None,
            )
        except IntegrityError:
            if services.orders.get(order_id) is None:
                raise
    services.artifact_store.put_cad_ir(job_id, version.document)
    document = validate_canonical(version.document)
    try:
        services.worker_protocol.enqueue(
            Job(
                job_id,
                order_id,
                JobType.BUILD_CAD,
                f"project:{project.id}:{version.number}",
                {WorkerCapability.CAD_BUILD},
                document.schema_version,
                required_capability_keys(JobType.BUILD_CAD),
            )
        )
    except (IntegrityError, WorkerProtocolError):
        if services.worker_protocol.get_job(job_id) is None:
            raise


def dispatch(project, version):
    try:
        ensure_build(project, version)
    except Exception:  # noqa: BLE001 - the snapshot is durable; dispatch remains retryable
        runtime().logger.exception(
            "project build dispatch failed: project=%s revision=%s",
            project.id,
            version.number,
        )


def version_state(version, request):
    services = runtime()
    job = services.worker_protocol.get_job(UUID(version.job_id))
    if job is None:
        return {"status": "DISPATCH_PENDING", "artifacts": []}
    state = services.get_drawing_job(UUID(version.order_id), request)
    if state["status"] == "READY":
        # A worker completion without its independent report cannot make an
        # editable revision ready, even if it uploaded two files.
        try:
            report = json.loads(
                services.artifact_store.artifact(
                    UUID(version.job_id), "VALIDATION_REPORT"
                ).path.read_text(encoding="utf-8")
            )
            valid = report.get("valid") is True
        except (ArtifactIntegrityError, ValueError, AttributeError):
            valid = False
        if not valid:
            state.update(
                status="FAILED",
                failure_message="Геометрия версии не подтверждена проверкой.",
                artifacts=[],
            )
    if state["status"] != "READY":
        state["artifacts"] = []
    return state


def snapshot(project, request):
    services = runtime()
    versions = services.projects.versions(project.id)
    current = next(v for v in versions if v.number == project.head)
    return {
        "id": project.id,
        "name": project.name,
        "revision": project.head,
        "cad_ir": current.document,
        "versions": [
            {
                "revision": v.number,
                "created_at": (
                    v.created_at
                    if v.created_at.tzinfo
                    else v.created_at.replace(tzinfo=UTC)
                ).isoformat(),
                "operation": v.operation,
                "order_id": v.order_id,
            }
            for v in versions
        ],
        **version_state(current, request),
    }


@router.get("")
def list_projects(
    request: Request, limit: Annotated[int, Field(ge=1, le=100)] = 50
) -> list[dict]:
    principal = runtime().require_principal(request)
    return [
        {"id": p.id, "name": p.name, "revision": p.head}
        for p in runtime().projects.list(principal.user_id, limit=limit)
    ]


@router.post("", status_code=201)
def create_project(body: CreateProject, request: Request) -> dict:
    services = runtime()
    principal = services.require_principal(request)
    source = {}
    if body.source_order_id is not None:
        order = services.visible_order(body.source_order_id, principal)
        if services.get_drawing_job(body.source_order_id, request)["status"] != "READY":
            raise HTTPException(409, "Дождитесь готовности исходной модели.")
        try:
            try:
                stored = services.artifact_store.cad_ir(order.latest_job_id)
            except ArtifactIntegrityError:
                stored = services.artifact_store.artifact(order.latest_job_id, "CAD_IR")
            value = validate_canonical(
                json.loads(stored.path.read_text(encoding="utf-8"))
            ).canonical_dict()
        except (ArtifactIntegrityError, ValueError) as error:
            raise HTTPException(
                409, "Редактируемый CAD-IR исходной модели недоступен."
            ) from error
        source = {"order_id": order.id, "job_id": order.latest_job_id}
    else:
        services._within_quota(principal)
        try:
            value = enclosure(**body.enclosure.model_dump())
        except (EditRefused, CadIrValidationError) as error:
            raise HTTPException(422, str(error)) from error
    project = services.projects.create(
        principal.user_id, body.name.strip(), value, **source
    )
    dispatch(project, services.projects.version(project.id, 1))
    return snapshot(project, request)


@router.get("/{project_id}")
def get_project(project_id: UUID, request: Request) -> dict:
    project, _ = visible(project_id, request)
    return snapshot(project, request)


@router.post("/{project_id}/retry-build")
def retry_build(project_id: UUID, request: Request) -> dict:
    project, _ = visible(project_id, request)
    dispatch(project, runtime().projects.version(project.id, project.head))
    return snapshot(project, request)


@router.post("/{project_id}/edits", status_code=201)
def edit_project(project_id: UUID, body: Edit, request: Request) -> dict:
    services = runtime()
    project, principal = visible(project_id, request)
    operation = body.model_dump(mode="json", exclude={"action_id"})
    try:
        previous = services.projects.replay(project.id, body.action_id, operation)
        if previous is not None:
            dispatch(project, previous)
            return snapshot(services.projects.get(project.id), request)
        if project.head != body.expected_revision or project.head >= 1000:
            raise VersionConflict(
                "Обновите проект перед правкой; не больше 1000 версий в проекте."
            )
        current = services.projects.version(project.id, project.head)
        if body.kind == "restore":
            target = services.projects.version(project.id, body.revision)
            if target is None or version_state(target, request)["status"] != "READY":
                raise VersionConflict(
                    "Восстановить можно только ранее проверенную версию."
                )
            value = target.document
        else:
            if version_state(current, request)["status"] != "READY":
                raise VersionConflict(
                    "Дождитесь проверки текущей версии или восстановите предыдущую."
                )
            if body.kind == "parameters":
                value = edit_parameters(current.document, body.changes)
            elif body.kind == "hole":
                value = add_hole(current.document, body.diameter, body.x, body.y)
            else:
                value = edit_text(current.document, body.text)
        services._within_quota(principal)
        version = services.projects.append(
            project.id, body.expected_revision, body.action_id, operation, value
        )
    except VersionConflict as error:
        raise HTTPException(409, str(error)) from error
    except (EditRefused, CadIrValidationError) as error:
        raise HTTPException(422, str(error)) from error
    except IntegrityError as error:
        raise HTTPException(409, "Проект уже изменён. Обновите страницу.") from error
    dispatch(project, version)
    return snapshot(services.projects.get(project.id), request)


@router.get("/{project_id}/cad-ir")
def download_project(
    project_id: UUID,
    request: Request,
    revision: Annotated[int | None, Field(ge=1)] = None,
):
    project, _ = visible(project_id, request)
    version = runtime().projects.version(project.id, revision or project.head)
    if version is None:
        raise HTTPException(404, "revision was not found")
    return Response(
        json.dumps(version.document, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="kontur-{project.id}-v{version.number}.cad-ir.json"'
        },
    )
