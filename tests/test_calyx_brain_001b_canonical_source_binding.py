from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.literature_extraction.candidate_handoff import (
    LiteratureCandidateHandoffService,
)
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.routes import (
    get_candidate_handoff_service,
    get_literature_repository,
    get_source_binding_repository,
    router,
)
from app.literature_extraction.service import extract_and_persist
from app.literature_extraction.source_binding import (
    CanonicalLiteratureSourceBinding,
    FileLiteratureSourceBindingRepository,
    LiteratureSourceBindingError,
)


def _source(path: Path) -> Path:
    path.write_text(
        "Orchid Trait Study\n\nAbstract\nOrchid roots were studied.\n\n"
        "Methods\nPCR was used.\n\nResults\nEscherichia coli was characterized "
        "by a red flower trait.\n\nDiscussion\nIndependent review is required.\n",
        encoding="utf-8",
    )
    return path


def _binding(paper) -> CanonicalLiteratureSourceBinding:
    return CanonicalLiteratureSourceBinding(
        paper_id=paper.paper_id,
        source_object_type="LITERATURE_DOCUMENT",
        source_object_id=101,
        revision_id=201,
        extraction_run_id=301,
        anchor_ids={
            evidence.evidence_id: 400 + index
            for index, evidence in enumerate(paper.evidence, start=1)
        },
        display_policy="METADATA_ONLY",
        internal_use_permission=True,
    )


def _verified_binding(paper, literature: LiteratureResultRepository):
    raw_bytes = literature.get_raw_bytes(paper.paper_id)
    assert raw_bytes is not None
    return _binding(paper).with_verified_integrity(paper, raw_bytes)


@pytest.mark.asyncio
async def test_create_get_and_idempotent_replay(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    repository = FileLiteratureSourceBindingRepository(tmp_path / "literature")
    binding = _verified_binding(paper, literature)

    first, first_created = repository.create(binding)
    second, second_created = repository.create(binding)

    assert first_created is True
    assert second_created is False
    assert first.fingerprint == second.fingerprint
    assert repository.get(paper.paper_id) == binding
    assert all(item["excerpt_hash"] for item in binding.evidence_integrity.values())


@pytest.mark.asyncio
async def test_conflicting_rebind_preserves_existing_binding(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    repository = FileLiteratureSourceBindingRepository(tmp_path / "literature")
    original = _verified_binding(paper, literature)
    repository.create(original)
    conflict = replace(original, source_object_id=999)

    with pytest.raises(LiteratureSourceBindingError) as caught:
        repository.create(conflict)

    assert caught.value.code == "CONFLICTING_SOURCE_REBIND"
    assert repository.get(paper.paper_id) == original


@pytest.mark.asyncio
async def test_missing_and_foreign_anchor_bindings_are_rejected(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    valid = _binding(paper)
    missing = dict(valid.anchor_ids)
    missing.pop(next(iter(missing)))
    incomplete = replace(valid, anchor_ids=missing)
    foreign = replace(valid, anchor_ids={**valid.anchor_ids, "foreign-evidence": 999})

    with pytest.raises(LiteratureSourceBindingError) as missing_error:
        incomplete.validate_against_paper(paper)
    with pytest.raises(LiteratureSourceBindingError) as foreign_error:
        foreign.validate_against_paper(paper)

    assert missing_error.value.code == "CANONICAL_EVIDENCE_BINDING_MISSING"
    assert foreign_error.value.code == "ANCHOR_EVIDENCE_IDS_NOT_IN_PAPER"


@pytest.mark.asyncio
async def test_tampered_raw_source_is_rejected_after_binding(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    binding = _verified_binding(paper, literature)
    raw_path = literature.root / paper.paper_id / "raw.txt"
    raw_path.write_bytes(raw_path.read_bytes() + b"tampered")

    with pytest.raises(LiteratureSourceBindingError) as caught:
        binding.validate_integrity(paper, raw_path.read_bytes())

    assert caught.value.code == "RAW_SOURCE_HASH_MISMATCH"


@pytest.mark.asyncio
async def test_tampered_excerpt_proof_is_rejected(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    binding = _verified_binding(paper, literature)
    evidence_id = next(iter(binding.evidence_integrity))
    integrity = {key: dict(value) for key, value in binding.evidence_integrity.items()}
    integrity[evidence_id]["excerpt_hash"] = "0" * 64
    corrupted = replace(binding, evidence_integrity=integrity)
    raw_bytes = literature.get_raw_bytes(paper.paper_id)
    assert raw_bytes is not None

    with pytest.raises(LiteratureSourceBindingError) as caught:
        corrupted.validate_integrity(paper, raw_bytes)

    assert caught.value.code == "SOURCE_INTEGRITY_PROOF_MISMATCH"


@pytest.mark.asyncio
async def test_authenticated_api_persists_binding_and_handoff_uses_it(
    tmp_path: Path, monkeypatch
) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    bindings = FileLiteratureSourceBindingRepository(tmp_path / "literature")
    candidates = MemoryCandidateRepository()
    handoff = LiteratureCandidateHandoffService(
        CandidateExtractionService(candidates), candidates
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_literature_repository] = lambda: literature
    app.dependency_overrides[get_source_binding_repository] = lambda: bindings
    app.dependency_overrides[get_candidate_handoff_service] = lambda: handoff
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    payload = {
        "source_object_type": "LITERATURE_DOCUMENT",
        "source_object_id": 101,
        "revision_id": 201,
        "extraction_run_id": 301,
        "anchor_ids": _binding(paper).anchor_ids,
        "display_policy": "METADATA_ONLY",
        "internal_use_permission": True,
    }

    with TestClient(app) as client:
        binding_path = f"/api/literature-extraction/papers/{paper.paper_id}/source-binding"
        handoff_path = f"/api/literature-extraction/papers/{paper.paper_id}/candidate-handoff"
        assert client.put(binding_path, json=payload).status_code == 401
        created = client.put(binding_path, json=payload, headers={"X-API-Key": "test-key"})
        replay = client.put(binding_path, json=payload, headers={"X-API-Key": "test-key"})
        result = client.post(
            handoff_path,
            json={"use_persisted_binding": True},
            headers={"X-API-Key": "test-key"},
        )

    assert created.status_code == 201
    assert replay.status_code == 200
    assert created.json()["binding_fingerprint"] == replay.json()["binding_fingerprint"]
    assert created.json()["exact_source_integrity"] is True
    assert result.status_code == 201
    assert result.json()["published"] is False
    assert result.json()["review_required"] is True
    assert result.json()["exact_source_integrity"] is True
    assert candidates.candidates[0]["review_state"] == "REQUIRED"
    assert candidates.evidence_links[0]["revision_id"] == 201
    locator = candidates.evidence_links[0]["anchor"]["locator"]
    assert locator["source_hash"] == paper.source.content_hash
    assert locator["excerpt_hash"]
    assert candidates.evidence_links[0]["anchor"]["char_start"] is not None
