"""Tests for the governed Matrix identification workflow (Phase 3).

Covers evidence classification (supporting / partial / contradicting / missing),
ambiguity detection, unobserved characters, review-gate exclusion of unreviewed
or rejected machine suggestions, contributor-image provenance links, synonym
reconciliation, honest limitations, checksum idempotency, and restart-stable
persistence.
"""

from __future__ import annotations

from pathlib import Path

from runtime.matrix_contributor_bridge import (
    attach_contributor_extractions,
    review_contributor_suggestion,
)
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import create_session, get_session
from runtime.matrix_identification_workflow import build_identification_report
from runtime.matrix_taxon_resolution import StaticTaxonResolver

SYNONYM_ENTRIES = [
    {
        "canonical_taxon_id": "world-plants:phragmipedium-kovachii",
        "accepted_name": "Phragmipedium kovachii",
        "synonyms": ["Phragmipedium peruvianum"],
    }
]

IMAGE = {
    "submission_id": "sub-wf-1",
    "content_sha256": "ab" * 32,
    "original_object_ref": "originals/ab/kovachii_flower.jpg",
    "mime_type": "image/jpeg",
    "contributor_id": "member-7",
    "contributor_display_name": "R. Orchidist",
    "attribution_line": "R. Orchidist (CC-BY-NC)",
    "permission_grant": "cc-by-nc",
    "taxon_name": None,
    "taxon_certainty": "unknown",
}


def _make_registry(registry_root: Path) -> None:
    create_registry_version(
        registry_id="phragmipedium-wf",
        version="1",
        title="Phragmipedium workflow test matrix",
        scope={"genus": "Phragmipedium"},
        characters=[
            RegistryCharacter("petal_color", "Petal color", weight=1),
            RegistryCharacter("pouch_shape", "Pouch shape", weight=2),
            RegistryCharacter(
                "leaf_length_cm", "Leaf length", value_type="numeric_range", weight=1
            ),
            RegistryCharacter("sepal_texture", "Sepal texture", weight=1),
            RegistryCharacter("labellum_shape", "Labellum shape", weight=1),
        ],
        candidates=[
            Candidate(
                "world-plants:phragmipedium-besseae",
                "Phragmipedium besseae",
                {
                    "petal_color": "red",
                    "pouch_shape": "slipper",
                    "leaf_length_cm": {"min": 20, "max": 35},
                },
                provenance={"source": "test"},
            ),
            Candidate(
                "world-plants:phragmipedium-kovachii",
                "Phragmipedium kovachii",
                {
                    "petal_color": "pink",
                    "pouch_shape": "slipper",
                    "leaf_length_cm": {"min": 30, "max": 60},
                },
                provenance={"source": "test"},
            ),
            Candidate(
                "unreconciled:peruvianum-row",
                "Phragmipedium peruvianum",
                {
                    "petal_color": "pink",
                    "pouch_shape": "slipper",
                    "leaf_length_cm": {"min": 30, "max": 60},
                },
                provenance={"source": "test"},
            ),
        ],
        provenance={"source": "test"},
        actor="test",
        root=registry_root,
    )


def _reviewed_session(tmp_path: Path) -> str:
    _make_registry(tmp_path / "registries")
    session = create_session(
        registry_id="phragmipedium-wf",
        version="1",
        actor="member-7",
        metadata={"contributor_submission_id": "sub-wf-1"},
        root=tmp_path / "sessions",
        registry_root=tmp_path / "registries",
    )
    session_id = session["session_id"]
    attached = attach_contributor_extractions(
        session_id,
        IMAGE,
        [
            {"character": "petal_color", "value": "pink", "machine_confidence": 0.81,
             "extractor": "vision-stub", "extractor_version": "0.1.0"},
            {"character": "pouch_shape", "value": "unknown-shape", "machine_confidence": 0.33,
             "extractor": "vision-stub", "extractor_version": "0.1.0"},
            {"character": "leaf_length_cm", "value": 25, "machine_confidence": 0.55,
             "extractor": "vision-stub", "extractor_version": "0.1.0"},
            {"character": "sepal_texture", "value": "smooth", "machine_confidence": 0.4,
             "extractor": "vision-stub", "extractor_version": "0.1.0"},
            {"character": "fragrance", "value": "sweet", "machine_confidence": 0.2,
             "extractor": "vision-stub", "extractor_version": "0.1.0"},
        ],
        root=tmp_path / "sessions",
        registry_root=tmp_path / "registries",
    )
    by_character = {s["character"]: s for s in attached["suggestions"]}
    review_contributor_suggestion(
        session_id, by_character["petal_color"]["suggestion_id"],
        decision="accept", reviewer="expert-1", certainty="probable",
        root=tmp_path / "sessions", registry_root=tmp_path / "registries",
    )
    review_contributor_suggestion(
        session_id, by_character["pouch_shape"]["suggestion_id"],
        decision="revise", reviewer="expert-1", revised_value="slipper",
        certainty="certain", comments="pouch clearly slipper-shaped",
        root=tmp_path / "sessions", registry_root=tmp_path / "registries",
    )
    review_contributor_suggestion(
        session_id, by_character["leaf_length_cm"]["suggestion_id"],
        decision="accept", reviewer="expert-1", certainty="certain",
        root=tmp_path / "sessions", registry_root=tmp_path / "registries",
    )
    review_contributor_suggestion(
        session_id, by_character["sepal_texture"]["suggestion_id"],
        decision="accept", reviewer="expert-1", certainty="certain",
        root=tmp_path / "sessions", registry_root=tmp_path / "registries",
    )
    # Rejected: unmapped character; never scored, audit only.
    review_contributor_suggestion(
        session_id, by_character["fragrance"]["suggestion_id"],
        decision="reject", reviewer="expert-1",
        comments="not a registry character",
        root=tmp_path / "sessions", registry_root=tmp_path / "registries",
    )
    return session_id


def _report(tmp_path: Path, session_id: str, **kwargs) -> dict:
    kwargs.setdefault("synonym_entries", SYNONYM_ENTRIES)
    return build_identification_report(
        session_id,
        root=tmp_path / "sessions",
        registry_root=tmp_path / "registries",
        **kwargs,
    )


def _candidate(report: dict, name: str) -> dict:
    return next(
        item for item in report["ranked_candidates"] if item["scientific_name"] == name
    )


def test_report_classifies_supporting_partial_contradicting_and_missing(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    report = _report(tmp_path, session_id)

    kovachii = _candidate(report, "Phragmipedium kovachii")
    supporting = {row["character"] for row in kovachii["supporting_characters"]}
    assert {"petal_color", "pouch_shape"} <= supporting
    partial = {row["character"] for row in kovachii["partial_characters"]}
    assert "leaf_length_cm" in partial
    # Candidate lacks a state for the observed character: coverage reduced,
    # never treated as biological absence.
    missing = {row["character"] for row in kovachii["missing_candidate_states"]}
    assert "sepal_texture" in missing
    assert "not evidence of biological absence" in kovachii[
        "missing_candidate_states"
    ][0]["note"]

    besseae = _candidate(report, "Phragmipedium besseae")
    contradicting = {row["character"] for row in besseae["contradicting_characters"]}
    assert "petal_color" in contradicting
    # Conflicting evidence is preserved, not silently resolved.
    conflict_row = next(
        row for row in besseae["contradicting_characters"] if row["character"] == "petal_color"
    )
    assert conflict_row["observed_value"] == "pink"
    assert conflict_row["candidate_state"] == "red"


def test_ambiguous_leaders_flagged_when_scores_tie(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    report = _report(tmp_path, session_id)
    assert report["ambiguity"]["is_ambiguous"] is True
    leaders = {item["scientific_name"] for item in report["ambiguity"]["leader_group"]}
    assert leaders == {"Phragmipedium kovachii", "Phragmipedium peruvianum"}
    assert any("indistinguishable" in item for item in report["limitations"])


def test_unobserved_characters_reported_as_missing_evidence(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    report = _report(tmp_path, session_id)
    unobserved = {item["character"] for item in report["unobserved_characters"]}
    assert "labellum_shape" in unobserved
    assert "petal_color" not in unobserved


def test_unreviewed_and_rejected_suggestions_never_score(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    report = _report(tmp_path, session_id)
    # Exactly the four accepted/revised suggestions became observations.
    assert report["observation_count"] == 4
    gate = report["review_gate"]
    assert gate["suggestion_counts"].get("rejected") == 1
    excluded = {(item["character"], item["state"]) for item in gate["excluded_from_scoring"]}
    assert ("fragrance", "rejected") in excluded
    # No pending suggestions remain in this fixture; add one and confirm exclusion.
    attach_contributor_extractions(
        session_id,
        IMAGE,
        [{"character": "labellum_shape", "value": "pouched", "machine_confidence": 0.3,
          "extractor": "vision-stub", "extractor_version": "0.1.0"}],
        root=tmp_path / "sessions",
        registry_root=tmp_path / "registries",
    )
    report2 = _report(tmp_path, session_id)
    assert report2["observation_count"] == 4  # unreviewed suggestion did not score
    excluded2 = {
        (item["character"], item["state"])
        for item in report2["review_gate"]["excluded_from_scoring"]
    }
    assert ("labellum_shape", "pending_review") in excluded2


def test_provenance_links_reach_source_image_and_attribution(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    report = _report(tmp_path, session_id)
    kovachii = _candidate(report, "Phragmipedium kovachii")
    petal = next(
        row for row in kovachii["supporting_characters"] if row["character"] == "petal_color"
    )
    link = petal["evidence_links"][0]
    assert link["submission_id"] == "sub-wf-1"
    assert link["content_sha256"] == "ab" * 32
    assert link["original_object_ref"] == "originals/ab/kovachii_flower.jpg"
    assert link["attribution_line"] == "R. Orchidist (CC-BY-NC)"
    assert link["permission_grant"] == "cc-by-nc"
    assert link["reviewer"] == "expert-1"
    image = report["contributor_images"]["sub-wf-1"]
    assert image["attribution_line"] == "R. Orchidist (CC-BY-NC)"


def test_synonym_groups_collapse_without_deleting_ranked_rows(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    report = _report(tmp_path, session_id)
    collapsed = [g for g in report["synonym_groups"] if g["collapsed"]]
    assert len(collapsed) == 1
    group = collapsed[0]
    assert group["accepted_name"] == "Phragmipedium kovachii"
    assert group["aliases"] == ["Phragmipedium peruvianum"]
    assert len(group["members"]) == 2
    peruvianum = _candidate(report, "Phragmipedium peruvianum")
    assert peruvianum["taxonomic_resolution"]["resolution_state"] == "resolved_synonym"
    assert (
        peruvianum["taxonomic_resolution"]["accepted_name"] == "Phragmipedium kovachii"
    )


def test_unresolved_names_are_surfaced_not_silently_mapped(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    report = build_identification_report(
        session_id,
        taxon_resolver=StaticTaxonResolver([]),
        root=tmp_path / "sessions",
        registry_root=tmp_path / "registries",
    )
    states = {
        item["scientific_name"]: item["taxonomic_resolution"]["resolution_state"]
        for item in report["ranked_candidates"]
    }
    assert set(states.values()) == {"unresolved"}
    assert any("could not be reconciled" in item for item in report["limitations"])


def test_zero_observation_session_reports_no_evidential_weight(tmp_path) -> None:
    _make_registry(tmp_path / "registries")
    session = create_session(
        registry_id="phragmipedium-wf",
        version="1",
        actor="member-9",
        root=tmp_path / "sessions",
        registry_root=tmp_path / "registries",
    )
    report = _report(tmp_path, session["session_id"])
    assert report["observation_count"] == 0
    assert all(item["score"] == 0 for item in report["ranked_candidates"])
    assert any("no evidential weight" in item for item in report["limitations"])
    stages = {s["stage"]: s["actor"] for s in report["automation_stages"]}
    assert stages["expert_review"] == "human"
    assert stages["candidate_scoring"] == "automated"


def test_report_checksum_is_deterministic_across_repeated_calls(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    first = _report(tmp_path, session_id)
    second = _report(tmp_path, session_id)
    assert first["checksum_sha256"] == second["checksum_sha256"]
    assert first["schema_version"] == "matrix-identification-report/v1"


def test_report_and_session_survive_store_reinstantiation(tmp_path) -> None:
    session_id = _reviewed_session(tmp_path)
    before = _report(tmp_path, session_id)
    # Simulate a restart: fresh reads over the same governed roots.
    reloaded = get_session(session_id, root=tmp_path / "sessions")
    assert len(reloaded["observations"]) == 4
    after = _report(tmp_path, session_id)
    assert after["checksum_sha256"] == before["checksum_sha256"]
