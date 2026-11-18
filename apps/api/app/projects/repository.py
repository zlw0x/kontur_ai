"""Immutable snapshots plus an optimistic head; no in-process project state."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column

import app.accounts.models  # noqa: F401
from app.database import Base


class ProjectRow(Base):
    __tablename__ = "cad_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    head: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VersionRow(Base):
    __tablename__ = "cad_project_versions"
    __table_args__ = (UniqueConstraint("project_id", "action_id"),)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cad_projects.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_id: Mapped[str] = mapped_column(String(36))
    operation: Mapped[dict] = mapped_column(JSON)
    document: Mapped[dict] = mapped_column(JSON)
    order_id: Mapped[str] = mapped_column(String(36))
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VersionConflict(ValueError):
    pass


class ProjectRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    def create(
        self,
        owner_id: UUID | None,
        name: str,
        document: dict,
        *,
        order_id=None,
        job_id=None,
    ):
        now = datetime.now(UTC)
        project = ProjectRow(
            id=str(uuid4()),
            owner_id=str(owner_id) if owner_id else None,
            name=name,
            head=1,
            created_at=now,
        )
        version = VersionRow(
            project_id=project.id,
            number=1,
            action_id=str(uuid4()),
            operation={"kind": "create"},
            document=document,
            order_id=str(order_id or uuid4()),
            job_id=str(job_id or uuid4()),
            created_at=now,
        )
        with self.sessions.begin() as session:
            session.add(project)
            session.flush()
            session.add(version)
        return project

    def get(self, project_id):
        with self.sessions() as session:
            return session.get(ProjectRow, str(project_id))

    def list(self, owner_id, *, limit=50):
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(ProjectRow)
                    .where(ProjectRow.owner_id == (str(owner_id) if owner_id else None))
                    .order_by(ProjectRow.created_at.desc(), ProjectRow.id)
                    .limit(limit)
                )
            )

    def versions(self, project_id):
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(VersionRow)
                    .where(VersionRow.project_id == str(project_id))
                    .order_by(VersionRow.number.desc())
                )
            )

    def version(self, project_id, number):
        with self.sessions() as session:
            return session.get(VersionRow, (str(project_id), number))

    def has_job(self, job_id):
        with self.sessions() as session:
            return (
                session.scalar(
                    select(VersionRow.project_id)
                    .where(VersionRow.job_id == str(job_id))
                    .limit(1)
                )
                is not None
            )

    def replay(self, project_id, action_id, operation):
        with self.sessions() as session:
            previous = session.scalar(
                select(VersionRow).where(
                    VersionRow.project_id == str(project_id),
                    VersionRow.action_id == str(action_id),
                )
            )
            if previous is not None and previous.operation != operation:
                raise VersionConflict("Этот запрос уже использован для другой правки.")
            return previous

    def append(self, project_id, expected, action_id, operation, document):
        with self.sessions.begin() as session:
            changed = session.execute(
                update(ProjectRow)
                .where(ProjectRow.id == str(project_id), ProjectRow.head == expected)
                .values(head=expected + 1)
            ).rowcount
            if not changed:
                raise VersionConflict(
                    "Проект уже изменён в другом окне. Откройте последнюю версию."
                )
            version = VersionRow(
                project_id=str(project_id),
                number=expected + 1,
                action_id=str(action_id),
                operation=operation,
                document=document,
                order_id=str(uuid4()),
                job_id=str(uuid4()),
                created_at=datetime.now(UTC),
            )
            session.add(version)
        return version
