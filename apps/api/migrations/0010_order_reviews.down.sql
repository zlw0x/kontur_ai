-- Dropping this throws away every record of who released which part.
--
-- Orders keep whatever status they were left in, so a part approved by an operator
-- stays approved — and becomes indistinguishable from one the pipeline released on
-- its own, which is the distinction the table exists to make. There is no other
-- copy: the decision is not in the order row, which holds only where the order
-- ended up.

DROP INDEX IF EXISTS ix_order_reviews_created_at;
DROP INDEX IF EXISTS ix_order_reviews_order_id;
DROP TABLE IF EXISTS order_reviews;
