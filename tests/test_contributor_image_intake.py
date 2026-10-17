"""Focused tests for governed contributor-image intake (AC-1)."""

from pathlib import Path

import pytest

from runtime.contributor_image_intake import (
    SUPPORTED_MEDIA,
    intake_contributor_batch,
)


def _submission(**overrides):
    base = {
        "submission_id": "sub-001",
        "contributor_id": "member-42",
        "contributor_display_name": "A. Grower",
        "permission_grant": "cc-by",
        "rights_holder_affirmed": True,
        "original_object_ref": "objects/originals/sub-001.jpg",
        "content_sha256": "a" * 64,
        "mime_type": "image/jpeg",
        "taxon_name": "Phragmipedium besseae",
        "taxon_certainty": "determined_by_contributor",
        "candidate_taxa": [
            {"name": "Phragmipedium besseae", "taxon_id": "world-plants:phragmipedium-besseae"}
        ],
        "provenance": {"channel": "member-upload", "captured_at": "2026-09-30"},
    }
    base.update(overrides)
    return base


def test_missing_permission_grant_is_rejected():
    result = intake_contributor_batch(
        [_submission(permission_grant=None)], batch_id="batch-1"
    )
    assert len(result.staged) == 0
    assert result.rejected[0].reason == "missing_or_unrecognized_permission_grant"
    assert result.summary()["no_production_mutation"] is True


def test_unrecognized_permission_grant_is_rejected():
    result = intake_contributor_batch(
        [_submission(permission_grant="public-domain-ish")], batch_id="batch-1"
    )
    assert len(result.staged) == 0
    assert result.rejected[0].reason == "missing_or_unrecognized_permission_grant"


def test_rights_holder_affirmation_required():
    result = intake_contributor_batch(
        [_submission(rights_holder_affirmed=False)], batch_id="batch-1"
    )
    assert len(result.staged) == 0
    assert result.rejected[0].reason == "rights_holder_affirmation_required"


def test_attribution_and_original_preserved_verbatim(tmp_path: Path):
    result = intake_contributor_batch([_submission()], batch_id="batch-1")
    staged = result.staged[0]
    assert staged.contributor_id == "member-42"
    assert staged.contributor_display_name == "A. Grower"
    assert staged.attribution_line == "A. Grower (CC-BY)"
    assert staged.original_object_ref == "objects/originals/sub-001.jpg"
    assert staged.content_sha256 == "a" * 64
    assert staged.original_preserved is True


def test_unknown_taxon_is_staged_with_uncertainty_preserved():
    result = intake_contributor_batch(
        [
            _submission(
                taxon_name=None,
                taxon_certainty="unknown",
                candidate_taxa=[
                    {"name": "Phragmipedium besseae"},
                    {"name": "Phragmipedium kovachii"},
                ],
            )
        ],
        batch_id="batch-1",
    )
    staged = result.staged[0]
    assert staged.taxon_certainty == "unknown"
    assert staged.reconciliation_state == "unresolved"
    assert [item["name"] for item in staged.candidate_taxa] == [
        "Phragmipedium besseae",
        "Phragmipedium kovachii",
    ]
    assert result.review_queue[0].review_state == "needs_taxon_resolution"


def test_canonical_lookup_resolves_taxon_without_guessing():
    lookup = {"Phragmipedium besseae": "world-plants:phragmipedium-besseae"}
    resolved = intake_contributor_batch(
        [_submission()], batch_id="b1", canonical_lookup=lookup
    )
    assert resolved.staged[0].canonical_taxon_id == "world-plants:phragmipedium-besseae"
    assert resolved.staged[0].reconciliation_state == "resolved"
    assert resolved.review_queue == ()

    unresolved = intake_contributor_batch(
        [_submission(taxon_name="Phragmipedium inventii")],
        batch_id="b2",
        canonical_lookup=lookup,
    )
    assert unresolved.staged[0].canonical_taxon_id is None
    assert unresolved.staged[0].reconciliation_state == "unresolved"


def test_batch_dedup_is_idempotent_by_content_checksum():
    seen: set[str] = set()
    first = intake_contributor_batch([_submission()], batch_id="b1", seen_checksums=seen)
    second = intake_contributor_batch(
        [_submission(submission_id="sub-001-resubmitted")],
        batch_id="b2",
        seen_checksums=seen,
    )
    assert len(first.staged) == 1
    assert len(second.staged) == 0
    assert second.duplicate_skipped == 1
    assert second.idempotent is True


def test_unsupported_media_rejected():
    result = intake_contributor_batch(
        [_submission(mime_type="image/svg+xml")], batch_id="batch-1"
    )
    assert len(result.staged) == 0
    assert result.rejected[0].reason == "unsupported_media_type"
    assert "image/svg+xml" not in SUPPORTED_MEDIA


def test_missing_original_reference_or_checksum_rejected():
    result = intake_contributor_batch(
        [
            _submission(submission_id="s1", original_object_ref=None),
            _submission(submission_id="s2", content_sha256="not-a-sha"),
            _submission(submission_id="s3", content_sha256="b" * 64,
                        original_object_ref="objects/originals/s3.png",
                        mime_type="image/png"),
        ],
        batch_id="batch-1",
    )
    assert [item.submission_id for item in result.rejected] == ["s1", "s2"]
    assert len(result.staged) == 1


def test_invalid_taxon_certainty_rejected():
    result = intake_contributor_batch(
        [_submission(taxon_certainty="positive-id")], batch_id="batch-1"
    )
    assert len(result.staged) == 0
    assert result.rejected[0].reason == "unrecognized_taxon_certainty"
