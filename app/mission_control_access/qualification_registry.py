from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

_ALLOWED_QUALIFICATIONS = frozenset(
    {
        "qualified.science-reviewer",
        "qualified.expert-reviewer",
        "qualified.publication-reviewer",
    }
)


class QualificationRegistryError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


@dataclass(frozen=True)
class ReviewerQualificationClaims:
    qualifications: tuple[str, ...] = ()
    qualification_expires_at: dict[str, str] = field(default_factory=dict)
    specialties: tuple[str, ...] = ()


def _registry_payload() -> dict[str, Any]:
    raw = os.getenv("MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationRegistryError("INVALID_REVIEWER_QUALIFICATION_REGISTRY") from exc
    if not isinstance(payload, dict):
        raise QualificationRegistryError("INVALID_REVIEWER_QUALIFICATION_REGISTRY")
    return payload


def reviewer_qualification_claims(
    subject_id: str,
    *,
    auth_source: str,
) -> ReviewerQualificationClaims:
    """Resolve server-controlled scientific qualification claims for owner sessions.

    API keys intentionally cannot receive scientific-review qualifications through
    this registry. Missing configuration grants nothing. Actual qualification
    assignment is an operator/governance action outside this function.
    """
    if auth_source != "owner_session":
        return ReviewerQualificationClaims()

    entry = _registry_payload().get(subject_id)
    if entry is None:
        return ReviewerQualificationClaims()
    if not isinstance(entry, dict):
        raise QualificationRegistryError(
            "INVALID_REVIEWER_QUALIFICATION_ENTRY", {"subject_id": subject_id}
        )

    raw_qualifications = entry.get("qualifications", [])
    raw_expirations = entry.get("qualification_expires_at", {})
    raw_specialties = entry.get("specialties", [])
    if not isinstance(raw_qualifications, list) or not all(
        isinstance(value, str) for value in raw_qualifications
    ):
        raise QualificationRegistryError(
            "INVALID_REVIEWER_QUALIFICATIONS", {"subject_id": subject_id}
        )
    qualifications = tuple(sorted(set(raw_qualifications)))
    unknown = sorted(set(qualifications) - _ALLOWED_QUALIFICATIONS)
    if unknown:
        raise QualificationRegistryError(
            "UNKNOWN_REVIEWER_QUALIFICATION",
            {"subject_id": subject_id, "qualifications": unknown},
        )

    if not isinstance(raw_expirations, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_expirations.items()
    ):
        raise QualificationRegistryError(
            "INVALID_REVIEWER_QUALIFICATION_EXPIRY", {"subject_id": subject_id}
        )
    expiration_keys = set(raw_expirations)
    if not expiration_keys.issubset(set(qualifications)):
        raise QualificationRegistryError(
            "UNDECLARED_REVIEWER_QUALIFICATION_EXPIRY", {"subject_id": subject_id}
        )

    if not isinstance(raw_specialties, list) or not all(
        isinstance(value, str) and value.strip() for value in raw_specialties
    ):
        raise QualificationRegistryError(
            "INVALID_REVIEWER_SPECIALTIES", {"subject_id": subject_id}
        )

    return ReviewerQualificationClaims(
        qualifications=qualifications,
        qualification_expires_at=dict(raw_expirations),
        specialties=tuple(sorted(set(value.strip() for value in raw_specialties))),
    )
