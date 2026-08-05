"""CALYX CORE 3 — Acceptance tests for the literature acquisition pipeline.

Issue #387: Productionize licensed image and literature evidence pipelines.

Covers:
- Bounded DOI/URL acquisition with source checkpoints
- Raw source, extraction manifest, evidence spans, source binding, content hashes
- Canonical taxon IDs persisted during reviewed handoff
- Ambiguous taxon matches enter review queue
- Replay is idempotent
- Acquisition bound enforced
- Unsupported source types are rejected
"""

from __future__ import annotations

import hashlib

import pytest

from app.harvest.literature_acquisition import (
    AcquisitionBoundExceeded,
    AcquisitionRequest,
    LiteratureAcquisitionError,
    LiteratureAcquisitionPipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pipeline(**kwargs) -> LiteratureAcquisitionPipeline:
    return LiteratureAcquisitionPipeline(**kwargs)


def _req(
    *,
    document_id: str = "doc-001",
    source_type: str = "doi",
    source_ref: str = "10.1000/test.001",
    raw_text: str | None = None,
    metadata: dict | None = None,
) -> AcquisitionRequest:
    return AcquisitionRequest(
        document_id=document_id,
        source_type=source_type,
        source_ref=source_ref,
        raw_text=raw_text,
        metadata=metadata or {},
    )


def _expected_record_id(source_type: str, source_ref: str) -> str:
    return hashlib.sha256(f"{source_type}:{source_ref}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Happy-path fixture: acquire → stage → provenance
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_single_doi_acquired_and_staged(self):
        pipeline = _pipeline()
        stats = pipeline.acquire([_req()])

        assert stats["acquired"] == 1
        assert stats["rejected"] == 0
        assert stats["staged"] == 1

    def test_single_url_acquired_and_staged(self):
        pipeline = _pipeline()
        stats = pipeline.acquire([_req(source_type="url", source_ref="https://example.org/paper")])
        assert stats["acquired"] == 1
        assert stats["staged"] == 1

    def test_content_hash_is_sha256_of_raw_text(self):
        text = "Orchid species exhibit extraordinary floral diversity."
        pipeline = _pipeline()
        pipeline.acquire([_req(raw_text=text)])
        record_id = _expected_record_id("doi", "10.1000/test.001")
        record = pipeline._records[record_id]
        assert record.content_hash == hashlib.sha256(text.encode()).hexdigest()

    def test_content_hash_falls_back_to_source_ref(self):
        pipeline = _pipeline()
        pipeline.acquire([_req()])
        record_id = _expected_record_id("doi", "10.1000/test.001")
        record = pipeline._records[record_id]
        expected = hashlib.sha256("10.1000/test.001".encode()).hexdigest()
        assert record.content_hash == expected

    def test_source_binding_preserved(self):
        pipeline = _pipeline()
        pipeline.acquire([_req(source_type="doi", source_ref="10.9999/xyz")])
        record_id = _expected_record_id("doi", "10.9999/xyz")
        record = pipeline._records[record_id]
        binding = record.source_binding
        assert binding["source_type"] == "doi"
        assert binding["source_ref"] == "10.9999/xyz"
        assert "acquired_at" in binding

    def test_metadata_preserved(self):
        meta = {"journal": "Annals of Botany", "year": 2024}
        pipeline = _pipeline()
        pipeline.acquire([_req(metadata=meta)])
        record_id = _expected_record_id("doi", "10.1000/test.001")
        record = pipeline._records[record_id]
        assert record.metadata["journal"] == "Annals of Botany"

    def test_extraction_manifest_stored(self):
        def extractor(req):
            return {
                "spans": [{"text": "Cattleya labiata", "char_start": 0, "char_end": 16}],
                "manifest": {"ner": "completed", "sections": "completed"},
            }

        pipeline = _pipeline(extractor=extractor)
        pipeline.acquire([_req()])
        record_id = _expected_record_id("doi", "10.1000/test.001")
        record = pipeline._records[record_id]
        assert record.extraction_manifest["ner"] == "completed"
        assert len(record.evidence_spans) == 1
        assert record.evidence_spans[0].text == "Cattleya labiata"

    def test_evidence_spans_char_positions_stored(self):
        def extractor(req):
            return {
                "spans": [
                    {
                        "span_id": "s1",
                        "text": "fragrant",
                        "page_start": 3,
                        "char_start": 10,
                        "char_end": 18,
                    }
                ],
                "manifest": {},
            }

        pipeline = _pipeline(extractor=extractor)
        pipeline.acquire([_req()])
        record_id = _expected_record_id("doi", "10.1000/test.001")
        span = pipeline._records[record_id].evidence_spans[0]
        assert span.span_id == "s1"
        assert span.page_start == 3
        assert span.char_start == 10
        assert span.char_end == 18


# ---------------------------------------------------------------------------
# Idempotency (replay)
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_replay_does_not_duplicate_staging_records(self):
        pipeline = _pipeline()
        req = _req()
        pipeline.acquire([req])
        pipeline.acquire([req])
        assert len(pipeline.staging()) == 1
        assert len(pipeline._records) == 1

    def test_replay_does_not_grow_review_queue(self):
        pipeline = _pipeline()
        req = _req(metadata={"scientific_name": "Orchis ambigua"})
        pipeline.acquire([req])
        pipeline.acquire([req])
        assert len(pipeline.review_queue()) == 1

    def test_checkpoint_updated_on_replay(self):
        pipeline = _pipeline()
        req = _req()
        pipeline.acquire([req])
        first_checkpoint = dict(pipeline.checkpoint())
        pipeline.acquire([req])
        second_checkpoint = pipeline.checkpoint()
        # record_id and source_ref unchanged; processed_at may differ
        assert first_checkpoint["doc-001"]["record_id"] == second_checkpoint["doc-001"]["record_id"]


# ---------------------------------------------------------------------------
# Bound enforcement
# ---------------------------------------------------------------------------


class TestBound:
    def test_bound_exceeded_raises(self):
        pipeline = _pipeline(bound=2)
        requests = [
            _req(document_id=f"doc-{i}", source_ref=f"10.0/{i}")
            for i in range(5)
        ]
        with pytest.raises(AcquisitionBoundExceeded):
            pipeline.acquire(requests)

    def test_bound_none_disables_limit(self):
        pipeline = _pipeline(bound=None)
        requests = [
            _req(document_id=f"doc-{i}", source_ref=f"10.0/{i}")
            for i in range(20)
        ]
        stats = pipeline.acquire(requests)
        assert stats["acquired"] == 20

    def test_records_up_to_bound_are_staged(self):
        pipeline = _pipeline(bound=3)
        requests = [
            _req(document_id=f"doc-{i}", source_ref=f"10.0/{i}")
            for i in range(10)
        ]
        try:
            pipeline.acquire(requests)
        except AcquisitionBoundExceeded:
            pass
        assert len(pipeline.staging()) == 3


# ---------------------------------------------------------------------------
# Rejection — unsupported source types and empty refs
# ---------------------------------------------------------------------------


class TestRejection:
    def test_unsupported_source_type_rejected(self):
        pipeline = _pipeline()
        bad_req = AcquisitionRequest(
            document_id="bad",
            source_type="ftp",
            source_ref="ftp://example.org/paper.pdf",
        )
        stats = pipeline.acquire([bad_req])
        assert stats["rejected"] == 1
        assert pipeline.rejected()[0]["reason"] == "unsupported_source_type"

    def test_empty_source_ref_rejected(self):
        pipeline = _pipeline()
        bad_req = AcquisitionRequest(
            document_id="empty",
            source_type="doi",
            source_ref="   ",
        )
        stats = pipeline.acquire([bad_req])
        assert stats["rejected"] == 1
        assert pipeline.rejected()[0]["reason"] == "empty_source_ref"

    def test_mixed_batch_partial_rejection(self):
        pipeline = _pipeline()
        stats = pipeline.acquire(
            [
                _req(document_id="ok"),
                AcquisitionRequest(document_id="bad", source_type="ftp", source_ref="ftp://x"),
            ]
        )
        assert stats["acquired"] == 1
        assert stats["rejected"] == 1


# ---------------------------------------------------------------------------
# Taxon resolution and review queue
# ---------------------------------------------------------------------------


class TestTaxonResolution:
    def test_no_names_no_resolver_queues_review(self):
        pipeline = _pipeline()
        pipeline.acquire([_req()])
        assert pipeline.staging()[0].taxon_review_pending is True
        assert len(pipeline.review_queue()) == 1

    def test_resolved_taxa_stored_in_staging(self):
        pipeline = _pipeline(taxon_resolver=lambda name: "gbif:8765")
        pipeline.acquire([_req(metadata={"scientific_name": "Cattleya labiata"})])
        staged = pipeline.staging()[0]
        assert "gbif:8765" in staged.canonical_taxon_ids
        assert staged.taxon_review_pending is False

    def test_ambiguous_name_queues_review(self):
        pipeline = _pipeline(taxon_resolver=lambda name: None)
        pipeline.acquire([_req(metadata={"scientific_name": "Orchis ambigua"})])
        assert len(pipeline.review_queue()) == 1
        staged = pipeline.staging()[0]
        assert staged.taxon_review_pending is True

    def test_multiple_names_all_resolved(self):
        mapping = {"Cattleya labiata": "gbif:1", "Dendrobium nobile": "gbif:2"}
        pipeline = _pipeline(taxon_resolver=mapping.get)
        meta = {"scientific_names": ["Cattleya labiata", "Dendrobium nobile"]}
        pipeline.acquire([_req(metadata=meta)])
        staged = pipeline.staging()[0]
        assert "gbif:1" in staged.canonical_taxon_ids
        assert "gbif:2" in staged.canonical_taxon_ids
        assert staged.taxon_review_pending is False

    def test_partial_resolution_still_queues_review(self):
        mapping = {"Cattleya labiata": "gbif:1"}
        pipeline = _pipeline(taxon_resolver=mapping.get)
        meta = {"scientific_names": ["Cattleya labiata", "Unknown orchid sp."]}
        pipeline.acquire([_req(metadata=meta)])
        staged = pipeline.staging()[0]
        assert staged.taxon_review_pending is True

    def test_review_queue_entry_preserves_unresolved_names(self):
        pipeline = _pipeline(taxon_resolver=lambda name: None)
        pipeline.acquire([_req(metadata={"scientific_name": "Mystery orchid"})])
        item = pipeline.review_queue()[0]
        assert "Mystery orchid" in item.unresolved_names

    def test_no_graph_mutation_when_review_pending(self):
        """Pipeline never mutates production graph for pending records."""
        pipeline = _pipeline()
        pipeline.acquire([_req(metadata={"scientific_name": "Ambiguus orchidus"})])
        # staging exists but taxon_id is unset — no graph write possible
        staged = pipeline.staging()[0]
        assert staged.taxon_review_pending is True
        assert staged.canonical_taxon_ids == ()


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


class TestCheckpoints:
    def test_checkpoint_recorded_per_document(self):
        pipeline = _pipeline()
        pipeline.acquire([_req(document_id="doc-A")])
        ckpt = pipeline.checkpoint()
        assert "doc-A" in ckpt
        assert "record_id" in ckpt["doc-A"]

    def test_checkpoint_contains_source_ref(self):
        pipeline = _pipeline()
        pipeline.acquire([_req(document_id="doc-B", source_ref="10.1234/ab")])
        assert pipeline.checkpoint()["doc-B"]["source_ref"] == "10.1234/ab"
