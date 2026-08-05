"""CALYX CORE 3 — Licensed image and literature pipeline tests (closes #387).

Covers:
- Licensed image staging: happy path, license allowlist enforcement, idempotency,
  review queue for unresolved taxa, explicit rejection of unlicensed/missing media.
- Literature staging: happy path, idempotency, review queue, provenance preservation.
- Replay idempotency for both pipelines.
"""

from __future__ import annotations

import pytest

from runtime.image_staging import (
    ImageStagingResult,
    RejectedImage,
    stage_image_batch,
)
from runtime.literature_staging import (
    LiteratureStagingResult,
    stage_literature_batch,
)

CANONICAL_LOOKUP: dict[str, str] = {
    "Laelia anceps": "taxon-001",
    "Cattleya trianae": "taxon-002",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _image(
    src_id: str = "img-001",
    url: str = "https://example.com/img.jpg",
    license_code: str = "http://creativecommons.org/licenses/by/4.0/",
    taxon_name: str | None = "Laelia anceps",
    source: str = "gbif",
    publisher: str = "GBIF",
) -> dict:
    return {
        "source": source,
        "source_record_id": src_id,
        "url": url,
        "license": license_code,
        "taxon_name": taxon_name,
        "creator": "Collector A",
        "publisher": publisher,
        "thumbnail_url": url + "?thumb",
        "mime_type": "image/jpeg",
        "raw": {},
    }


def _lit_record(
    src_id: str = "lit-001",
    doi: str | None = "10.1234/test",
    title: str = "Orchid pollination study",
    taxon_name: str | None = "Laelia anceps",
    raw_text: str | None = "Evidence text about Laelia anceps pollination.",
    source: str = "bhl",
) -> dict:
    return {
        "source": source,
        "source_record_id": src_id,
        "doi": doi,
        "title": title,
        "taxon_name": taxon_name,
        "authors": ["Smith J", "Brown K"],
        "publication_year": 2021,
        "evidence_spans": [{"page_start": 3, "section_id": "results"}],
        "raw_text": raw_text,
        "source_url": "https://www.biodiversitylibrary.org/page/12345",
        "extraction_manifest": {"extractor": "bhl-v1"},
        "raw": {},
    }


# ===========================================================================
# IMAGE STAGING TESTS
# ===========================================================================


class TestImageStagingHappyPath:
    def test_single_image_staged(self):
        result = stage_image_batch(
            [_image()], source="gbif", canonical_lookup=CANONICAL_LOOKUP
        )
        assert isinstance(result, ImageStagingResult)
        assert len(result.staged) == 1
        assert len(result.rejected) == 0
        img = result.staged[0]
        assert img.source == "gbif"
        assert img.canonical_taxon_id == "taxon-001"
        assert img.reconciliation_state == "resolved"
        assert img.license is not None

    def test_inat_image_staged(self):
        result = stage_image_batch(
            [_image(source="inaturalist", license_code="cc-by")],
            source="inaturalist",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert len(result.staged) == 1

    def test_summary_no_production_mutation(self):
        result = stage_image_batch(
            [_image()], source="gbif", canonical_lookup=CANONICAL_LOOKUP
        )
        s = result.summary()
        assert s["no_production_mutation"] is True
        assert s["staged_count"] == 1
        assert s["rejected_count"] == 0

    def test_as_dict_serializable(self):
        result = stage_image_batch(
            [_image()], source="gbif", canonical_lookup=CANONICAL_LOOKUP
        )
        d = result.staged[0].as_dict()
        assert d["source"] == "gbif"
        assert d["canonical_taxon_id"] == "taxon-001"


class TestImageLicenseEnforcement:
    def test_no_license_rejected(self):
        img = dict(_image())
        img["license"] = None
        result = stage_image_batch([img], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 0
        assert len(result.rejected) == 1
        rej = result.rejected[0]
        assert isinstance(rej, RejectedImage)
        assert "allowlist" in rej.reason.lower() or "missing" in rej.reason.lower()

    def test_unsupported_license_rejected(self):
        img = dict(_image())
        img["license"] = "all-rights-reserved"
        result = stage_image_batch([img], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 0
        assert len(result.rejected) == 1

    def test_cc0_accepted(self):
        result = stage_image_batch(
            [_image(license_code="cc0")],
            source="gbif",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert len(result.staged) == 1
        assert len(result.rejected) == 0

    def test_cc_by_nc_sa_accepted(self):
        result = stage_image_batch(
            [_image(license_code="cc-by-nc-sa")],
            source="gbif",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert len(result.staged) == 1

    def test_missing_url_rejected(self):
        img = dict(_image())
        img["url"] = ""
        result = stage_image_batch([img], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 0
        assert len(result.rejected) == 1

    def test_missing_src_id_rejected(self):
        img = dict(_image())
        img["source_record_id"] = ""
        result = stage_image_batch([img], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 0
        assert len(result.rejected) == 1

    def test_rejected_serializable(self):
        img = dict(_image())
        img["license"] = None
        result = stage_image_batch([img], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        d = result.rejected[0].as_dict()
        assert d["reason"]


class TestImageIdempotency:
    def test_same_batch_twice_skips(self):
        images = [_image("img-001"), _image("img-002", url="https://example.com/img2.jpg")]
        first = stage_image_batch(images, source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        seen = {img.acquisition_checksum for img in first.staged}
        second = stage_image_batch(images, source="gbif", seen_checksums=seen, canonical_lookup=CANONICAL_LOOKUP)
        assert second.duplicate_skipped == 2
        assert len(second.staged) == 0
        assert second.idempotent is True

    def test_new_image_not_skipped(self):
        first = stage_image_batch([_image("img-001")], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        seen = {img.acquisition_checksum for img in first.staged}
        second = stage_image_batch(
            [_image("img-001"), _image("img-002", url="https://example.com/img2.jpg")],
            source="gbif",
            seen_checksums=seen,
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert second.duplicate_skipped == 1
        assert len(second.staged) == 1


class TestImageReviewQueue:
    def test_unresolved_taxon_enters_review(self):
        img = _image(taxon_name="Unknown sp.")
        result = stage_image_batch([img], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 1  # still staged
        assert len(result.review_queue) == 1
        item = result.review_queue[0]
        assert item.review_state == "needs_taxon_resolution"

    def test_review_item_serializable(self):
        img = _image(taxon_name="Unknown sp.")
        result = stage_image_batch([img], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        d = result.review_queue[0].as_dict()
        assert d["review_state"] == "needs_taxon_resolution"


class TestImageNoReconciliation:
    def test_staged_without_lookup(self):
        result = stage_image_batch(
            [_image()], source="gbif", canonical_lookup=None
        )
        assert len(result.staged) == 1
        assert result.staged[0].canonical_taxon_id is None
        assert result.staged[0].reconciliation_state == "reconciliation_unavailable"


def test_image_unsupported_source_raises():
    with pytest.raises(ValueError, match="unsupported image source"):
        stage_image_batch([], source="unknown")


# ===========================================================================
# LITERATURE STAGING TESTS
# ===========================================================================


class TestLiteratureStagingHappyPath:
    def test_single_record_staged(self):
        result = stage_literature_batch(
            [_lit_record()], source="bhl", canonical_lookup=CANONICAL_LOOKUP
        )
        assert isinstance(result, LiteratureStagingResult)
        assert len(result.staged) == 1
        assert len(result.review_queue) == 0
        rec = result.staged[0]
        assert rec.source == "bhl"
        assert rec.canonical_taxon_id == "taxon-001"
        assert rec.reconciliation_state == "resolved"
        assert rec.content_hash is not None
        assert len(rec.evidence_spans) == 1
        assert len(rec.authors) == 2

    def test_summary_no_production_mutation(self):
        result = stage_literature_batch(
            [_lit_record()], source="bhl", canonical_lookup=CANONICAL_LOOKUP
        )
        s = result.summary()
        assert s["no_production_mutation"] is True
        assert s["candidate_knowledge_governance_intact"] is True
        assert s["staged_count"] == 1

    def test_as_dict_serializable(self):
        result = stage_literature_batch(
            [_lit_record()], source="bhl", canonical_lookup=CANONICAL_LOOKUP
        )
        d = result.staged[0].as_dict()
        assert d["canonical_taxon_id"] == "taxon-001"
        assert isinstance(d["authors"], list)
        assert isinstance(d["evidence_spans"], list)


class TestLiteratureIdempotency:
    def test_same_batch_twice_skips(self):
        records = [_lit_record("lit-001"), _lit_record("lit-002", doi="10.9999/b")]
        first = stage_literature_batch(records, source="bhl", canonical_lookup=CANONICAL_LOOKUP)
        seen = {r.acquisition_checksum for r in first.staged}
        second = stage_literature_batch(records, source="bhl", seen_checksums=seen, canonical_lookup=CANONICAL_LOOKUP)
        assert second.duplicate_skipped == 2
        assert second.idempotent is True

    def test_new_record_not_skipped(self):
        first = stage_literature_batch([_lit_record("lit-001")], source="bhl", canonical_lookup=CANONICAL_LOOKUP)
        seen = {r.acquisition_checksum for r in first.staged}
        second = stage_literature_batch(
            [_lit_record("lit-001"), _lit_record("lit-002", doi="10.9999/b")],
            source="bhl",
            seen_checksums=seen,
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert second.duplicate_skipped == 1
        assert len(second.staged) == 1


class TestLiteratureReviewQueue:
    def test_unresolved_taxon_in_review(self):
        rec = _lit_record(taxon_name="Mysterious orchid sp.")
        result = stage_literature_batch([rec], source="bhl", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 1
        assert len(result.review_queue) == 1
        assert result.review_queue[0].taxon_name == "Mysterious orchid sp."

    def test_missing_src_id_in_review(self):
        rec = dict(_lit_record())
        rec["source_record_id"] = ""
        result = stage_literature_batch([rec], source="bhl", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 0
        assert len(result.review_queue) == 1
        assert result.review_queue[0].review_state == "needs_taxon_resolution"


class TestLiteratureProvenancePreservation:
    def test_content_hash_computed(self):
        rec = _lit_record(raw_text="Some evidence text about Laelia.")
        result = stage_literature_batch([rec], source="bhl", canonical_lookup=CANONICAL_LOOKUP)
        assert result.staged[0].content_hash is not None

    def test_no_content_hash_when_no_raw_text(self):
        rec = dict(_lit_record())
        rec["raw_text"] = None
        result = stage_literature_batch([rec], source="bhl", canonical_lookup=CANONICAL_LOOKUP)
        assert result.staged[0].content_hash is None

    def test_evidence_spans_preserved(self):
        rec = _lit_record()
        result = stage_literature_batch([rec], source="bhl", canonical_lookup=CANONICAL_LOOKUP)
        assert result.staged[0].evidence_spans[0]["page_start"] == 3

    def test_extraction_manifest_preserved(self):
        rec = _lit_record()
        result = stage_literature_batch([rec], source="bhl", canonical_lookup=CANONICAL_LOOKUP)
        assert result.staged[0].extraction_manifest["extractor"] == "bhl-v1"

    def test_checkpoint_tracking(self):
        records = [_lit_record("lit-001"), _lit_record("lit-002", doi="10.9999/b")]
        result = stage_literature_batch(records, source="bhl", batch_start=10, canonical_lookup=CANONICAL_LOOKUP)
        assert result.batch_start == 10
        assert result.batch_end == 12
        assert result.checkpoint["batch_start"] == 10


class TestLiteratureNoReconciliation:
    def test_staged_without_lookup(self):
        result = stage_literature_batch(
            [_lit_record()], source="bhl", canonical_lookup=None
        )
        assert len(result.staged) == 1
        assert result.staged[0].canonical_taxon_id is None
        assert result.staged[0].reconciliation_state == "reconciliation_unavailable"
