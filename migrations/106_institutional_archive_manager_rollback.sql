BEGIN;
DROP TABLE IF EXISTS archive_checkpoints;
DROP TABLE IF EXISTS archive_provenance;
DROP TABLE IF EXISTS archive_relationships;
DROP TABLE IF EXISTS archive_entities;
DROP TABLE IF EXISTS archive_files;
DROP TABLE IF EXISTS archive_documents;
DROP TABLE IF EXISTS archive_import_runs;
COMMIT;
