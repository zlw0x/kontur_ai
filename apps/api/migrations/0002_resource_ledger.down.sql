ALTER TABLE jobs DROP COLUMN required_capability_keys;
ALTER TABLE local_workers DROP COLUMN capability_manifest;
DROP TABLE worker_capability_snapshots;
DROP TABLE job_cost_snapshots;
DROP TABLE pricing_profiles;
DROP TABLE resource_events;
