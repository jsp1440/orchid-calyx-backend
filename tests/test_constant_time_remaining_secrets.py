"""Constant-time compares for the remaining admin, review and claim secrets.

Covers the auth checks that still compared a presented secret with ``!=``:

* ``app/routers/reference_docs.py`` admin gate: constant-time, header-only
  (``X-Orchid-Admin-Key``); the ``api_key`` query parameter (which lands in URL
  and access logs) is refused with a 400 naming the header, and the legacy
  ``api_key`` form field no longer authorises anything.
* ``app/review_api/dependencies.py`` API-key identity.
* ``app/calyx_orchestrator/sandbox_supervisor_service.py`` claim token.
* the constituent manage token keeps accepting a whitespace-padded valid token.

Every wrong, missing or non-ASCII value is a 401/403 (or a PermissionError),
never a 500, and an unset configured key still refuses every request.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.sandbox_supervisor_evidence import ValidationRequestEnvelope
from app.calyx_orchestrator.sandbox_supervisor_models import (
    SandboxValidationRequestRecord,
)
from app.calyx_orchestrator.sandbox_supervisor_service import SandboxSupervisorService
from app.constituent_platform import service as constituent_service
from app.database import Base
from app.deps import get_db
from app.mission_control_access import AccessPrincipal
from app.review_api.dependencies import authenticated_principal
from app.routers import reference_docs

ADMIN_KEY = "reference-docs-admin-key"
CALYX_KEY = "calyx-api-key-for-review"

# Raw header bytes as a client puts them on the wire (Starlette decodes latin-1).
NON_ASCII_HEADERS = {
    "latin-1": b"k\xe9y",
    "emoji-utf8": "\U0001f33a".encode(),
    "valid-key-plus-latin-1": ADMIN_KEY.encode() + b"\xff",
    "cyrillic-lookalike": "reference-docs-аdmin-key".encode(),
}


class _NoDocs:
    """A stand-in session: every lookup misses, so an authorised PATCH answers 404."""

    def get(self, *_args, **_kwargs):
        return None


@pytest.fixture
def docs(monkeypatch) -> TestClient:
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(reference_docs.router)
    app.dependency_overrides[get_db] = lambda: _NoDocs()
    return TestClient(app, raise_server_exceptions=False)


def _patch(client: TestClient, *, headers=None, params=None):
    return client.patch("/admin/reference-docs/doc-1", json={"notes": "n"}, headers=headers or {}, params=params)


def _upload(client: TestClient, *, headers=None, data=None):
    form = {"document_type": "NOT_A_TYPE", "title": "t", "version_label": "v1", **(data or {})}
    return client.post(
        "/admin/reference-docs",
        data=form,
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        headers=headers or {},
    )


# --- reference docs admin gate ---------------------------------------------


def test_reference_docs_admin_header_authorises_patch_and_upload(docs):
    # Past the gate: PATCH reaches the lookup (404), upload reaches type validation (400).
    assert _patch(docs, headers={"X-Orchid-Admin-Key": ADMIN_KEY}).status_code == 404
    upload = _upload(docs, headers={"X-Orchid-Admin-Key": ADMIN_KEY})
    assert upload.status_code == 400
    assert "Invalid document_type" in upload.json()["detail"]


@pytest.mark.parametrize("headers", [{}, {"X-Orchid-Admin-Key": "wrong"}, {"X-Orchid-Admin-Key": ""}])
def test_reference_docs_wrong_or_missing_admin_key_is_403(docs, headers):
    for response in (_patch(docs, headers=headers), _upload(docs, headers=headers)):
        assert response.status_code == 403
        assert "X-Orchid-Admin-Key" in response.json()["detail"]


@pytest.mark.parametrize("value", sorted(NON_ASCII_HEADERS))
def test_reference_docs_non_ascii_admin_key_is_403_not_500(docs, value):
    wrong = _patch(docs, headers={"X-Orchid-Admin-Key": "wrong"})
    non_ascii = _patch(docs, headers={"X-Orchid-Admin-Key": NON_ASCII_HEADERS[value]})
    assert (non_ascii.status_code, non_ascii.content) == (wrong.status_code, wrong.content) == (403, wrong.content)
    assert _upload(docs, headers={"X-Orchid-Admin-Key": NON_ASCII_HEADERS[value]}).status_code == 403


def test_reference_docs_query_parameter_key_is_refused_even_when_correct(docs):
    for headers in ({}, {"X-Orchid-Admin-Key": ADMIN_KEY}):
        response = _patch(docs, headers=headers, params={"api_key": ADMIN_KEY})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "query parameter" in detail and "X-Orchid-Admin-Key" in detail
        assert ADMIN_KEY not in detail


def test_reference_docs_legacy_form_field_key_no_longer_authorises(docs):
    response = _upload(docs, data={"api_key": ADMIN_KEY})
    assert response.status_code == 403
    assert "X-Orchid-Admin-Key" in response.json()["detail"]


def test_reference_docs_unconfigured_key_refuses_every_request(docs, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    for headers in ({}, {"X-Orchid-Admin-Key": ""}, {"X-Orchid-Admin-Key": ADMIN_KEY}):
        assert _patch(docs, headers=headers).status_code == 503
        assert _upload(docs, headers=headers).status_code == 503
    monkeypatch.setenv("ADMIN_API_KEY", "")
    assert _patch(docs, headers={"X-Orchid-Admin-Key": ""}).status_code == 503


def test_reference_docs_admin_key_precedence_and_calyx_fallback(docs, monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", CALYX_KEY)
    # ADMIN_API_KEY wins when set: the Calyx key is not an admin key then.
    assert _patch(docs, headers={"X-Orchid-Admin-Key": CALYX_KEY}).status_code == 403
    monkeypatch.delenv("ADMIN_API_KEY")
    assert _patch(docs, headers={"X-Orchid-Admin-Key": CALYX_KEY}).status_code == 404
    assert _patch(docs, headers={"X-Orchid-Admin-Key": ADMIN_KEY}).status_code == 403


def test_reference_docs_public_reads_stay_open(docs):
    # The gate only guards the admin routes; public reads still need no key.
    assert docs.get("/reference-docs/doc-1").status_code == 404


def test_reference_docs_openapi_no_longer_advertises_an_api_key_parameter(docs):
    spec = docs.get("/openapi.json").json()
    patch_params = spec["paths"]["/admin/reference-docs/{doc_id}"]["patch"]["parameters"]
    names = {p["name"] for p in patch_params}
    assert "api_key" not in names and "X-Orchid-Admin-Key" in names
    upload_schema_ref = spec["paths"]["/admin/reference-docs"]["post"]["requestBody"]["content"]
    assert "api_key" not in str(upload_schema_ref) and "api_key" not in str(spec["components"]["schemas"])


# --- review API key identity -----------------------------------------------


@pytest.fixture
def review(monkeypatch) -> TestClient:
    monkeypatch.setenv("CALYX_API_KEY", CALYX_KEY)
    app = FastAPI()

    @app.get("/principal")
    def principal(p: Annotated[AccessPrincipal, Depends(authenticated_principal)]):
        return {"principal_id": p.principal_id}

    return TestClient(app, raise_server_exceptions=False)


def test_review_api_key_valid_is_accepted(review):
    response = review.get("/principal", headers={"X-API-Key": CALYX_KEY})
    assert response.status_code == 200, response.text
    assert response.json()["principal_id"] == "backend_api_key"


@pytest.mark.parametrize(
    "value",
    ["wrong", CALYX_KEY + "x", b"k\xe9y", "\U0001f33a".encode(), CALYX_KEY.encode() + b"\xff"],
)
def test_review_api_key_wrong_or_non_ascii_is_401_not_500(review, value):
    response = review.get("/principal", headers={"X-API-Key": value})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


def test_review_api_key_unconfigured_refuses_any_key(review, monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY")
    assert review.get("/principal", headers={"X-API-Key": CALYX_KEY}).status_code == 401
    monkeypatch.setenv("CALYX_API_KEY", "")
    assert review.get("/principal", headers={"X-API-Key": CALYX_KEY}).status_code == 401
    assert review.get("/principal").status_code == 401


def test_review_api_key_is_compared_in_constant_time(review, monkeypatch):
    calls: list[tuple[object, object]] = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    assert review.get("/principal", headers={"X-API-Key": "wrong"}).status_code == 401
    assert (b"wrong", CALYX_KEY.encode()) in calls


# --- sandbox supervisor claim token ----------------------------------------


def _claimed(db: Session) -> SandboxValidationRequestRecord:
    envelope = ValidationRequestEnvelope.build(
        repository="jsp1440/orchid-calyx-backend",
        branch="autonomy/example",
        checkout_commit_sha="c" * 40,
        preset="pytest",
        targets=[{"path": "tests/test_example.py", "sha256": "a" * 64}],
        timeout_seconds=60,
    )
    service = SandboxSupervisorService(db)
    service.create_request(
        owner="owner-1",
        program_job_id=None,
        repository=envelope.repository,
        branch=envelope.branch,
        checkout_commit_sha=envelope.checkout_commit_sha,
        preset=envelope.preset,
        targets=[item.as_dict() for item in envelope.targets],
        timeout_seconds=envelope.timeout_seconds,
    )
    claimed = service.claim_next(worker_id="worker-1")
    assert claimed is not None and claimed.claim_token
    return claimed


def _receipt(request_digest: str) -> dict:
    return {
        "request_digest": request_digest,
        "authorization_id": "sandbox-auth-1",
        "policy_digest": "b" * 64,
        "evidence_uri": "github-actions:run/123",
        "outcome": "delivered",
        "return_code": 0,
        "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "issued_at": datetime(2026, 8, 8, 20, 0, tzinfo=timezone.utc).isoformat(),
    }


@pytest.fixture
def supervisor_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[SandboxValidationRequestRecord.__table__])
    with Session(engine) as db:
        yield db


@pytest.mark.parametrize(
    "presented",
    [
        "00000000-0000-0000-0000-000000000000",  # same length, wrong value
        "é" * 36,  # non-ASCII: must be a mismatch, not a TypeError
        "",
    ],
)
def test_claim_token_mismatch_fails_closed(supervisor_db, presented):
    claimed = _claimed(supervisor_db)
    with pytest.raises(PermissionError, match="CLAIM_MISMATCH"):
        SandboxSupervisorService(supervisor_db).complete(
            request_id=claimed.request_id,
            worker_id="worker-1",
            claim_token=presented,
            receipt_payload=_receipt(claimed.request_digest),
        )
    supervisor_db.refresh(claimed)
    assert claimed.status == "claimed" and claimed.claim_token


def test_claim_token_is_compared_in_constant_time(supervisor_db, monkeypatch):
    claimed = _claimed(supervisor_db)
    token = claimed.claim_token
    calls: list[tuple[object, object]] = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    completed = SandboxSupervisorService(supervisor_db).complete(
        request_id=claimed.request_id,
        worker_id="worker-1",
        claim_token=token,
        receipt_payload=_receipt(claimed.request_digest),
    )
    assert completed.status == "completed"
    assert (token.encode(), token.encode()) in calls


def test_cleared_claim_token_never_matches(supervisor_db):
    claimed = _claimed(supervisor_db)
    claimed.claim_token = None
    supervisor_db.commit()
    with pytest.raises(PermissionError, match="CLAIM_MISMATCH"):
        SandboxSupervisorService(supervisor_db).complete(
            request_id=claimed.request_id,
            worker_id="worker-1",
            claim_token="",
            receipt_payload=_receipt(claimed.request_digest),
        )


# --- constituent manage token: whitespace padding --------------------------


def test_manage_token_whitespace_padding_is_accepted(monkeypatch):
    monkeypatch.setenv("CONSTITUENT_MANAGE_SECRET", "manage-secret")
    token = constituent_service.issue_manage_token("user@example.com")
    assert token
    for padded in (f" {token}", f"{token} ", f"\t{token}\n", f"  {token}  "):
        assert constituent_service.verify_manage_token("user@example.com", padded)
    # Padding is trimmed, nothing else: a wrong, truncated, other-address or blank token still fails.
    assert not constituent_service.verify_manage_token("user@example.com", f" {token[:-1]} ")
    assert not constituent_service.verify_manage_token("other@example.com", f" {token} ")
    assert not constituent_service.verify_manage_token("user@example.com", "   ")
    assert not constituent_service.verify_manage_token("user@example.com", f"{token}é")
