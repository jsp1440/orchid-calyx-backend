from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.kernel import (
    IntegrityAudit,
    IntegrityFinding,
    IntegritySeverity,
    IntegrityStatus,
    OCIDFactory,
    OCIDKind,
    ScientificObjectValidationError,
)


def test_integrity_finding_is_immutable_and_normalized() -> None:
    finding = IntegrityFinding(
        rule_id="  graph.endpoint.exists  ",
        severity=IntegritySeverity.WARNING,
        message="  Target endpoint could not be resolved.  ",
        field_name="  target_ocid  ",
        details={"source": "relationship"},
    )
    assert finding.rule_id == "graph.endpoint.exists"
    assert finding.message == "Target endpoint could not be resolved."
    assert finding.field_name == "target_ocid"
    with pytest.raises(FrozenInstanceError):
        finding.message = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        finding.details["source"] = "changed"  # type: ignore[index]


def test_integrity_finding_rejects_empty_rule_and_message() -> None:
    with pytest.raises(ScientificObjectValidationError, match="rule_id"):
        IntegrityFinding(" ", IntegritySeverity.ERROR, "message")
    with pytest.raises(ScientificObjectValidationError, match="message"):
        IntegrityFinding("rule", IntegritySeverity.ERROR, " ")


def test_integrity_audit_defaults_to_event_ocid() -> None:
    audit = IntegrityAudit(target_ocids=(OCIDFactory.new(),))
    assert audit.ocid.kind is OCIDKind.EVENT
    assert audit.status is IntegrityStatus.PENDING
    assert not audit.passed


def test_integrity_audit_requires_unique_targets() -> None:
    target = OCIDFactory.new()
    with pytest.raises(ScientificObjectValidationError, match="must be unique"):
        IntegrityAudit(target_ocids=(target, target))


def test_running_integrity_audit_requires_started_at() -> None:
    with pytest.raises(ScientificObjectValidationError, match="require started_at"):
        IntegrityAudit(target_ocids=(OCIDFactory.new(),), status=IntegrityStatus.RUNNING)


def test_passed_audit_rejects_blocking_findings() -> None:
    now = datetime.now(timezone.utc)
    finding = IntegrityFinding(
        "publication.manifest.complete",
        IntegritySeverity.ERROR,
        "Manifest is incomplete.",
    )
    with pytest.raises(ScientificObjectValidationError, match="cannot contain"):
        IntegrityAudit(
            created_at=now,
            target_ocids=(OCIDFactory.new(),),
            status=IntegrityStatus.PASSED,
            started_at=now,
            completed_at=now + timedelta(seconds=1),
            findings=(finding,),
        )


def test_failed_audit_requires_blocking_finding() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ScientificObjectValidationError, match="require an error"):
        IntegrityAudit(
            created_at=now,
            target_ocids=(OCIDFactory.new(),),
            status=IntegrityStatus.FAILED,
            started_at=now,
            completed_at=now + timedelta(seconds=1),
            findings=(
                IntegrityFinding(
                    "metadata.recommended",
                    IntegritySeverity.WARNING,
                    "Recommended metadata is absent.",
                ),
            ),
        )


def test_integrity_audit_normalizes_times_and_reports_blocking_findings() -> None:
    local_tz = timezone(timedelta(hours=-7))
    created = datetime(2026, 7, 23, 12, tzinfo=local_tz)
    started = created + timedelta(minutes=1)
    completed = started + timedelta(minutes=2)
    blocking = IntegrityFinding(
        "evidence.reference.valid",
        IntegritySeverity.CRITICAL,
        "Evidence reference is invalid.",
    )
    audit = IntegrityAudit(
        created_at=created,
        target_ocids=(OCIDFactory.new(),),
        status=IntegrityStatus.FAILED,
        requested_by="  curator@example.org  ",
        started_at=started,
        completed_at=completed,
        findings=(blocking,),
    )
    assert audit.requested_by == "curator@example.org"
    assert audit.started_at == datetime(2026, 7, 23, 19, 1, tzinfo=timezone.utc)
    assert audit.completed_at == datetime(2026, 7, 23, 19, 3, tzinfo=timezone.utc)
    assert audit.blocking_findings == (blocking,)
