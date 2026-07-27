-- POSTMVP-003A: scheduler diagnostics.
--
-- Capacity a worker last reported. Without it, a worker that is simply busy is
-- indistinguishable from one that cannot serve the job at all, and both look
-- to the customer like a hung order.

ALTER TABLE local_workers ADD COLUMN available_slots integer NOT NULL DEFAULT 0
    CHECK (available_slots >= 0);
