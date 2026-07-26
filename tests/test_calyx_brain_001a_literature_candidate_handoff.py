from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.literature_extraction.candidate_handoff import (
    LiteratureCandidateHandoffError,
    LiteratureCandidateHandoffService,
    LiteratureSourceBinding,
)
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.routes import (
    get_candidate_handoff_service,
    get_literature_repository,
    router,
)
from app.literature_extraction.service import extract_and_persist


def _source(path: Path, statement: str) -> Path:
    path.write_bytes(
        (
            "Escherichia coli Orchid Trait Study\n\n"
            "Abstract\nEscherichia coli was studied on orchid roots.\n\n"
            "Methods\nPCR was used to observe Escherichia coli.\n\n"
            f"Results\n{statement}\n\n"
            "Discussion\nThe flower trait requires independent review.\n"
        ).encode()
    )
    return path


def _binding(paper) -> LiteratureSourceBinding:
    return LiteratureSourceBinding(
        source_object_type="LITERATURE_DOCUMENT",
        source_object_id=101,
        revision_id=201,
        extraction_run_id=301,
        anchor_ids={
            evidence.evidence_id: 400 + index
            for index, evidence in enumerate(paper.evidence, start=1)
        },
        display_policy="INTERNAL_RESEARCH_ONLY",
        internal_use_permission=True,
    )


@pytest.mark.asyncio
async def test_verified_literature_to_review_only_candidate_handoff(
    tmp_path: Path,
) -> None:
    source = _source(
        tmp_path / "trait.txt",
        "Escherichia coli was characterized by a red flower trait.",
    )
    literature_repository = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(source, literature_repository)
    candidate_repository = MemoryCandidateRepository()
    service = LiteratureCandidateHandoffService(
        CandidateExtractionService(candidate_repository), candidate_repository
    )

    first = service.handoff(paper, _binding(paper))
    second = service.handoff(paper, _binding(paper))

    assert first["state"] == second["state"] == "COMPLETED"
    assert first["plan_counts"] == {"EXTRACT": 1}
    assert second["plan_counts"] == {"REUSE": 1}
    assert first["candidate_ids"] == second["candidate_ids"]
    assert len(candidate_repository.candidates) == 1
    candidate = candidate_repository.candidates[0]
    assert candidate["kind"] == "TRAIT"
    assert candidate["review_state"] == "REQUIRED"
    assert candidate["published"] is False
    assert candidate["confidence_components"]["extraction"] == 0.5
    assert candidate["qualifiers"]["unresolved_entities"] == ["escherichia coli"]
    link = candidate_repository.evidence_links[0]
    assert link["revision_id"] == 201
    assert link["extraction_run_id"] == 301
    assert link["anchor"]["locator"]["source_hash"] == paper.source.content_hash
    assert link["anchor"]["char_start"] is not None
    assert candidate_repository.reviews


@pytest.mark.asyncio
async def test_ambiguity_is_blocked_and_reported_without_candidate_creation(
    tmp_path: Path,
) -> None:
    source = _source(
        tmp_path / "ambiguous.txt",
        "ATP in Escherichia coli was characterized by a red flower trait.",
    )
    paper = await extract_and_persist(
        source, LiteratureResultRepository(tmp_path / "literature")
    )
    candidate_repository = MemoryCandidateRepository()
    service = LiteratureCandidateHandoffService(
        CandidateExtractionService(candidate_repository), candidate_repository
    )

    with pytest.raises(LiteratureCandidateHandoffError) as caught:
        service.handoff(paper, _binding(paper))

    assert caught.value.code == "NO_ELIGIBLE_CANDIDATES"
    assert any(
        item.code == "AMBIGUOUS_OR_MISSING_SUBJECT" for item in caught.value.blocked
    )
    assert candidate_repository.candidates == []
    assert candidate_repository.runs == {}


@pytest.mark.asyncio
async def test_authenticated_handoff_api_is_queryable_and_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    source = _source(
        tmp_path / "api.txt",
        "Escherichia coli was characterized by a red flower trait.",
    )
    literature_repository = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(source, literature_repository)
    candidate_repository = MemoryCandidateRepository()
    handoff_service = LiteratureCandidateHandoffService(
        CandidateExtractionService(candidate_repository), candidate_repository
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_literature_repository] = lambda: literature_repository
    app.dependency_overrides[get_candidate_handoff_service] = lambda: handoff_service
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    payload = {
        "source_object_type": "LITERATURE_DOCUMENT",
        "source_object_id": 101,
        "revision_id": 201,
        "extraction_run_id": 301,
        "anchor_ids": _binding(paper).anchor_ids,
        "display_policy": "METADATA_ONLY",
    }

    with TestClient(app) as client:
        path = f"/api/literature-extraction/papers/{paper.paper_id}/candidate-handoff"
        assert client.post(path, json=payload).status_code == 401
        first = client.post(path, json=payload, headers={"X-API-Key": "test-key"})
        second = client.post(path, json=payload, headers={"X-API-Key": "test-key"})

    assert first.status_code == second.status_code == 201
    assert first.json()["plan_counts"] == {"EXTRACT": 1}
    assert second.json()["plan_counts"] == {"REUSE": 1}
    assert first.json()["candidate_ids"] == second.json()["candidate_ids"]
    assert first.json()["published"] is False
    assert candidate_repository.evidence_links[0]["authorized_quote"] is None
