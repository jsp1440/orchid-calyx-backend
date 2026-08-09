from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.taxonomy_releases import create_taxonomy_release_router
from runtime import world_plants_activation_decision as decision


class FakeStore:
    engine = object()

    def __init__(self, *, completed: bool, staged: int, rows: int, report: dict | None):
        self._completed = completed
        self._staged = staged
        self._rows = rows
        self._report = report

    def get(self, release_id: str):
        if release_id != "release-1":
            return None
        return {
            "release_id": release_id,
            "state": "review_required",
            "snapshot": {
                "sha256": "a" * 64,
                "version_label": "26-08",
                "filename": "WorldOrchids 26-08 (Aug 2 2026).csv",
                "acquired_at": "2026-08-02",
                "row_count": self._rows,
            },
            "automatic_promotion": False,
        }

    def checkpoint(self, release_id: str):
        return {
            "next_row_index": self._staged,
            "staged_count": self._staged,
            "completed": self._completed,
            "updated_at": "2026-08-08T20:00:00+00:00",
        }

    def counts(self, release_id: str):
        return {"staged": self._staged, "open_review": 0}

    def change_report(self, release_id: str):
        return self._report


REPORT = {
    "baseline_release_id": "baseline-1",
    "summary": {
        "current_rows": 34724,
        "baseline_rows": 34675,
        "added_taxa": 65,
        "removed_taxa": 17,
        "changed_records": 4461,
        "synonym_changes": 562,
        "status_changes": 0,
        "distribution_changes": 3781,
        "accepted_name_change_candidates": 0,
        "duplicate_identities": 1,
        "malformed_rows": 1,
    },
    "interpretation_note": "Review change evidence before activation.",
}


def test_open_review_items_hold_activation_decision(monkeypatch):
    store = FakeStore(completed=True, staged=34724, rows=34724, report=REPORT)
    monkeypatch.setattr(
        decision,
        "_open_review_items",
        lambda store, release_id: [
            {
                "review_key": "duplicate:S:Gastrochilus wenchuanensis",
                "category": "duplicate_identity",
                "summary": "Duplicate taxon identity requires review",
                "evidence": {"count": 2},
                "status": "open",
                "updated_at": "2026-08-08T20:00:00+00:00",
            }
        ],
    )

    packet = decision.build_activation_decision_packet(store, "release-1")

    assert packet["decision_state"] == "HOLD"
    assert packet["ready_for_owner_activation_decision"] is False
    assert packet["blockers"] == ["OPEN_TAXONOMY_REVIEW_ITEMS"]
    assert packet["open_review_count"] == 1
    assert packet["activation_authorized"] is False
    assert packet["activation_invoked"] is False
    assert packet["production_taxonomy_mutation_authorized"] is False
    assert packet["knowledge_graph_mutation_authorized"] is False


def test_completed_reviewed_evidence_is_ready_only_for_owner_decision(monkeypatch):
    store = FakeStore(completed=True, staged=34724, rows=34724, report=REPORT)
    monkeypatch.setattr(decision, "_open_review_items", lambda store, release_id: [])

    packet = decision.build_activation_decision_packet(store, "release-1")

    assert packet["decision_state"] == "READY_FOR_OWNER_ACTIVATION_DECISION"
    assert packet["ready_for_owner_activation_decision"] is True
    assert packet["blockers"] == []
    assert packet["owner_approval_required"] is True
    assert packet["activation_authorized"] is False
    assert packet["automatic_promotion"] is False
    assert packet["read_only"] is True


def test_incomplete_staging_and_missing_report_fail_closed(monkeypatch):
    store = FakeStore(completed=False, staged=2000, rows=34724, report=None)
    monkeypatch.setattr(decision, "_open_review_items", lambda store, release_id: [])

    packet = decision.build_activation_decision_packet(store, "release-1")

    assert packet["decision_state"] == "HOLD"
    assert packet["blockers"] == ["STAGING_INCOMPLETE", "CHANGE_REPORT_MISSING"]
    assert packet["ready_for_owner_activation_decision"] is False


def test_owner_gated_activation_decision_route_is_read_only(monkeypatch):
    store = FakeStore(completed=True, staged=34724, rows=34724, report=REPORT)
    monkeypatch.setattr(decision, "_open_review_items", lambda store, release_id: [])

    app = FastAPI()
    app.include_router(
        create_taxonomy_release_router(
            require_owner=lambda: {"subject": "owner"},
            get_durable_store=lambda: store,
            get_migration_preflight=lambda: {"schema_complete": True},
        )
    )
    response = TestClient(app).get(
        "/api/mission-control/taxonomy/releases/release-1/activation-decision"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready_for_owner_activation_decision"] is True
    assert payload["activation_authorized"] is False
    assert payload["activation_invoked"] is False
    assert payload["read_only"] is True
