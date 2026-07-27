from sqlalchemy import inspect

from app.database import Base, create_session_factory
from app.workers.models import ArtifactRow, JobRow, WorkerRow


def test_worker_protocol_tables_create_with_uniqueness_constraints():
    engine, _ = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    tables = inspect(engine).get_table_names()
    assert {WorkerRow.__tablename__, JobRow.__tablename__, ArtifactRow.__tablename__}.issubset(tables)
    constraints = inspect(engine).get_unique_constraints(ArtifactRow.__tablename__)
    assert any(set(item["column_names"]) == {"job_id", "sha256"} for item in constraints)
