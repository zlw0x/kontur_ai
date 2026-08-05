-- A paused job has nowhere to go once `retry_after` is dropped, so it is returned
-- to the queue first: PENDING is where the reaper would have put it anyway, and
-- leaving it PAUSED with no time on it is the silence this migration removed.
UPDATE jobs SET status = 'PENDING', lease_owner = NULL, lease_expires_at = NULL
 WHERE status = 'PAUSED';

DROP INDEX IF EXISTS ix_jobs_retry_after;
ALTER TABLE jobs DROP COLUMN reaped_at;
ALTER TABLE jobs DROP COLUMN retry_after;
