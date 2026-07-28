-- POSTMVP-003C: Codex model provenance.
--
-- `model` becomes `requested_model`: the old column recorded whatever the CLI
-- happened to use, which was always NULL because no model was ever named.
-- Renaming keeps those historical rows readable while giving the field the
-- meaning it now has.

ALTER TABLE resource_events RENAME COLUMN model TO requested_model;
ALTER TABLE resource_events RENAME COLUMN reasoning_effort TO requested_reasoning_effort;

ALTER TABLE resource_events ADD COLUMN observed_model varchar(100) NULL;
ALTER TABLE resource_events ADD COLUMN observed_reasoning_effort varchar(16) NULL;

-- How much is actually known about which model served the run:
-- UNKNOWN | EXPLICIT_NOT_REPORTED | VERIFIED | MISMATCH.
ALTER TABLE resource_events ADD COLUMN model_observation_status varchar(32) NULL;

ALTER TABLE resource_events ADD COLUMN routing_profile_version varchar(50) NULL;
ALTER TABLE resource_events ADD COLUMN routing_rule_id varchar(100) NULL;
ALTER TABLE resource_events ADD COLUMN prompt_bundle_sha256 varchar(64) NULL;

-- Identity of everything that determined the run's output: input, prompt
-- bundle, model, reasoning effort, CLI version and routing profile version.
ALTER TABLE resource_events ADD COLUMN provenance_sha256 varchar(64) NULL;

CREATE INDEX ix_resource_events_requested_model ON resource_events(requested_model);
CREATE INDEX ix_resource_events_model_observation_status
    ON resource_events(model_observation_status);
