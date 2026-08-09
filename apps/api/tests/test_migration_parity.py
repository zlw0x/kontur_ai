"""The ORM and the SQL migrations describe the same database.

Tests build their schema with `Base.metadata.create_all`, while production
builds it from `apps/api/migrations/*.up.sql`. Nothing forces the two to agree,
so a column added to only one of them would pass every test and then fail on a
real deployment. This test is that missing link.
"""

import re
from pathlib import Path

from app.database import Base
import app.accounts.models  # noqa: F401  (registers users and sessions)
import app.ledger.models  # noqa: F401  (registers the ledger tables)
import app.orders.models  # noqa: F401
import app.orders.review  # noqa: F401  (registers order_reviews)
import app.workers.models  # noqa: F401

MIGRATIONS = Path(__file__).parents[1] / "migrations"

CREATE_TABLE = re.compile(r"CREATE TABLE (\w+)\s*\((.*?)\n\);", re.DOTALL)
ADD_COLUMN = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+)")
RENAME_COLUMN = re.compile(r"ALTER TABLE (\w+) RENAME COLUMN (\w+) TO (\w+)")


def migrated_schema() -> dict[str, set[str]]:
    schema: dict[str, set[str]] = {}
    for path in sorted(MIGRATIONS.glob("*.up.sql")):
        sql = strip_comments(path.read_text(encoding="utf-8"))
        for table, body in CREATE_TABLE.findall(sql):
            schema[table] = {
                column
                for column in (column_name(line) for line in body.split(",\n"))
                if column is not None
            }
        for table, column in ADD_COLUMN.findall(sql):
            schema.setdefault(table, set()).add(column)
        # Applied in file order, so a later rename supersedes the name an
        # earlier migration created.
        for table, old, new in RENAME_COLUMN.findall(sql):
            columns = schema.setdefault(table, set())
            columns.discard(old)
            columns.add(new)
    return schema


def strip_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


def column_name(line: str) -> str | None:
    token = line.strip().split(" ", 1)[0]
    if not token or token.upper() in {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
        return None
    return token if re.fullmatch(r"\w+", token) else None


def test_every_orm_table_and_column_exists_in_the_migrations():
    schema = migrated_schema()
    missing = []
    for name, table in Base.metadata.tables.items():
        if name not in schema:
            missing.append(f"table {name}")
            continue
        for column in table.columns:
            if column.name not in schema[name]:
                missing.append(f"{name}.{column.name}")
    assert not missing, f"declared in the ORM but never migrated: {missing}"


def test_every_migrated_table_is_declared_in_the_orm():
    declared = set(Base.metadata.tables)
    assert set(migrated_schema()) - declared == set()


#: A column definition that references another table.
#:
#: Anything may sit between the type and `REFERENCES` — `NOT NULL`, a bare `NULL`,
#: a `DEFAULT` — so the middle is skipped rather than enumerated. The first attempt
#: spelled out `(?:\s+NOT NULL)?` and missed 0001's `lease_owner varchar(36) NULL
#: REFERENCES local_workers(id)`, which then looked like an ORM constraint nobody
#: had migrated. A pattern that lists the cases it knows about is a pattern that
#: reports the ones it does not as defects.
REFERENCES = re.compile(
    r"^\s*(\w+)\s+[\w()]+[^,]*?\bREFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\)",
    re.MULTILINE | re.IGNORECASE,
)


def migrated_references() -> set[tuple[str, str, str, str]]:
    """`(table, column, referenced table, referenced column)` from the SQL."""
    found: set[tuple[str, str, str, str]] = set()
    for path in sorted(MIGRATIONS.glob("*.up.sql")):
        sql = strip_comments(path.read_text(encoding="utf-8"))
        for table, body in CREATE_TABLE.findall(sql):
            for column, target, target_column in REFERENCES.findall(body):
                found.add((table, column, target, target_column))
        for statement in sql.split(";"):
            add = ADD_COLUMN.search(statement)
            reference = REFERENCES.search(statement)
            if add and reference:
                found.add((add.group(1), add.group(2), reference.group(2), reference.group(3)))
    return found


def test_every_migrated_foreign_key_is_declared_in_the_orm():
    """Columns were compared and constraints were not, and that gap had a defect in it.

    `orders.owner_id REFERENCES users(id)` was written into migration 0009 and left
    out of the ORM model — a deliberate-looking omission with a comment explaining
    it. Nothing caught it: the tests build their schema with `create_all`, and
    SQLite does not enforce foreign keys by default, so an order owned by an account
    that does not exist inserted cleanly in every test and would have been refused
    in production.

    A test against real PostgreSQL found it. This one finds the next one without
    needing a database at all.
    """
    declared = {
        (table.name, column.name, key.column.table.name, key.column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        for key in column.foreign_keys
    }
    migrated = migrated_references()

    assert migrated - declared == set(), (
        f"migrated but not declared in the ORM: {sorted(migrated - declared)}"
    )
    assert declared - migrated == set(), (
        f"declared in the ORM but never migrated: {sorted(declared - migrated)}"
    )
