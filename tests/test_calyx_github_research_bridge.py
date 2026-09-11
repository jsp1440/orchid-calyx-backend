from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.github_research_bridge import router
from app.routers.owner_operations import MEMORY

_SECRET = "bridge-test-secret"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _configure(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv(
        "CALYX_GITHUB_RESEARCH_REPOSITORIES",
        "jsp1440/Orchid-Continuum-Brain",
    )
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_AUTHORS", "jsp1440")
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_LABEL", "calyx-research")
    monkeypatch.setenv("CALYX_API_KEY", "readiness-key")
    for rows in MEMORY.values():
        rows.clear()


def _payload(
    *,
    repository: str = "jsp1440/Orchid-Continuum-Brain",
    author: str = "jsp1440",
    labels: list[str] | None = None,
    body: str | None = None,
) -> dict:
    return {
        "action": "labeled",
        "repository": {"full_name": repository},
        "issue": {
            "number": 101,
            "title": "Five orchid investigation",
            "body": body
            or (
                "## Story taxa\n"
                "1. *Calypso bulbosa*\n"
                "2. *Pleione humilis*\n\n"
                "## Required outputs\n"
                "1. Evidence dossiers\n"
                "2. Relationship matrix\n"
            ),
            "html_url": (
                "https://github.com/jsp1440/Orchid-Continuum-Brain/issues/101"
            ),
            "state": "open",
            "created_at": "2026-08-25T06:48:25Z",
            "updated_at": "2026-08-25T06:48:25Z",
            "user": {"login": author},
            "labels": [
                {"name": name} for name in (labels or ["calyx-research"])
            ],
        },
        "sender": {"login": author},
    }


def _post(api: TestClient, payload: dict, *, delivery: str = "delivery-1"):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(
        _SECRET.encode(), raw, hashlib.sha256
    ).hexdigest()
    return api.post(
        "/api/integrations/github/research/issues",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": signature,
        },
    )


def test_signed_allowlisted_issue_creates_one_existing_queue_request(
    monkeypatch,
) -> None:
    _configure(monkeypatch)
    response = _post(_client(), _payload())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued_waiting_for_executor"
    assert data["created"] is True
    request = data["research_request"]
    assert request["id"].startswith("RSR-GH-")
    assert request["taxa"] == ["Calypso bulbosa", "Pleione humilis"]
    assert request["requested_outputs"] == [
        "Evidence dossiers",
        "Relationship matrix",
    ]
    assert request["provenance"]["source_issue_number"] == 101
    assert request["provenance"]["source_repository"] == (
        "jsp1440/Orchid-Continuum-Brain"
    )
    assert len(MEMORY["research_requests"]) == 1
    assert data["authority"]["knowledge_graph_mutation"] is False


def test_replayed_or_revised_issue_is_idempotent(monkeypatch) -> None:
    _configure(monkeypatch)
    api = _client()
    first = _post(api, _payload(), delivery="delivery-1")
    second = _post(api, _payload(), delivery="delivery-2")
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["created"] is False
    assert (
        second.json()["research_request"]["id"]
        == first.json()["research_request"]["id"]
    )
    assert len(MEMORY["research_requests"]) == 1


def test_invalid_signature_fails_closed(monkeypatch) -> None:
    _configure(monkeypatch)
    raw = json.dumps(_payload()).encode()
    response = _client().post(
        "/api/integrations/github/research/issues",
        content=raw,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": "sha256=invalid",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == (
        "GITHUB_RESEARCH_SIGNATURE_INVALID"
    )
    assert MEMORY["research_requests"] == []


def test_repository_author_and_label_are_independently_enforced(
    monkeypatch,
) -> None:
    _configure(monkeypatch)
    api = _client()
    denied_repo = _post(api, _payload(repository="other/repo"))
    denied_author = _post(api, _payload(author="someone-else"))
    denied_label = _post(api, _payload(labels=["documentation"]))
    assert denied_repo.status_code == 403
    assert denied_repo.json()["detail"]["code"] == (
        "GITHUB_RESEARCH_REPOSITORY_NOT_ALLOWED"
    )
    assert denied_author.status_code == 403
    assert denied_author.json()["detail"]["code"] == (
        "GITHUB_RESEARCH_AUTHOR_NOT_ALLOWED"
    )
    assert denied_label.status_code == 403
    assert denied_label.json()["detail"]["code"] == (
        "GITHUB_RESEARCH_OPT_IN_LABEL_REQUIRED"
    )
    assert MEMORY["research_requests"] == []


def test_oversize_payload_is_rejected_before_json_processing(monkeypatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_MAX_PAYLOAD_BYTES", "1024")
    response = _post(_client(), _payload(body="x" * 2000))
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == (
        "GITHUB_RESEARCH_PAYLOAD_TOO_LARGE"
    )
    assert MEMORY["research_requests"] == []


def test_readiness_is_protected_and_secret_safe(monkeypatch) -> None:
    _configure(monkeypatch)
    api = _client()
    denied = api.get("/api/integrations/github/research/readiness")
    assert denied.status_code == 401
    response = api.get(
        "/api/integrations/github/research/readiness",
        headers={"X-API-Key": "readiness-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["configured"] is True
    assert data["webhook_secret_configured"] is True
    assert _SECRET not in response.text
    assert data["executor_status"] == "not_activated"
