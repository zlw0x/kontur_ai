"""Database primitives shared by bounded contexts.

No request handler may create its own engine: this keeps transaction boundaries
explicit and lets tests use a disposable SQLite database.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_session_factory(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
