"""``calyx_advisory_contract.v1``: what Calyx may say, and what it may never do.

Calyx is a peer advisory intelligence. Brain owns scientific reasoning,
evidence, provenance, uncertainty, safety and autonomy governance. An advisory
finding therefore describes a gap in how knowledge is *taught or presented*; it
never edits a claim, an evidence state or an uncertainty statement.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

CONTRACT = "calyx_advisory_contract.v1"

FINDING_KINDS: tuple[str, ...] = (
    "educational_gap",
    "ux_gap",
    "curriculum_gap",
    "accessibility_gap",
    "teaching_opportunity",
    "no_action",
)

SEVERITIES: tuple[str, ...] = ("info", "low", "medium", "high")

#: Evidence states Brain assigns. Calyx reads them; it never sets or changes one.
EVIDENCE_STATES: tuple[str, ...] = ("established", "supported", "contested", "unresolved")
UNCERTAIN_STATES = frozenset({"contested", "unresolved"})

#: Things Calyx must not do. Carried in every advisory so a consumer can see the
#: boundary the advisory was produced under; a document claiming otherwise fails
#: validation.
PROHIBITED_ACTIONS: tuple[str, ...] = (
    "alter_canonical_taxonomy",
    "rewrite_scientific_evidence",
    "erase_uncertainty",
    "choose_convenient_answer_for_pedagogy",
    "weaken_provenance",
    "disclose_protected_locality",
    "alter_secrets",
    "authorize_spending",
    "deploy_production",
    "override_scientific_or_owner_gate",
)

#: Keys that would carry precise locality. Never allowed in an advisory.
LOCALITY_KEYS = frozenset(
    {"latitude", "longitude", "lat", "lon", "lng", "coordinates", "locality", "geometry"}
)


class ContractViolation(ValueError):
    """An advisory or a presentation breaks the Calyx contract."""


def checksum(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def contains_locality_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in LOCALITY_KEYS or contains_locality_key(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_locality_key(item) for item in value)
    return False


def validate_advisory(advisory: Mapping[str, Any]) -> None:
    """Raise :class:`ContractViolation` unless ``advisory`` honours the contract."""
    if advisory.get("contract") != CONTRACT:
        raise ContractViolation("ADVISORY_CONTRACT_MISMATCH")
    if set(advisory.get("prohibited_actions") or ()) != set(PROHIBITED_ACTIONS):
        raise ContractViolation("ADVISORY_PROHIBITED_ACTIONS_ALTERED")
    findings = advisory.get("findings")
    if not isinstance(findings, list) or not findings:
        raise ContractViolation("ADVISORY_FINDINGS_REQUIRED")
    if contains_locality_key(advisory):
        raise ContractViolation("ADVISORY_CONTAINS_LOCALITY")
    for finding in findings:
        if finding.get("kind") not in FINDING_KINDS:
            raise ContractViolation("FINDING_KIND_UNKNOWN")
        if finding.get("severity") not in SEVERITIES:
            raise ContractViolation("FINDING_SEVERITY_UNKNOWN")
        if finding.get("scientific_effect") != "none":
            raise ContractViolation("FINDING_CHANGES_SCIENCE")
        if finding["kind"] != "no_action" and not finding.get("evidence"):
            raise ContractViolation("FINDING_EVIDENCE_REQUIRED")
    if len(findings) > 1 and any(f["kind"] == "no_action" for f in findings):
        raise ContractViolation("NO_ACTION_MUST_STAND_ALONE")
