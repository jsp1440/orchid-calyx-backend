from __future__ import annotations

import base64
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.figure_assisted_gateway import router
from app.security import verify_owner_or_api_key
from runtime.figure_assisted_gateway import (
    AssistedFigureGateway,
    FigureBrief,
    FigureSource,
    orchid_root_velamen_brief,
)


def _gateway() -> AssistedFigureGateway:
    gateway = AssistedFigureGateway()
    gateway.register_brief(orchid_root_velamen_brief())
    return gateway


def _svg() -> bytes:
    return b'<svg xmlns="http://www.w3.org/2000/svg"><text>velamen</text></svg>'


def _pptx(*, traversal: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/presentation.xml", "<p:presentation/>")
        if traversal:
            archive.writestr("../escape.txt", "blocked")
    return buffer.getvalue()


def test_velamen_brief_is_deterministic_and_candidate_only() -> None:
    gateway = _gateway()
    first = gateway.brief_package("figure-brief:orchid-root-velamen-v1")
    second = gateway.brief_package("figure-brief:orchid-root-velamen-v1")
    assert first == second
    assert len(first["brief_digest"]) == 64
    assert first["brief"]["required_labels"] == (
        "root tip",
        "velamen",
        "exodermis",
        "passage cells",
        "cortex",
        "endodermis",
        "stele",
    )
    assert first["instructions"]["provider_network_call_authorized"] is False
    assert first["instructions"]["credential_storage_authorized"] is False
    assert first["publication_authorized"] is False


def test_cost_and_license_guards_fail_closed() -> None:
    source = FigureSource(
        source_uri="evidence://figure/1",
        citation="Evidence",
        license="cc-by-4.0",
        evidence_sha256="a" * 64,
    )
    brief = FigureBrief(
        brief_id="brief:test",
        project_id="project:test",
        title="Test",
        purpose="Test figure",
        required_labels=("velamen",),
        source_records=(source,),
        output_formats=("svg",),
        provider_hint=None,
        estimated_cost_usd=25.01,
    )
    with pytest.raises(ValueError, match="ESTIMATED_COST_EXCEEDS_BOUND"):
        AssistedFigureGateway().register_brief(brief)

    bad_source = FigureSource(
        source_uri="evidence://figure/1",
        citation="Evidence",
        license="all-rights-reserved",
        evidence_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="SOURCE_LICENSE_NOT_ALLOWED"):
        bad_source.validate()


def test_svg_import_preserves_provenance_hotspots_and_replay() -> None:
    gateway = _gateway()
    kwargs = {
        "brief_id": "figure-brief:orchid-root-velamen-v1",
        "format": "svg",
        "content": _svg(),
        "source_uri": "file://operator-export/root-velamen.svg",
        "creator": "Assisted scientific illustration workflow",
        "attribution": "Figure candidate; source evidence retained in brief",
        "license": "internal-reviewed",
        "semantic_hotspots": [
            {
                "concept_id": "concept:velamen",
                "label": "velamen",
                "evidence_uri": "evidence://knowledge-explorer/velamen/1",
            }
        ],
    }
    first = gateway.import_asset(**kwargs)
    replay = gateway.import_asset(**kwargs)
    assert first == replay
    assert first.duplicate_of is None
    assert first.media_type == "image/svg+xml"
    assert first.semantic_hotspots[0]["concept_id"] == "concept:velamen"
    assert first.publication_authorized is False
    assert first.production_graph_mutation_authorized is False

    readiness = gateway.readiness("figure-brief:orchid-root-velamen-v1")
    assert readiness["decision"] == "REVIEW_ONLY"
    assert readiness["ready_for_scientific_review"] is True
    assert readiness["ready_for_publication"] is False
    assert readiness["missing_formats"] == ["png", "pptx"]
    assert "REQUIRED_OUTPUT_FORMATS_MISSING" in readiness["blockers"]
    assert "SCIENTIFIC_REVIEW_REQUIRED" in readiness["blockers"]
    assert "LICENSING_REVIEW_REQUIRED" in readiness["blockers"]


def test_active_or_external_svg_content_is_rejected() -> None:
    gateway = _gateway()
    for content in (
        b"<svg><script>alert(1)</script></svg>",
        b'<svg><image href="https://example.test/a.png"/></svg>',
        b"<!DOCTYPE svg><svg></svg>",
    ):
        with pytest.raises(ValueError, match="SVG_ACTIVE_CONTENT_FORBIDDEN"):
            gateway.import_asset(
                brief_id="figure-brief:orchid-root-velamen-v1",
                format="svg",
                content=content,
                source_uri="file://operator-export/bad.svg",
                creator="operator",
                attribution="candidate",
                license="internal-reviewed",
            )


def test_output_signatures_and_pptx_structure_are_checked() -> None:
    gateway = _gateway()
    common = {
        "brief_id": "figure-brief:orchid-root-velamen-v1",
        "source_uri": "file://operator-export/asset",
        "creator": "operator",
        "attribution": "candidate",
        "license": "internal-reviewed",
    }
    with pytest.raises(ValueError, match="PNG_SIGNATURE_INVALID"):
        gateway.import_asset(format="png", content=b"not-png", **common)
    with pytest.raises(ValueError, match="PPTX_SIGNATURE_INVALID"):
        gateway.import_asset(format="pptx", content=b"not-zip", **common)

    imported = gateway.import_asset(format="pptx", content=_pptx(), **common)
    assert imported.media_type.endswith("presentationml.presentation")
    with pytest.raises(ValueError, match="PPTX_PATH_INVALID"):
        gateway.import_asset(format="pptx", content=_pptx(traversal=True), **common)


def test_brief_rejects_unrequested_import_format() -> None:
    source = FigureSource(
        source_uri="evidence://figure/1",
        citation="Evidence",
        license="cc-by-4.0",
        evidence_sha256="b" * 64,
    )
    brief = FigureBrief(
        brief_id="brief:svg-only",
        project_id="project:test",
        title="SVG only",
        purpose="Bounded format test",
        required_labels=("velamen",),
        source_records=(source,),
        output_formats=("svg",),
        provider_hint=None,
        estimated_cost_usd=0,
    )
    gateway = AssistedFigureGateway()
    gateway.register_brief(brief)
    with pytest.raises(ValueError, match="OUTPUT_FORMAT_NOT_REQUESTED"):
        gateway.import_asset(
            brief_id=brief.brief_id,
            format="png",
            content=b"\x89PNG\r\n\x1a\nminimal",
            source_uri="file://operator-export/a.png",
            creator="operator",
            attribution="candidate",
            license="internal-reviewed",
        )


def test_conflicting_same_asset_identity_is_rejected() -> None:
    gateway = _gateway()
    first = gateway.import_asset(
        brief_id="figure-brief:orchid-root-velamen-v1",
        format="svg",
        content=_svg(),
        source_uri="file://operator-export/root.svg",
        creator="operator",
        attribution="candidate",
        license="internal-reviewed",
    )
    assert first.asset_id
    with pytest.raises(ValueError, match="IMMUTABLE_FIGURE_ASSET_CONFLICT"):
        gateway.import_asset(
            brief_id="figure-brief:orchid-root-velamen-v1",
            format="svg",
            content=_svg(),
            source_uri="file://operator-export/root.svg",
            creator="different creator",
            attribution="candidate",
            license="internal-reviewed",
        )


def test_protected_routes_require_authentication_and_accept_assisted_import() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    unauthenticated = client.get(
        "/brain/mission-control/figures/fixtures/orchid-root-velamen"
    )
    assert unauthenticated.status_code in {401, 403}

    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "owner"}
    authenticated = TestClient(app)
    fixture = authenticated.get(
        "/brain/mission-control/figures/fixtures/orchid-root-velamen"
    )
    assert fixture.status_code == 200
    payload = {
        "format": "svg",
        "content_base64": base64.b64encode(_svg()).decode("ascii"),
        "source_uri": "file://operator-export/api.svg",
        "creator": "operator",
        "attribution": "candidate",
        "license": "internal-reviewed",
        "semantic_hotspots": [],
    }
    imported = authenticated.post(
        "/brain/mission-control/figures/briefs/figure-brief:orchid-root-velamen-v1/imports",
        json=payload,
    )
    assert imported.status_code == 200
    assert imported.json()["publication_authorized"] is False


def test_invalid_base64_is_rejected_by_api() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "owner"}
    client = TestClient(app)
    response = client.post(
        "/brain/mission-control/figures/briefs/figure-brief:orchid-root-velamen-v1/imports",
        json={
            "format": "svg",
            "content_base64": "%%%%",
            "source_uri": "file://operator-export/api.svg",
            "creator": "operator",
            "attribution": "candidate",
            "license": "internal-reviewed",
            "semantic_hotspots": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "ASSET_BASE64_INVALID"
