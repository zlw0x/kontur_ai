-- A job may now say why it stopped.
--
-- `JobStatus` had PENDING, LEASED and COMPLETED. A build that failed went back
-- to PENDING, was re-leased up to `max_attempts`, and then sat there forever —
-- indistinguishable from a job waiting for a worker. The customer's page said
-- "waiting to start" for the rest of time.
--
-- Both columns are nullable, and not only because every existing row has no
-- answer to give: most jobs never fail, and a FAILED status with no reason is
-- worse than none. They are written together or not at all.

ALTER TABLE jobs ADD COLUMN failure_code VARCHAR(64);
ALTER TABLE jobs ADD COLUMN failure_message VARCHAR(400);
