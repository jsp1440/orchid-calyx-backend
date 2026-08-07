-- BUILD-BRAIN-114F/114E: durable bounded per-job input manifests.
-- Safe to apply repeatedly; no existing rows are rewritten.

ALTER TABLE calyx_engineering_program_jobs
    ADD COLUMN IF NOT EXISTS input_json TEXT NULL;

COMMENT ON COLUMN calyx_engineering_program_jobs.input_json IS
    'Canonical bounded JSON input manifest for governed executor assignment construction; snapshots expose only digest/key metadata.';
