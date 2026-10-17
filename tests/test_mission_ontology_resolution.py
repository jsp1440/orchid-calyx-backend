"""Deterministic tests for the ontology_resolution mission handler (#1722)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from app.missions.ontology_resolution import (
    MAX_CANDIDATES,
    MAX_COMPARISONS,
    MAX_ID,
    MAX_SOURCE_LENGTH,
    MAX_SYNONYMS_PER_TERM,
    MAX_TERM_ROWS,
    MAX_TERMS,
    MAX_TEXT_LENGTH,
    build_ontology_resolution_report,
)
from app.missions.registry import MISSION_TYPES
from app.missions.repositories import InMemoryMissionRepository
from app.missions.services import MissionService
from app.ontology.services import DeterministicResolutionEngine

CODE = "ONTOLOGY_RESOLUTION_MANIFEST_INVALID"


def term(term_id: Any, label: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "term_id": term_id,
        "registry_id": 1,
        "canonical_key": label.replace(" ", "_").lower(),
        "preferred_label": label,
        "namespace": "oc.glossary",
        "version": "1.0.0",
        "registry_status": "ACTIVE",
        "term_status": "ACTIVE",
    }
    data.update(overrides)
    return data


def candidate(candidate_id: Any, name: str) -> dict[str, Any]:
    return {"candidate_id": candidate_id, "name": name}


def manifest(
    terms: list[dict[str, Any]], candidates: list[dict[str, Any]], **overrides: Any
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source": "fixture-session-3",
        "terms": terms,
        "candidates": candidates,
    }
    data.update(overrides)
    return data


TERMS = [
    term(10, "Labellum", synonyms=["lip"]),
    term(11, "Pseudobulb"),
    term(12, "Column"),
]


def by_id(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {item["candidate_id"]: item for item in report["resolutions"]}


def run_mission(input_manifest: dict[str, Any], key: str) -> tuple[MissionService, int]:
    service = MissionService(InMemoryMissionRepository())
    mission = service.create(
        {
            "mission_key": key,
            "title": "Ontology resolution",
            "description": "Propose ontology term matches for human review.",
            "mission_type": "ontology_resolution",
            "requested_by": "owner",
            "priority": 50,
            "maximum_runs": 1,
            "input_manifest": input_manifest,
            "allowed_actions": ["report_for_review"],
            "prohibited_actions": [
                "taxonomy_write",
                "canonical_graph_publish",
                "external_api_call",
            ],
            "idempotency_key": key,
        },
        {"auth_type": "owner_session"},
    )
    mission_id = mission["mission_id"]
    service.submit(mission_id, "owner", "ready")
    service.approve(mission_id, "owner", "approve", "approval-1722")
    service.queue(mission_id, "owner", "queue")
    service.execute_cycle("worker-ontology")
    return service, mission_id


def test_registry_contract_preserves_limits():
    mission_type = MISSION_TYPES["ontology_resolution"]
    assert mission_type.handler == "ontology_resolution"
    assert mission_type.risk_level == "medium"
    assert mission_type.write_scope == "ontology_review_only"
    assert mission_type.allowed_database_schemas == ("oc_ontology",)
    assert "oc_taxonomy" in mission_type.forbidden_database_schemas
    assert mission_type.human_approval_required is True
    assert mission_type.publication_authority_required is False
    assert mission_type.canonical_graph_writes_permitted is False
    assert mission_type.taxonomy_writes_prohibited is True


def test_report_is_human_review_only_and_never_accepts():
    report = build_ontology_resolution_report(
        manifest(TERMS, [candidate(1, "Labellum"), candidate(2, "unknown structure")])
    )

    assert report["artifact_type"] == "ontology_resolution_proposals"
    assert report["review_state"] == "awaiting_human_review"
    assert report["human_review_required"] is True
    assert report["scientific_authority"] == "none"
    assert report["score_semantics"] == "string_match_score_not_scientific_confidence"
    for flag in (
        "scientific_conclusions_published",
        "approval_recorded",
        "resolutions_persisted",
        "ontology_mutated",
        "provider_called",
        "external_network_called",
        "domain_database_written",
        "canonical_graph_mutated",
        "taxonomy_mutated",
    ):
        assert report[flag] is False, flag
    assert "ACCEPTED" not in str(report)
    for item in report["resolutions"]:
        assert item["human_review_required"] is True
        for proposal in item["proposals"]:
            assert proposal["status"] in {"PROPOSED", "NEEDS_REVIEW"}


def test_methods_mirror_the_deterministic_engine():
    report = build_ontology_resolution_report(
        manifest(
            TERMS,
            [
                candidate(1, "Labellum"),
                candidate(2, "  PSEUDOBULB. "),
                candidate(3, "lip"),
                candidate(4, "Collumn"),
                candidate(5, "sepal"),
            ],
        )
    )
    items = by_id(report)
    assert items[1]["proposals"][0]["resolution_method"] == "EXACT"
    assert items[1]["proposals"][0]["ontology_term_id"] == 10
    assert items[2]["proposals"][0]["resolution_method"] == "NORMALIZED"
    assert items[3]["proposals"][0]["resolution_method"] == "SYNONYM"
    assert items[3]["proposals"][0]["ontology_term_id"] == 10
    assert items[4]["proposals"][0]["resolution_method"] == "FUZZY"
    assert "FUZZY_ONLY" in items[4]["review_flags"]
    assert items[5]["resolution_state"] == "UNRESOLVED_NEEDS_REVIEW"
    unresolved = items[5]["proposals"]
    assert len(unresolved) == 1
    assert unresolved[0]["resolution_method"] == "UNRESOLVED"
    assert unresolved[0]["ontology_term_id"] is None
    assert unresolved[0]["status"] == "NEEDS_REVIEW"
    assert unresolved[0]["explanation"] == {"reason": "NO_CONTROLLED_TERM_MATCH"}

    # Proposals are exactly the engine's, one per term, best-ranked first.
    rows = [
        {
            "id": 10,
            "registry_id": 1,
            "canonical_key": "labellum",
            "preferred_label": "Labellum",
            "namespace": "oc.glossary",
            "version": "1.0.0",
            "synonym": "lip",
        },
    ]
    assert items[3]["proposals"] == DeterministicResolutionEngine().suggestions(
        "lip", rows
    )


def test_term_matched_by_several_synonyms_is_proposed_once():
    terms = [term(10, "Labellum", synonyms=["lip", "Lip", "lipp"])]
    report = build_ontology_resolution_report(manifest(terms, [candidate(1, "lip")]))
    proposals = by_id(report)[1]["proposals"]
    assert [item["ontology_term_id"] for item in proposals] == [10]
    assert proposals[0]["resolution_method"] == "SYNONYM"


def test_ties_are_flagged_not_broken():
    terms = [
        term(10, "Column", registry_id=1),
        term(20, "Column", registry_id=2, namespace="oc.trait"),
    ]
    report = build_ontology_resolution_report(manifest(terms, [candidate(1, "Column")]))
    item = by_id(report)[1]
    assert [p["ontology_term_id"] for p in item["proposals"]] == [10, 20]
    assert "AMBIGUOUS_TOP_MATCH" in item["review_flags"]
    assert report["summary"]["ambiguous_candidates"] == 1


def test_only_terms_the_service_would_match_are_eligible():
    terms = [
        term(10, "Column", registry_id=1),
        term(
            20, "Column", registry_id=2, registry_status="DRAFT", namespace="oc.draft"
        ),
        term(30, "Column", registry_id=3, term_status="DEPRECATED", namespace="oc.old"),
        term(40, "Column", registry_id=4, term_status="DRAFT", namespace="oc.new"),
    ]
    report = build_ontology_resolution_report(manifest(terms, [candidate(1, "Column")]))
    proposals = by_id(report)[1]["proposals"]
    assert [p["ontology_term_id"] for p in proposals] == [10, 40]
    assert report["summary"]["terms_eligible"] == 2
    assert report["summary"]["terms_excluded"] == {
        "registry_not_active": 1,
        "term_deprecated": 1,
    }


def test_no_eligible_terms_leaves_every_candidate_unresolved():
    terms = [term(10, "Column", registry_status="RETIRED")]
    report = build_ontology_resolution_report(manifest(terms, [candidate(1, "Column")]))
    assert by_id(report)[1]["resolution_state"] == "UNRESOLVED_NEEDS_REVIEW"


def test_fuzzy_threshold_is_applied():
    strict = build_ontology_resolution_report(
        manifest(TERMS, [candidate(1, "Collumn")], fuzzy_threshold=1)
    )
    assert by_id(strict)[1]["resolution_state"] == "UNRESOLVED_NEEDS_REVIEW"
    assert strict["fuzzy_threshold"] == 1.0
    assert (
        build_ontology_resolution_report(manifest(TERMS, [candidate(1, "x")]))[
            "fuzzy_threshold"
        ]
        == 0.88
    )


def test_report_is_deterministic_order_independent_and_does_not_mutate_input():
    candidates = [candidate(2, "lip"), candidate(1, "Column")]
    original = manifest(copy.deepcopy(TERMS), candidates)
    snapshot = copy.deepcopy(original)
    first = build_ontology_resolution_report(original)
    second = build_ontology_resolution_report(
        manifest(
            list(reversed(copy.deepcopy(TERMS))),
            list(reversed(copy.deepcopy(candidates))),
        )
    )
    assert original == snapshot
    assert first == second
    assert [item["candidate_id"] for item in first["resolutions"]] == [1, 2]


@pytest.mark.parametrize(
    ("bad_manifest", "detail"),
    [
        (None, "manifest_not_object"),
        ([], "manifest_not_object"),
        (manifest(TERMS, [candidate(1, "a")], extra=1), "unknown_manifest_keys=extra"),
        (manifest(TERMS, [candidate(1, "a")], source=" "), "source_required"),
        (manifest(TERMS, [candidate(1, "a")], source=1), "source_not_string"),
        (
            manifest(TERMS, [candidate(1, "a")], fuzzy_threshold=True),
            "fuzzy_threshold_not_number",
        ),
        (
            manifest(TERMS, [candidate(1, "a")], fuzzy_threshold="0.9"),
            "fuzzy_threshold_not_number",
        ),
        (
            manifest(TERMS, [candidate(1, "a")], fuzzy_threshold=0.5),
            "fuzzy_threshold_out_of_range",
        ),
        (
            manifest(TERMS, [candidate(1, "a")], fuzzy_threshold=float("nan")),
            "fuzzy_threshold_out_of_range",
        ),
        (
            manifest(TERMS, [candidate(1, "a")], fuzzy_threshold=10**400),
            "fuzzy_threshold_out_of_range",
        ),
        (manifest([], [candidate(1, "a")]), "terms_required"),
        (manifest(TERMS, []), "candidates_required"),
        (manifest(["x"], [candidate(1, "a")]), "term_0_not_object"),
        (
            manifest([term(1, "a", status="ACTIVE")], [candidate(1, "a")]),
            "term_0_unknown_fields=status",
        ),
        (manifest([{"term_id": 1}], [candidate(1, "a")]), "term_0_missing_fields="),
        (manifest([term(True, "a")], [candidate(1, "a")]), "term_0_term_id_not_int"),
        (manifest([term("1", "a")], [candidate(1, "a")]), "term_0_term_id_not_int"),
        (manifest([term(0, "a")], [candidate(1, "a")]), "term_0_term_id_out_of_range"),
        (
            manifest([term(1, "a", registry_id=MAX_ID + 1)], [candidate(1, "a")]),
            "term_0_registry_id_out_of_range",
        ),
        (
            manifest([term(1, "a", preferred_label=" ")], [candidate(1, "a")]),
            "term_0_preferred_label_required",
        ),
        (
            manifest([term(1, "a", namespace=None)], [candidate(1, "a")]),
            "term_0_namespace_not_string",
        ),
        (
            manifest([term(1, "a", registry_status="APPROVED")], [candidate(1, "a")]),
            "term_0_registry_status_not_allowed",
        ),
        (
            manifest([term(1, "a", term_status="ACCEPTED")], [candidate(1, "a")]),
            "term_0_term_status_not_allowed",
        ),
        (
            manifest([term(1, "a", synonyms="lip")], [candidate(1, "a")]),
            "term_0_synonyms_not_list",
        ),
        (
            manifest([term(1, "a", synonyms=[1])], [candidate(1, "a")]),
            "term_0_synonym_not_string",
        ),
        (
            manifest([term(1, "a"), term(1, "b")], [candidate(1, "a")]),
            "term_1_duplicate_term_id",
        ),
        (
            manifest(
                [term(1, "a"), term(2, "b", canonical_key="a")], [candidate(1, "a")]
            ),
            "term_1_duplicate_canonical_key",
        ),
        (
            manifest([term(1, "a"), term(2, "b", version="2")], [candidate(1, "a")]),
            "term_1_registry_inconsistent",
        ),
        (
            manifest(
                [term(1, "a"), term(2, "b", registry_status="DRAFT")],
                [candidate(1, "a")],
            ),
            "term_1_registry_inconsistent",
        ),
        (manifest(TERMS, ["a"]), "candidate_0_not_object"),
        (
            manifest(TERMS, [{"candidate_id": 1, "name": "a", "kind": "ENTITY"}]),
            "candidate_0_unknown_fields=kind",
        ),
        (manifest(TERMS, [{"name": "a"}]), "candidate_0_missing_fields=candidate_id"),
        (manifest(TERMS, [candidate(False, "a")]), "candidate_0_candidate_id_not_int"),
        (manifest(TERMS, [candidate(1, "")]), "candidate_0_name_required"),
        (manifest(TERMS, [candidate(1, ["a"])]), "candidate_0_name_not_string"),
        (
            manifest(TERMS, [candidate(1, "a"), candidate(1, "b")]),
            "candidate_1_duplicate_candidate_id",
        ),
    ],
)
def test_out_of_contract_manifest_fails_closed(bad_manifest: Any, detail: str):
    with pytest.raises(ValueError, match=f"^{CODE}:{detail}"):
        build_ontology_resolution_report(bad_manifest)


def test_input_bounds_accept_values_at_the_limit():
    long_text = "a" * MAX_TEXT_LENGTH
    terms = [
        term(
            MAX_ID,
            long_text,
            registry_id=MAX_ID,
            synonyms=[f"s{i}" for i in range(MAX_SYNONYMS_PER_TERM)],
        )
    ]
    terms += [
        term(i, f"t{i}", registry_status="DRAFT", registry_id=2)
        for i in range(1, MAX_TERMS)
    ]
    report = build_ontology_resolution_report(
        manifest(terms, [candidate(MAX_ID, long_text)], source="s" * MAX_SOURCE_LENGTH)
    )
    assert report["summary"]["terms_supplied"] == MAX_TERMS
    assert by_id(report)[MAX_ID]["proposals"][0]["resolution_method"] == "EXACT"

    report = build_ontology_resolution_report(
        manifest(_synonym_terms(MAX_TERM_ROWS // 4, 4), [candidate(1, "zzz")])
    )
    assert report["summary"]["terms_eligible"] == MAX_TERM_ROWS // 4

    rows = [term(i, f"t{i}") for i in range(1, MAX_TERMS + 1)]

    per_candidate = MAX_COMPARISONS // MAX_CANDIDATES
    report = build_ontology_resolution_report(
        manifest(
            rows[:per_candidate],
            [candidate(i, f"c{i}") for i in range(1, MAX_CANDIDATES + 1)],
        )
    )
    assert report["summary"]["candidates_evaluated"] == MAX_CANDIDATES


def _synonym_terms(count: int, synonyms: int) -> list[dict[str, Any]]:
    return [
        term(i, f"t{i}", synonyms=[f"s{i}-{j}" for j in range(synonyms)])
        for i in range(1, count + 1)
    ]


@pytest.mark.parametrize(
    ("bad_manifest", "detail"),
    [
        (
            manifest(TERMS, [candidate(1, "a")], source="s" * (MAX_SOURCE_LENGTH + 1)),
            "source_too_long",
        ),
        (
            manifest(
                [term(i, f"t{i}") for i in range(1, MAX_TERMS + 2)], [candidate(1, "a")]
            ),
            "too_many_terms",
        ),
        (
            manifest(TERMS, [candidate(i, "a") for i in range(1, MAX_CANDIDATES + 2)]),
            "too_many_candidates",
        ),
        (
            manifest([term(1, "a" * (MAX_TEXT_LENGTH + 1))], [candidate(1, "a")]),
            "term_0_canonical_key_too_long",
        ),
        (
            manifest(TERMS, [candidate(1, "a" * (MAX_TEXT_LENGTH + 1))]),
            "candidate_0_name_too_long",
        ),
        (
            manifest(
                [term(1, "a", synonyms=["s"] * (MAX_SYNONYMS_PER_TERM + 1))],
                [candidate(1, "a")],
            ),
            "term_0_too_many_synonyms",
        ),
        (
            manifest(_synonym_terms(MAX_TERM_ROWS // 4 + 1, 4), [candidate(1, "a")]),
            "too_many_term_rows",
        ),
        (
            manifest(
                [
                    term(i, f"t{i}")
                    for i in range(1, MAX_COMPARISONS // MAX_CANDIDATES + 2)
                ],
                [candidate(i, "a") for i in range(1, MAX_CANDIDATES + 1)],
            ),
            "too_many_comparisons",
        ),
    ],
)
def test_input_bounds_fail_closed_past_the_limit(bad_manifest: Any, detail: str):
    with pytest.raises(ValueError, match=f"^{CODE}:{detail}"):
        build_ontology_resolution_report(bad_manifest)


def test_mission_lifecycle_completes_with_review_report():
    service, mission_id = run_mission(
        manifest(TERMS, [candidate(1, "lip"), candidate(2, "sepal")]), key="ontology-1"
    )

    completed = service.get(mission_id)
    assert completed["state"] == "completed"
    output = completed["output_manifest"]
    assert output["artifact_type"] == "ontology_resolution_proposals"
    assert output["review_state"] == "awaiting_human_review"
    assert output["resolutions_persisted"] is False
    assert output["taxonomy_mutated"] is False
    assert service.jobs(mission_id)[0]["state"] == "succeeded"


def test_mission_with_invalid_manifest_fails_and_does_not_complete():
    service, mission_id = run_mission(manifest(TERMS, []), key="ontology-bad")

    mission = service.get(mission_id)
    assert mission["state"] != "completed"
    assert mission["output_manifest"] == {}
    assert CODE in mission["last_error"]


def test_handler_module_has_no_provider_network_or_db_imports():
    source = Path("app/missions/ontology_resolution.py").read_text(encoding="utf-8")
    for token in (
        "anthropic",
        "openai",
        "requests",
        "httpx",
        "urllib",
        "psycopg",
        "subprocess",
        "socket",
        "repositories",
        "app.ontology.dependencies",
        "CandidateResolutionService",
    ):
        assert token not in source, token
