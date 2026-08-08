from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.literature_extraction.context import PipelineConfig
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.routes import get_literature_repository, router
from app.literature_extraction.service import (
    LiteraturePipelineError,
    extract_and_persist,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "literature"
    / "calyx_brain_001_orchid_study.txt"
)


@pytest.mark.asyncio
async def test_real_document_to_authenticated_queryable_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    repository = LiteratureResultRepository(tmp_path / "results")
    first = await extract_and_persist(FIXTURE, repository)
    second = await extract_and_persist(FIXTURE, repository)

    assert first.paper_id == second.paper_id
    assert first.analysis_manifest.analysis_id == second.analysis_manifest.analysis_id
    assert first.analysis_manifest.input_fingerprint == first.source.content_hash
    assert first.analysis_manifest.configuration_fingerprint
    assert [run.name for run in first.analysis_manifest.extractors] == [
        "metadata",
        "sections",
        "entities",
        "glossary",
        "claims",
    ]
    assert all(
        run.status == "completed" and run.version
        for run in first.analysis_manifest.extractors
    )
    assert first.metadata.title == "ATP Response in Escherichia coli on Orchid Roots"
    assert first.metadata.publication_year == 2025
    assert {section.canonical_type for section in first.sections} >= {
        "methods",
        "results",
        "discussion",
    }
    assert {entity.normalized_name for entity in first.entities} >= {
        "atp",
        "pcr",
        "escherichia coli",
    }
    assert {term.normalized_term for term in first.glossary_terms} >= {
        "atp",
        "pcr",
        "orchids",
        "roots",
        "microbiology",
    }
    assert all(term.status == "candidate" for term in first.glossary_terms)
    assert first.claims and first.evidence and first.normalized_evidence_records
    assert any(claim.subject_ids for claim in first.claims)
    assert any(
        record.unresolved_entities for record in first.normalized_evidence_records
    )
    assert all(
        not record.canonical_entity_ids for record in first.normalized_evidence_records
    )
    assert all(decision.status == "blocked" for decision in first.publication_decisions)

    raw = FIXTURE.read_text(encoding="utf-8")
    for evidence in first.evidence:
        assert (
            raw[evidence.span.char_start : evidence.span.char_end] == evidence.excerpt
        )
        assert evidence.supports_ids

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_literature_repository] = lambda: repository
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    with TestClient(app) as client:
        assert (
            client.get(
                f"/api/literature-extraction/papers/{first.paper_id}"
            ).status_code
            == 401
        )
        response = client.get(
            f"/api/literature-extraction/papers/{first.paper_id}",
            headers={"X-API-Key": "test-key"},
        )
    assert response.status_code == 200
    assert response.json()["claims"][0]["evidence_ids"]
    assert response.json()["glossary_terms"]


@pytest.mark.asyncio
async def test_empty_stage_is_a_structured_failure_and_is_persisted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "incomplete.txt"
    source.write_text("A title only\n", encoding="utf-8")
    repository = LiteratureResultRepository(tmp_path / "failed")

    with pytest.raises(LiteraturePipelineError) as caught:
        await extract_and_persist(source, repository)

    assert caught.value.stage == "sections"
    assert caught.value.code == "EMPTY_REQUIRED_OUTPUT"
    paper_id = f"paper-{__import__('hashlib').sha256(source.read_bytes()).hexdigest()}"
    persisted = repository.get(paper_id)
    assert persisted is not None
    assert persisted.analysis_manifest.status == "failed"


@pytest.mark.asyncio
async def test_identity_covers_document_pipeline_and_extractor_configuration(
    tmp_path: Path,
) -> None:
    repository = LiteratureResultRepository(tmp_path / "identity")
    first = await extract_and_persist(FIXTURE, repository)
    changed_pipeline = await extract_and_persist(
        FIXTURE,
        repository,
        config=PipelineConfig(pipeline_version="0.2.1"),
    )
    second_source = tmp_path / "second.txt"
    second_source.write_bytes(FIXTURE.read_bytes() + b"\nAdditional source material.\n")
    second_document = await extract_and_persist(second_source, repository)

    assert len({first.paper_id, second_document.paper_id}) == 2
    assert (
        len(
            {
                first.analysis_manifest.analysis_id,
                changed_pipeline.analysis_manifest.analysis_id,
                second_document.analysis_manifest.analysis_id,
            }
        )
        == 3
    )
    assert (
        first.analysis_manifest.configuration_fingerprint
        != changed_pipeline.analysis_manifest.configuration_fingerprint
    )


@pytest.mark.asyncio
async def test_crlf_evidence_offsets_reference_original_decoded_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "crlf.txt"
    source.write_bytes(FIXTURE.read_bytes().replace(b"\n", b"\r\n"))
    result = await extract_and_persist(
        source, LiteratureResultRepository(tmp_path / "crlf-results")
    )
    original = source.read_bytes().decode("utf-8")

    for evidence in result.evidence:
        assert (
            original[evidence.span.char_start : evidence.span.char_end]
            == evidence.excerpt
        )
