"""Database primitives shared by bounded contexts.

No request handler may create its own engine: this keeps transaction boundaries
explicit and lets tests use a disposable SQLite database.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def create_session_factory(database_url: str):
    options = {}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if database_url in ("sqlite://", "sqlite:///:memory:"):
            # An in-memory database lives inside one connection, so without a
            # shared connection every pool checkout would see an empty schema.
            options["poolclass"] = StaticPool
    engine = create_engine(database_url, future=True, **options)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
