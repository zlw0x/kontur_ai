-- POSTMVP-001/002/003: resource ledger, pricing profiles, cost snapshots and
-- the worker capability registry.
--
-- Identifiers stay varchar(36) to match the v1 tables and the SQLite test
-- database; see docs/adr/ADR-015-resource-ledger-and-cost-model.md.

CREATE TABLE resource_events (
    id varchar(36) PRIMARY KEY,
    job_id varchar(36) NOT NULL,
    event_key varchar(200) NOT NULL,
    event_type varchar(32) NOT NULL,
    stage varchar(32) NOT NULL,
    attempt_no integer NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),

    agent_role varchar(32) NULL,
    model varchar(100) NULL,
    reasoning_effort varchar(16) NULL,
    service_tier varchar(16) NULL,
    cli_version varchar(50) NULL,
    prompt_version varchar(50) NULL,
    thread_id varchar(100) NULL,
    token_source varchar(16) NULL,

    started_at timestamptz NOT NULL,
    finished_at timestamptz NULL,
    wall_ms bigint NULL CHECK (wall_ms >= 0),
    cpu_user_ms bigint NULL CHECK (cpu_user_ms >= 0),
    cpu_system_ms bigint NULL CHECK (cpu_system_ms >= 0),
    peak_memory_bytes bigint NULL CHECK (peak_memory_bytes >= 0),

    input_tokens bigint NULL CHECK (input_tokens >= 0),
    cached_input_tokens bigint NULL CHECK (cached_input_tokens >= 0),
    output_tokens bigint NULL CHECK (output_tokens >= 0),
    reasoning_tokens bigint NULL CHECK (reasoning_tokens >= 0),
    total_tokens bigint NULL CHECK (total_tokens >= 0),

    bytes_read bigint NULL CHECK (bytes_read >= 0),
    bytes_written bigint NULL CHECK (bytes_written >= 0),
    storage_byte_seconds numeric NULL CHECK (storage_byte_seconds >= 0),
    human_minutes numeric NULL CHECK (human_minutes >= 0),

    operation_code varchar(64) NULL,
    operation_count integer NULL CHECK (operation_count >= 0),
    failed_feature_count integer NULL CHECK (failed_feature_count >= 0),
    session_reuse_count integer NULL CHECK (session_reuse_count >= 0),
    forced_termination boolean NOT NULL DEFAULT false,
    result_bytes bigint NULL CHECK (result_bytes >= 0),

    exit_code integer NULL,
    termination_reason varchar(50) NULL,
    retry_number integer NOT NULL DEFAULT 0 CHECK (retry_number >= 0),

    success boolean NOT NULL,
    failure_code varchar(64) NULL,

    metadata jsonb NOT NULL DEFAULT '{}',
    -- Fingerprint of the submitted event. A resend of the same measurement is
    -- an idempotent replay; the same key with different content is a worker
    -- bug and is rejected rather than silently dropped or overwritten.
    content_sha256 varchar(64) NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_resource_events_job_event_key UNIQUE (job_id, event_key),
    CONSTRAINT ck_resource_events_interval
        CHECK (finished_at IS NULL OR finished_at >= started_at)
);
CREATE INDEX ix_resource_events_job_id ON resource_events(job_id);
CREATE INDEX ix_resource_events_event_type ON resource_events(event_type);
CREATE INDEX ix_resource_events_started_at ON resource_events(started_at);

CREATE TABLE pricing_profiles (
    id varchar(36) PRIMARY KEY,
    code varchar(50) NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    currency varchar(3) NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz NULL,
    config jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_pricing_profiles_code_version UNIQUE (code, version)
);

CREATE TABLE job_cost_snapshots (
    id varchar(36) PRIMARY KEY,
    job_id varchar(36) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'DRAFT',
    pricing_profile_id varchar(36) NOT NULL REFERENCES pricing_profiles(id),

    ai_allocated_cost numeric(14,4) NOT NULL,
    ai_shadow_cost numeric(14,4) NOT NULL,
    worker_cost numeric(14,4) NOT NULL,
    cad_license_cost numeric(14,4) NOT NULL,
    vps_cost numeric(14,4) NOT NULL,
    storage_cost numeric(14,4) NOT NULL,
    human_cost numeric(14,4) NOT NULL,
    payment_cost numeric(14,4) NOT NULL,
    resource_cost numeric(14,4) NOT NULL,

    complexity_surcharge numeric(14,4) NOT NULL,
    risk_reserve numeric(14,4) NOT NULL,
    margin_amount numeric(14,4) NOT NULL,
    final_price numeric(14,2) NOT NULL,

    formula_version varchar(20) NOT NULL,
    breakdown jsonb NOT NULL,
    calculated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_job_cost_snapshots_job_id ON job_cost_snapshots(job_id);
-- A job has at most one FINAL snapshot; drafts may be recalculated freely.
CREATE UNIQUE INDEX uq_job_cost_snapshots_final
    ON job_cost_snapshots(job_id) WHERE status = 'FINAL';

CREATE TABLE worker_capability_snapshots (
    id varchar(36) PRIMARY KEY,
    worker_id varchar(36) NOT NULL REFERENCES local_workers(id),
    manifest_sha256 varchar(64) NOT NULL,
    worker_version varchar(50) NOT NULL,
    kompas_version varchar(50) NULL,
    codex_cli_version varchar(50) NULL,
    cad_ir_versions jsonb NOT NULL DEFAULT '[]',
    capabilities jsonb NOT NULL DEFAULT '{}',
    observed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_worker_capability_snapshots_worker_manifest
        UNIQUE (worker_id, manifest_sha256)
);
CREATE INDEX ix_worker_capability_snapshots_worker_id
    ON worker_capability_snapshots(worker_id);

-- The manifest a worker most recently published; the snapshots above keep the
-- history that a cost or incident review needs.
ALTER TABLE local_workers ADD COLUMN capability_manifest jsonb NULL;

-- Capability keys a job needs before it may be leased. Existing v1 jobs carry
-- an empty list and stay leasable exactly as before.
ALTER TABLE jobs ADD COLUMN required_capability_keys jsonb NOT NULL DEFAULT '[]';

