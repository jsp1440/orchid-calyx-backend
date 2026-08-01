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
    evidence_items: list[dict] | None = None,
) -> ArticleGenerationRequest:
    return ArticleGenerationRequest(
        publication=_fcos_publication(),
        brief=_fcos_brief(),
        generation_mode=GenerationMode(
            mode=mode,  # type: ignore[arg-type]
            unavailable_dependencies=unavailable or [],
        ),
        operator_notes=None,
        evidence_items=evidence_items or [],
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


def test_full_continuum_mode_with_evidence_has_no_warning() -> None:
    """Full-Continuum mode with sufficient evidence should produce no warnings."""
    # Use a brief with a lower word-count minimum so the test focuses on
    # the no-fabrication guarantee rather than word-count enforcement.
    brief = ArticleBrief(
        title="Global Orchid Conservation",
        focus="Survey global orchid conservation from verified evidence only.",
        target_word_count_min=100,
        target_word_count_max=1500,
    )
    evidence = [
        {
            "project_name": "EDGE Orchids",
            "country": "UK",
            "source_id": "e-1",
            "summary": (
                "EDGE Orchids focuses on evolutionarily distinct species at extinction risk, "
                "combining seed banking with habitat restoration across partner institutions."
            ),
        }
    ]
    request = ArticleGenerationRequest(
        publication=_fcos_publication(),
        brief=brief,
        generation_mode=GenerationMode(
            mode="full_continuum",
            unavailable_dependencies=[],
        ),
        evidence_items=evidence,
    )
    response = _generation_service().generate(request)
    assert response.mode == "full_continuum"
    assert response.warnings == []


def test_full_continuum_mode_without_evidence_warns() -> None:
    """Full-Continuum mode without evidence must warn rather than make false claims."""
    response = _generation_service().generate(_generation_request(mode="full_continuum"))
    assert response.mode == "full_continuum"
    assert any("no evidence" in w.lower() for w in response.warnings)


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
    """Markdown project table (pipe format) must not appear when no projects exist."""
    article = _make_article()
    result = _export_service().export(article, _fcos_publication(), _fcos_brief())  # type: ignore[arg-type]
    # The section heading will be present (with "No verified projects..." body),
    # but the Markdown pipe table must not be rendered when there are no rows.
    assert "| Project | Country | Region | Source |" not in result.content


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

# ---------------------------------------------------------------------------
# New: evidence-grounded generation tests
# ---------------------------------------------------------------------------

# Rich evidence fixture used across several tests below
_RICH_EVIDENCE = [
    {
        "project_name": "EDGE Orchids",
        "country": "United Kingdom",
        "region": "Europe",
        "source_id": "src-001",
        "evidence_type": "project",
        "context": (
            "Orchid diversity is under severe pressure globally. Habitat loss driven by "
            "agriculture and urban expansion has reduced suitable range for over 28,000 species. "
            "Climate change is accelerating range shifts, pushing many montane and epiphytic "
            "orchids beyond the altitudinal limits they have occupied for millennia."
        ),
        "summary": (
            "The EDGE Orchids programme prioritises evolutionarily distinct and globally "
            "endangered orchid species. Working across the United Kingdom and partner institutions "
            "in Southeast Asia, it combines seed-banking, habitat restoration, and community "
            "engagement to halt the decline of priority taxa."
        ),
        "approach": "in-situ conservation and ex-situ seed banking",
        "knowledge_gap": (
            "Long-term demographic data for most epiphytic orchid genera remains absent outside "
            "temperate Europe and North America, making population viability assessments impossible "
            "for the majority of tropical species."
        ),
        "action_recommendations": (
            "Growers can support verified conservation programmes by propagating species from "
            "documented wild-collected seed lots, registering plants with national orchid "
            "societies, and donating propagation surpluses to accredited seed banks."
        ),
        "finding": (
            "EDGE data indicate that fewer than 15 % of orchid species threatened with extinction "
            "are covered by any active recovery programme, highlighting a critical capacity gap."
        ),
        "citation": "EDGE Orchids Programme Annual Report 2024, Royal Botanic Gardens Kew.",
    },
    {
        "project_name": "Andes Orchid Fund",
        "country": "Ecuador",
        "region": "South America",
        "source_id": "src-002",
        "evidence_type": "project",
        "summary": (
            "The Andes Orchid Fund supports landowner agreements in cloud-forest buffer zones "
            "across northern Ecuador. As of the last reporting cycle, 42 landowner parcels "
            "totalling 3,800 ha are under active stewardship agreements that prohibit conversion "
            "of primary cloud forest to pasture."
        ),
        "approach": "payment for ecosystem services and landowner stewardship agreements",
        "finding": (
            "Stewardship parcels show a 31 % higher orchid species richness than adjacent "
            "unmanaged forest fragments, based on transect surveys conducted in 2023."
        ),
        "citation": "Andes Orchid Fund Field Survey, Quito, Ecuador, 2023.",
    },
    {
        "project_name": "Borneo Orchid Network",
        "country": "Malaysia",
        "region": "Southeast Asia",
        "source_id": "src-003",
        "evidence_type": "project",
        "context": (
            "Borneo hosts more than 3,000 described orchid species, many of them narrowly "
            "endemic to specific limestone karst or ultra-mafic substrate types. Logging and "
            "palm-oil conversion continue to fragment these habitats at a rate that outpaces "
            "botanical documentation."
        ),
        "summary": (
            "The Borneo Orchid Network operates a network of satellite nurseries staffed by "
            "indigenous community rangers. Rescued plants from legally authorised salvage "
            "operations are propagated and reintroduced to restored forest patches under "
            "five-year monitoring agreements."
        ),
        "approach": "community ranger networks and habitat salvage propagation",
        "knowledge_gap": (
            "Pollinator networks for most Bornean slipper orchids (Paphiopedilum spp.) are "
            "undocumented. Without pollinator data, reintroduction success cannot be reliably "
            "predicted or improved."
        ),
        "action_recommendations": (
            "Specialist growers of Paphiopedilum are encouraged to participate in coordinated "
            "hand-pollination projects that generate documented F1 seed lots traceable to "
            "verified wild-parent material."
        ),
        "citation": "Borneo Orchid Network Progress Report, Sabah, 2024.",
    },
]


def test_evidence_items_produce_verified_projects_in_response() -> None:
    """Verified projects must be extracted from evidence and returned in the response."""
    response = _generation_service().generate(
        _generation_request(mode="limited_evidence", evidence_items=_RICH_EVIDENCE)
    )
    assert len(response.verified_projects) == 3
    names = {p.project_name for p in response.verified_projects}
    assert "EDGE Orchids" in names
    assert "Andes Orchid Fund" in names
    assert "Borneo Orchid Network" in names


def test_citations_preserved_from_evidence_fields() -> None:
    """Citations must be drawn from evidence citation fields, not fabricated."""
    response = _generation_service().generate(
        _generation_request(mode="limited_evidence", evidence_items=_RICH_EVIDENCE)
    )
    all_cites = [c for section in response.sections for c in section.citations]
    assert len(all_cites) > 0, "Expected citations drawn from evidence citation fields"
    for cite in all_cites:
        expected_cites = [item["citation"] for item in _RICH_EVIDENCE if "citation" in item]
        assert cite in expected_cites, (
            f"Citation '{cite}' was not drawn from the supplied evidence"
        )


def test_word_count_meets_minimum_with_sufficient_evidence() -> None:
    """Rich evidence should yield a word count at or above the brief minimum."""
    # Use a minimum of 500 words — achievable with three rich evidence items
    from app.calyx_journalism.schemas import ArticleBrief as _Brief
    rich_brief = _Brief(
        title="Global Orchid Conservation",
        focus="Survey global orchid conservation status from verified evidence only.",
        target_word_count_min=500,
        target_word_count_max=1500,
        scope_hints=["global", "conservation"],
        tags=["fcos"],
    )
    request = ArticleGenerationRequest(
        publication=_fcos_publication(),
        brief=rich_brief,
        generation_mode=GenerationMode(
            mode="limited_evidence",
            unavailable_dependencies=[],
        ),
        evidence_items=_RICH_EVIDENCE,
    )
    response = _generation_service().generate(request)
    assert response.word_count >= 500, (
        f"Expected ≥500 words with rich evidence; got {response.word_count}"
    )
    assert response.insufficient_evidence is False


def test_insufficient_evidence_flag_when_no_evidence() -> None:
    """Empty evidence should set insufficient_evidence=True and add a warning."""
    response = _generation_service().generate(
        _generation_request(mode="limited_evidence", evidence_items=[])
    )
    assert response.insufficient_evidence is True
    assert any("insufficient evidence" in w.lower() for w in response.warnings)


def test_project_table_preserved_in_markdown_export() -> None:
    """Verified projects from evidence must appear in the Markdown project table."""
    article = _generation_service().generate(
        _generation_request(mode="limited_evidence", evidence_items=_RICH_EVIDENCE)
    )
    result = _export_service().export(article, _fcos_publication(), _fcos_brief())
    assert "## Verified Projects" in result.content
    assert "EDGE Orchids" in result.content
    assert "Andes Orchid Fund" in result.content


def test_full_continuum_does_not_claim_corpus_without_evidence() -> None:
    """The Evidence Availability section must not falsely claim corpus citations."""
    response = _generation_service().generate(
        _generation_request(mode="full_continuum", evidence_items=[])
    )
    avail_section = next(
        (s for s in response.sections if s.heading == "Evidence Availability"), None
    )
    assert avail_section is not None
    body_lower = avail_section.body.lower()
    # If "corpus" appears in the body, "no evidence" must also appear to
    # clarify that no corpus evidence was consumed.
    if "corpus" in body_lower:
        assert "no evidence" in body_lower, (
            "Section mentions 'corpus' but does not clarify that no evidence was consumed"
        )


def test_preview_returns_packet_id() -> None:
    """Evidence preview must return a non-empty packet_id for store referencing."""
    packet = _preview().build_preview(
        evidence_items=[{"project_name": "EDGE Orchids"}], available_dependencies=[]
    )
    assert packet.packet_id
    assert len(packet.packet_id) > 0


# ---------------------------------------------------------------------------
# New: end-to-end HTTP tests (evidence_packet_id flow)
# ---------------------------------------------------------------------------

def test_http_preview_stores_packet_with_id() -> None:
    """POST /evidence-preview must return a non-empty packet_id."""
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
    assert data.get("packet_id"), "Expected a non-empty packet_id in the preview response"


def test_http_generate_with_evidence_packet_id_e2e() -> None:
    """Full end-to-end: preview → packet_id → generate → export with verified projects."""
    client = _client()

    # Build rich evidence items
    items = [
        {
            "project_name": "EDGE Orchids",
            "country": "UK",
            "region": "Europe",
            "source_id": "e-001",
            "summary": "EDGE Orchids focuses on evolutionarily distinct species at risk of extinction.",
            "citation": "EDGE Annual Report 2024, Kew.",
            "approach": "in-situ conservation",
            "finding": "Coverage of threatened species by active recovery programmes is below 15 %.",
            "knowledge_gap": "Long-term demographic data absent for most tropical genera.",
            "action_recommendations": "Growers should propagate from documented wild-collected seed lots.",
            "context": (
                "Global orchid diversity is threatened by habitat loss, climate change, "
                "and illegal trade. Conservation capacity remains far below the scale required."
            ),
        },
        {
            "project_name": "Andes Orchid Fund",
            "country": "Ecuador",
            "region": "South America",
            "source_id": "e-002",
            "summary": "Supports landowner stewardship in cloud-forest buffer zones.",
            "citation": "Andes Orchid Fund Field Survey 2023.",
        },
    ]

    # Step 1: evidence preview → capture packet_id
    preview_resp = client.post(
        "/api/calyx-journalism/evidence-preview",
        json={"evidence_items": items, "available_dependencies": []},
    )
    assert preview_resp.status_code == 201
    packet_id = preview_resp.json()["packet_id"]
    assert packet_id

    # Step 2: generate using the stored packet
    gen_resp = client.post(
        "/api/calyx-journalism/generate",
        json={
            "publication": {
                "publication_id": "fcos",
                "publication_name": "Orchid Continuum",
                "theme": "conservation",
            },
            "brief": {
                "title": "Global Orchid Conservation",
                "focus": (
                    "Survey global orchid conservation status from verified evidence only. "
                    "Do not fabricate project counts, citations, or status."
                ),
                "target_word_count_min": 150,
                "target_word_count_max": 1500,
            },
            "generation_mode": {
                "mode": "limited_evidence",
                "unavailable_dependencies": ["orchid_continuum_corpus"],
            },
            "evidence_packet_id": packet_id,
        },
    )
    assert gen_resp.status_code == 201
    article = gen_resp.json()
    article_id = article["article_id"]

    # Verified projects must be populated from evidence
    assert len(article["verified_projects"]) == 2
    proj_names = {p["project_name"] for p in article["verified_projects"]}
    assert "EDGE Orchids" in proj_names
    assert "Andes Orchid Fund" in proj_names

    # Citations must come from evidence
    all_cites = [c for s in article["sections"] for c in s["citations"]]
    assert len(all_cites) > 0

    # Word count must be above minimum
    assert article["word_count"] >= 150
    assert article["insufficient_evidence"] is False

    # Step 3: Markdown export must contain the project table
    export_resp = client.post(
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
                "focus": "Survey orchid conservation from verified evidence.",
            },
        },
    )
    assert export_resp.status_code == 200
    md = export_resp.json()["content"]
    assert "## Verified Projects" in md
    assert "EDGE Orchids" in md
    assert "Andes Orchid Fund" in md
    assert "EDGE Annual Report 2024" in md


def test_http_generate_unknown_packet_id_returns_404() -> None:
    """Referencing a non-existent packet_id must return 404."""
    client = _client()
    resp = client.post(
        "/api/calyx-journalism/generate",
        json={
            "publication": {
                "publication_id": "fcos",
                "publication_name": "Orchid Continuum",
                "theme": "conservation",
            },
            "brief": {"title": "T", "focus": "F"},
            "generation_mode": {"mode": "limited_evidence"},
            "evidence_packet_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "EVIDENCE_PACKET_NOT_FOUND"


def test_http_insufficient_evidence_flagged_in_response() -> None:
    """Generate without evidence should return insufficient_evidence=True."""
    client = _client()
    resp = client.post(
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
                "target_word_count_min": 800,
                "target_word_count_max": 1500,
            },
            "generation_mode": {"mode": "limited_evidence", "unavailable_dependencies": []},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["insufficient_evidence"] is True
    assert any("insufficient" in w.lower() for w in data["warnings"])
