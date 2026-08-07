from datetime import UTC, datetime

from app.multimodal_intelligence.persistence import PostgresOperationRepository


def test_postgres_repository_construction_is_inert() -> None:
    calls = 0

    def connection_factory():
        nonlocal calls
        calls += 1
        raise AssertionError("connection factory must not run during construction")

    repository = PostgresOperationRepository(connection_factory)
    assert repository is not None
    assert calls == 0


def test_postgres_row_conversion_preserves_review_and_provenance() -> None:
    row = (
        "00000000-0000-0000-0000-000000000001",
        "literature_validation",
        "a" * 64,
        "review_approved",
        {"claim_id": "claim-1", "publication_allowed": False},
        datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
        {"engine": "multimodal_intelligence", "production_mutation": False},
        False,
        {
            "decision": "approve",
            "rationale": "Evidence verified.",
            "reviewer": "owner",
            "decided_at": "2026-08-07T12:01:00+00:00",
        },
        [],
    )
    record = PostgresOperationRepository._record(row)
    assert record.operation_id.endswith("0001")
    assert record.review is not None
    assert record.review.decision == "approve"
    assert record.provenance["production_mutation"] is False
    assert record.human_review_required is False
