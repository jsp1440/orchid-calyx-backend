from pathlib import Path

import pytest

from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.service import extract_and_persist
from app.literature_extraction.source_binding import CanonicalLiteratureSourceBinding
from app.scientific_synthesis.matrix import EvidenceMatrixBuilder
from app.scientific_synthesis.models import BibliographicRecord, VerificationState


def _source(path: Path) -> Path:
    path.write_text(
        "Orchid Foliar Study\n\n"
        "Abstract\nPhalaenopsis leaves were studied.\n\n"
        "Methods\nNitrogen uptake was measured.\n\n"
        "Results\nPhalaenopsis was characterized by a red flower trait.\n\n"
        "Discussion\nIndependent review is required.\n",
        encoding="utf-8",
    )
    return path


def _bibliography(*, verified=True):
    return BibliographicRecord(
        source_id="doi:10.1000/orchid.4",
        title="Orchid Foliar Study",
        authors=("Ada Researcher",),
        year=2026,
        journal="Journal of Orchid Science",
        doi="10.1000/orchid.4",
        verification_state=(
            VerificationState.VERIFIED_AUTHORITY
            if verified
            else VerificationState.UNVERIFIED
        ),
        verification_provider="crossref" if verified else None,
        verification_identifier="10.1000/orchid.4" if verified else None,
    )


async def _paper_and_binding(tmp_path: Path):
    repository = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), repository)
    raw_bytes = repository.get_raw_bytes(paper.paper_id)
    assert raw_bytes is not None
    binding = CanonicalLiteratureSourceBinding(
        paper_id=paper.paper_id,
        source_object_type="LITERATURE_DOCUMENT",
        source_object_id=101,
        revision_id=201,
        extraction_run_id=301,
        anchor_ids={
            evidence.evidence_id: 400 + index
            for index, evidence in enumerate(paper.evidence, start=1)
        },
    ).with_verified_integrity(paper, raw_bytes)
    return paper, binding


@pytest.mark.asyncio
async def test_matrix_rows_are_source_bound_to_exact_original_evidence(tmp_path: Path):
    paper, binding = await _paper_and_binding(tmp_path)
    result = EvidenceMatrixBuilder().build(
        paper=paper, binding=binding, bibliography=_bibliography()
    )

    assert result["row_count"] >= 1
    assert result["scientific_fields_source_bound"] is True
    assert result["automatic_design_classification"] is False
    row = result["rows"][0]
    assert row["source_id"] == "doi:10.1000/orchid.4"
    assert row["evidence_class"].value == "OBSERVATIONAL"
    assert row["result"]
    assert row["anchors"]
    anchor = row["anchors"][0]
    assert anchor["content_hash"] == paper.source.content_hash
    assert anchor["excerpt_hash"]
    assert anchor["locator"]["char_start"] is not None
    assert anchor["locator"]["char_end"] is not None


@pytest.mark.asyncio
async def test_unverified_bibliography_cannot_create_scientific_matrix(tmp_path: Path):
    paper, binding = await _paper_and_binding(tmp_path)

    with pytest.raises(ValueError, match="VERIFIED_BIBLIOGRAPHY_REQUIRED"):
        EvidenceMatrixBuilder().build(
            paper=paper, binding=binding, bibliography=_bibliography(verified=False)
        )


@pytest.mark.asyncio
async def test_missing_integrity_proof_blocks_matrix(tmp_path: Path):
    paper, binding = await _paper_and_binding(tmp_path)
    unsafe = CanonicalLiteratureSourceBinding(
        paper_id=binding.paper_id,
        source_object_type=binding.source_object_type,
        source_object_id=binding.source_object_id,
        revision_id=binding.revision_id,
        extraction_run_id=binding.extraction_run_id,
        anchor_ids=binding.anchor_ids,
    )

    with pytest.raises(ValueError, match="SOURCE_INTEGRITY_PROOF_REQUIRED"):
        EvidenceMatrixBuilder().build(
            paper=paper, binding=unsafe, bibliography=_bibliography()
        )


@pytest.mark.asyncio
async def test_normalized_result_never_replaces_original_anchor_hash(tmp_path: Path):
    paper, binding = await _paper_and_binding(tmp_path)
    result = EvidenceMatrixBuilder().build(
        paper=paper, binding=binding, bibliography=_bibliography()
    )

    row = result["rows"][0]
    original_evidence_id = row["metadata"]["original_evidence_ids"][0]
    proof = binding.evidence_integrity[original_evidence_id]
    anchor = row["anchors"][0]
    assert anchor["excerpt_hash"] == proof["excerpt_hash"]
    assert anchor["content_hash"] == proof["source_hash"]
    assert row["result"] != ""


@pytest.mark.asyncio
async def test_matrix_fingerprint_is_deterministic(tmp_path: Path):
    paper, binding = await _paper_and_binding(tmp_path)
    builder = EvidenceMatrixBuilder()

    first = builder.build(paper=paper, binding=binding, bibliography=_bibliography())
    second = builder.build(paper=paper, binding=binding, bibliography=_bibliography())

    assert first["fingerprint"] == second["fingerprint"]
