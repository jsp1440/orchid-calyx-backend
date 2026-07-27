from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.kernel import (
    OCIDFactory,
    RuntimeContext,
    RuntimeOperation,
    RuntimeRequest,
    RuntimeResult,
    RuntimeStatus,
    ScientificObject,
    ScientificObjectValidationError,
)


def test_runtime_context_normalizes_time_and_attributes() -> None:
    local_tz = timezone(timedelta(hours=-7))
    context = RuntimeContext(
        actor="  curator@example.org  ",
        started_at=datetime(2026, 7, 23, 10, tzinfo=local_tz),
        attributes={"source": "calyx"},
    )

    assert context.actor == "curator@example.org"
    assert context.started_at == datetime(2026, 7, 23, 17, tzinfo=timezone.utc)
    assert context.attributes["source"] == "calyx"


def test_runtime_context_is_immutable() -> None:
    context = RuntimeContext()

    with pytest.raises(FrozenInstanceError):
        context.actor = "changed"  # type: ignore[misc]


def test_runtime_request_requires_execution_input() -> None:
    with pytest.raises(ScientificObjectValidationError, match="requires"):
        RuntimeRequest(operation=RuntimeOperation.EXECUTE_QUERY)


def test_runtime_request_accepts_scientific_object() -> None:
    obj = ScientificObject()
    request = RuntimeRequest(
        operation=RuntimeOperation.REGISTER_EVIDENCE,
        scientific_object=obj,
    )

    assert request.scientific_object is obj


def test_runtime_request_rejects_duplicate_target() -> None:
    obj = ScientificObject()

    with pytest.raises(ScientificObjectValidationError, match="must not duplicate"):
        RuntimeRequest(
            operation=RuntimeOperation.PUBLISH_ASSERTION,
            scientific_object=obj,
            target_ocid=obj.ocid,
        )


def test_terminal_runtime_result_requires_completion_time() -> None:
    with pytest.raises(ScientificObjectValidationError, match="require completed_at"):
        RuntimeResult(
            operation=RuntimeOperation.PUBLISH_EVENT,
            status=RuntimeStatus.SUCCEEDED,
            correlation_id=RuntimeContext().correlation_id,
        )


def test_failed_runtime_result_requires_error_details() -> None:
    with pytest.raises(ScientificObjectValidationError, match="require error_code"):
        RuntimeResult(
            operation=RuntimeOperation.COMMIT_PUBLICATION,
            status=RuntimeStatus.FAILED,
            correlation_id=RuntimeContext().correlation_id,
            completed_at=datetime.now(timezone.utc),
        )


def test_runtime_result_tracks_unique_events_and_terminal_state() -> None:
    event_ocid = OCIDFactory.new()
    result = RuntimeResult(
        operation=RuntimeOperation.PUBLISH_KNOWLEDGE,
        status=RuntimeStatus.SUCCEEDED,
        correlation_id=RuntimeContext().correlation_id,
        event_ocids=(event_ocid,),
        completed_at=datetime.now(timezone.utc),
    )

    assert result.is_terminal
    assert result.event_ocids == (event_ocid,)
