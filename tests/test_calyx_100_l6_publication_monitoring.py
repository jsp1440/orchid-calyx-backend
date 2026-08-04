from runtime.calyx_certification.publication_monitoring import (
    evaluate_publication_monitoring,
)


def test_evidence_change_creates_review_task_without_mutation():
    result = evaluate_publication_monitoring(
        {"publication_id": "pub:1", "ledger_artifact_id": "ledger:1"},
        [{"type": "evidence_changed"}, {"type": "source_retracted"}],
    )
    assert result["validity"] == "stale_review_required"
    assert result["review_task_required"] is True
    assert result["review_reasons"] == ["evidence_changed", "source_retracted"]
    assert result["historical_reasoning_mutated"] is False
    assert result["publication_change_authorized"] is False


def test_no_signal_preserves_current_validity():
    result = evaluate_publication_monitoring(
        {"publication_id": "pub:2", "ledger_artifact_id": "ledger:2"},
        [],
    )
    assert result["validity"] == "current"
    assert result["review_task_required"] is False
    assert result["blockers"] == []


def test_missing_identity_fails_closed():
    result = evaluate_publication_monitoring({}, [{"type": "source_withdrawn"}])
    assert result["review_task_required"] is True
    assert result["blockers"] == [
        "PUBLICATION_ID_MISSING",
        "LEDGER_ARTIFACT_ID_MISSING",
    ]
