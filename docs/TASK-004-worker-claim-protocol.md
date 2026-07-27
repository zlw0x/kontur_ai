# TASK-004: worker claim protocol

## Current acceptance evidence

- Worker credentials are generated server-side, returned once, and stored only
  as SHA-256 hashes.
- Registration, heartbeat and claim endpoints require typed DTOs; worker bearer
  credentials never enter request logs.
- Lease heartbeat and completion endpoints authenticate directly from the bearer
  credential; path/body job IDs must match.
- The protocol service checks capabilities, CAD-IR support, lease ownership and
  expiry, and makes repeat completion idempotent.
- SQLAlchemy models establish durable `local_workers`, `jobs` and `artifacts`
  tables. `uq_artifacts_job_sha256` blocks duplicate artifact insertion.
- `SqlWorkerProtocolService` performs claim selection inside one transaction
  using `FOR UPDATE SKIP LOCKED`, and locks rows for renew/completion.
- Completion writes artifacts in the same transaction, while replay returns an
  acknowledgement without inserting duplicate rows.
- `migrations/0001_worker_protocol.{up,down}.sql` provides explicit PostgreSQL
  rollout and rollback.

## Remaining TASK-004 work

Normal API startup uses the SQL repository. The in-memory implementation is
selected explicitly by tests. An opt-in integration test runs when
`TEST_DATABASE_URL` points to PostgreSQL.
