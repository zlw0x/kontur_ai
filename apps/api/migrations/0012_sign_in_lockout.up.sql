-- What a run of wrong passwords costs.
--
-- ADR-037 shipped authentication that is correct and not yet hard to grind
-- against, and said so. bcrypt at cost 12 makes each guess expensive; nothing made
-- the *number* of guesses expensive, so a patient attacker had unlimited tries at
-- a quarter of a second each.
--
-- Two columns rather than a table of rate events, because the question is "how
-- many in a row for this account" and the answer is one number. Durable rather
-- than in-process for the reason everything else in this schema is durable: an
-- attacker who can wait for a deploy has waited out an in-memory counter.
--
-- Per account rather than per address or per connection. That is the thing being
-- protected — a password — and it holds whichever machine the guessing comes from.
-- The cost is real and is named in `app.accounts.limits`: somebody who knows a
-- customer's address can shut them out for fifteen minutes at a time. For a pilot
-- that is the better trade, and it is why the count resets on the first success
-- rather than on a timer.

ALTER TABLE users ADD COLUMN failed_sign_ins integer NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN locked_until timestamptz;

-- The order quotas that ship with this need no schema at all: an order already
-- records who owns it and when it was created, and an upload *is* an order. A
-- table of rate events would be a row written on every request to answer a
-- question rows that already exist can answer.
--
-- `ix_orders_owner_id` from 0009 is what makes both counts cheap.
