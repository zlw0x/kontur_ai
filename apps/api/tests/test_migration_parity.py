"""The ORM and the SQL migrations describe the same database.

Tests build their schema with `Base.metadata.create_all`, while production
builds it from `apps/api/migrations/*.up.sql`. Nothing forces the two to agree,
so a column added to only one of them would pass every test and then fail on a
real deployment. This test is that missing link.
"""

import re
from pathlib import Path

from app.database import Base
import app.ledger.models  # noqa: F401  (registers the ledger tables)
import app.workers.models  # noqa: F401

MIGRATIONS = Path(__file__).parents[1] / "migrations"

CREATE_TABLE = re.compile(r"CREATE TABLE (\w+)\s*\((.*?)\n\);", re.DOTALL)
ADD_COLUMN = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+)")


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
