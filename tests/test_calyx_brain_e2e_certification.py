from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"

CANONICAL_MIGRATIONS = (
    "087b_context_preserving_interpretation.sql",
    "088b_publication_registry_policy_foundation.sql",
    "088c_atomic_graph_transaction_publication_engine.sql",
    "088d_publication_lifecycle_corrections_rollback.sql",
    "101_research_workspace_foundation.sql",
    "103_reasoning_ledger.sql",
    "104_orchid_continuum_brain.sql",
    "105_reasoning_ledger_publication_adapter.sql",
)


def test_canonical_migration_chain_is_complete_and_ordered():
    migrations = [MIGRATIONS / name for name in CANONICAL_MIGRATIONS]

    for path in migrations:
        assert path.is_file(), f"missing canonical migration: {path.name}"
        sql = path.read_text(encoding="utf-8")
        assert sql.strip(), f"empty migration: {path.name}"
        assert "BEGIN RSA PRIVATE KEY" not in sql
        assert "OPENSSH PRIVATE KEY" not in sql

    assert tuple(path.name for path in migrations) == CANONICAL_MIGRATIONS
    assert len(set(CANONICAL_MIGRATIONS)) == len(CANONICAL_MIGRATIONS)


def test_governed_chain_uses_canonical_components_only():
    required = (
        ROOT / "app" / "brain" / "ledger_bridge.py",
        ROOT / "app" / "reasoning_ledger" / "persistence.py",
        ROOT / "app" / "reasoning_publication" / "service.py",
        ROOT / "migrations" / "103_reasoning_ledger.sql",
        ROOT / "migrations" / "105_reasoning_ledger_publication_adapter.sql",
    )
    for path in required:
        assert path.is_file(), f"canonical component missing: {path.relative_to(ROOT)}"

    bridge = required[0].read_text(encoding="utf-8")
    publication = required[2].read_text(encoding="utf-8").lower()

    assert "automatically_approved" in bridge
    assert "automatically_published" in bridge
    assert "reasoning_ledger" in publication

    # Private-reasoning identifiers must be recognized only so the publication
    # boundary can reject them; their presence in the deny-list is protective.
    assert '"chain_of_thought"' in publication
    assert '"private_cot"' in publication
    assert "_reject_private" in publication
    assert "private_reasoning_prohibited" in publication


def test_certification_regression_suites_exist():
    suites = (
        "test_build_087b_scientific_interpretation.py",
        "test_build_088b_publication_foundation.py",
        "test_build_088c_atomic_graph_publication.py",
        "test_build_088d_publication_lifecycle.py",
        "test_calyx_brain_integration.py",
        "test_calyx_brain_integration_migrations.py",
        "test_calyx_brain_003_migration.py",
    )
    missing = [name for name in suites if not (ROOT / "tests" / name).is_file()]
    assert not missing, f"missing certification suites: {missing}"
