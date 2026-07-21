from dataclasses import dataclass
from enum import StrEnum


class RetractionReason(StrEnum):
    SOURCE_FORMALLY_RETRACTED = "SOURCE_FORMALLY_RETRACTED"
    EVIDENCE_INTEGRITY_FAILURE = "EVIDENCE_INTEGRITY_FAILURE"
    INTERPRETATION_INVALIDATED = "INTERPRETATION_INVALIDATED"
    ASSERTION_INVALIDATED = "ASSERTION_INVALIDATED"
    TAXONOMY_INVALIDATED = "TAXONOMY_INVALIDATED"
    PROVENANCE_INVALID = "PROVENANCE_INVALID"
    PUBLICATION_POLICY_VIOLATION = "PUBLICATION_POLICY_VIOLATION"
    COPYRIGHT_OR_LEGAL_RESTRICTION = "COPYRIGHT_OR_LEGAL_RESTRICTION"
    ADMINISTRATIVE_SCIENTIFIC_ERROR = "ADMINISTRATIVE_SCIENTIFIC_ERROR"


@dataclass(frozen=True)
class LifecycleAuthority:
    service_identity: str
    authority_reference: str
    correlation_id: str

    def __post_init__(self):
        if not all(
            value.strip()
            for value in (
                self.service_identity,
                self.authority_reference,
                self.correlation_id,
            )
        ):
            raise ValueError("TRUSTED_LIFECYCLE_AUTHORITY_REQUIRED")


@dataclass(frozen=True)
class LifecycleReason:
    reason_code: str
    rationale: str

    def __post_init__(self):
        if not self.reason_code.strip() or not self.rationale.strip():
            raise ValueError("LIFECYCLE_REASON_REQUIRED")
