import json
from pathlib import Path

import pytest

from app.calyx_conversation.extracted_literature_evidence import (
    reviewed_evidence_for_documents,
)
from app.literature_extraction.models import PublicationDecision
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.service import extract_and_persist
from app.literature_extraction.source_binding import (
    CanonicalLiteratureSourceBinding,
    FileLiteratureSourceBindingRepository,
)


def _source(path: Path) -> Path:
    path.write_text(
        "Orchid nutrient study\n\nAbstract\nLaelia anceps leaves were studied.\n\n"
        "Methods\nLeaves were treated with a mineral solution.\n\n"
        "Results\nLaelia anceps showed measurable nutrient uptake.\n\n"
        "Discussion\nThe result requires independent replication.\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_bridge_returns_only_publication_eligible_integrity_verified_records(
    tmp_path: Path,
):
    root = tmp_path / "literature"
    repository = LiteratureResultRepository(root)
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), repository)
    assert paper.normalized_evidence_records
    record = paper.normalized_evidence_records[0]
    paper.publication_decisions = [
        PublicationDecision(
            publication_decision_id="pub-1",
            review_item_id="review-1",
            source_record_id=record.record_id,
            status="eligible_for_publication",
            reason_codes=["test-reviewed"],
        )
    ]
    paper_path = root / paper.paper_id / "paper.json"
    paper_path.write_text(paper.model_dump_json(indent=2), encoding="utf-8")

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
        display_policy="METADATA_ONLY",
        internal_use_permission=True,
    ).with_verified_integrity(paper, raw_bytes)
    FileLiteratureSourceBindingRepository(root).create(binding)

    result = reviewed_evidence_for_documents([101], root=str(root))
    assert result["status"] == "available"
    assert result["reviewed_record_count"] == 1
    document = result["documents"]["101"]
    assert document["status"] == "available"
    assert document["records"][0]["record_id"] == record.record_id
    assert document["records"][0]["publication_status"] == "eligible_for_publication"
    assert document["records"][0]["evidence_anchors"]


def test_reverse_binding_lookup_is_bounded_and_type_specific(tmp_path: Path):
    root = tmp_path / "literature"
    root.mkdir()
    for paper_id, source_type, source_id in (
        ("p1", "LITERATURE_DOCUMENT", 101),
        ("p2", "OTHER", 101),
        ("p3", "LITERATURE_DOCUMENT", 102),
    ):
        path = root / paper_id
        path.mkdir()
        binding = {
            "paper_id": paper_id,
            "source_object_type": source_type,
            "source_object_id": source_id,
            "revision_id": 1,
            "extraction_run_id": 1,
            "anchor_ids": {"e1": 1},
            "display_policy": "METADATA_ONLY",
            "internal_use_permission": True,
            "language": "en",
            "evidence_integrity": {"e1": {"anchor_id": 1}},
        }
        (path / "source-binding.json").write_text(
            json.dumps(binding), encoding="utf-8"
        )

    matches = FileLiteratureSourceBindingRepository(root).find_by_source_object(
        "LITERATURE_DOCUMENT", 101
    )
    assert [item.paper_id for item in matches] == ["p1"]
