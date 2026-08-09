-- Dropping these returns the service to unlimited password guessing at whatever
-- rate bcrypt allows. Nothing else is lost: the counters are rebuilt from the next
-- failure, and an account currently locked out simply stops being.

ALTER TABLE users DROP COLUMN IF EXISTS locked_until;
ALTER TABLE users DROP COLUMN IF EXISTS failed_sign_ins;
