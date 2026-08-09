-- Dropping these returns the service to one shared static token and orders that
-- belong to nobody.
--
-- What does not survive is every account and every record of who owns what. There
-- is no other copy: `owner_id` is the only place it was written down, and the
-- sessions table is the only thing that can revoke a sign-in. So this is reversible
-- in the sense that the schema goes back, and not in the sense that the state does
-- — which is true of 0008 as well, and is why both say so here rather than in a
-- runbook nobody reads at the moment they need it.
--
-- The order matters: `orders.owner_id` references `users`, so the column goes
-- first, then the sessions that reference users, then users.

DROP INDEX IF EXISTS ix_orders_owner_id;
ALTER TABLE orders DROP COLUMN IF EXISTS owner_id;

DROP INDEX IF EXISTS ix_sessions_user_id;
DROP TABLE IF EXISTS sessions;

DROP INDEX IF EXISTS ix_users_role;
DROP TABLE IF EXISTS users;
