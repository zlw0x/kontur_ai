-- What an operator decided about an order, and why.
--
-- A table and not a log line. A log rotates, is not queryable, and cannot be
-- joined to the order it is about — and the question this has to answer months
-- later is "who released this part, and what did they say about it", which is
-- exactly the question a rotated log cannot answer.
--
-- Until this existed `automatic_acceptance` was effectively always true: an order
-- reached READY without a single person seeing it. For a pilot that is not
-- acceptable — the model can build a perfectly valid part that is not the part on
-- the drawing, and the only thing catching that is the shape claim, which catches
-- a lot and not everything.

CREATE TABLE order_reviews (
    id varchar(36) PRIMARY KEY,
    order_id varchar(36) NOT NULL REFERENCES orders (id),
    -- Null for the manual operator key, which authenticates as staff and is not a
    -- person. Writing some invented user id here would make the audit trail claim
    -- somebody approved this when nobody did.
    reviewer_id varchar(36) REFERENCES users (id),
    decision varchar(24) NOT NULL,
    -- Free text. Required by the API for a rejection and for a request for changes,
    -- because "no" with no reason is not a decision anybody can act on.
    reason text,
    -- The version the operator was looking at. The transition already checked it;
    -- keeping it is what makes the row a record of what was decided *about* rather
    -- than only of what happened afterwards.
    order_version_before integer NOT NULL,
    order_status_after varchar(32) NOT NULL,
    created_at timestamptz NOT NULL
);

-- The only two questions asked of it: this order's history, and what has been
-- decided lately.
CREATE INDEX IF NOT EXISTS ix_order_reviews_order_id ON order_reviews (order_id);
CREATE INDEX IF NOT EXISTS ix_order_reviews_created_at ON order_reviews (created_at);
