#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE IF NOT EXISTS schema_migrations (version varchar(100) PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"

is_applied() {
  [ "$(psql -Atc "SELECT count(*) FROM schema_migrations WHERE version='$1'")" != "0" ]
}

record() {
  psql -v ON_ERROR_STOP=1 -c "INSERT INTO schema_migrations(version) VALUES ('$1')"
}

apply() {
  psql -v ON_ERROR_STOP=1 --single-transaction -f "/migrations/$1.up.sql"
  record "$1"
}

if ! is_applied 0001_worker_protocol; then
  existing_tables="$(psql -Atc \
    "SELECT count(*) FROM (VALUES ('local_workers'), ('jobs'), ('artifacts')) AS expected(name)
     WHERE to_regclass('public.' || name) IS NOT NULL")"

  if [ "$existing_tables" = "3" ]; then
    # Databases created before schema_migrations was introduced are adopted
    # only when the complete v1 table set is present.
    record 0001_worker_protocol
  elif [ "$existing_tables" = "0" ]; then
    apply 0001_worker_protocol
  else
    echo "Refusing to adopt a partial worker protocol schema ($existing_tables of 3 tables present)." >&2
    exit 1
  fi
fi

# Migrations after 0001 have always been journalled, so they need no adoption
# path: apply in order, skip what is already recorded.
#
# Read from the directory rather than from a list written here. The list was
# hand-maintained, and a migration missing from it does not fail — it is silently
# not applied, and the first sign is the API raising on a column that should
# exist. That is exactly what happened to 0005 and 0006: both files were written,
# both were committed, neither ran.
#
# The numeric prefix is what orders them, and `sort` on the filename is that
# order. A migration whose name does not sort where it belongs is a naming
# mistake, and one visible in a directory listing.
for path in $(ls /migrations/*.up.sql | sort); do
  version="$(basename "$path" .up.sql)"
  [ "$version" = "0001_worker_protocol" ] && continue
  if ! is_applied "$version"; then
    apply "$version"
  fi
done
