-- Dropping this table returns the service to keeping orders in the API process's
-- memory. The drawing cycle still works, because `drawing-tracking.json` is still
-- read from the artifact store for orders that predate the table — that fallback
-- exists for orders created before 0008 and is what makes this reversible at all.
--
-- What does not survive is a status an operator decided: a cancelled order comes
-- back as whatever its job is doing. There is nowhere else that was written down,
-- which is the whole reason for the table.

DROP INDEX IF EXISTS ix_orders_latest_job_id;
DROP INDEX IF EXISTS ix_orders_status;
DROP TABLE IF EXISTS orders;
