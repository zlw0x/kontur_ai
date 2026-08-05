-- A job may now be paused until a stated time, and nothing is left leased forever.
--
-- Two findings, one migration, because they are the same gap seen from two ends.
--
-- 0005 gave a job a way to say it had stopped. What it could not say is "not yet":
-- an exhausted Codex quota returns on a date, so the job is neither failed — the
-- drawing is fine and it will build — nor waiting for a worker, because every
-- worker would be told the same thing today. `retry_after` is that date, and a job
-- carrying one sits in PAUSED until it passes.
--
-- The other end is worse and was measured. `claim` selects jobs with
-- `attempt < max_attempts`, so a worker that dies on its **last** attempt without
-- reporting leaves the row LEASED with an expired lease and no code — unclaimable
-- by anyone, un-failed, and indistinguishable on the customer's page from a queue
-- with no worker on it. Forever. The reaper is what ends that, and `reaped_at`
-- records that something other than a worker moved the row.

ALTER TABLE jobs ADD COLUMN retry_after TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN reaped_at TIMESTAMPTZ;

-- The reaper sweeps by time, on every poll: without these it is a full scan of the
-- table each pass, which is fine at pilot scale and is not what a queue should do.
CREATE INDEX IF NOT EXISTS ix_jobs_retry_after ON jobs (retry_after)
    WHERE retry_after IS NOT NULL;
