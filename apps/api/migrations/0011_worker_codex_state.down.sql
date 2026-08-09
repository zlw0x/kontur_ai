-- Dropping these returns the scheduler to handing AI jobs to workers that cannot
-- run them. Nothing is lost that is not re-sent: a worker states its Codex state on
-- every heartbeat, so the columns refill within one poll interval of being restored.
--
-- What does not come back on its own is the orders already spent: an outage with
-- this column absent costs three leases and three failures per order rather than a
-- pause, and those attempts are gone.

ALTER TABLE local_workers DROP COLUMN IF EXISTS codex_detail;
ALTER TABLE local_workers DROP COLUMN IF EXISTS codex_retry_after;
ALTER TABLE local_workers DROP COLUMN IF EXISTS codex_state;
