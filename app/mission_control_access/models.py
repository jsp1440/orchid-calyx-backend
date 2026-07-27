from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MissionControlRole(StrEnum):
    PUBLIC = "PUBLIC"
    VOLUNTEER = "VOLUNTEER"
    EXPERT = "EXPERT"
    ADMINISTRATOR = "ADMINISTRATOR"


class Capability(StrEnum):
    VIEW_PUBLIC = "mission_control.view.public"
    VIEW_OPERATIONS = "mission_control.view.operations"
    VIEW_RESTRICTED_EVIDENCE = "review.evidence.restricted"
    REVIEW_SCIENCE = "review.science"
    REVIEW_EXPERT = "review.expert"
    REVIEW_PUBLISH = "review.publish"
    MANAGE_ASSIGNMENTS = "review.assignments.manage"
    EXPORT_EXTERNAL = "review.external.export"
    IMPORT_EXTERNAL = "review.external.import"
    VIEW_AUDIT = "governance.audit.view"


@dataclass(frozen=True)
class AccessPrincipal:
    principal_id: str
    roles: tuple[MissionControlRole, ...] = ()
    direct_capabilities: tuple[str, ...] = ()
    qualifications: tuple[str, ...] = ()
    specialties: tuple[str, ...] = ()
    authenticated: bool = True
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    capability: str
    principal_id: str
    reason_code: str
    effective_capabilities: tuple[str, ...]
