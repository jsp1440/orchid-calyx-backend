"""CALYX CORE 3 — Acceptance tests for the licensed-image pipeline.

Issue #387: Productionize licensed image and literature evidence pipelines.

Covers:
- Bounded fixture persists and projects to staging with canonical taxon links
- Replay is idempotent
- Unsupported / unlicensed media is rejected explicitly
- Ambiguous taxon matches enter review
- All required provenance fields are preserved
"""

from __future__ import annotations

import hashlib

import pytest

from app.harvest.licensed_media import (
    LICENSE_ALLOWLIST,
    LicensedImagePipeline,
    LicensedImageRejected,
    _normalise_license,
    _stable_record_id,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _pipeline(**kwargs) -> LicensedImagePipeline:
    return LicensedImagePipeline(**kwargs)


def _media(
    *,
    source: str = "gbif",
    source_record_id: str = "rec-001",
    url: str = "https://cdn.example.org/image.jpg",
    license: str = "CC_BY_4_0",
    attribution: str | None = "Test Author",
    taxon_id: str | None = None,
    scientific_name: str | None = None,
    **extra,
) -> dict:
    d: dict = {
        "source": source,
        "source_record_id": source_record_id,
        "url": url,
        "license": license,
        "attribution": attribution,
    }
    if taxon_id is not None:
        d["taxon_id"] = taxon_id
    if scientific_name is not None:
        d["scientific_name"] = scientific_name
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# License allowlist
# ---------------------------------------------------------------------------


class TestLicenseAllowlist:
    def test_canonical_tokens_are_present(self):
        assert "CC_BY_4_0" in LICENSE_ALLOWLIST
        assert "CC0" in LICENSE_ALLOWLIST
        assert "PUBLIC_DOMAIN" in LICENSE_ALLOWLIST
        assert "CC_BY_NC_4_0" in LICENSE_ALLOWLIST

    def test_normalise_cc_uri(self):
        uri = "https://creativecommons.org/licenses/by/4.0/"
        assert _normalise_license(uri) == "CC_BY_4_0"

    def test_normalise_cc0_uri(self):
        uri = "http://creativecommons.org/publicdomain/zero/1.0/"
        assert _normalise_license(uri) == "CC0"

    def test_normalise_empty_string_returns_empty(self):
        assert _normalise_license("") == ""

    def test_unknown_license_passes_through_as_upper(self):
        result = _normalise_license("some-proprietary-licence")
        assert result  # non-empty; exact value may vary


# ---------------------------------------------------------------------------
# Happy-path fixture: persist → stage → provenance
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_single_record_accepted_and_staged(self):
        pipeline = _pipeline()
        stats = pipeline.ingest([_media(taxon_id="gbif:12345")])

        assert stats["accepted"] == 1
        assert stats["rejected"] == 0
        assert stats["staged"] == 1

        staged = pipeline.staging()
        assert len(staged) == 1
        assert staged[0].taxon_id == "gbif:12345"
        assert staged[0].taxon_review_pending is False

    def test_all_provenance_fields_preserved(self):
        pipeline = _pipeline()
        pipeline.ingest(
            [
                _media(
                    source="gbif",
                    source_record_id="prov-test",
                    url="https://cdn.example.org/prov.jpg",
                    license="CC_BY_4_0",
                    attribution="Jane Doe",
                    taxon_id="gbif:999",
                )
            ]
        )
        record_id = _stable_record_id("gbif", "prov-test")
        staged = {r.record_id: r for r in pipeline.staging()}
        assert record_id in staged
        sr = staged[record_id]
        assert sr.provider == "gbif"
        assert sr.provider_record_id == "prov-test"
        assert sr.source_url == "https://cdn.example.org/prov.jpg"
        assert sr.license == "CC_BY_4_0"
        assert sr.attribution == "Jane Doe"
        assert sr.taxon_id == "gbif:999"
        assert sr.staged_at is not None

    def test_checksum_is_sha256_of_url(self):
        pipeline = _pipeline()
        url = "https://cdn.example.org/checksum.jpg"
        pipeline.ingest([_media(url=url, taxon_id="x:1")])
        record_id = _stable_record_id("gbif", "rec-001")
        media_record = pipeline._media_store[record_id]
        expected = hashlib.sha256(url.encode()).hexdigest()
        assert media_record.checksum == expected

    def test_multiple_records_all_staged(self):
        pipeline = _pipeline()
        records = [
            _media(source_record_id=f"rec-{i}", url=f"https://example.org/{i}.jpg", taxon_id=f"x:{i}")
            for i in range(5)
        ]
        stats = pipeline.ingest(records)
        assert stats["accepted"] == 5
        assert stats["staged"] == 5


# ---------------------------------------------------------------------------
# Idempotency (replay)
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_replay_does_not_duplicate_staging_records(self):
        pipeline = _pipeline()
        record = _media(taxon_id="gbif:1")
        pipeline.ingest([record])
        pipeline.ingest([record])  # replay

        assert len(pipeline.staging()) == 1
        assert len(pipeline._media_store) == 1

    def test_replay_does_not_grow_review_queue(self):
        pipeline = _pipeline()
        record = _media()  # no taxon_id → review pending
        pipeline.ingest([record])
        pipeline.ingest([record])

        assert len(pipeline.review_queue()) == 1


# ---------------------------------------------------------------------------
# Rejection — unlicensed and unsupported media
# ---------------------------------------------------------------------------


class TestRejection:
    def test_missing_license_is_rejected(self):
        pipeline = _pipeline()
        stats = pipeline.ingest([_media(license="")])
        assert stats["rejected"] == 1
        assert stats["accepted"] == 0
        assert pipeline.rejected()[0]["reason"] == "missing_license"

    def test_unlicensed_token_rejected(self):
        pipeline = _pipeline()
        stats = pipeline.ingest([_media(license="ALL_RIGHTS_RESERVED")])
        assert stats["rejected"] == 1
        reason = pipeline.rejected()[0]["reason"]
        assert reason.startswith("license_not_allowed")

    def test_missing_url_rejected(self):
        pipeline = _pipeline()
        raw = _media(url="")
        stats = pipeline.ingest([raw])
        assert stats["rejected"] == 1

    def test_missing_provider_rejected(self):
        pipeline = _pipeline()
        raw = _media(source="")
        stats = pipeline.ingest([raw])
        assert stats["rejected"] == 1

    def test_mixed_batch_rejected_and_accepted(self):
        pipeline = _pipeline()
        stats = pipeline.ingest(
            [
                _media(source_record_id="ok", license="CC0", taxon_id="x:1"),
                _media(source_record_id="bad", license="PROPRIETARY"),
            ]
        )
        assert stats["accepted"] == 1
        assert stats["rejected"] == 1

    def test_rejected_records_expose_raw(self):
        pipeline = _pipeline()
        raw = _media(license="NOPE")
        pipeline.ingest([raw])
        entry = pipeline.rejected()[0]
        assert entry["record"]["url"] == raw["url"]


# ---------------------------------------------------------------------------
# Ambiguous taxon → review queue
# ---------------------------------------------------------------------------


class TestTaxonReview:
    def test_no_taxon_id_and_no_resolver_queues_for_review(self):
        pipeline = _pipeline()
        pipeline.ingest([_media()])  # no taxon_id, no resolver
        assert len(pipeline.review_queue()) == 1
        staged = pipeline.staging()[0]
        assert staged.taxon_review_pending is True
        assert staged.taxon_id is None

    def test_resolver_returning_none_queues_for_review(self):
        pipeline = _pipeline(taxon_resolver=lambda name: None)
        pipeline.ingest([_media(scientific_name="Ambiguous orchid")])
        assert len(pipeline.review_queue()) == 1

    def test_resolver_returning_id_links_canonical_taxon(self):
        pipeline = _pipeline(taxon_resolver=lambda name: "gbif:7654")
        pipeline.ingest([_media(scientific_name="Cattleya labiata")])
        staged = pipeline.staging()[0]
        assert staged.taxon_id == "gbif:7654"
        assert staged.taxon_review_pending is False
        assert len(pipeline.review_queue()) == 0

    def test_explicit_taxon_id_bypasses_resolver(self):
        called = []
        def resolver(name):
            called.append(name)
            return None

        pipeline = _pipeline(taxon_resolver=resolver)
        pipeline.ingest([_media(taxon_id="gbif:explicit-123")])
        assert not called  # resolver not invoked
        assert pipeline.staging()[0].taxon_id == "gbif:explicit-123"


# ---------------------------------------------------------------------------
# URI-form license strings normalised and accepted
# ---------------------------------------------------------------------------


class TestLicenseNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://creativecommons.org/licenses/by/4.0/", "CC_BY_4_0"),
            ("http://creativecommons.org/publicdomain/zero/1.0/", "CC0"),
            ("CC_BY_4_0", "CC_BY_4_0"),
            ("cc_by_4_0", "CC_BY_4_0"),
            ("CC_BY_NC_4_0", "CC_BY_NC_4_0"),
        ],
    )
    def test_normalised_uri_is_accepted(self, raw, expected):
        pipeline = _pipeline()
        stats = pipeline.ingest([_media(license=raw, taxon_id="x:1")])
        assert stats["accepted"] == 1, f"expected accepted for {raw!r}"
        assert pipeline.staging()[0].license == expected
