from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PublicationState(StrEnum):
    PUBLICATION_CANDIDATE = "PUBLICATION_CANDIDATE"
    VALIDATING = "VALIDATING"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"


class PublicationPathway(StrEnum):
    AUTOMATIC = "AUTOMATIC_GOVERNED_PUBLICATION"
    HUMAN = "HUMAN_AUTHORIZED_PUBLICATION"
    PROVISIONAL = "PROVISIONAL_PUBLICATION"


@dataclass(frozen=True)
class CandidateRequest:
    assertion_id: int
    assertion_version: int
    policy_id: str
    policy_version: int
    requested_pathway: PublicationPathway
    idempotency_key: str
    actor: str
    correlation_id: str

    def __post_init__(self) -> None:
        if min(self.assertion_id, self.assertion_version, self.policy_version) <= 0:
            raise ValueError("INVALID_VERSIONED_REFERENCE")
        if not all(
            value.strip()
            for value in (
                self.policy_id,
                self.idempotency_key,
                self.actor,
                self.correlation_id,
            )
        ):
            raise ValueError("INCOMPLETE_CANDIDATE_REQUEST")


@dataclass(frozen=True)
class PublicationPolicy:
    policy_id: str
    version: int
    name: str
    supported_assertion_types: tuple[str, ...]
    supported_domains: tuple[str, ...]
    automatic_assertion_types: tuple[str, ...] = ()
    automatic_domains: tuple[str, ...] = ()
    prohibited_assertion_types: tuple[str, ...] = ()
    prohibited_domains: tuple[str, ...] = ()
    mandatory_review_impact_classes: tuple[str, ...] = (
        "CONSERVATION_HIGH_IMPACT",
        "NOMENCLATURAL_ACT",
    )
    permitted_copyright_policies: tuple[str, ...] = ("DERIVED_FACTS_ALLOWED",)
    minimum_independent_sources: int = 2
    require_complete_provenance: bool = True
    require_unambiguous_taxonomy: bool = True
    reject_unresolved_conflicts: bool = True
    provisional_enabled: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)
    approval_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.version <= 0 or self.minimum_independent_sources <= 0:
            raise ValueError("INVALID_POLICY_NUMERIC_VALUE")
        if (
            not self.policy_id.strip()
            or not self.name.strip()
            or not self.supported_assertion_types
            or not self.supported_domains
            or not self.provenance
        ):
            raise ValueError("INCOMPLETE_POLICY")

    def rules(self) -> dict[str, Any]:
        return {
            name: sorted(getattr(self, name))
            for name in (
                "supported_assertion_types",
                "supported_domains",
                "automatic_assertion_types",
                "automatic_domains",
                "prohibited_assertion_types",
                "prohibited_domains",
                "mandatory_review_impact_classes",
                "permitted_copyright_policies",
            )
        } | {
            "minimum_independent_sources": self.minimum_independent_sources,
            "require_complete_provenance": self.require_complete_provenance,
            "require_unambiguous_taxonomy": self.require_unambiguous_taxonomy,
            "reject_unresolved_conflicts": self.reject_unresolved_conflicts,
            "provisional_enabled": self.provisional_enabled,
        }
