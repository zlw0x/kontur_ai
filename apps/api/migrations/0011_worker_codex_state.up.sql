-- What a worker last saw of its own Codex CLI.
--
-- `worker_capability_snapshots` and `local_workers.capability_manifest` already
-- carry `codex_cli_version` — which version is *installed*. That says nothing
-- about whether it can answer, and the difference was measured: the account's
-- quota ran out until a stated date, and orders went on being handed to workers
-- that returned `CODEX_CAPACITY_LIMIT` the moment they read the manifest. Three
-- leases and three failures per order, every one of them predictable from the
-- first, and the status page said "no worker has capacity" — which was true, and
-- was not the reason.
--
-- Stored rather than held in the API process, for the reason 0008 moved orders
-- into the database: a restart would forget that the whole fleet is waiting on a
-- quota, and a second API process would never have known.

ALTER TABLE local_workers ADD COLUMN codex_state varchar(16);
ALTER TABLE local_workers ADD COLUMN codex_retry_after timestamptz;
ALTER TABLE local_workers ADD COLUMN codex_detail varchar(300);

-- No default and no backfill. NULL means "this worker has never said", which is
-- exactly true of every row written before this migration, and is read as
-- available — being unable to say is not a reason to refuse a worker's work, the
-- same rule the engine declaration follows. It also means the gate can only ever
-- withhold work from a worker that has stated it cannot do that work.
