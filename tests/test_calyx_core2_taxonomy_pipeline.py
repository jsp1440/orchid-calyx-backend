"""CALYX CORE 2 — Taxonomy vertical pipeline acceptance tests.

Acceptance criteria verified (issue #386):
  - Bounded taxonomy fixture reaches staging with provenance
    (release_id, checksum, source version, acquisition time).
  - Accepted names and synonyms reach staging with reconciliation outcomes.
  - Replay (running the pipeline twice over the same release) produces
    zero duplicate graph deltas.
  - Unmatched taxa enter an explicit review queue.
  - No production graph mutation.
  - Staging is not automatically promoted.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from runtime.knowledge_graph.taxonomy_staging_pipeline import TaxonomyStagingPipeline


# ---------------------------------------------------------------------------
# fixtures helpers
# ---------------------------------------------------------------------------

def _make_fixture_report(
    accepted: list[tuple[str, str]],
    synonyms: list[tuple[str, str]] = (),
    *,
    release_id: str = "test-release-001",
    sha256: str = "abc123",
    version_label: str = "2026-01",
    acquired_at: str = "2026-01-15T00:00:00+00:00",
) -> dict:
    """Build a minimal WorldPlantsReleaseStore-shaped report dict."""
    fixture_rows = [{"name": name, "taxon_code": code} for (code, name) in accepted]
    fixture_synonym_rows = [
        {"input_match_name": syn, "accepted_match_name": acc, "relationship": "synonym"}
        for (syn, acc) in synonyms
    ]
    return {
        "release_id": release_id,
        "state": "inspected",
        "snapshot": {
            "sha256": sha256,
            "version_label": version_label,
            "acquired_at": acquired_at,
        },
        "canonical_promotion": "blocked_pending_staging_comparison_and_owner_approval",
        "automatic_promotion": False,
        "_fixture_rows": fixture_rows,
        "_fixture_synonym_rows": fixture_synonym_rows,
    }


# ---------------------------------------------------------------------------
# bounded taxonomy staging tests
# ---------------------------------------------------------------------------


def test_taxonomy_bounded_fixture_reaches_staging_with_provenance(tmp_path):
    """Bounded taxonomy fixture reaches staging with all required provenance fields."""
    db_path = tmp_path / "staging.sqlite3"
    pipeline = TaxonomyStagingPipeline(db_path)
    report = _make_fixture_report(
        accepted=[
            ("G", "Cattleya"),
            ("S", "Cattleya labiata"),
            ("S", "Cattleya trianae"),
        ],
        synonyms=[
            ("Cattleya warscewiczii", "Cattleya labiata"),
        ],
        release_id="prov-test-001",
        sha256="deadbeef01",
        version_label="2026-02",
        acquired_at="2026-02-01T12:00:00+00:00",
    )

    result = pipeline.run(report)

    assert result.release_id == "prov-test-001"
    assert result.accepted_count == 3
    assert result.synonym_count == 1
    assert result.edge_count == 1
    assert result.production_graph_mutation is False
    assert result.automatic_promotion is False
    assert result.idempotent_replay is False

    # Check provenance fields on a stored node
    node = pipeline.get_node("Cattleya labiata")
    assert node is not None
    assert node["release_id"] == "prov-test-001"
    assert node["source_sha256"] == "deadbeef01"
    assert node["source_version"] == "2026-02"
    assert node["acquired_at"] == "2026-02-01T12:00:00+00:00"
    assert node["status"] == "accepted"
    assert node["reconciliation_outcome"] == "accepted"

    # Synonym node has correct provenance and reconciliation
    syn_node = pipeline.get_node("Cattleya warscewiczii")
    assert syn_node is not None
    assert syn_node["status"] == "synonym"
    assert syn_node["accepted_canonical_name"] == "Cattleya labiata"
    assert syn_node["reconciliation_outcome"] == "synonym_resolved"
    assert syn_node["release_id"] == "prov-test-001"


def test_taxonomy_replay_produces_zero_duplicate_deltas(tmp_path):
    """Running the pipeline twice over the same release is idempotent."""
    db_path = tmp_path / "staging.sqlite3"
    pipeline = TaxonomyStagingPipeline(db_path)
    report = _make_fixture_report(
        accepted=[("S", "Epidendrum ibaguense"), ("S", "Epidendrum radicans")],
        synonyms=[("Epidendrum ramosum", "Epidendrum ibaguense")],
        release_id="idempotency-001",
    )

    result_1 = pipeline.run(report)
    counts_after_first = pipeline.count_staged("idempotency-001")

    result_2 = pipeline.run(report)
    counts_after_second = pipeline.count_staged("idempotency-001")

    # Counts must not change on the second run
    assert counts_after_first == counts_after_second
    assert result_2.idempotent_replay is True
    # Core counts are preserved
    assert result_1.accepted_count == 2
    assert result_1.synonym_count == 1
    assert result_1.edge_count == 1


def test_taxonomy_unmatched_synonym_enters_review_queue(tmp_path):
    """A synonym whose accepted taxon is not in the backbone enters the review queue."""
    db_path = tmp_path / "staging.sqlite3"
    pipeline = TaxonomyStagingPipeline(db_path)
    report = _make_fixture_report(
        accepted=[("S", "Lepanthes telipogoniflora")],
        synonyms=[
            # This synonym points to a taxon not present in accepted rows
            ("Lepanthes unknown orphan", "Ghost taxon not in backbone"),
        ],
        release_id="orphan-review-001",
    )

    result = pipeline.run(report)

    assert result.unmatched_synonym_count >= 1
    assert len(result.unresolved_review_queue) >= 1
    unresolved_names = [
        item["canonical_name"] for item in result.unresolved_review_queue
    ]
    assert any("Lepanthes unknown orphan" in n for n in unresolved_names)


def test_taxonomy_staging_no_promotion(tmp_path):
    """The pipeline never auto-promotes the release."""
    db_path = tmp_path / "staging.sqlite3"
    pipeline = TaxonomyStagingPipeline(db_path)
    report = _make_fixture_report(
        accepted=[("S", "Maxillaria tenuifolia")],
        release_id="no-promo-001",
    )
    result = pipeline.run(report)
    assert result.production_graph_mutation is False
    assert result.automatic_promotion is False


def test_taxonomy_staging_multiple_releases_independent(tmp_path):
    """Two releases staged to the same DB; node counts are release-agnostic."""
    db_path = tmp_path / "staging.sqlite3"
    pipeline = TaxonomyStagingPipeline(db_path)

    report_a = _make_fixture_report(
        accepted=[("S", "Dracula bella")],
        release_id="rel-a",
        sha256="sha-a",
    )
    report_b = _make_fixture_report(
        accepted=[("S", "Dracula bella"), ("S", "Dracula sodiroi")],
        release_id="rel-b",
        sha256="sha-b",
    )

    result_a = pipeline.run(report_a)
    result_b = pipeline.run(report_b)

    # Each result returns the count of nodes written in that run
    assert result_a.accepted_count == 1
    assert result_b.accepted_count == 2
    # Second run is not an idempotent replay (different release id)
    assert result_b.idempotent_replay is False
