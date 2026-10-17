"""Deterministic tests for the literature_ingestion_review mission handler (#1731)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from app.missions.literature_review import (
    MAX_AUTHORS,
    MAX_EVIDENCE_SPAN_LENGTH,
    MAX_EVIDENCE_SPANS,
    MAX_RECORDS,
    MAX_STRING_LENGTH,
    build_literature_ingestion_review,
)
from app.missions.registry import MISSION_TYPES
from app.missions.repositories import InMemoryMissionRepository
from app.missions.services import MissionService


def manifest(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source": "fixture-bibliography",
        "records": [
            {
                "source_record_id": "rec-1",
                "doi": "10.1000/fixture.1",
                "title": "Pollinator observations in a fixture orchid",
                "authors": ["A. Author", "B. Author"],
                "publication_year": 2019,
                "taxon_name": "Fixture orchid",
                "evidence_spans": [{"page": 3, "text": "visited by bees"}],
            },
            {"source_record_id": "rec-1", "title": "Duplicate of rec-1"},
            {"source_record_id": "rec-2", "title": "No taxon given"},
        ],
    }
    data.update(overrides)
    return data


def mission_payload(
    input_manifest: dict[str, Any], key: str = "lit-review-1"
) -> dict[str, Any]:
    return {
        "mission_key": key,
        "title": "Literature ingestion review",
        "description": "Stage bibliographic metadata for human review.",
        "mission_type": "literature_ingestion_review",
        "requested_by": "owner",
        "priority": 50,
        "maximum_runs": 1,
        "input_manifest": input_manifest,
        "allowed_actions": ["stage_for_review"],
        "prohibited_actions": [
            "taxonomy_write",
            "canonical_graph_publish",
            "external_api_call",
        ],
        "idempotency_key": key,
    }


def run_mission(
    input_manifest: dict[str, Any], key: str = "lit-review-1"
) -> tuple[MissionService, int]:
    service = MissionService(InMemoryMissionRepository())
    mission = service.create(
        mission_payload(input_manifest, key), {"auth_type": "owner_session"}
    )
    mission_id = mission["mission_id"]
    service.submit(mission_id, "owner", "ready")
    service.approve(mission_id, "owner", "approve", "approval-1731")
    service.queue(mission_id, "owner", "queue")
    service.execute_cycle("worker-lit")
    return service, mission_id


def test_registry_contract_preserves_limits():
    mission_type = MISSION_TYPES["literature_ingestion_review"]
    assert mission_type.handler == "literature_ingestion_review"
    assert mission_type.risk_level == "medium"
    assert mission_type.write_scope == "read_only"
    assert mission_type.allowed_database_schemas == ()
    assert "oc_taxonomy" in mission_type.forbidden_database_schemas
    assert mission_type.human_approval_required is True
    assert mission_type.publication_authority_required is False
    assert mission_type.canonical_graph_writes_permitted is False
    assert mission_type.taxonomy_writes_prohibited is True


def test_packet_is_human_review_only_and_never_asserts_canonical_identity():
    packet = build_literature_ingestion_review(manifest())

    assert packet["review_state"] == "awaiting_human_review"
    assert packet["human_review_required"] is True
    assert packet["scientific_authority"] == "none"
    for flag in (
        "scientific_conclusions_published",
        "approval_recorded",
        "provider_called",
        "external_network_called",
        "domain_database_written",
        "canonical_graph_mutated",
        "taxonomy_mutated",
    ):
        assert packet[flag] is False, flag

    staged = packet["staged_records"]
    assert [record["source_record_id"] for record in staged] == ["rec-1", "rec-2"]
    assert all(record["canonical_taxon_id"] is None for record in staged)
    assert all(
        record["reconciliation_state"] == "reconciliation_unavailable"
        for record in staged
    )
    assert staged[0]["publication_year"] == 2019
    assert staged[0]["evidence_spans"] == [{"page": 3, "text": "visited by bees"}]
    assert [item["source_record_id"] for item in packet["review_queue"]] == [
        "rec-1",
        "rec-2",
    ]
    assert packet["summary"]["duplicate_skipped"] == 1
    assert packet["duplicate_source_record_ids_dropped"] == ["rec-1"]
    assert packet["summary"]["no_production_mutation"] is True


def test_packet_is_deterministic_and_does_not_mutate_input():
    original = manifest()
    snapshot = copy.deepcopy(original)
    first = build_literature_ingestion_review(original)
    second = build_literature_ingestion_review(copy.deepcopy(original))
    assert first == second
    assert len(first["packet_digest"]) == 64
    assert original == snapshot


@pytest.mark.parametrize(
    "bad_manifest",
    [
        {},
        {"source": "", "records": [{"source_record_id": "x"}]},
        {"source": "s", "records": []},
        {"source": "s", "records": "not-a-list"},
        {"source": "s", "records": [1]},
        {"source": "s", "records": [{"source_record_id": "x"}], "publish": True},
        {
            "source": "s",
            "records": [{"source_record_id": "x", "canonical_taxon_id": "T1"}],
        },
        {
            "source": "s",
            "records": [{"source_record_id": "x", "review_state": "approved"}],
        },
        {
            "source": "s",
            "records": [{"source_record_id": "x", "evidence_spans": ["text"]}],
        },
        {
            "source": "s",
            "records": [{"source_record_id": str(i)} for i in range(MAX_RECORDS + 1)],
        },
    ],
)
def test_out_of_contract_manifest_fails_closed(bad_manifest: dict[str, Any]):
    with pytest.raises(ValueError, match="LITERATURE_REVIEW_MANIFEST_INVALID"):
        build_literature_ingestion_review(bad_manifest)


def test_mission_lifecycle_completes_with_review_packet():
    service, mission_id = run_mission(manifest())

    completed = service.get(mission_id)
    assert completed["state"] == "completed"
    output = completed["output_manifest"]
    assert output["artifact_type"] == "literature_ingestion_review_packet"
    assert output["review_state"] == "awaiting_human_review"
    assert output["canonical_graph_mutated"] is False
    assert output["taxonomy_mutated"] is False
    assert service.jobs(mission_id)[0]["state"] == "succeeded"


def test_mission_with_invalid_manifest_fails_and_does_not_complete():
    service, mission_id = run_mission(
        {"source": "s", "records": []}, key="lit-review-bad"
    )

    mission = service.get(mission_id)
    assert mission["state"] != "completed"
    assert mission["output_manifest"] == {}
    assert "LITERATURE_REVIEW_MANIFEST_INVALID" in mission["last_error"]


def test_handler_module_has_no_provider_network_or_db_imports():
    source = Path("app/missions/literature_review.py").read_text(encoding="utf-8")
    for token in (
        "anthropic",
        "openai",
        "requests",
        "httpx",
        "urllib",
        "psycopg",
        "subprocess",
        "socket",
    ):
        assert token not in source, token


def _one(**fields: Any) -> dict[str, Any]:
    return {"source": "s", "records": [{"source_record_id": "x", **fields}]}


LONG = "a" * (MAX_STRING_LENGTH + 1)


@pytest.mark.parametrize(
    ("bad_manifest", "detail"),
    [
        (_one(authors=5), "authors_not_string"),
        (_one(authors=["ok", 5]), "authors_not_string"),
        (_one(title={"text": "t"}), "title_not_string"),
        (_one(doi=["10.1/x"]), "doi_not_string"),
        (_one(taxon_name=7), "taxon_name_not_string"),
        (
            {"source": "s", "records": [{"source_record_id": 9}]},
            "source_record_id_not_string",
        ),
        (_one(publication_year=True), "publication_year_not_int"),
        (_one(publication_year="2019"), "publication_year_not_int"),
        (_one(publication_year=2019.0), "publication_year_not_int"),
        (_one(title=LONG), "title_too_long"),
        (_one(doi=LONG), "doi_too_long"),
        (_one(taxon_name=LONG), "taxon_name_too_long"),
        (_one(authors=LONG), "authors_too_long"),
        (_one(authors=[LONG]), "authors_too_long"),
        (_one(authors=["a"] * (MAX_AUTHORS + 1)), "too_many_authors"),
        (
            {"source": "s", "records": [{"source_record_id": LONG}]},
            "source_record_id_too_long",
        ),
        ({"source": LONG, "records": [{"source_record_id": "x"}]}, "source_too_long"),
        (
            _one(evidence_spans=[{"page": i} for i in range(MAX_EVIDENCE_SPANS + 1)]),
            "too_many_evidence_spans",
        ),
        (
            _one(evidence_spans=[{"text": "a" * MAX_EVIDENCE_SPAN_LENGTH}]),
            "evidence_span_too_long",
        ),
        (_one(evidence_spans=[{"text": {1, 2}}]), "evidence_span_not_json"),
    ],
)
def test_field_types_and_bounds_fail_closed_with_coded_prefix(
    bad_manifest: dict[str, Any], detail: str
):
    with pytest.raises(
        ValueError, match=f"LITERATURE_REVIEW_MANIFEST_INVALID:.*{detail}"
    ):
        build_literature_ingestion_review(bad_manifest)


def test_fields_at_their_bounds_are_accepted():
    at_limit = "a" * MAX_STRING_LENGTH
    packet = build_literature_ingestion_review(
        _one(
            title=at_limit,
            doi=None,
            authors=["a"] * MAX_AUTHORS,
            publication_year=None,
            evidence_spans=[{"page": i} for i in range(MAX_EVIDENCE_SPANS)],
        )
    )
    assert packet["staged_records"][0]["title"] == at_limit
    assert len(packet["staged_records"][0]["evidence_spans"]) == MAX_EVIDENCE_SPANS
    assert packet["duplicate_source_record_ids_dropped"] == []


def test_every_duplicate_drop_is_listed_in_order():
    packet = build_literature_ingestion_review(
        {
            "source": "s",
            "records": [
                {"source_record_id": "a"},
                {"source_record_id": "b"},
                {"source_record_id": "a"},
                {"source_record_id": "b"},
                {"source_record_id": "a"},
                {"title": "no id"},
            ],
        }
    )
    assert packet["duplicate_source_record_ids_dropped"] == ["a", "b", "a"]
    assert packet["summary"]["duplicate_skipped"] == 3
    assert [r["source_record_id"] for r in packet["staged_records"]] == ["a", "b"]
