from __future__ import annotations

import pytest

from app.multimodal_intelligence.operator import (
    InMemoryOperationRepository,
    MultimodalError,
    MultimodalOperatorService,
)


def _service_with_record() -> tuple[MultimodalOperatorService, str]:
    service = MultimodalOperatorService(InMemoryOperationRepository())
    record = service._record(
        "matrix_ranking",
        {"sample": "request"},
        {"candidates": [], "autonomous_identification": False},
    )
    return service, record.operation_id


def test_repository_enforces_idempotent_request_hash() -> None:
    service = MultimodalOperatorService(InMemoryOperationRepository())
    first = service._record("matrix_ranking", {"a": 1}, {"value": 1})
    second = service._record("matrix_ranking", {"a": 1}, {"value": 2})
    assert second.operation_id == first.operation_id
    assert second.result == {"value": 1}


def test_operation_detail_and_provenance_bundle() -> None:
    service, operation_id = _service_with_record()
    record = service.get_operation(operation_id)
    bundle = service.provenance_bundle(operation_id)
    assert record.operation_id == operation_id
    assert bundle["operation_id"] == operation_id
    assert len(bundle["result_hash"]) == 64
    assert bundle["provenance"]["live_provider_calls"] == 0


def test_review_decision_removes_record_from_queue() -> None:
    service, operation_id = _service_with_record()
    assert service.review_queue()["total"] == 1
    updated = service.decide_review(
        operation_id,
        decision="approve",
        rationale="Evidence and explanation reviewed.",
        reviewer="owner",
    )
    assert updated.state == "review_approved"
    assert updated.human_review_required is False
    assert service.review_queue()["total"] == 0


def test_review_rejects_unsupported_decision() -> None:
    service, operation_id = _service_with_record()
    with pytest.raises(MultimodalError, match="Unsupported review decision"):
        service.decide_review(
            operation_id,
            decision="publish",
            rationale="Not allowed.",
            reviewer="owner",
        )


def test_review_queue_supports_filtering_and_pagination() -> None:
    service = MultimodalOperatorService(InMemoryOperationRepository())
    service._record("matrix_ranking", {"a": 1}, {"value": 1})
    service._record("vision_conversion", {"a": 2}, {"value": 2})
    service._record("matrix_ranking", {"a": 3}, {"value": 3})
    page = service.review_queue(operation_type="matrix_ranking", offset=1, limit=1)
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0].operation_type == "matrix_ranking"


def test_invalid_pagination_fails_closed() -> None:
    service = MultimodalOperatorService(InMemoryOperationRepository())
    with pytest.raises(MultimodalError, match="outside allowed bounds"):
        service.review_queue(offset=-1)


def test_missing_operation_uses_structured_error_code() -> None:
    service = MultimodalOperatorService(InMemoryOperationRepository())
    with pytest.raises(MultimodalError) as error:
        service.get_operation("missing")
    assert error.value.code == "OPERATION_NOT_FOUND"


def test_benchmark_exposes_named_fixture_cases() -> None:
    service = MultimodalOperatorService(InMemoryOperationRepository())
    report = service.benchmark()
    assert report["suite"] == "fixture_multimodal_v2"
    assert report["case_count"] == 4
    assert {case["case_id"] for case in report["cases"]} == {
        "literature-provenance",
        "matrix-explainability",
        "vision-license",
        "identification-abstention",
    }


def test_configuration_reports_disabled_production_integrations() -> None:
    service = MultimodalOperatorService(InMemoryOperationRepository())
    config = service.configuration()
    assert config["production_persistence_enabled"] is False
    assert config["live_vision_provider_enabled"] is False
    assert config["automatic_publication_enabled"] is False
    assert config["human_review_required"] is True


def test_audit_export_identifies_repository_backend() -> None:
    service, _ = _service_with_record()
    audit = service.export_audit()
    assert audit["record_count"] == 1
    assert audit["repository"] == "InMemoryOperationRepository"
    assert audit["production_persistence"] is False
