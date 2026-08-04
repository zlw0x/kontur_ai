-- Rolling back loses the reasons already recorded. The statuses go with them:
-- a FAILED row would otherwise survive into a build whose enum cannot read it,
-- so it returns to PENDING, which is what such a row meant before this existed.

UPDATE jobs SET status = 'PENDING' WHERE status = 'FAILED';
ALTER TABLE jobs DROP COLUMN failure_message;
ALTER TABLE jobs DROP COLUMN failure_code;
