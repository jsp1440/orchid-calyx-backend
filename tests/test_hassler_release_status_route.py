"""OC-COMPLETE-002 — Mission Control exposure of exact Hassler release state."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.taxonomy_releases import create_taxonomy_release_router
from runtime.hassler_release_lifecycle import (
    EXPECTED_ACQUIRED_AT,
    EXPECTED_FILENAME,
    EXPECTED_SHA256,
    EXPECTED_SIZE_BYTES,
    EXPECTED_VERSION_LABEL,
    Evidence,
)

ROUTE = "/api/mission-control/taxonomy/hassler-release-status"

SNAPSHOT = {
    "filename": EXPECTED_FILENAME,
    "sha256": EXPECTED_SHA256,
    "size_bytes": EXPECTED_SIZE_BYTES,
    "version_label": EXPECTED_VERSION_LABEL,
    "acquired_at": EXPECTED_ACQUIRED_AT,
    "row_count": 34_724,
}


class FakeDurableStore:
    """Minimal durable-store double covering the read paths the route uses."""

    def __init__(self, *, present: bool, staged: int = 0, completed: bool = False):
        self._present = present
        self._staged = staged
        self._completed = completed

    def _report(self):
        return {
            "release_id": EXPECTED_SHA256,
            "snapshot": dict(SNAPSHOT),
            "state": "staged" if self._completed else "inspected",
            "automatic_promotion": False,
        }

    def list_reports(self):
        return [self._report()] if self._present else []

    def get_with_inspection(self, release_id: str):
        if self._present and release_id == EXPECTED_SHA256:
            return self._report()
        return None

    def checkpoint(self, release_id: str):
        if not self._present:
            raise KeyError(release_id)
        return {
            "next_row_index": self._staged,
            "staged_count": self._staged,
            "completed": self._completed,
            "updated_at": "2026-08-22T00:00:00+00:00",
        }

    def counts(self, release_id: str):
        if not self._present:
            raise KeyError(release_id)
        return {"staged": self._staged, "open_review": 0}

    def change_report(self, release_id: str):
        if not self._present or self._staged == 0:
            return None
        return {"summary": {"added_taxa": 65, "removed_taxa": 17, "malformed_rows": 1}}


class UnavailableDurableStore:
    """Durable store that cannot be constructed at all."""

    def __init__(self):
        raise RuntimeError("durable intake unavailable")


def _client(store_factory, active_probe=None):
    app = FastAPI()
    kwargs = {
        "get_durable_store": store_factory,
        "require_owner": lambda: {"owner": "test"},
        "get_migration_preflight": lambda: {
            "state": "migration_verified",
            "schema_complete": True,
        },
    }
    if active_probe is not None:
        kwargs["get_active_taxonomy"] = active_probe
    app.include_router(create_taxonomy_release_router(**kwargs))
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_intake(tmp_path, monkeypatch):
    monkeypatch.setenv("CALYX_TAXONOMY_INTAKE_DIR", str(tmp_path / "intake"))
    monkeypatch.delenv("CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED", raising=False)


def test_absent_release_reports_absent_and_full_identity():
    response = _client(lambda: FakeDurableStore(present=False)).get(ROUTE)
    assert response.status_code == 200
    body = response.json()
    assert body["lifecycle"]["lifecycle_state"] == "ABSENT"
    assert body["lifecycle"]["durably_uploaded"] is False
    identity = body["status_block"]["release_identity"]
    assert identity["sha256"] == EXPECTED_SHA256
    assert identity["filename"] == EXPECTED_FILENAME
    assert identity["version_label"] == EXPECTED_VERSION_LABEL


def test_unavailable_durable_store_is_not_reported_as_absent():
    response = _client(UnavailableDurableStore).get(ROUTE)
    assert response.status_code == 200
    body = response.json()
    assert body["lifecycle"]["lifecycle_state"] == "UNAVAILABLE"
    assert body["lifecycle"]["durably_uploaded"] is None
    assert "release_list" in body["status_block"]["unavailable_evidence"]


def test_present_release_is_uploaded_inspected_with_no_staging_state():
    response = _client(lambda: FakeDurableStore(present=True)).get(ROUTE)
    body = response.json()
    assert body["lifecycle"]["lifecycle_state"] == "UPLOADED_INSPECTED"
    assert body["lifecycle"]["identity"]["verified"] is True
    assert body["status_block"]["staged_release_id"] is None


def test_completed_staging_is_reported_without_implying_activation():
    response = _client(
        lambda: FakeDurableStore(present=True, staged=34_724, completed=True)
    ).get(ROUTE)
    body = response.json()
    block = body["status_block"]
    assert body["lifecycle"]["lifecycle_state"] == "STAGED_COMPLETE"
    assert block["staged_release_id"] == EXPECTED_SHA256
    assert block["active_release_id"] is None
    assert block["active_vs_staged"] == "unavailable"
    assert block["taxonomy_activation"] == "separately_protected_owner_gate"
    assert body["lifecycle"]["activation_authorized"] is False
    assert body["lifecycle"]["activation_implied_by_upload_or_staging"] is False


def test_default_activation_probe_is_unavailable_not_false():
    """No canonical activation probe exists; the route must not assert "not active"."""
    response = _client(lambda: FakeDurableStore(present=True)).get(ROUTE)
    activation = response.json()["lifecycle"]["activation"]
    assert activation["evidence"] == "unavailable"
    assert activation["exact_release_is_active"] is None


def test_explicit_canonical_probe_can_report_activation():
    response = _client(
        lambda: FakeDurableStore(present=True, staged=34_724, completed=True),
        active_probe=lambda: Evidence.of(
            {"active_release_id": EXPECTED_SHA256}, "canonical probe"
        ),
    ).get(ROUTE)
    body = response.json()
    assert body["lifecycle"]["lifecycle_state"] == "ACTIVATED"
    assert body["status_block"]["active_vs_staged"] == "exact_release_is_active"


def test_downstream_relink_surfaces_are_always_enumerated():
    response = _client(
        lambda: FakeDurableStore(present=True, staged=34_724, completed=True)
    ).get(ROUTE)
    audit = response.json()["downstream_relink_impact"]
    assert set(audit["surfaces_enumerated"]) == {
        "occurrences",
        "media",
        "traits",
        "literature",
        "interactions",
        "knowledge_graph",
    }
    assert audit["drivers"]["malformed_rows"] == 1
    assert audit["counts_complete"] is False
    assert audit["relink_execution_authorized"] is False


def test_route_never_reports_a_mutation():
    response = _client(lambda: FakeDurableStore(present=True)).get(ROUTE)
    body = response.json()
    assert body["read_only"] is True
    assert body["automatic_promotion"] is False
    assert body["lifecycle"]["knowledge_graph_mutation_authorized"] is False
    assert body["lifecycle"]["scientific_publication_authorized"] is False
