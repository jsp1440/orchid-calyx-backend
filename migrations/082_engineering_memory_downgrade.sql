-- BUILD-1184: Continuum Engineering Memory v1 — rollback.
-- Drops the v1 engineering-memory tables and their indexes.
-- Order respects the lessons -> runs foreign key.
-- Owner authorization required before running against any shared database.

DROP TABLE IF EXISTS engineering_memory_retrievals;
DROP TABLE IF EXISTS engineering_memory_lessons;
DROP TABLE IF EXISTS engineering_memory_runs;
