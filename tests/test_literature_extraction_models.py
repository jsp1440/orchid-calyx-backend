from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.literature_extraction.models import (
    AnalysisManifest,
    Entity,
    ExtractorRun,
    PaperKnowledge,
    PaperMetadata,
    Provenance,
    SourceDocument,
)


def make_paper() -> PaperKnowledge:
    return PaperKnowledge(
        paper_id="doi:10.0000/example",
        source=SourceDocument(
            content_hash="sha256:0123456789abcdef",
            media_type="application/pdf",
            original_filename="velamen-study.pdf",
            language="en",
        ),
        metadata=PaperMetadata(
            title="A study of orchid velamen",
            authors=["Example, A."],
        ),
        entities=[
            Entity(
                entity_id="entity:velamen",
                entity_type="anatomical_structure",
                name="velamen",
                provenance=Provenance(
                    method="source_reported",
                    confidence=1.0,
                ),
            )
        ],
        analysis_manifest=AnalysisManifest(
            analysis_id="analysis:doi:10.0000/example:1",
            analysis_version=1,
            created_at=datetime.now(timezone.utc),
            pipeline_version="0.1.0",
            status="completed",
            extractors=[
                ExtractorRun(
                    name="metadata",
                    version="0.1.0",
                    status="completed",
                    output_count=1,
                )
            ],
        ),
    )


def test_minimal_paper_package_round_trips() -> None:
    paper = make_paper()
    restored = PaperKnowledge.model_validate_json(paper.model_dump_json())

    assert restored.paper_id == paper.paper_id
    assert restored.entities[0].name == "velamen"
    assert restored.analysis_manifest.analysis_version == 1


def test_unknown_fields_are_rejected() -> None:
    payload = make_paper().model_dump()
    payload["invented_field"] = "must not silently pass"

    with pytest.raises(ValidationError):
        PaperKnowledge.model_validate(payload)


def test_confidence_must_be_bounded() -> None:
    with pytest.raises(ValidationError):
        Provenance(method="model_extracted", confidence=1.5)
