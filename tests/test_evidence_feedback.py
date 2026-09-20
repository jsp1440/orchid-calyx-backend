from __future__ import annotations

import pytest

from app.evidence_feedback import (
    CaseStatus,
    Disposition,
    EvidenceFeedbackService,
    FeedbackClass,
    FileEvidenceFeedbackRepository,
    ObjectType,
    ReviewLane,
)


def service_at(tmp_path):
    return EvidenceFeedbackService(
        FileEvidenceFeedbackRepository(tmp_path),
        clock=lambda: "2026-09-20T20:00:00+00:00",
    )


def test_lexicon_typo_creates_new_version_and_preserves_audit(tmp_path):
    service = service_at(tmp_path)
    original = service.register_object(
        object_id="lexicon:labellum",
        object_type=ObjectType.LEXICON,
        payload={"term": "labellum", "definition": "a modified petel"},
    )

    submitted = service.submit(
        object_id=original.object_id,
        object_version_hash=original.version_hash,
        object_type=ObjectType.LEXICON,
        page_context="/lexicon/labellum",
        feedback_class=FeedbackClass.SUGGEST_CORRECTION,
        statement="Petal is misspelled.",
        proposed_replacement="a modified petal",
        submitter_id="member-7",
        defect_kind="typo",
    )

    assert submitted.created is True
    assert submitted.case.disposition is Disposition.AUTO_CORRECTABLE
    assert submitted.case.review_lane is ReviewLane.DETERMINISTIC
    resolved = service.accept_trivial_correction(
        case_id=submitted.case.case_id,
        reviewer_id="deterministic-spelling-check",
        corrected_payload={
            "term": "labellum",
            "definition": "a modified petal",
        },
    )

    assert resolved.status is CaseStatus.RESOLVED
    assert resolved.disposition is Disposition.CORRECTION_ACCEPTED
    assert resolved.object_version_hash == original.version_hash
    assert resolved.resulting_version_hash != original.version_hash

    restarted = FileEvidenceFeedbackRepository(tmp_path)
    persisted = restarted.get_case(resolved.case_id)
    versions = restarted.list_object_versions(original.object_id)
    events = restarted.list_events(resolved.case_id)

    assert persisted == resolved
    assert {version.version_hash for version in versions} == {
        original.version_hash,
        resolved.resulting_version_hash,
    }
    assert any(event["event"] == "correction_accepted" for event in events)


def test_duplicate_feedback_is_suppressed_across_restart(tmp_path):
    service = service_at(tmp_path)
    version = service.register_object(
        object_id="lexicon:column",
        object_type=ObjectType.LEXICON,
        payload={"term": "column", "definition": "fused reproductive structure"},
    )
    request = {
        "object_id": version.object_id,
        "object_version_hash": version.version_hash,
        "object_type": ObjectType.LEXICON,
        "page_context": "/lexicon/column",
        "feedback_class": FeedbackClass.REPORT_PROBLEM,
        "statement": "The wording needs a citation.",
        "submitter_id": "member-9",
    }

    first = service.submit(**request)
    restarted = EvidenceFeedbackService(
        FileEvidenceFeedbackRepository(tmp_path),
        clock=lambda: "2026-09-20T20:01:00+00:00",
    )
    second = restarted.submit(**request)

    assert first.created is True
    assert second.created is False
    assert second.duplicate_of == first.case.case_id
    assert second.case == first.case
    assert restarted.repository.list_events(first.case.case_id)[-1][
        "event"
    ] == "duplicate_submission_suppressed"


@pytest.mark.parametrize(
    ("object_type", "expected_lane"),
    [
        (ObjectType.MATRIX_IDENTIFICATION, ReviewLane.SCIENTIFIC),
        (ObjectType.IMAGE_ANNOTATION, ReviewLane.SCIENTIFIC),
        (ObjectType.TAXONOMY, ReviewLane.TAXONOMIC),
    ],
)
def test_governed_objects_never_enter_deterministic_correction(
    tmp_path,
    object_type,
    expected_lane,
):
    service = service_at(tmp_path)
    version = service.register_object(
        object_id=f"object:{object_type.value}",
        object_type=object_type,
        payload={"assertion": "current published assertion"},
    )

    submitted = service.submit(
        object_id=version.object_id,
        object_version_hash=version.version_hash,
        object_type=object_type,
        page_context=f"/objects/{object_type.value}",
        feedback_class=FeedbackClass.CHALLENGE,
        statement="I think a different species is correct.",
        proposed_replacement="another scientific assertion",
        submitter_id="member-11",
        defect_kind="typo",
    )

    assert submitted.case.disposition in {
        Disposition.NEEDS_SCIENTIFIC_REVIEW,
        Disposition.NEEDS_TAXONOMIC_REVIEW,
    }
    assert submitted.case.review_lane is expected_lane
    assert submitted.case.status is CaseStatus.PENDING_REVIEW
    with pytest.raises(ValueError, match="GOVERNED_REVIEW_REQUIRED"):
        service.accept_trivial_correction(
            case_id=submitted.case.case_id,
            reviewer_id="automation",
            corrected_payload={"assertion": "mutated without review"},
        )
    assert len(service.repository.list_object_versions(version.object_id)) == 1


def test_partner_character_challenge_reconstructs_exact_source_version(tmp_path):
    service = service_at(tmp_path)
    version = service.register_object(
        object_id="character:iospe:stanhopea-oculata:lip",
        object_type=ObjectType.STRUCTURED_CHARACTER,
        payload={
            "source": "IOSPE",
            "source_url": "https://example.test/iospe/stanhopea-oculata",
            "character": "lip markings",
            "value": "two eyespots",
        },
    )

    submitted = service.submit(
        object_id=version.object_id,
        object_version_hash=version.version_hash,
        object_type=ObjectType.STRUCTURED_CHARACTER,
        page_context="/matrix/stanhopea-oculata",
        feedback_class=FeedbackClass.CHALLENGE,
        statement="The linked description conflicts with this character.",
        citation="https://example.test/iospe/stanhopea-oculata",
        submitter_id="collaborator-2",
        source_partner_id="iospe",
    )

    assert (
        submitted.case.disposition
        is Disposition.NEEDS_SOURCE_PARTNER_REVIEW
    )
    assert submitted.case.review_lane is ReviewLane.SOURCE_PARTNER
    source = service.repository.get_object_version(
        submitted.case.object_id,
        submitted.case.object_version_hash,
    )
    assert source.payload["source"] == "IOSPE"


def test_pending_state_and_submitter_visibility_are_bounded(tmp_path):
    service = service_at(tmp_path)
    version = service.register_object(
        object_id="matrix:episode:42",
        object_type=ObjectType.MATRIX_IDENTIFICATION,
        payload={"candidates": ["taxon:1", "taxon:2"]},
    )
    submitted = service.submit(
        object_id=version.object_id,
        object_version_hash=version.version_hash,
        object_type=ObjectType.MATRIX_IDENTIFICATION,
        page_context="/matrix/result/42",
        feedback_class=FeedbackClass.ADD_EVIDENCE,
        statement="A diagnostic character was not included.",
        submitter_id="member-42",
    )

    status = service.status_for_submitter(
        case_id=submitted.case.case_id,
        submitter_id="member-42",
    )
    assert status == {
        "case_id": submitted.case.case_id,
        "status": "pending_review",
        "disposition": "needs_scientific_review",
        "resolution": None,
        "resulting_version_hash": None,
    }
    with pytest.raises(PermissionError, match="CASE_STATUS_NOT_VISIBLE"):
        service.status_for_submitter(
            case_id=submitted.case.case_id,
            submitter_id="different-member",
        )


def test_submission_requires_persisted_exact_object_version(tmp_path):
    service = service_at(tmp_path)

    with pytest.raises(ValueError, match="OBJECT_VERSION_NOT_FOUND"):
        service.submit(
            object_id="lexicon:missing",
            object_version_hash="0" * 64,
            object_type=ObjectType.LEXICON,
            page_context="/lexicon/missing",
            feedback_class=FeedbackClass.REPORT_PROBLEM,
            statement="This object does not exist.",
        )
