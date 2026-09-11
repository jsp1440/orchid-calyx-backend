from pathlib import Path

import pytest

from app.literature_extraction.canonical_binding_resolver import (
    BindingScope,
    DocumentIntelligenceBindingResolver,
    PostgresLiteratureSourceBindingRepository,
)
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.service import extract_and_persist
from app.literature_extraction.source_binding import LiteratureSourceBindingError


def _source(path: Path) -> Path:
    path.write_text(
        "Orchid Trait Study\n\nAbstract\nOrchid roots were studied.\n\n"
        "Methods\nPCR was used.\n\nResults\nEscherichia coli was characterized "
        "by a red flower trait.\n\nDiscussion\nIndependent review is required.\n",
        encoding="utf-8",
    )
    return path


class CanonicalCursor:
    def __init__(self, paper, *, ambiguous_record: bool = False, ambiguous_anchor: bool = False):
        self.paper = paper
        self.ambiguous_record = ambiguous_record
        self.ambiguous_anchor = ambiguous_anchor
        self.rows = []
        self.statements: list[tuple[str, tuple]] = []
        self.binding_id = 901
        self.anchor_by_span = {
            (evidence.span.char_start, evidence.span.char_end): 400 + index
            for index, evidence in enumerate(paper.evidence, start=1)
        }

    def execute(self, query, params=()):
        normalized = " ".join(str(query).split())
        params = tuple(params)
        self.statements.append((normalized, params))
        if "FROM oc_document_intelligence.records" in normalized:
            self.rows = [(7, 201)]
            if self.ambiguous_record:
                self.rows.append((8, 202))
        elif "FROM oc_document_intelligence.purpose_assignments" in normalized:
            self.rows = [("LITERATURE_DOCUMENT", 101)]
        elif "FROM oc_document_intelligence.extraction_runs" in normalized:
            self.rows = [(301,)]
        elif "FROM oc_document_intelligence.source_anchors" in normalized:
            start, end = params[-2], params[-1]
            anchor = self.anchor_by_span.get((start, end))
            self.rows = [(anchor,)] if anchor is not None else []
            if self.ambiguous_anchor and self.rows:
                self.rows.append((anchor + 1000,))
        elif "FROM oc_document_intelligence.display_policies" in normalized:
            self.rows = [("METADATA_ONLY", True)]
        elif "FROM oc_document_intelligence.literature_source_bindings" in normalized:
            self.rows = []
        elif "INSERT INTO oc_document_intelligence.literature_source_bindings" in normalized:
            self.rows = [(self.binding_id,)]
        elif "INSERT INTO oc_document_intelligence.literature_evidence_bindings" in normalized:
            self.rows = []
        else:
            raise AssertionError(f"Unexpected SQL: {normalized}")
        return self

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


@pytest.mark.asyncio
async def test_resolver_uses_only_unique_existing_canonical_identities(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    raw_bytes = literature.get_raw_bytes(paper.paper_id)
    assert raw_bytes is not None
    cursor = CanonicalCursor(paper)

    resolved = DocumentIntelligenceBindingResolver().resolve(cursor, paper, raw_bytes)

    assert resolved.record_id == 7
    assert resolved.analysis_id == paper.analysis_manifest.analysis_id
    assert resolved.binding.source_object_type == "LITERATURE_DOCUMENT"
    assert resolved.binding.source_object_id == 101
    assert resolved.binding.revision_id == 201
    assert resolved.binding.extraction_run_id == 301
    assert resolved.binding.anchor_ids == {
        evidence.evidence_id: cursor.anchor_by_span[
            (evidence.span.char_start, evidence.span.char_end)
        ]
        for evidence in paper.evidence
    }
    resolved.binding.validate_integrity(paper, raw_bytes)


@pytest.mark.asyncio
async def test_resolver_refuses_ambiguous_source_record(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    raw_bytes = literature.get_raw_bytes(paper.paper_id)
    assert raw_bytes is not None

    with pytest.raises(LiteratureSourceBindingError) as caught:
        DocumentIntelligenceBindingResolver().resolve(
            CanonicalCursor(paper, ambiguous_record=True), paper, raw_bytes
        )

    assert caught.value.code == "SOURCE_BINDING_AMBIGUOUS"


@pytest.mark.asyncio
async def test_resolver_refuses_ambiguous_evidence_anchor(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    raw_bytes = literature.get_raw_bytes(paper.paper_id)
    assert raw_bytes is not None

    with pytest.raises(LiteratureSourceBindingError) as caught:
        DocumentIntelligenceBindingResolver().resolve(
            CanonicalCursor(paper, ambiguous_anchor=True), paper, raw_bytes
        )

    assert caught.value.code == "EXTRACTION_RUN_WITH_EXACT_EVIDENCE_NOT_FOUND"
    assert "ANCHOR_BINDING_AMBIGUOUS" in caught.value.details["run_failures"].values()


@pytest.mark.asyncio
async def test_postgres_binding_persistence_is_additive_and_scoped(tmp_path: Path) -> None:
    literature = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(_source(tmp_path / "paper.txt"), literature)
    raw_bytes = literature.get_raw_bytes(paper.paper_id)
    assert raw_bytes is not None
    cursor = CanonicalCursor(paper)
    resolved = DocumentIntelligenceBindingResolver().resolve(cursor, paper, raw_bytes)
    cursor.statements.clear()

    stored, created = PostgresLiteratureSourceBindingRepository().create(
        cursor,
        scope=BindingScope(owner_id="owner", project_id="research-station"),
        resolved=resolved,
    )

    assert created is True
    assert stored.binding.fingerprint == resolved.binding.fingerprint
    sql = [statement for statement, _ in cursor.statements]
    assert any("INSERT INTO oc_document_intelligence.literature_source_bindings" in item for item in sql)
    assert sum(
        "INSERT INTO oc_document_intelligence.literature_evidence_bindings" in item
        for item in sql
    ) == len(paper.evidence)
    assert not any(item.startswith(("UPDATE ", "DELETE ")) for item in sql)
