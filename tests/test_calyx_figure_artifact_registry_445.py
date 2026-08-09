from __future__ import annotations

from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
from runtime.figure_assisted_gateway import AssistedFigureGateway, FigureBrief, FigureSource


def _source() -> FigureSource:
    return FigureSource(
        source_uri="evidence://figure/source",
        citation="Reviewed evidence",
        license="cc-by-4.0",
        evidence_sha256="c" * 64,
    )


def _brief(brief_id: str) -> FigureBrief:
    return FigureBrief(
        brief_id=brief_id,
        project_id="project:artifact-registry",
        title=brief_id,
        purpose="Exercise canonical artifact provenance and duplicate detection.",
        required_labels=("velamen",),
        source_records=(_source(),),
        output_formats=("svg",),
        provider_hint=None,
        estimated_cost_usd=0,
    )


def test_import_uses_build_brain_111_registry_and_preserves_evidence() -> None:
    registry = ImmutableArtifactRegistry()
    gateway = AssistedFigureGateway(registry)
    gateway.register_brief(_brief("brief:a"))
    asset = gateway.import_asset(
        brief_id="brief:a",
        format="svg",
        content=b"<svg><text>velamen</text></svg>",
        source_uri="file://operator/a.svg",
        creator="operator",
        attribution="candidate",
        license="cc-by-4.0",
        semantic_hotspots=[
            {
                "concept_id": "concept:velamen",
                "label": "velamen",
                "evidence_uri": "evidence://knowledge-explorer/velamen/1",
            }
        ],
    )
    record = registry.require_evidence(asset.asset_id)
    assert record.checksum == asset.checksum
    assert record.producer_assignment_id == "build-fig-301-assisted-gateway"
    assert record.evidence_uris == (
        "evidence://figure/source",
        "evidence://knowledge-explorer/velamen/1",
    )
    assert record.metadata["publication_authorized"] is False


def test_duplicate_content_across_briefs_reuses_registry_duplicate_signal() -> None:
    registry = ImmutableArtifactRegistry()
    gateway = AssistedFigureGateway(registry)
    gateway.register_brief(_brief("brief:a"))
    gateway.register_brief(_brief("brief:b"))
    content = b"<svg><text>same evidence-bound plate</text></svg>"
    first = gateway.import_asset(
        brief_id="brief:a",
        format="svg",
        content=content,
        source_uri="file://operator/a.svg",
        creator="operator",
        attribution="candidate",
        license="cc-by-4.0",
    )
    second = gateway.import_asset(
        brief_id="brief:b",
        format="svg",
        content=content,
        source_uri="file://operator/b.svg",
        creator="operator",
        attribution="candidate",
        license="cc-by-4.0",
    )
    assert second.asset_id != first.asset_id
    assert second.duplicate_of == first.asset_id
    assert registry.snapshot()["artifact_count"] == 2
    assert registry.snapshot()["unique_content_count"] == 1
