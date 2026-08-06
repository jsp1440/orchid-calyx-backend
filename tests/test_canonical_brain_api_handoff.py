from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.brain.routes import router as protected_brain_router
from app.canonical_brain import (
    BrainCaptureBundle,
    BrainObject,
    BrainRelationship,
    build_canonical_brain_fixture,
    capture_build_bundle,
    create_brain_router,
)
from app.security import verify_owner_or_api_key


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _build_record() -> BrainObject:
    return BrainObject(
        object_id="build:brain-api-handoff",
        object_type="build",
        title="Canonical Brain API and capture handoff",
        summary="Adds protected discovery APIs and atomic build capture.",
        aliases=["BUILD-BRAIN-101"],
        tags=["brain", "api", "capture"],
        lifecycle="implemented",
        source_uri="docs/architecture/BUILD-BRAIN-101.md",
        content_checksum=_checksum("build:brain-api-handoff"),
        created_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
    )


def test_read_only_api_is_searchable_and_discoverable() -> None:
    app = FastAPI()
    app.include_router(create_brain_router(), prefix="/brain")
    client = TestClient(app)

    status = client.get("/canonical/status")
    assert status.status_code == 200
    assert status.json()["write_enabled"] is False
    assert status.json()["publication_enabled"] is False

    search = client.get("/canonical/search", params={"q": "FigureLabs glossary"})
    assert search.status_code == 200
    assert search.json()[0]["object_id"] == "architecture:knowledge-explorer"

    intents = client.get("/canonical/objects/architecture:atlas/intents")
    assert intents.status_code == 200
    assert intents.json()[0]["object_id"] == "intent:preserve-biodiversity"

    missing = client.get("/canonical/objects/architecture:missing")
    assert missing.status_code == 404


def test_canonical_brain_routes_are_mounted_on_protected_brain_router() -> None:
    app = FastAPI()
    app.include_router(protected_brain_router)

    unauthorized = TestClient(app).get("/brain/canonical/status")
    assert unauthorized.status_code == 401

    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "owner"}
    authorized = TestClient(app).get("/brain/canonical/status")
    assert authorized.status_code == 200
    assert authorized.json()["write_enabled"] is False


def test_capture_bundle_is_atomic_and_repeatable() -> None:
    registry = build_canonical_brain_fixture()
    record = _build_record()
    relation = BrainRelationship(
        relationship_id="rel:brain-api-implements-brain",
        subject_id=record.object_id,
        relationship_type="implements",
        object_id="architecture:brain",
        rationale="The build implements the canonical Brain discovery boundary.",
        source_uri=record.source_uri,
    )
    bundle = BrainCaptureBundle(
        build_id=record.object_id,
        objects=[record],
        relationships=[relation],
        submitted_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        source_uri=record.source_uri,
    )

    first = capture_build_bundle(registry, bundle)
    second = capture_build_bundle(registry, bundle)
    assert first.snapshot_checksum == second.snapshot_checksum
    assert registry.get(record.object_id) == record


def test_capture_bundle_rolls_back_on_broken_relationship() -> None:
    registry = build_canonical_brain_fixture()
    before = registry.snapshot().snapshot_checksum
    record = _build_record()
    broken = BrainRelationship(
        relationship_id="rel:broken",
        subject_id=record.object_id,
        relationship_type="depends_on",
        object_id="architecture:not-registered",
        rationale="This endpoint does not exist.",
        source_uri=record.source_uri,
    )
    bundle = BrainCaptureBundle(
        build_id=record.object_id,
        objects=[record],
        relationships=[broken],
        submitted_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        source_uri=record.source_uri,
    )

    with pytest.raises(ValueError, match="registered endpoints"):
        capture_build_bundle(registry, bundle)
    assert registry.snapshot().snapshot_checksum == before
    assert registry.get(record.object_id) is None
