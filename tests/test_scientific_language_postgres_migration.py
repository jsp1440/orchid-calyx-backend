from dataclasses import replace
from pathlib import Path

from runtime.brain_capability_registry import (
    CapabilityRegistry,
    canonical_brain_registry,
)

MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "710_scientific_language_persistence.sql"
)
SQL = MIGRATION.read_text(encoding="utf-8")


def test_migration_is_additive_private_and_transactional():
    assert "BEGIN;" in SQL
    assert "COMMIT;" in SQL
    assert "CREATE SCHEMA IF NOT EXISTS oc_scientific_language" in SQL
    assert SQL.count("CREATE TABLE IF NOT EXISTS") == 4
    assert SQL.count("REVOKE ALL ON oc_scientific_language.") == 4
    assert "DROP TABLE" not in SQL
    assert "TRUNCATE" not in SQL
    assert " ON DELETE CASCADE" not in SQL


def test_candidate_contract_retains_every_governed_state_and_boundary():
    for state in (
        "UNRESOLVED",
        "CANDIDATES",
        "AMBIGUOUS",
        "MATCHED_PENDING_REVIEW",
        "REVIEWED_MATCH",
        "NEW_CONCEPT_CANDIDATE",
        "REJECTED",
    ):
        assert f"'{state}'" in SQL
    assert "source_provenance JSONB NOT NULL" in SQL
    assert "CHECK (review_required)" in SQL
    assert "CHECK (NOT canonical_promotion_authorized)" in SQL
    assert "CHECK (NOT knowledge_graph_publication_authorized)" in SQL
    assert "REFERENCES oc_concepts.concepts(concept_id) ON DELETE RESTRICT" in SQL


def test_figure_contract_retains_types_provenance_and_non_evidence_boundary():
    for request_type in (
        "DIAGRAM",
        "SKETCH",
        "COLOR_ILLUSTRATION",
        "PHOTO_SET",
        "ANIMATION",
        "COMPARISON_PLATE",
        "DISSECTION",
    ):
        assert f"'{request_type}'" in SQL
    assert "source_ref TEXT NOT NULL" in SQL
    assert "source_hash TEXT NOT NULL" in SQL
    assert "CHECK (NOT scientific_evidence)" in SQL
    assert "CHECK (NOT figure_approval_authorized)" in SQL
    assert "CHECK (NOT canonical_mutation_authorized)" in SQL


def test_records_and_review_decisions_are_append_only():
    assert SQL.count("BEFORE UPDATE OR DELETE") == 4
    assert "glossary_candidate_reviews_append_only" in SQL
    assert "figure_request_reviews_append_only" in SQL
    assert "SCIENTIFIC_LANGUAGE_RECORD_IS_APPEND_ONLY" in SQL


def test_brain_registry_exposes_verified_language_layer_without_authority():
    registry = canonical_brain_registry()
    item = registry._items["scientific_language_intake"]
    decision = registry.eligibility("scientific_language_intake")

    assert item.status == "OPERATIONAL"
    assert item.canonical_issue == "orchid-calyx-backend#710"
    assert item.public_entry_point == "/api/scientific-interpretation/language"
    assert "production application remains owner-gated" in item.persistence
    assert item.blockers == ()
    assert decision["eligible"] is True
    assert registry.orchestrator_view()["execution_authority"] is False
    assert registry.orchestrator_view()["publication_authority"] is False


def test_reasoning_ledger_is_still_not_promoted_by_dependency_completion():
    # The ledger is now registered OPERATIONAL explicitly (7423c45). What this
    # guards is that an operational dependency alone never promotes it: the
    # same registry with the ledger's own status at PARTIAL stays ineligible.
    registry = canonical_brain_registry()
    items = dict(registry._items)
    items["reasoning_ledger"] = replace(items["reasoning_ledger"], status="PARTIAL")
    partial = CapabilityRegistry(tuple(items.values()))

    assert partial.eligibility("scientific_language_intake")["eligible"] is True
    result = partial.eligibility("reasoning_ledger")
    assert result["eligible"] is False
    assert result["reasons"] == ["status is PARTIAL, not OPERATIONAL"]
