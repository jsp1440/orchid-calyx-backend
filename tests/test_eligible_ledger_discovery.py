from datetime import datetime, timezone
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.reasoning_publication.routes import eligible_for_publication
from scripts import discover_eligible_reasoning_ledgers as discovery


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.statement = ""
        self.parameters = None
        self.rollbacks = 0

    def execute(self, statement, parameters):
        self.statement = str(statement)
        self.parameters = parameters
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(all=lambda: self.rows)
        )

    def rollback(self):
        self.rollbacks += 1


def approved_row():
    review_hash = "a" * 64
    return {
        "ledger_id": "ledger-123",
        "project_id": "project-456",
        "current_version": 7,
        "current_content_hash": "b" * 64,
        "updated_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
        "canonical_payload": {
            "title": "Reviewed orchid assertion",
            "version": 7,
            "review_content_hash": review_hash,
            "review_decisions": [
                {
                    "decision_id": "decision-789",
                    "reviewer": "human-reviewer",
                    "outcome": "approved",
                    "ledger_version": 7,
                    "reviewed_content_hash": review_hash,
                    "decided_at": "2026-08-05T00:00:00+00:00",
                }
            ],
        },
    }


def test_endpoint_requires_authentication():
    with pytest.raises(HTTPException) as error:
        eligible_for_publication(SimpleNamespace(), {}, FakeDb([]))

    assert error.value.status_code == 401
    assert error.value.detail == {"code": "AUTHENTICATED_SUBJECT_REQUIRED"}


def test_endpoint_is_read_only_and_returns_exact_eligible_revision(monkeypatch):
    db = FakeDb([approved_row()])
    monkeypatch.setattr(
        "app.reasoning_publication.routes.ExistingKnowledgeGraphPublicationGate.from_environment",
        lambda: (_ for _ in ()).throw(AssertionError("publication gate invoked")),
    )

    result = eligible_for_publication(
        SimpleNamespace(), {"actor": "owner"}, db
    )

    assert db.statement.lstrip().upper().startswith("SELECT")
    assert re.search(r"\b(INSERT|UPDATE|DELETE)\b", db.statement.upper()) is None
    assert db.parameters == {"owner": "owner"}
    assert result["result"] == "ELIGIBLE_LEDGER_FOUND"
    assert result["read_only"] is True
    assert result["production_mutation"] is False
    assert result["publication_endpoint_invoked"] is False
    assert result["eligible_ledgers"][0]["ledger_id"] == "ledger-123"
    assert result["eligible_ledgers"][0]["version"] == 7
    assert result["eligible_ledgers"][0]["review_content_hash"] == "a" * 64


def test_endpoint_returns_clear_no_eligible_ledger_result():
    result = eligible_for_publication(
        SimpleNamespace(), {"actor": "owner"}, FakeDb([])
    )

    assert result["result"] == "NO_ELIGIBLE_LEDGER"
    assert result["eligible_count"] == 0
    assert result["eligible_ledgers"] == []


def test_operator_discovery_never_calls_publication_endpoint(monkeypatch):
    calls = []

    def fake_call(path, method="GET", payload=None, token=""):
        calls.append((path, method, payload, token))
        if path.endswith("session-token"):
            return 200, {"token": "owner-token"}
        return 200, {
            "result": "ELIGIBLE_LEDGER_FOUND",
            "eligible_count": 1,
            "eligible_ledgers": [
                {
                    "ledger_id": "ledger-123",
                    "version": 7,
                    "review_content_hash": "a" * 64,
                }
            ],
        }

    monkeypatch.setattr(discovery, "ACCESS_CODE", "configured-owner-code")
    monkeypatch.setattr(discovery, "call", fake_call)

    result = discovery.discover()

    assert [call[0] for call in calls] == [
        "/api/mission-control/owner/session-token",
        "/api/reasoning-ledgers/eligible-for-publication",
    ]
    assert all("/publish" not in call[0] for call in calls)
    assert result["publication_endpoint_invoked"] is False
    assert result["eligible_ledgers"][0] == {
        "ledger_id": "ledger-123",
        "version": 7,
        "review_content_hash": "a" * 64,
    }
