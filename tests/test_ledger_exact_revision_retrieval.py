"""Exact reasoning-ledger revision retrieval (CALYX-VERIFY-LEDGER-001, #1135).

The Verification Workbench can see that a ledger exists — a mission carries
``ledger_id`` and ``version`` — and could not retrieve the revision being
verified. Recorded existence is not inspected reasoning, and the frontend says
so rather than implying an audit happened.

The property under test is exactness. Answering a request for version 3 with
version 7 would attach the wrong reasoning to a claim under review, which is
worse than returning nothing at all. So the wrong-version case is tested
harder than the happy path, and the fallback-to-latest behaviour is asserted
*absent* rather than assumed.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.reasoning_ledger import routes


class FakeDb:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def revision(version: int, *, title: str = "Thermal niche reasoning"):
    """A stand-in for one persisted ReasoningLedger revision."""
    return SimpleNamespace(version=version, title=title)


def install_service(monkeypatch, *, revisions=None, raises=None):
    """Point the route at a fake operational service."""

    class FakeService:
        def __init__(self, _db):
            pass

        def history(self, ledger_id, owner):
            if raises is not None:
                raise raises
            return {"revisions": list(revisions or []), "audit_events": []}

    monkeypatch.setattr(routes, "OperationalReasoningLedgerService", FakeService)


@pytest.fixture(autouse=True)
def canonical_projection(monkeypatch):
    """Keep the canonical serializer's identity without depending on its shape."""
    monkeypatch.setattr(
        routes,
        "ledger_to_dict",
        lambda ledger: {
            "version": ledger.version,
            "title": ledger.title,
            "ledger_fingerprint": f"fingerprint-{ledger.version}",
        },
    )


AUTH = {"subject": "owner@example.com"}
REQUEST = SimpleNamespace()


def call(ledger_id="ledger-1", version=2, db=None):
    return routes.get_ledger_revision(ledger_id, version, REQUEST, AUTH, db or FakeDb())


def test_returns_the_exact_revision_requested(monkeypatch):
    install_service(monkeypatch, revisions=[revision(1), revision(2), revision(7)])

    body = call(version=2)

    assert body["requested_version"] == 2
    assert body["revision"]["version"] == 2
    assert body["revision"]["ledger_fingerprint"] == "fingerprint-2"


def test_never_falls_back_to_the_latest_revision(monkeypatch):
    # The core contract. A ledger at version 7 asked for version 3 must fail,
    # not answer with 7 — a claim verified against the wrong reasoning is a
    # scientific error, not a convenience.
    install_service(monkeypatch, revisions=[revision(1), revision(7)])

    with pytest.raises(HTTPException) as excinfo:
        call(version=3)

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "LEDGER_REVISION_NOT_FOUND"
    assert excinfo.value.detail["requested_version"] == 3


def test_reports_which_revisions_exist_so_missing_is_not_empty(monkeypatch):
    # "That revision is gone" and "this ledger has no reasoning" are different
    # facts. The caller must be able to tell them apart.
    install_service(monkeypatch, revisions=[revision(1), revision(2)])

    with pytest.raises(HTTPException) as excinfo:
        call(version=9)

    assert excinfo.value.detail["available_versions"] == [1, 2]


def test_an_empty_ledger_history_is_still_a_not_found(monkeypatch):
    install_service(monkeypatch, revisions=[])

    with pytest.raises(HTTPException) as excinfo:
        call(version=1)

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["available_versions"] == []


@pytest.mark.parametrize("version", [0, -1, -42])
def test_rejects_a_non_positive_version_as_malformed(monkeypatch, version):
    # Versions are 1-based. Treating 0 as "the first one" would answer a
    # malformed request with real reasoning.
    install_service(monkeypatch, revisions=[revision(1)])

    with pytest.raises(HTTPException) as excinfo:
        call(version=version)

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "LEDGER_REVISION_INVALID"


def test_unknown_ledger_is_reported_as_not_found(monkeypatch):
    install_service(monkeypatch, raises=routes.LedgerNotFoundError("no such ledger"))

    with pytest.raises(HTTPException) as excinfo:
        call()

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "LEDGER_NOT_FOUND"


def test_persistence_failure_is_unavailable_not_empty_reasoning(monkeypatch):
    # The failure this endpoint exists alongside: a database outage must never
    # be presented as a ledger containing no reasoning.
    db = FakeDb()
    install_service(monkeypatch, raises=SQLAlchemyError("connection lost"))

    with pytest.raises(HTTPException) as excinfo:
        call(db=db)

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["code"] == "LEDGER_PERSISTENCE_UNAVAILABLE"
    assert db.rollbacks == 1


def test_retrieval_does_not_certify_the_reasoning(monkeypatch):
    # Inspectable is not verified. A consumer must not be able to read a
    # successful retrieval as a scientific endorsement.
    install_service(monkeypatch, revisions=[revision(2)])

    body = call(version=2)

    assert body["inspectable"] is True
    assert body["reasoning_certified"] is False


def test_returns_only_the_canonical_projection(monkeypatch):
    # No new serializer was introduced, so nothing can be exposed here that the
    # existing current/history routes do not already expose. This pins that the
    # route delegates rather than assembling its own payload.
    seen = []

    def spy(ledger):
        seen.append(ledger)
        return {"version": ledger.version}

    monkeypatch.setattr(routes, "ledger_to_dict", spy)
    install_service(monkeypatch, revisions=[revision(4)])

    body = call(version=4)

    assert [item.version for item in seen] == [4]
    assert set(body) == {
        "ledger_id",
        "requested_version",
        "revision",
        "inspectable",
        "reasoning_certified",
    }


def test_enforces_the_owner_boundary_through_the_shared_path(monkeypatch):
    # history() calls current() first, so ownership is checked by the same code
    # path as every other ledger read rather than by a second rule here.
    calls = []

    class RecordingService:
        def __init__(self, _db):
            pass

        def history(self, ledger_id, owner):
            calls.append((ledger_id, owner))
            return {"revisions": [revision(1)], "audit_events": []}

    monkeypatch.setattr(routes, "OperationalReasoningLedgerService", RecordingService)

    call(ledger_id="ledger-9", version=1)

    assert calls == [("ledger-9", "owner@example.com")]
