-- The last of KOMPAS leaves the vocabulary.
--
-- ENGINE-MIG-008 renamed the engine's terms and kept the old ones parseable,
-- because they are stored: `KOMPAS_BUILD` in two JSON arrays, `KOMPAS_STARTUP`
-- in a resource-event column, `M3D` as an artifact type. The note said they
-- would leave once no stored row carried them. This is that: rather than wait
-- for the rows to age out, the rows are rewritten and the names deleted.
--
-- Every rewrite is a rename of the same thing, not a reinterpretation. A worker
-- that declared KOMPAS_BUILD could build CAD and still can; a startup stage
-- measured the same seconds under either name.

UPDATE local_workers
   SET capabilities = (
        SELECT jsonb_agg(CASE WHEN value = '"KOMPAS_BUILD"'::jsonb
                              THEN '"CAD_BUILD"'::jsonb ELSE value END)
          FROM jsonb_array_elements(capabilities) AS value)
 WHERE capabilities @> '["KOMPAS_BUILD"]'::jsonb;

UPDATE jobs
   SET required_capabilities = (
        SELECT jsonb_agg(CASE WHEN value = '"KOMPAS_BUILD"'::jsonb
                              THEN '"CAD_BUILD"'::jsonb ELSE value END)
          FROM jsonb_array_elements(required_capabilities) AS value)
 WHERE required_capabilities @> '["KOMPAS_BUILD"]'::jsonb;

UPDATE resource_events SET stage = 'CAD_STARTUP' WHERE stage = 'KOMPAS_STARTUP';

-- Artifact rows are left alone on purpose. An M3D row is a file that was really
-- delivered to a customer before the migration, and rewriting its type would
-- make the record say a STEP was delivered when one was not. The type no longer
-- appears in any map, so such a row is simply no longer downloadable — which is
-- true, because nothing can open it here either.

-- The manifest snapshot column goes with the field that fed it. It records the
-- KOMPAS version a worker reported, and no worker has reported one since
-- ENGINE-MIG-007 gave engines a name of their own; every row written since is
-- NULL, and the ones before it name a version of software this service no
-- longer speaks to.
ALTER TABLE worker_capability_snapshots DROP COLUMN kompas_version;
