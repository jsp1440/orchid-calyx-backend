from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DataSensitivity(StrEnum):
    """Canonical sensitivity classes for scientific and partner-provided data."""

    PUBLIC = "PUBLIC"
    ATTRIBUTED = "ATTRIBUTED"
    RESEARCH_RESTRICTED = "RESEARCH_RESTRICTED"
    SENSITIVE_CONSERVATION = "SENSITIVE_CONSERVATION"
    SEALED_PARTNER = "SEALED_PARTNER"


class DisclosureMode(StrEnum):
    """Maximum disclosure a caller may receive for a governed record."""

    FULL = "FULL"
    GENERALIZED = "GENERALIZED"
    AGGREGATE_ONLY = "AGGREGATE_ONLY"
    EXISTENCE_ONLY = "EXISTENCE_ONLY"
    DENY = "DENY"


@dataclass(frozen=True)
class DataPolicy:
    """Source-attached policy contract for one record or evidence bundle.

    A policy travels with the scientific record.  It deliberately separates
    scientific provenance from access rights so aggregation cannot erase either.
    """

    policy_id: str
    authority_org: str
    sensitivity: DataSensitivity
    required_capabilities: tuple[str, ...] = ()
    allowed_purposes: tuple[str, ...] = ()
    attribution_required: bool = True
    allow_export: bool = False
    allow_model_processing: bool = False
    approved_model_providers: tuple[str, ...] = ()
    default_disclosure: DisclosureMode = DisclosureMode.DENY
    location_disclosure: DisclosureMode = DisclosureMode.DENY
    image_disclosure: DisclosureMode = DisclosureMode.DENY
    agreement_reference: str | None = None
    embargo_until: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DataAccessContext:
    principal_id: str
    authenticated: bool
    capabilities: tuple[str, ...] = ()
    purpose: str | None = None
    project_id: str | None = None
    model_provider: str | None = None
    requests_export: bool = False
    requests_model_processing: bool = False


@dataclass(frozen=True)
class DataPolicyDecision:
    allowed: bool
    disclosure: DisclosureMode
    location_disclosure: DisclosureMode
    image_disclosure: DisclosureMode
    reason_codes: tuple[str, ...]
    policy_id: str
    authority_org: str
    attribution_required: bool
