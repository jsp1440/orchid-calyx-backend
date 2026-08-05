"""CALYX CORE 2 — Occurrence vertical pipeline acceptance tests.

Acceptance criteria verified (issue #386):
  - Bounded occurrence fixture reaches staging with durable persistence.
  - Durable checkpoints survive across store instances (simulate restart).
  - GBIF taxonKey / iNat taxon identifier-to-canonical-taxon reconciliation
    runs and attaches canonical_taxon_id to persisted records.
  - Replay produces zero duplicate records.
  - Unresolved occurrences are captured and surfaced.
  - No production graph mutation.
"""

from __future__ import annotations

import pytest

from app.harvest.durable_checkpoints import DurableSqliteCheckpointStore
from app.harvest.durable_persistence import DurableSqliteHarvestPersistence
from app.harvest.models import HarvestCheckpoint
from runtime.knowledge_graph.canonical_taxonomy import build_canonical_registry
from runtime.knowledge_graph.occurrence_reconciler import OccurrenceCanonicalReconciler


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_registry(taxa: list[tuple[str, str, str]]):
    """Build a minimal CanonicalRegistry.

    taxa: list of (taxon_code, name, gbif_taxon_key)
    """
    rows = [{"name": name, "taxon_code": code} for (code, name, _) in taxa]
    authority_rows = [
        {
            "canonical_name": name,
            "authority": "GBIF",
            "external_id": key,
            "confidence": 1.0,
            "provenance": "fixture",
        }
        for (_, name, key) in taxa
        if key
    ]
    return build_canonical_registry(load_rows=rows, authority_rows=authority_rows)


def _gbif_occurrence(key: str, sci_name: str, taxon_key: str | None = None) -> dict:
    return {
        "source": "gbif",
        "source_record_id": key,
        "scientific_name": sci_name,
        "taxon_key": taxon_key,
        "latitude": 0.0,
        "longitude": 0.0,
    }


def _inat_occurrence(key: str, sci_name: str, taxon_key: str | None = None) -> dict:
    return {
        "source": "inaturalist",
        "source_record_id": key,
        "scientific_name": sci_name,
        "taxon_key": taxon_key,
        "latitude": -1.0,
        "longitude": -78.0,
    }


# ---------------------------------------------------------------------------
# durable persistence tests
# ---------------------------------------------------------------------------


def test_durable_persistence_saves_and_deduplicates(tmp_path):
    db = DurableSqliteHarvestPersistence(tmp_path / "occ.sqlite3")
    records = [
        _gbif_occurrence("R001", "Cattleya labiata", "12345"),
        _gbif_occurrence("R002", "Cattleya trianae", "67890"),
    ]
    saved = db.save_batch(source="gbif", records=records)
    assert saved == 2
    assert db.count("gbif") == 2

    # Re-inserting the same records must be a no-op
    saved_again = db.save_batch(source="gbif", records=records)
    assert saved_again == 0
    assert db.count("gbif") == 2


def test_durable_persistence_survives_restart(tmp_path):
    db_path = tmp_path / "occ.sqlite3"
    db = DurableSqliteHarvestPersistence(db_path)
    db.save_batch(
        source="gbif",
        records=[_gbif_occurrence("X001", "Dracula bella", "11111")],
    )

    # Simulate restart by creating a new store instance against the same path
    db2 = DurableSqliteHarvestPersistence(db_path)
    assert db2.count("gbif") == 1
    rows = db2.all("gbif")
    assert rows[0]["source_record_id"] == "X001"


def test_durable_persistence_canonical_taxon_id_attach(tmp_path):
    db = DurableSqliteHarvestPersistence(tmp_path / "occ.sqlite3")
    db.save_batch(
        source="gbif",
        records=[_gbif_occurrence("G777", "Lepanthes telipogoniflora", "99999")],
    )
    db.update_canonical_taxon_id(
        source="gbif",
        source_record_id="G777",
        canonical_taxon_id="canon:42",
    )
    rows = db.all("gbif")
    assert rows[0]["_canonical_taxon_id"] == "canon:42"


# ---------------------------------------------------------------------------
# durable checkpoint tests
# ---------------------------------------------------------------------------


def test_durable_checkpoint_save_and_load(tmp_path):
    store = DurableSqliteCheckpointStore(tmp_path / "cp.sqlite3")
    store.save_from_state("gbif", "orchids-2026", {"offset": 300, "processed": 300})

    cp = store.load("gbif", "orchids-2026")
    assert cp is not None
    assert cp.offset == 300
    assert cp.processed == 300
    assert cp.completed is False


def test_durable_checkpoint_survives_restart(tmp_path):
    cp_path = tmp_path / "cp.sqlite3"
    store = DurableSqliteCheckpointStore(cp_path)
    store.save_from_state("gbif", "orchids-2026", {"offset": 600, "processed": 600})

    store2 = DurableSqliteCheckpointStore(cp_path)
    cp = store2.load("gbif", "orchids-2026")
    assert cp is not None
    assert cp.offset == 600


def test_durable_checkpoint_clear(tmp_path):
    store = DurableSqliteCheckpointStore(tmp_path / "cp.sqlite3")
    store.save_from_state("gbif", "orchids-2026", {"offset": 100})
    store.clear("gbif", "orchids-2026")
    assert store.load("gbif", "orchids-2026") is None


def test_durable_checkpoint_replay_idempotent(tmp_path):
    """Saving the same state twice does not duplicate rows."""
    store = DurableSqliteCheckpointStore(tmp_path / "cp.sqlite3")
    state = {"offset": 200, "processed": 200}
    store.save_from_state("gbif", "job-x", state)
    store.save_from_state("gbif", "job-x", state)
    jobs = store.list_jobs("gbif")
    assert len(jobs) == 1
    assert jobs[0]["offset"] == 200


# ---------------------------------------------------------------------------
# occurrence reconciler tests
# ---------------------------------------------------------------------------


def test_occurrence_reconciler_exact_authority_id(tmp_path):
    """GBIF taxonKey resolves to canonical taxon via authority mapping."""
    registry = _make_registry(
        [
            ("S", "Cattleya labiata", "12345"),
            ("S", "Cattleya trianae", "67890"),
        ]
    )
    reconciler = OccurrenceCanonicalReconciler(registry)

    outcome = reconciler.reconcile(
        _gbif_occurrence("R001", "Cattleya labiata", taxon_key="12345")
    )
    assert outcome.resolved is True
    assert outcome.canonical_name == "Cattleya labiata"
    assert outcome.reconciliation_method == "exact_authority_id"
    assert outcome.confidence >= 0.99


def test_occurrence_reconciler_name_fallback(tmp_path):
    """Fallback to canonical name lookup when no taxonKey is available."""
    registry = _make_registry(
        [("S", "Epidendrum ibaguense", "")]
    )
    reconciler = OccurrenceCanonicalReconciler(registry)

    outcome = reconciler.reconcile(
        _gbif_occurrence("R002", "Epidendrum ibaguense", taxon_key=None)
    )
    assert outcome.resolved is True
    assert outcome.reconciliation_method == "canonical_name_lookup"


def test_occurrence_reconciler_unresolved_surfaced(tmp_path):
    """Records that cannot be resolved appear in the unresolved list."""
    registry = _make_registry(
        [("S", "Known orchid", "11111")]
    )
    reconciler = OccurrenceCanonicalReconciler(registry)

    records = [
        _gbif_occurrence("R100", "Completely Unknown Species", taxon_key="99999"),
    ]
    resolved, unresolved = reconciler.reconcile_batch(records)
    assert len(resolved) == 0
    assert len(unresolved) == 1
    assert unresolved[0].reconciliation_method == "unresolved"


def test_occurrence_reconciler_batch_summary(tmp_path):
    """reconciliation_summary produces a well-formed contract dict."""
    registry = _make_registry(
        [("S", "Masdevallia veitchiana", "55555")]
    )
    reconciler = OccurrenceCanonicalReconciler(registry)
    records = [
        _gbif_occurrence("A", "Masdevallia veitchiana", taxon_key="55555"),
        _gbif_occurrence("B", "Ghost species", taxon_key="00001"),
    ]
    summary = reconciler.reconciliation_summary(records)
    assert summary["contract"] == "calyx-occurrence-canonical-reconciliation-v1"
    assert summary["total"] == 2
    assert summary["resolved"] == 1
    assert summary["unresolved"] == 1
    assert summary["production_graph_mutation"] is False
    assert "exact_authority_id" in summary["by_method"]


# ---------------------------------------------------------------------------
# end-to-end: bounded occurrence fixture reaches staging with canonical IDs
# ---------------------------------------------------------------------------


def test_bounded_occurrence_fixture_reaches_staging_with_canonical_ids(tmp_path):
    """Bounded occurrence fixture: persist + reconcile → canonical taxon IDs attached."""
    registry = _make_registry(
        [
            ("S", "Cattleya labiata", "12345"),
            ("S", "Dracula bella", "67890"),
        ]
    )
    reconciler = OccurrenceCanonicalReconciler(registry)
    db = DurableSqliteHarvestPersistence(tmp_path / "occ.sqlite3")
    cp_store = DurableSqliteCheckpointStore(tmp_path / "cp.sqlite3")

    records = [
        _gbif_occurrence("G001", "Cattleya labiata", taxon_key="12345"),
        _gbif_occurrence("G002", "Dracula bella", taxon_key="67890"),
        _inat_occurrence("I001", "Unknown orchid", taxon_key=None),
    ]

    # Persist raw records
    db.save_batch(source="gbif", records=[r for r in records if r["source"] == "gbif"])
    db.save_batch(source="inaturalist", records=[r for r in records if r["source"] == "inaturalist"])

    # Save checkpoint
    cp_store.save_from_state("gbif", "bounded-2026", {"offset": len(records), "processed": len(records)})

    # Reconcile and annotate
    resolved, unresolved = reconciler.reconcile_batch(records)
    for outcome in resolved:
        db.update_canonical_taxon_id(
            source=outcome.source,
            source_record_id=outcome.source_record_id,
            canonical_taxon_id=str(outcome.canonical_taxon_id),
        )

    # Verify
    gbif_rows = db.all("gbif")
    assert len(gbif_rows) == 2
    canon_ids = {r["_canonical_taxon_id"] for r in gbif_rows}
    assert None not in canon_ids  # all GBIF records resolved

    inat_rows = db.all("inaturalist")
    assert len(inat_rows) == 1
    # Unknown record has no canonical ID
    assert inat_rows[0]["_canonical_taxon_id"] is None

    assert len(resolved) == 2
    assert len(unresolved) == 1

    # Checkpoint persisted
    cp = cp_store.load("gbif", "bounded-2026")
    assert cp is not None
    assert cp.processed == len(records)

    # No production mutation
    summary = reconciler.reconciliation_summary(records)
    assert summary["production_graph_mutation"] is False
