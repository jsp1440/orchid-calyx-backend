from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class GateStatus(str, Enum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    UNVERIFIED = "UNVERIFIED"


class CertificationTarget(BaseModel):
    application_id: str
    application_name: str
    source_repository: str
    source_ref: str = "main"
    runtime_url: HttpUrl | None = None
    preview_url: HttpUrl | None = None
    policy_version: str = "oc-app-cert-v1"


class CertificationGate(BaseModel):
    gate_id: str
    status: GateStatus
    evidence_type: Literal["source", "test", "api", "browser", "deployment", "configuration"]
    observed_evidence: str
    blocker: str | None = None
    smallest_next_action: str | None = None
    evidence_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CertificationReport(BaseModel):
    contract_version: Literal["oc-application-certification-v1"] = "oc-application-certification-v1"
    application_id: str
    application_name: str
    source_repository: str
    source_ref: str
    source_sha: str | None = None
    runtime_url: str | None = None
    policy_version: str
    gates: list[CertificationGate]
    source_audit_status: GateStatus
    runtime_audit_status: GateStatus
    scientific_provenance_status: GateStatus
    security_status: GateStatus
    media_status: GateStatus
    accessibility_status: GateStatus
    publish_ready: Literal["YES", "NO", "UNVERIFIED"]
    exact_blockers: list[str] = Field(default_factory=list)
    source_under_test: str | None = None
    last_verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
