from pathlib import Path


def test_original_runtime_migration_did_not_include_semantic_index():
    original = Path("migrations/086d_persistent_runtime.sql").read_text(encoding="utf-8")
    assert "'candidate_knowledge','evidence_aggregation'" in original
    assert "semantic_index" not in original


def test_corrective_migration_adds_semantic_index_without_reset_operations():
    migration = Path("migrations/086e_semantic_index_runtime_snapshot.sql").read_text(
        encoding="utf-8"
    )
    assert "'semantic_index'" in migration
    assert "runtime_repository_snapshots_repository_kind_check" in migration
    lowered = migration.casefold()
    for forbidden in ("truncate ", "delete from", "drop table", "drop schema"):
        assert forbidden not in lowered


def test_postgres_semantic_repository_uses_the_newly_permitted_kind():
    source = Path("app/semantic_index/postgres_repository.py").read_text(encoding="utf-8")
    assert 'snapshot_kind = "semantic_index"' in source
