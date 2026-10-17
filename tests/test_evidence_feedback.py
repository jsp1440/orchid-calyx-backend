from __future__ import annotations

import pytest

from app.evidence_feedback import (
    CaseStatus,
    Disposition,
    EvidenceFeedbackService,
    FeedbackClass,
    ObjectType,
    ReviewLane,
)
from tests.evidence_feedback_stores import STORES, make_store


@pytest.fixture(params=STORES)
def store(request, tmp_path, monkeypatch):
    return make_store(request.param, tmp_path, monkeypatch)


def service_at(store):
    return EvidenceFeedbackService(
        store.repository(),
        clock=lambda: "2026-09-20T20:00:00+00:00",
    )


def test_lexicon_typo_creates_new_version_and_preserves_audit(store):
    service = service_at(store)
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

    restarted = store.repository()
    persisted = restarted.get_case(resolved.case_id)
    versions = restarted.list_object_versions(original.object_id)
    events = restarted.list_events(resolved.case_id)

    assert persisted == resolved
    assert {version.version_hash for version in versions} == {
        original.version_hash,
        resolved.resulting_version_hash,
    }
    assert any(event["event"] == "correction_accepted" for event in events)


def test_duplicate_feedback_is_suppressed_across_restart(store):
    service = service_at(store)
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
        store.repository(),
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
    store,
    object_type,
    expected_lane,
):
    service = service_at(store)
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


def test_partner_character_challenge_reconstructs_exact_source_version(store):
    service = service_at(store)
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


def test_pending_state_and_submitter_visibility_are_bounded(store):
    service = service_at(store)
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


def test_submission_requires_persisted_exact_object_version(store):
    service = service_at(store)

    with pytest.raises(ValueError, match="OBJECT_VERSION_NOT_FOUND"):
        service.submit(
            object_id="lexicon:missing",
            object_version_hash="0" * 64,
            object_type=ObjectType.LEXICON,
            page_context="/lexicon/missing",
            feedback_class=FeedbackClass.REPORT_PROBLEM,
            statement="This object does not exist.",
        )


def test_repository_contract_codes_are_identical_across_stores(store):
    """Both stores refuse the same inputs with the same stable codes."""

    from dataclasses import replace

    from app.evidence_feedback.repository import EvidenceFeedbackRepositoryError

    service = service_at(store)
    base = service.register_object(
        object_id="lexicon:lip",
        object_type=ObjectType.LEXICON,
        payload={"definition": "the labellum"},
    )
    submitted = service.submit(
        object_id=base.object_id,
        object_version_hash=base.version_hash,
        object_type=ObjectType.LEXICON,
        page_context="/lexicon/lip",
        feedback_class=FeedbackClass.REPORT_PROBLEM,
        statement="Needs a citation.",
        submitter_id="member-1",
    )
    repository = store.repository()

    def code_of(call) -> str:
        with pytest.raises(EvidenceFeedbackRepositoryError) as caught:
            call()
        return str(caught.value)

    # A fingerprint stays bound to its first case.
    assert code_of(
        lambda: repository.save_case(replace(submitted.case, case_id="efc-other"))
    ) == "FINGERPRINT_ALREADY_BOUND"
    # Lineage must name a stored version of the same object.
    assert code_of(
        lambda: service.register_object(
            object_id=base.object_id,
            object_type=ObjectType.LEXICON,
            payload={"definition": "labellum"},
            previous_version_hash="f" * 64,
        )
    ) == "OBJECT_VERSION_NOT_FOUND"
    assert code_of(
        lambda: repository.get_object_version(base.object_id, "not-a-hash")
    ) == "INVALID_OBJECT_VERSION_HASH"
    assert code_of(
        lambda: repository.save_object_version(replace(base, version_hash="0" * 64))
    ) == "OBJECT_VERSION_HASH_MISMATCH"
    assert code_of(lambda: repository.get_case("efc-missing")) == "CASE_NOT_FOUND"
    assert code_of(lambda: repository.get_case("   ")) == "CASE_ID_REQUIRED"
    assert code_of(lambda: repository.list_object_versions(" ")) == "OBJECT_ID_REQUIRED"
    assert code_of(lambda: repository.find_by_fingerprint("")) == "FINGERPRINT_REQUIRED"
    assert code_of(
        lambda: repository.append_event(
            case_id="efc-missing", event="x", timestamp="t", actor_id=None
        )
    ) == "CASE_NOT_FOUND"
    # Nothing a refused call attempted was persisted.
    assert repository.list_object_versions(base.object_id) == [base]
    assert repository.find_by_fingerprint(submitted.case.fingerprint) == submitted.case
    # Surrounding whitespace is not identity in either store.
    assert repository.get_case(f"  {submitted.case.case_id} ") == submitted.case
    assert repository.get_object_version(
        f" {base.object_id}", base.version_hash.upper()
    ) == base


def test_payload_round_trip_keeps_its_content_hash(store):
    """A stored payload reads back with the exact hash it was registered under."""

    from app.evidence_feedback.models import content_hash

    service = service_at(store)
    payload = {
        "definition": "Säule — fused column",
        "large": 1e16,
        "small": 0.1,
        "exponent": 1.5e-7,
        "integer": 12345678901234567890,
        "nested": {"b": [1, 2.0, None, True], "a": ""},
    }
    version = service.register_object(
        object_id="lexicon:column",
        object_type=ObjectType.LEXICON,
        payload=payload,
    )
    persisted = store.repository().get_object_version(
        version.object_id, version.version_hash
    )
    assert persisted == version
    assert content_hash(persisted.payload) == version.version_hash
    again = store.repository().save_object_version(persisted)
    assert again == version


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_non_finite_numbers(value):
    from app.evidence_feedback.models import canonical_json

    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_json({"value": value})
