ALTER TABLE worker_capability_snapshots ADD COLUMN kompas_version VARCHAR(50);

-- Rolling back restores the names an older build can read.
--
-- It cannot restore which workers *originally* said KOMPAS_BUILD — that
-- distinction was already gone, and it never meant anything different. Every
-- CAD_BUILD becomes KOMPAS_BUILD, which is what an older build expects to see.

UPDATE local_workers
   SET capabilities = (
        SELECT jsonb_agg(CASE WHEN value = '"CAD_BUILD"'::jsonb
                              THEN '"KOMPAS_BUILD"'::jsonb ELSE value END)
          FROM jsonb_array_elements(capabilities) AS value)
 WHERE capabilities @> '["CAD_BUILD"]'::jsonb;

UPDATE jobs
   SET required_capabilities = (
        SELECT jsonb_agg(CASE WHEN value = '"CAD_BUILD"'::jsonb
                              THEN '"KOMPAS_BUILD"'::jsonb ELSE value END)
          FROM jsonb_array_elements(required_capabilities) AS value)
 WHERE required_capabilities @> '["CAD_BUILD"]'::jsonb;

UPDATE resource_events SET stage = 'KOMPAS_STARTUP' WHERE stage = 'CAD_STARTUP';
