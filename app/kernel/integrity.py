"""Scientific integrity validation and audit models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind
from .models import ScientificObject


class IntegritySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IntegrityStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class IntegrityFinding:
    rule_id: str
    severity: IntegritySeverity
    message: str
    object_ocid: OCID | None = None
    field_name: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rule_id = self.rule_id.strip()
        message = self.message.strip()
        field_name = self.field_name.strip() if self.field_name is not None else None
        if not rule_id:
            raise ScientificObjectValidationError("integrity finding rule_id must not be empty")
        if not message:
            raise ScientificObjectValidationError("integrity finding message must not be empty")
        object.__setattr__(self, "rule_id", rule_id)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "field_name", field_name or None)
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class IntegrityAudit(ScientificObject):
    ocid: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.EVENT))
    object_type: str = "integrity_audit"
    target_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    status: IntegrityStatus = IntegrityStatus.PENDING
    requested_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    findings: tuple[IntegrityFinding, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ScientificObject.__post_init__(self)
        if self.ocid.kind is not OCIDKind.EVENT:
            raise ScientificObjectValidationError("integrity audit requires an EVENT OCID")
        target_ocids = tuple(self.target_ocids)
        findings = tuple(self.findings)
        if not target_ocids:
            raise ScientificObjectValidationError("integrity audit requires at least one target OCID")
        if len(set(target_ocids)) != len(target_ocids):
            raise ScientificObjectValidationError("integrity audit target_ocids must be unique")
        requested_by = self.requested_by.strip() if self.requested_by is not None else None
        started_at = _normalize_datetime(self.started_at, "started_at")
        completed_at = _normalize_datetime(self.completed_at, "completed_at")
        if self.status is IntegrityStatus.RUNNING and started_at is None:
            raise ScientificObjectValidationError("running integrity audits require started_at")
        if self.status in {IntegrityStatus.PASSED, IntegrityStatus.FAILED, IntegrityStatus.CANCELLED}:
            if started_at is None or completed_at is None:
                raise ScientificObjectValidationError("terminal integrity audits require started_at and completed_at")
        elif completed_at is not None:
            raise ScientificObjectValidationError("completed_at is valid only for terminal integrity audits")
        if started_at is not None and started_at < self.created_at:
            raise ScientificObjectValidationError("started_at must not precede created_at")
        if completed_at is not None and started_at is not None and completed_at < started_at:
            raise ScientificObjectValidationError("completed_at must not precede started_at")
        has_failure = any(
            finding.severity in {IntegritySeverity.ERROR, IntegritySeverity.CRITICAL}
            for finding in findings
        )
        if self.status is IntegrityStatus.PASSED and has_failure:
            raise ScientificObjectValidationError("passed integrity audits cannot contain error or critical findings")
        if self.status is IntegrityStatus.FAILED and not has_failure:
            raise ScientificObjectValidationError("failed integrity audits require an error or critical finding")
        object.__setattr__(self, "target_ocids", target_ocids)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "requested_by", requested_by or None)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)

    @property
    def passed(self) -> bool:
        return self.status is IntegrityStatus.PASSED

    @property
    def blocking_findings(self) -> tuple[IntegrityFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.severity in {IntegritySeverity.ERROR, IntegritySeverity.CRITICAL}
        )


def _normalize_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScientificObjectValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
