CREATE TABLE local_workers (
    id varchar(36) PRIMARY KEY,
    name varchar(100) NOT NULL UNIQUE,
    token_hash varchar(64) NOT NULL UNIQUE,
    status varchar(32) NOT NULL DEFAULT 'READY',
    capabilities jsonb NOT NULL DEFAULT '[]',
    supported_cad_ir jsonb NOT NULL DEFAULT '[]',
    app_version varchar(50) NOT NULL,
    last_seen_at timestamptz NULL
);

CREATE TABLE jobs (
    id varchar(36) PRIMARY KEY,
    order_id varchar(36) NOT NULL,
    job_type varchar(64) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'PENDING',
    idempotency_key varchar(80) NOT NULL UNIQUE,
    required_capabilities jsonb NOT NULL DEFAULT '[]',
    required_cad_ir varchar(20) NOT NULL,
    attempt integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    lease_owner varchar(36) NULL REFERENCES local_workers(id),
    lease_expires_at timestamptz NULL,
    completed_key varchar(80) NULL
);
CREATE INDEX ix_jobs_order_id ON jobs(order_id);
CREATE INDEX ix_jobs_status ON jobs(status);
CREATE INDEX ix_jobs_lease_expires_at ON jobs(lease_expires_at);

CREATE TABLE artifacts (
    id varchar(36) PRIMARY KEY,
    job_id varchar(36) NOT NULL REFERENCES jobs(id),
    artifact_type varchar(32) NOT NULL,
    object_key text NOT NULL,
    sha256 varchar(71) NOT NULL,
    size_bytes integer NOT NULL CHECK (size_bytes >= 0),
    CONSTRAINT uq_artifacts_job_sha256 UNIQUE(job_id, sha256)
);
CREATE INDEX ix_artifacts_job_id ON artifacts(job_id);
