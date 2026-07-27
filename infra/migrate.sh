#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE IF NOT EXISTS schema_migrations (version varchar(100) PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"

if [ "$(psql -Atc "SELECT count(*) FROM schema_migrations WHERE version='0001_worker_protocol'")" = "0" ]; then
  existing_tables="$(psql -Atc \
    "SELECT count(*) FROM (VALUES ('local_workers'), ('jobs'), ('artifacts')) AS expected(name)
     WHERE to_regclass('public.' || name) IS NOT NULL")"

  if [ "$existing_tables" = "3" ]; then
    # Databases created before schema_migrations was introduced are adopted
    # only when the complete v1 table set is present.
    psql -v ON_ERROR_STOP=1 -c \
      "INSERT INTO schema_migrations(version) VALUES ('0001_worker_protocol')"
  elif [ "$existing_tables" = "0" ]; then
    psql -v ON_ERROR_STOP=1 --single-transaction \
      -f /migrations/0001_worker_protocol.up.sql
    psql -v ON_ERROR_STOP=1 -c \
      "INSERT INTO schema_migrations(version) VALUES ('0001_worker_protocol')"
  else
    echo "Refusing to adopt a partial worker protocol schema ($existing_tables of 3 tables present)." >&2
    exit 1
  fi
fi
