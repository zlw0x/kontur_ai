-- The order gets a row. It had been two dictionaries in the API process.
--
--     order_records: dict[uuid.UUID, OrderRecord] = {}
--     drawing_orders: dict[uuid.UUID, dict] = {}
--
-- Jobs, artifacts and the ledger have been in this database since 0001 and 0002.
-- The order — the thing the customer actually has — was the half that was not, so
-- a restart of the API lost every order in flight and a second API process never
-- saw the first one's. The drawing cycle survived only because its tracking was
-- also written to a JSON file beside the artifacts, which is a database with no
-- transactions and no constraints.
--
-- What is here is narrow on purpose. A job already records its lease, its
-- attempts, its failure code and its `retry_after`, and copying that progress onto
-- the order would be a second place for one truth to live — the arrangement this
-- migration exists to end, not to formalise. These columns are what only the order
-- knows.

CREATE TABLE orders (
    id varchar(36) PRIMARY KEY,
    status varchar(32) NOT NULL DEFAULT 'DRAFT',
    version integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    latest_job_id varchar(36),
    source_job_id varchar(36),
    clarification_round integer NOT NULL DEFAULT 0
);

-- The two questions anything asks: what is waiting on an operator, and which order
-- does this job belong to.
CREATE INDEX IF NOT EXISTS ix_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS ix_orders_latest_job_id ON orders (latest_job_id);
