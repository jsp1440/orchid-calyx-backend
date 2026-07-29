from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_brain_migration_is_additive_and_separates_outreach_graph():
    sql = (ROOT / "migrations" / "104_orchid_continuum_brain.sql").read_text(
        encoding="utf-8"
    )
    normalized = sql.upper()
    assert "CREATE SCHEMA IF NOT EXISTS OC_BRAIN" in normalized
    assert "CREATE TABLE IF NOT EXISTS OC_BRAIN.OUTREACH_NODES" in normalized
    assert "CREATE TABLE IF NOT EXISTS OC_BRAIN.OUTREACH_EDGES" in normalized
    assert "REFERENCES OC_GRAPH.KG_NODES" in normalized
    assert "DROP TABLE" not in normalized
    assert "ALTER TABLE" not in normalized


def test_rollback_is_explicitly_separate_from_forward_migration():
    rollback = (
        ROOT / "migrations" / "104_orchid_continuum_brain_rollback.sql"
    ).read_text(encoding="utf-8")
    assert "DROP SCHEMA IF EXISTS oc_brain CASCADE" in rollback
