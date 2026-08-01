"""Canonical Brain-route contract for the Calyx Journalism MVP."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.calyx_journalism.persistence import TABLES
from app.database import get_db
from app.main import app
from app.security import verify_owner_or_api_key

_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
for table in TABLES:
    table.create(_engine, checkfirst=True)


async def _auth_bypass() -> dict[str, str]:
    return {"actor": "test-journalism-owner", "auth_type": "test"}


def _test_db():
    with Session(_engine) as session:
        yield session


def _client() -> TestClient:
    app.dependency_overrides[verify_owner_or_api_key] = _auth_bypass
    app.dependency_overrides[get_db] = _test_db
    return TestClient(app, raise_server_exceptions=True)


def teardown_function() -> None:
    app.dependency_overrides.clear()
    with Session(_engine) as session:
        for table in reversed(TABLES):
            session.execute(table.delete())
        session.commit()


def test_canonical_journalism_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    required = {
        "/brain/journalism/presets",
        "/brain/journalism/presets/{preset_id}",
        "/brain/journalism/brief",
        "/brain/journalism/evidence-preview",
        "/brain/journalism/generate",
        "/brain/journalism/export/markdown",
    }
    assert required <= paths


def test_journalism_requires_authentication() -> None:
    app.dependency_overrides[get_db] = _test_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/brain/journalism/presets")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_presets_and_evidence_preview_use_canonical_brain_routes() -> None:
    client = _client()
    presets = client.get("/brain/journalism/presets")
    assert presets.status_code == 200
    assert "fcos" in {item["preset_id"] for item in presets.json()["presets"]}

    preview = client.post(
        "/brain/journalism/evidence-preview",
        json={
            "evidence_items": [
                {
                    "project_name": "EDGE Orchids",
                    "country": "UK",
                    "source_id": "e-001",
                }
            ],
            "available_dependencies": [],
        },
    )
    assert preview.status_code == 201
    assert preview.json()["item_count"] == 1


def test_generate_and_markdown_export_round_trip_on_brain_route() -> None:
    client = _client()
    publication = {
        "publication_id": "fcos",
        "publication_name": "Orchid Continuum",
        "theme": "conservation",
    }
    brief = {
        "title": "Global Orchid Conservation",
        "focus": "Verified evidence only.",
    }
    generated = client.post(
        "/brain/journalism/generate",
        json={
            "publication": publication,
            "brief": brief,
            "generation_mode": {
                "mode": "limited_evidence",
                "unavailable_dependencies": ["orchid_continuum_corpus"],
            },
        },
    )
    assert generated.status_code == 201
    article_id = generated.json()["article_id"]

    exported = client.post(
        "/brain/journalism/export/markdown",
        json={
            "article_id": article_id,
            "publication": publication,
            "brief": brief,
        },
    )
    assert exported.status_code == 200
    assert exported.json()["filename"].endswith(".md")
