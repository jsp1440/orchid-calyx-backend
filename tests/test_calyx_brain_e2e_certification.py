from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"

CANONICAL_MIGRATION_PREFIXES = (
    "087b_",
    "088b_",
    "088c_",
    "088d_",
    "101_",
    "103_",
    "104_",
    "105_",
)


def _forward_migration(prefix: str) -> Path:
    candidates = sorted(
        path
        for path in MIGRATIONS.glob(f"{prefix}*.sql")
        if "rollback" not in path.name.lower()
    )
    assert candidates, f"missing forward migration for {prefix}"
    assert len(candidates) == 1, (
        f"ambiguous forward migration for {prefix}: "
        + ", ".join(path.name for path in candidates)
    )
    return candidates[0]


def test_canonical_migration_chain_is_complete_and_ordered():
    migrations = [_forward_migration(prefix) for prefix in CANONICAL_MIGRATION_PREFIXES]
    names = [path.name for path in migrations]

    assert names == sorted(names, key=lambda name: CANONICAL_MIGRATION_PREFIXES.index(name[:5]))
    assert len(set(names)) == len(names)

    for path in migrations:
        sql = path.read_text(encoding="utf-8")
        assert sql.strip(), f"empty migration: {path.name}"
        assert "BEGIN RSA PRIVATE KEY" not in sql
        assert "OPENSSH PRIVATE KEY" not in sql


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
    publication = required[2].read_text(encoding="utf-8")

    assert "automatically_approved" in bridge
    assert "automatically_published" in bridge
    assert "reasoning_ledger" in publication.lower()
    assert "chain_of_thought" not in publication.lower()


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
