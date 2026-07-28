"""Focused tests for MISSION-CONTROL-CALYX-JOURNALISM-MVP-001.

Validation matrix
-----------------
1. Schema validation — ArticleBrief word-count ordering
2. Preset registry — FCOS preset is present and well-formed
3. Evidence preview — mode classification (full vs limited)
4. Evidence preview — verified projects extracted from evidence
5. Evidence preview — unavailable dependencies reported explicitly
6. Evidence preview — empty evidence → limited_evidence mode
7. Article generation — no fabricated citations
8. Article generation — limited-evidence mode warnings declared
9. Article generation — unavailable dependencies forwarded
10. Markdown export — round-trips article correctly
11. Markdown export — unavailable-dependency section present
12. Markdown export — verified project table only when projects present
13. HTTP — POST /api/calyx-journalism/brief returns 401 without auth
14. HTTP — POST /api/calyx-journalism/brief accepted with API key
15. HTTP — GET /api/calyx-journalism/presets returns fcos preset
16. HTTP — GET /api/calyx-journalism/presets/{unknown} returns 404
17. HTTP — POST /api/calyx-journalism/evidence-preview returns packet
18. HTTP — POST /api/calyx-journalism/generate and export round-trip
19. HTTP — POST /api/calyx-journalism/export/markdown 404 on unknown id
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.calyx_journalism.presets import fcos_preset, get_preset, list_presets
from app.calyx_journalism.schemas import (
    ArticleBrief,
    ArticleGenerationRequest,
    GenerationMode,
    PublicationMeta,
)
from app.calyx_journalism.services import (
    ArticleGenerationService,
    ArticleStore,
    EvidencePreviewService,
    MarkdownExportService,
)
from app.main import app
from app.security import verify_owner_or_api_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API_KEY = "test-journalism-key"


async def _auth_bypass() -> dict:
    return {"actor": "test", "auth_type": "api_key"}


def _client() -> TestClient:
    app.dependency_overrides[verify_owner_or_api_key] = _auth_bypass
    return TestClient(app, raise_server_exceptions=True)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _fcos_publication() -> PublicationMeta:
    return PublicationMeta(
        publication_id="fcos-global-orchid-conservation",
        publication_name="Orchid Continuum — Conservation Report",
        theme="global_orchid_conservation",
        language="en",
    )


def _fcos_brief() -> ArticleBrief:
    return ArticleBrief(
        title="Global Orchid Conservation",
        focus="Survey global orchid conservation status from verified evidence only.",
        target_word_count_min=800,
        target_word_count_max=1500,
        scope_hints=["global", "conservation"],
        tags=["fcos"],
    )


# ---------------------------------------------------------------------------
# 1. Schema — ArticleBrief word-count ordering guard
# ---------------------------------------------------------------------------

def test_article_brief_rejects_inverted_word_count() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ArticleBrief(
            title="T",
            focus="F",
            target_word_count_min=1500,
            target_word_count_max=800,
        )


def test_article_brief_accepts_equal_word_count() -> None:
    brief = ArticleBrief(
        title="T",
        focus="F",
        target_word_count_min=1000,
        target_word_count_max=1000,
    )
    assert brief.target_word_count_min == brief.target_word_count_max


# ---------------------------------------------------------------------------
# 2. Preset registry
# ---------------------------------------------------------------------------

def test_fcos_preset_is_registered() -> None:
    presets = list_presets()
    ids = [p["preset_id"] for p in presets]
    assert "fcos" in ids


def test_fcos_preset_has_required_fields() -> None:
    preset = get_preset("fcos")
    assert preset is not None
    assert "publication" in preset
    assert "brief" in preset
    pub = preset["publication"]
    brief = preset["brief"]
    assert pub["publication_id"] == "fcos-global-orchid-conservation"  # type: ignore[index]
    assert brief["target_word_count_min"] == 800  # type: ignore[index]
    assert brief["target_word_count_max"] == 1500  # type: ignore[index]


def test_unknown_preset_returns_none() -> None:
    assert get_preset("does-not-exist") is None


# ---------------------------------------------------------------------------
# 3–6. Evidence preview service
# ---------------------------------------------------------------------------

def _preview() -> EvidencePreviewService:
    return EvidencePreviewService()


def test_full_continuum_mode_when_all_deps_available() -> None:
    all_deps = list(EvidencePreviewService.FULL_CONTINUUM_DEPENDENCIES)
    packet = _preview().build_preview(
        evidence_items=[{"project_name": "EDGE Orchids", "country": "UK"}],
        available_dependencies=all_deps,
    )
    assert packet.mode == "full_continuum"
    assert not packet.unavailable_dependencies


def test_limited_evidence_mode_when_deps_missing() -> None:
    packet = _preview().build_preview(
        evidence_items=[{"project_name": "P"}],
        available_dependencies=["orchid_continuum_corpus"],
    )
    assert packet.mode == "limited_evidence"
    assert len(packet.unavailable_dependencies) > 0


def test_verified_projects_extracted_from_evidence() -> None:
    items = [
        {"project_name": "EDGE Orchids", "country": "UK", "region": "Europe", "source_id": "src-001"},
        {"project_name": "Andes Orchid Fund", "country": "Ecuador", "region": "South America"},
    ]
    packet = _preview().build_preview(evidence_items=items, available_dependencies=[])
    assert len(packet.verified_projects) == 2
    names = {p.project_name for p in packet.verified_projects}
    assert "EDGE Orchids" in names
    assert "Andes Orchid Fund" in names


def test_no_fabricated_projects_when_evidence_empty() -> None:
    packet = _preview().build_preview(evidence_items=[], available_dependencies=[])
    assert packet.mode == "limited_evidence"
    assert packet.verified_projects == []
    assert packet.item_count == 0


def test_duplicate_evidence_rows_deduplicated() -> None:
    items = [
        {"project_name": "EDGE Orchids", "country": "UK"},
        {"project_name": "EDGE Orchids", "country": "UK"},
    ]
    packet = _preview().build_preview(evidence_items=items, available_dependencies=[])
    assert len(packet.verified_projects) == 1


def test_unavailable_dependencies_reported_explicitly() -> None:
    packet = _preview().build_preview(evidence_items=[], available_dependencies=[])
    assert set(packet.unavailable_dependencies) == set(
        EvidencePreviewService.FULL_CONTINUUM_DEPENDENCIES
    )


# ---------------------------------------------------------------------------
# 7–9. Article generation service
# ---------------------------------------------------------------------------

def _generation_service() -> ArticleGenerationService:
    return ArticleGenerationService()


def _generation_request(
    mode: str = "limited_evidence",
    unavailable: list[str] | None = None,
) -> ArticleGenerationRequest:
    return ArticleGenerationRequest(
        publication=_fcos_publication(),
        brief=_fcos_brief(),
        generation_mode=GenerationMode(
            mode=mode,  # type: ignore[arg-type]
            unavailable_dependencies=unavailable or [],
        ),
        operator_notes=None,
    )


def test_generated_article_has_no_fabricated_citations() -> None:
    response = _generation_service().generate(_generation_request())
    for section in response.sections:
        # Citations must be empty unless caller supplied evidence with citations
        assert section.citations == [], (
            f"Section '{section.heading}' contains citations that were not supplied by the caller"
        )


def test_limited_evidence_warning_is_present() -> None:
    response = _generation_service().generate(
        _generation_request(mode="limited_evidence", unavailable=["orchid_continuum_corpus"])
    )
    assert response.mode == "limited_evidence"
    assert any("limited-evidence" in w for w in response.warnings)


def test_unavailable_dependencies_forwarded_in_response() -> None:
    missing = ["orchid_continuum_corpus", "canonical_taxonomy"]
    response = _generation_service().generate(
        _generation_request(mode="limited_evidence", unavailable=missing)
    )
    assert set(response.unavailable_dependencies) == set(missing)


def test_full_continuum_mode_has_no_warning() -> None:
    response = _generation_service().generate(_generation_request(mode="full_continuum"))
    assert response.mode == "full_continuum"
    assert response.warnings == []


def test_article_id_is_unique_across_calls() -> None:
    svc = _generation_service()
    r1 = svc.generate(_generation_request())
    r2 = svc.generate(_generation_request())
    assert r1.article_id != r2.article_id


# ---------------------------------------------------------------------------
# 10–12. Markdown export service
# ---------------------------------------------------------------------------

def _export_service() -> MarkdownExportService:
    return MarkdownExportService()


def _make_article(unavailable: list[str] | None = None) -> object:
    return _generation_service().generate(
        _generation_request(unavailable=unavailable or [])
    )


def test_markdown_contains_title() -> None:
    article = _make_article()
    result = _export_service().export(article, _fcos_publication(), _fcos_brief())  # type: ignore[arg-type]
    assert f"# {article.title}" in result.content  # type: ignore[union-attr]


def test_markdown_export_produces_valid_filename() -> None:
    article = _make_article()
    result = _export_service().export(article, _fcos_publication(), _fcos_brief())  # type: ignore[arg-type]
    assert result.filename.endswith(".md")
    assert len(result.filename) > 4


def test_markdown_includes_unavailable_dependency_section() -> None:
    article = _make_article(unavailable=["orchid_continuum_corpus"])
    result = _export_service().export(article, _fcos_publication(), _fcos_brief())  # type: ignore[arg-type]
    assert "Unavailable Dependencies" in result.content
    assert "orchid_continuum_corpus" in result.content


def test_markdown_omits_project_table_when_no_verified_projects() -> None:
    article = _make_article()
    result = _export_service().export(article, _fcos_publication(), _fcos_brief())  # type: ignore[arg-type]
    assert "## Verified Projects" not in result.content


# ---------------------------------------------------------------------------
# 13–19. HTTP contract via TestClient
# ---------------------------------------------------------------------------

def test_http_brief_requires_auth() -> None:
    # No dependency override — raw auth check
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/calyx-journalism/brief",
            json={
                "publication": {
                    "publication_id": "fcos",
                    "publication_name": "Test",
                    "theme": "conservation",
                },
                "brief": {
                    "title": "T",
                    "focus": "F",
                },
            },
        )
    assert response.status_code == 401


def test_http_brief_accepted_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.post(
            "/api/calyx-journalism/brief",
            headers={"X-API-Key": API_KEY},
            json={
                "publication": {
                    "publication_id": "fcos",
                    "publication_name": "Orchid Continuum",
                    "theme": "conservation",
                },
                "brief": {
                    "title": "Global Survey",
                    "focus": "Survey orchid conservation from verified evidence.",
                    "target_word_count_min": 800,
                    "target_word_count_max": 1500,
                },
            },
        )
    assert response.status_code == 201
    data = response.json()
    assert data["accepted"] is True
    assert data["brief"]["title"] == "Global Survey"


def test_http_presets_lists_fcos() -> None:
    client = _client()
    response = client.get("/api/calyx-journalism/presets")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    preset_ids = [p["preset_id"] for p in data["presets"]]
    assert "fcos" in preset_ids


def test_http_preset_unknown_returns_404() -> None:
    client = _client()
    response = client.get("/api/calyx-journalism/presets/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PRESET_NOT_FOUND"


def test_http_evidence_preview_returns_packet() -> None:
    client = _client()
    response = client.post(
        "/api/calyx-journalism/evidence-preview",
        json={
            "evidence_items": [
                {"project_name": "EDGE Orchids", "country": "UK", "source_id": "e-001"}
            ],
            "available_dependencies": [],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["item_count"] == 1
    assert data["mode"] == "limited_evidence"
    assert len(data["verified_projects"]) == 1
    assert data["verified_projects"][0]["project_name"] == "EDGE Orchids"


def test_http_generate_then_export_round_trip() -> None:
    client = _client()

    # Generate
    gen_response = client.post(
        "/api/calyx-journalism/generate",
        json={
            "publication": {
                "publication_id": "fcos",
                "publication_name": "Orchid Continuum",
                "theme": "conservation",
            },
            "brief": {
                "title": "Global Orchid Conservation",
                "focus": "Verified evidence only.",
            },
            "generation_mode": {
                "mode": "limited_evidence",
                "unavailable_dependencies": ["orchid_continuum_corpus"],
            },
        },
    )
    assert gen_response.status_code == 201
    article = gen_response.json()
    article_id = article["article_id"]
    assert article["mode"] == "limited_evidence"
    assert "orchid_continuum_corpus" in article["unavailable_dependencies"]

    # Export
    export_response = client.post(
        "/api/calyx-journalism/export/markdown",
        json={
            "article_id": article_id,
            "publication": {
                "publication_id": "fcos",
                "publication_name": "Orchid Continuum",
                "theme": "conservation",
            },
            "brief": {
                "title": "Global Orchid Conservation",
                "focus": "Verified evidence only.",
            },
        },
    )
    assert export_response.status_code == 200
    export_data = export_response.json()
    assert export_data["article_id"] == article_id
    assert export_data["filename"].endswith(".md")
    assert "# Global Orchid Conservation" in export_data["content"]
    assert "Unavailable Dependencies" in export_data["content"]


def test_http_export_unknown_article_returns_404() -> None:
    client = _client()
    response = client.post(
        "/api/calyx-journalism/export/markdown",
        json={
            "article_id": "00000000-0000-0000-0000-000000000000",
            "publication": {
                "publication_id": "fcos",
                "publication_name": "Orchid Continuum",
                "theme": "conservation",
            },
            "brief": {
                "title": "T",
                "focus": "F",
            },
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ARTICLE_NOT_FOUND"
