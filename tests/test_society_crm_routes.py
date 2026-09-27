"""HTTP contract for the society CRM administration API (PostgreSQL-backed)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.constituent_platform import society_routes
from app.constituent_platform.society_service import CRMPrincipal


pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)

API_KEY = "test-backend-api-key"


MIGRATIONS = (
    "migrations/20260823_oc_constituent_communications_foundation.sql",
    "migrations/20260926_society_crm_p0_core.sql",
    "migrations/20260927_society_crm_p1_tenant_isolation.sql",
)


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        for path in MIGRATIONS:
            conn.execute(Path(path).read_text(encoding="utf-8"))


async def _principal_from_header(request: Request) -> CRMPrincipal:
    """Test stand-in for Supabase verification only; API-key callers use the real path."""
    subject = request.headers.get("x-test-subject")
    if subject:
        return CRMPrincipal(subject)
    return await society_routes.society_principal(request, request.headers.get("x-api-key"))


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv(society_routes.API_ENABLED_ENV, "true")
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    application = FastAPI()
    for router in society_routes.iter_routers():
        application.include_router(router)
    return application


@pytest.fixture()
def operator(app: FastAPI) -> TestClient:
    # Real authentication path: backend API key -> platform operator.
    return TestClient(app, headers={"X-API-Key": API_KEY})


@pytest.fixture()
def people(app: FastAPI):
    app.dependency_overrides[society_routes.society_principal] = _principal_from_header

    def client(subject: str) -> TestClient:
        return TestClient(app, headers={"x-test-subject": subject})

    yield client
    app.dependency_overrides.clear()


def _new_society(operator: TestClient, people) -> tuple[str, TestClient, str]:
    slug = f"t-{uuid.uuid4().hex[:12]}"
    assert operator.post("/api/society-platform/organizations",
                         json={"slug": slug, "display_name": "Orchid Society"}).status_code == 201
    admin_subject = f"supabase:{uuid.uuid4()}"
    response = operator.post(f"/api/society-platform/organizations/{slug}/admins",
                             json={"display_name": "Pat Admin", "auth_subject": admin_subject})
    assert response.status_code == 201, response.text
    admin = people(admin_subject)
    assert admin.post(f"/api/society/{slug}/levels", json={
        "code": "individual", "display_name": "Individual", "dues_amount_cents": 3000,
        "entitlements": ["society.member_portal"],
    }).status_code == 201
    return slug, admin, admin_subject


def test_api_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(society_routes.API_ENABLED_ENV, raising=False)
    application = FastAPI()
    for router in society_routes.iter_routers():
        application.include_router(router)
    response = TestClient(application).get("/api/society/any-society/me")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SOCIETY_CRM_DISABLED"


def test_unauthenticated_requests_are_rejected(app: FastAPI) -> None:
    response = TestClient(app).get("/api/society/any-society/members")
    assert response.status_code in (401, 404)
    response = TestClient(app).post("/api/society-platform/organizations",
                                    json={"slug": "nope-nope", "display_name": "Nope"})
    assert response.status_code == 401
    wrong = TestClient(app, headers={"X-API-Key": "wrong"})
    assert wrong.post("/api/society-platform/organizations",
                      json={"slug": "nope-nope", "display_name": "Nope"}).status_code == 401


def test_admin_member_workflow_over_http(operator: TestClient, people) -> None:
    slug, admin, _ = _new_society(operator, people)
    base = f"/api/society/{slug}"

    me = admin.get(f"{base}/me").json()
    assert "admin" in me["roles"] and "role.admin" in me["capabilities"]

    created = admin.post(f"{base}/members", json={
        "display_name": "New Member", "email": "new@example.org", "level_code": "individual",
    })
    assert created.status_code == 201, created.text
    mid = created.json()["membership_id"]
    assert created.json()["status"] == "pending"

    renewed = admin.post(f"{base}/members/{mid}/renewals", json={"renewal_key": "join-1"}).json()
    assert renewed["applied"] is True and renewed["member"]["status"] == "active"
    assert admin.post(f"{base}/members/{mid}/renewals", json={"renewal_key": "join-1"}).json()["applied"] is False

    assert admin.put(f"{base}/members/{mid}/email", json={"email": "moved@example.org"}).json()[
        "primary_email"] == "moved@example.org"
    address = admin.put(f"{base}/members/{mid}/address", json={
        "line1": "1 Orchid Way", "locality": "Arroyo Grande", "administrative_area": "CA",
        "postal_code": "93420", "country_code": "US"})
    assert address.status_code == 200 and address.json()["mailing_locality"] == "Arroyo Grande"

    listing = admin.get(f"{base}/members", params={"status": "active", "q": "moved@"}).json()
    assert listing["total"] == 1 and listing["items"][0]["membership_id"] == mid

    # Actionable errors.
    duplicate = admin.post(f"{base}/members", json={
        "display_name": "Dup", "email": "MOVED@example.org", "level_code": "individual"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "DUPLICATE_MEMBER_EMAIL"
    assert "existing member" in duplicate.json()["detail"]["message"]
    no_reason = admin.post(f"{base}/members/{mid}/status", json={"status": "cancelled"})
    assert no_reason.status_code == 422
    assert no_reason.json()["detail"]["code"] == "MEMBERSHIP_TRANSITION_REASON_REQUIRED"
    cancelled = admin.post(f"{base}/members/{mid}/status", json={"status": "cancelled", "reason": "Moved away"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"

    history = admin.get(f"{base}/members/{mid}/history").json()
    assert [r["renewal_key"] for r in history["renewals"]] == ["join-1"]
    assert "membership.status_changed" in [e["action"] for e in history["audit"]]


def test_cross_tenant_and_unprivileged_access_over_http(operator: TestClient, people) -> None:
    slug_a, admin_a, _ = _new_society(operator, people)
    slug_b, admin_b, _ = _new_society(operator, people)
    member_b = admin_b.post(f"/api/society/{slug_b}/members", json={
        "display_name": "Bee", "email": "shared@example.org", "level_code": "individual"}).json()

    # A's admin in B's society: 403 with an explanation, never B's data.
    denied = admin_a.get(f"/api/society/{slug_b}/members/{member_b['membership_id']}")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "SOCIETY_CAPABILITY_REQUIRED:roster.read"
    assert "Bee" not in denied.text and "shared@example.org" not in denied.text
    # B's membership id through A's society: indistinguishable from nonexistent.
    missing = admin_a.get(f"/api/society/{slug_a}/members/{member_b['membership_id']}")
    nonexistent = admin_a.get(f"/api/society/{slug_a}/members/999999999")
    assert missing.status_code == nonexistent.status_code == 404
    assert missing.json() == nonexistent.json()
    assert admin_a.post(f"/api/society/{slug_b}/staff/roles",
                        json={"constituent_id": member_b["constituent_id"], "role": "admin"}).status_code == 403

    # A plain signed-in person with no role anywhere.
    stranger = people(f"supabase:{uuid.uuid4()}")
    assert stranger.get(f"/api/society/{slug_a}/me").json()["capabilities"] == []
    assert stranger.get(f"/api/society/{slug_a}/members").status_code == 403
    assert stranger.post(f"/api/society/{slug_a}/levels",
                         json={"code": "x", "display_name": "X"}).status_code == 403
    # A signed-in society admin is not a platform operator.
    assert admin_a.post("/api/society-platform/organizations",
                        json={"slug": f"t-{uuid.uuid4().hex[:12]}", "display_name": "Rogue"}).status_code == 403
    assert admin_a.get("/api/society/no-such-society/members").status_code == 404


def test_database_unavailable_is_explained_without_secrets(app: FastAPI, people, monkeypatch: pytest.MonkeyPatch) -> None:
    app.dependency_overrides[society_routes.society_principal] = _principal_from_header
    monkeypatch.setenv("DATABASE_URL", "postgresql://crm:s3cret-password@127.0.0.1:1/nowhere?connect_timeout=1")
    response = TestClient(app, headers={"x-test-subject": f"supabase:{uuid.uuid4()}"}).get("/api/society/some-org/me")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CRM_DATABASE_UNAVAILABLE"
    assert "s3cret" not in response.text
