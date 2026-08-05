"""Tests for CALYX CORE 4 — Minimal operator UI and end-to-end certification.

Covers issue #388 acceptance criteria:
- Browser/API test covers question → evidence → Reasoning Ledger → review pending.
- Approved fixture can be discovered automatically by the UI.
- Publication remains impossible without owner confirmation.
- One supervised production demonstration produces an auditable graph version
  or an explicit no-eligible-ledger result.
- Duplicate replay is a no-op.
- UI displays plain-language errors and never asks the owner to copy
  ledger hashes or workflow names.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Return a TestClient with owner auth bypassed via API key."""
    import os

    os.environ.setdefault("CALYX_API_KEY", "test-api-key-lane4")
    os.environ.setdefault("CALYX_OWNER_SESSION_SECRET", "test-secret-lane4")

    # Reset in-memory stores before each test for isolation
    from app.routers import calyx_operator_workflow as wf

    wf._MISSIONS.clear()
    wf._LEDGER_REVIEWS.clear()
    wf._PUBLICATIONS.clear()

    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-api-key-lane4"}


# ---------------------------------------------------------------------------
# 1. Operator panel smoke test
# ---------------------------------------------------------------------------


def test_operator_panel_returns_structure(client: TestClient):
    """Panel endpoint returns the expected operator-facing structure."""
    resp = client.get(
        "/api/mission-control/calyx-operator/panel",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    panel = body["operator_panel"]
    assert "active_missions" in panel
    assert "pending_review_ledgers" in panel
    assert "eligible_for_publication" in panel
    assert "automatic_publication" in panel
    assert panel["automatic_publication"] is False
    assert panel["human_review_mandatory"] is True
    assert "plain_language_status" in panel
    assert isinstance(panel["plain_language_status"], str)


# ---------------------------------------------------------------------------
# 2. Start mission → evidence → ledger → review pending
# ---------------------------------------------------------------------------


def test_start_mission_laelia_anceps_lifecycle(client: TestClient):
    """Full lifecycle: question → plan → evidence → ledger → human_review_required."""
    payload = {
        "question": "What is the taxonomy, distribution, and mycorrhizal ecology of Laelia anceps?",
        "taxon_hint": "Laelia anceps",
        "max_sources": 5,
    }
    resp = client.post(
        "/api/mission-control/calyx-operator/missions",
        json=payload,
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()

    # Status must be human_review_required — never auto-published
    assert body["status"] == "human_review_required"
    assert body["publication_eligible"] is False
    assert body["automatic_publication"] is False

    # Evidence must be present
    assert body["evidence_count"] > 0

    # Plan must be bounded
    plan = body["plan"]
    assert plan["bounded"] is True
    assert plan["automatic_publication"] is False
    assert plan["human_review_mandatory"] is True

    # Ledger must exist and be pending review
    assert "ledger_id" in body
    assert body["ledger_review_state"] == "pending"

    # Gaps are reported (not hidden)
    assert isinstance(body["gaps"], list)

    # Mission ID returned
    assert "mission_id" in body
    assert "ledger_id" in body


def test_get_mission_state(client: TestClient):
    """GET /missions/{id} returns current operator-facing state."""
    # First create a mission
    create_resp = client.post(
        "/api/mission-control/calyx-operator/missions",
        json={
            "question": "Describe the pollination biology of Laelia anceps.",
            "taxon_hint": "Laelia anceps",
        },
        headers=_auth_headers(),
    )
    assert create_resp.status_code == 200
    mission_id = create_resp.json()["mission_id"]

    resp = client.get(
        f"/api/mission-control/calyx-operator/missions/{mission_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mission_id"] == mission_id
    assert body["status"] == "human_review_required"
    assert body["publication_eligible"] is False
    assert "evidence_count" in body
    assert "contradictions" in body
    assert "gaps" in body
    assert "blockers" in body


def test_get_mission_not_found(client: TestClient):
    """GET /missions/{id} for unknown mission returns 404."""
    resp = client.get(
        "/api/mission-control/calyx-operator/missions/nonexistent-mission-id",
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. Ledger discovery — eligible ledgers endpoint
# ---------------------------------------------------------------------------


def test_list_eligible_ledgers_empty_initially(client: TestClient):
    """No eligible ledgers when none have been approved."""
    resp = client.get(
        "/api/mission-control/calyx-operator/ledgers/eligible",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["eligible_ledgers"] == []
    assert body["automatic_publication"] is False


def test_approved_ledger_appears_in_eligible_list(client: TestClient):
    """After approval, ledger appears in the eligible discovery endpoint."""
    # Create mission
    create_resp = client.post(
        "/api/mission-control/calyx-operator/missions",
        json={
            "question": "Conservation status of Laelia anceps in Mexico.",
            "taxon_hint": "Laelia anceps",
        },
        headers=_auth_headers(),
    )
    ledger_id = create_resp.json()["ledger_id"]

    # Approve the ledger
    review_resp = client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "approve",
            "rationale": "Evidence is accurate; sources are cited; gaps are acknowledged.",
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    assert review_resp.status_code == 200
    assert review_resp.json()["publication_eligible"] is True

    # Eligible ledger must now appear
    eligible_resp = client.get(
        "/api/mission-control/calyx-operator/ledgers/eligible",
        headers=_auth_headers(),
    )
    assert eligible_resp.status_code == 200
    body = eligible_resp.json()
    assert body["count"] == 1
    assert body["eligible_ledgers"][0]["ledger_id"] == ledger_id


# ---------------------------------------------------------------------------
# 4. Ledger review — approve / request_revision / reject
# ---------------------------------------------------------------------------


def _create_mission_and_get_ledger(client: TestClient) -> str:
    resp = client.post(
        "/api/mission-control/calyx-operator/missions",
        json={
            "question": "Describe the distribution range of Laelia anceps across Central America.",
            "taxon_hint": "Laelia anceps",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()["ledger_id"]


def test_review_decision_approve(client: TestClient):
    ledger_id = _create_mission_and_get_ledger(client)
    resp = client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "approve",
            "rationale": "Evidence verified; scientific quality confirmed.",
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_state"] == "approved"
    assert body["publication_eligible"] is True


def test_review_decision_request_revision(client: TestClient):
    ledger_id = _create_mission_and_get_ledger(client)
    resp = client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "request_revision",
            "rationale": "Missing mycorrhizal evidence; please add source citation.",
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_state"] == "revision_requested"
    assert body["publication_eligible"] is False


def test_review_decision_reject(client: TestClient):
    ledger_id = _create_mission_and_get_ledger(client)
    resp = client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "reject",
            "rationale": "Evidence sources are unreliable.",
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_state"] == "rejected"
    assert body["publication_eligible"] is False


def test_ledger_not_found(client: TestClient):
    resp = client.get(
        "/api/mission-control/calyx-operator/ledgers/nonexistent-id",
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Supervised publication safeguards
# ---------------------------------------------------------------------------


def test_publication_without_confirmation_rejected(client: TestClient):
    """Publication must be impossible without explicit_owner_confirmation=true."""
    ledger_id = _create_mission_and_get_ledger(client)
    # Approve first
    client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "approve",
            "rationale": "Evidence verified by reviewer.",
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    # Try to publish without confirmation
    resp = client.post(
        "/api/mission-control/calyx-operator/publications",
        json={
            "ledger_id": ledger_id,
            "explicit_owner_confirmation": False,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 403
    assert "explicit_owner_confirmation" in resp.json()["detail"].lower()


def test_publication_of_unapproved_ledger_rejected(client: TestClient):
    """Publication of a non-approved ledger must be rejected."""
    ledger_id = _create_mission_and_get_ledger(client)
    # Do NOT approve — ledger is still pending
    resp = client.post(
        "/api/mission-control/calyx-operator/publications",
        json={
            "ledger_id": ledger_id,
            "explicit_owner_confirmation": True,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 422


def test_supervised_publication_with_explicit_confirmation(client: TestClient):
    """Supervised publication with explicit confirmation produces an auditable record."""
    ledger_id = _create_mission_and_get_ledger(client)
    # Approve
    client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "approve",
            "rationale": "Verified by reviewer.",
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    # Publish with explicit confirmation
    resp = client.post(
        "/api/mission-control/calyx-operator/publications",
        json={
            "ledger_id": ledger_id,
            "explicit_owner_confirmation": True,
            "publication_note": "Demonstration publication for Laelia anceps.",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["idempotent"] is False
    assert "publication_id" in body
    assert "graph_version" in body
    assert body["automatic_publication"] is False
    assert body["status"] == "staged_for_review"
    # No production graph mutation
    assert "staged" in body["message"].lower()


def test_duplicate_publication_is_noop(client: TestClient):
    """Replaying publication for the same ledger is idempotent — no duplicate action."""
    ledger_id = _create_mission_and_get_ledger(client)
    # Approve
    client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "approve",
            "rationale": "Evidence verified by reviewer.",
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    # First publication
    resp1 = client.post(
        "/api/mission-control/calyx-operator/publications",
        json={
            "ledger_id": ledger_id,
            "explicit_owner_confirmation": True,
        },
        headers=_auth_headers(),
    )
    assert resp1.status_code == 200
    publication_id = resp1.json()["publication_id"]

    # Duplicate replay
    resp2 = client.post(
        "/api/mission-control/calyx-operator/publications",
        json={
            "ledger_id": ledger_id,
            "explicit_owner_confirmation": True,
        },
        headers=_auth_headers(),
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["idempotent"] is True
    assert body2["publication_id"] == publication_id
    assert "duplicate" in body2["message"].lower()


# ---------------------------------------------------------------------------
# 6. Graph version endpoint
# ---------------------------------------------------------------------------


def test_graph_version_before_any_publication(client: TestClient):
    resp = client.get(
        "/api/mission-control/calyx-operator/graph/version",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_graph_version"] is None
    assert body["automatic_publication"] is False
    assert body["human_review_mandatory"] is True


def test_graph_version_after_publication(client: TestClient):
    """Graph version is updated after a supervised publication."""
    ledger_id = _create_mission_and_get_ledger(client)
    client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "approve",
            "rationale": "Evidence verified by reviewer.",
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    client.post(
        "/api/mission-control/calyx-operator/publications",
        json={"ledger_id": ledger_id, "explicit_owner_confirmation": True},
        headers=_auth_headers(),
    )
    resp = client.get(
        "/api/mission-control/calyx-operator/graph/version",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_graph_version"] is not None
    assert body["total_publications"] == 1


# ---------------------------------------------------------------------------
# 7. Full end-to-end: question → evidence → ledger → review → publication
# ---------------------------------------------------------------------------


def test_full_e2e_laelia_anceps_workflow(client: TestClient):
    """Full end-to-end scenario from issue #388: Laelia anceps mission."""
    # Step 1: Start the mission
    start_resp = client.post(
        "/api/mission-control/calyx-operator/missions",
        json={
            "question": (
                "Describe the taxonomy, distribution, pollination biology, "
                "conservation status, and mycorrhizal ecology of Laelia anceps."
            ),
            "taxon_hint": "Laelia anceps",
            "max_sources": 10,
        },
        headers=_auth_headers(),
    )
    assert start_resp.status_code == 200
    start = start_resp.json()
    assert start["status"] == "human_review_required"
    assert start["publication_eligible"] is False
    mission_id = start["mission_id"]
    ledger_id = start["ledger_id"]

    # Step 2: Inspect mission state
    state_resp = client.get(
        f"/api/mission-control/calyx-operator/missions/{mission_id}",
        headers=_auth_headers(),
    )
    assert state_resp.status_code == 200
    state = state_resp.json()
    assert state["evidence_count"] > 0
    assert state["ledger_review_state"] == "pending"

    # Step 3: Inspect ledger
    ledger_resp = client.get(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}",
        headers=_auth_headers(),
    )
    assert ledger_resp.status_code == 200
    ledger = ledger_resp.json()
    assert ledger["review_state"] == "pending"
    assert ledger["publication_eligible"] is False

    # Step 4: Check operator panel — ledger pending review
    panel_resp = client.get(
        "/api/mission-control/calyx-operator/panel",
        headers=_auth_headers(),
    )
    panel = panel_resp.json()["operator_panel"]
    assert panel["pending_review_ledgers"] == 1
    assert panel["eligible_for_publication"] == 0

    # Step 5: Approve the ledger
    review_resp = client.post(
        f"/api/mission-control/calyx-operator/ledgers/{ledger_id}/review",
        json={
            "decision": "approve",
            "rationale": (
                "Taxonomy confirmed against GBIF. Distribution evidence verified. "
                "Gaps in mycorrhizal and conservation data acknowledged and documented."
            ),
            "reviewer_id": "owner-jsp1440",
        },
        headers=_auth_headers(),
    )
    assert review_resp.status_code == 200
    assert review_resp.json()["review_state"] == "approved"

    # Step 6: Eligible ledger discovered automatically (no ID copying needed)
    eligible_resp = client.get(
        "/api/mission-control/calyx-operator/ledgers/eligible",
        headers=_auth_headers(),
    )
    eligible = eligible_resp.json()
    assert eligible["count"] == 1
    discovered_ledger_id = eligible["eligible_ledgers"][0]["ledger_id"]
    assert discovered_ledger_id == ledger_id  # No manual ID lookup needed

    # Step 7: Supervised publication with explicit owner confirmation
    pub_resp = client.post(
        "/api/mission-control/calyx-operator/publications",
        json={
            "ledger_id": discovered_ledger_id,
            "explicit_owner_confirmation": True,
            "publication_note": "Laelia anceps mission — demonstration publication.",
        },
        headers=_auth_headers(),
    )
    assert pub_resp.status_code == 200
    pub = pub_resp.json()
    assert pub["idempotent"] is False
    assert pub["automatic_publication"] is False
    pub_id = pub["publication_id"]

    # Step 8: Audit record accessible
    audit_resp = client.get(
        f"/api/mission-control/calyx-operator/publications/{pub_id}",
        headers=_auth_headers(),
    )
    assert audit_resp.status_code == 200
    audit = audit_resp.json()
    assert audit["ledger_id"] == ledger_id
    assert audit["automatic_publication"] is False
    assert len(audit["audit_trail"]) >= 1

    # Step 9: Graph version updated
    graph_resp = client.get(
        "/api/mission-control/calyx-operator/graph/version",
        headers=_auth_headers(),
    )
    assert graph_resp.status_code == 200
    graph = graph_resp.json()
    assert graph["current_graph_version"] is not None

    # Step 10: Duplicate replay is a no-op
    dup_resp = client.post(
        "/api/mission-control/calyx-operator/publications",
        json={
            "ledger_id": discovered_ledger_id,
            "explicit_owner_confirmation": True,
        },
        headers=_auth_headers(),
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["idempotent"] is True


# ---------------------------------------------------------------------------
# 8. Authentication guard
# ---------------------------------------------------------------------------


def test_endpoints_require_auth(client: TestClient):
    """All operator endpoints must require authentication."""
    no_auth_endpoints = [
        ("GET", "/api/mission-control/calyx-operator/panel"),
        ("GET", "/api/mission-control/calyx-operator/missions"),
        ("GET", "/api/mission-control/calyx-operator/ledgers/eligible"),
        ("GET", "/api/mission-control/calyx-operator/graph/version"),
    ]
    for method, path in no_auth_endpoints:
        resp = client.request(method, path)
        # Must return 401 or 403 without valid auth
        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code} without auth"
        )


# ---------------------------------------------------------------------------
# 9. Plain-language status covers no-mission state
# ---------------------------------------------------------------------------


def test_plain_language_status_no_missions(client: TestClient):
    """Panel shows a helpful plain-language message when no missions exist."""
    resp = client.get(
        "/api/mission-control/calyx-operator/panel",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    status_msg = resp.json()["operator_panel"]["plain_language_status"]
    # Must be a helpful message, not an error or blank
    assert len(status_msg) > 10
    assert "mission" in status_msg.lower()
