"""Module Junction Manifest validation (oc-junction-manifest-v1), fail-closed.

The manifest is the least-privilege boundary: a module may publish only listed
event types, subscribe only to listed ``{event_type, entity_scope}`` pairs, and
may propose work only if explicitly permitted. A junction manifest can NEVER
grant execution authority: ``execution_authority`` is const ``"none"``.

Validation semantics are a direct port of the J0 reference validator
(Orchid-Continuum-Brain ``scripts/oc_junction_validate.py``): any absent,
malformed, or ambiguous input yields failures, never a permissive default.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .profile import (
    CONSEQUENCE_CLASSES,  # noqa: F401  (re-exported for callers)
    HEARTBEAT_EVENT,
    KNOWN_EVENT_TYPES,
    MANIFEST_VERSION,
    MAX_PAYLOAD_BYTES,
    PROFILE_ID,
    SUPPORTED_PROFILE_MAJOR,
    JunctionValidationError,
)

_MODULE_ID = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_.]+$")
_ENTITY_SCOPE = re.compile(r"^(taxon|genus|module|domain):[A-Za-z0-9._:/×-]{1,128}$")

ENTITY_SCOPE_PATTERN = _ENTITY_SCOPE


def validate_manifest(doc: Any) -> list[str]:
    """Validate one Module Junction Manifest. Fail closed on any defect."""

    failures: list[str] = []
    if not isinstance(doc, dict):
        return ["manifest is not a JSON object"]

    if doc.get("manifest_version") != MANIFEST_VERSION:
        failures.append(f"manifest_version must be {MANIFEST_VERSION}")

    module_id = doc.get("module_id")
    if not isinstance(module_id, str) or not _MODULE_ID.fullmatch(module_id):
        failures.append("module_id is missing or invalid")

    module_version = doc.get("module_version")
    if not isinstance(module_version, str) or not _SEMVER.fullmatch(module_version):
        failures.append("module_version must be semantic (MAJOR.MINOR.PATCH)")

    profile = doc.get("profile")
    if not isinstance(profile, dict):
        failures.append("profile block is required")
    else:
        if profile.get("id") != PROFILE_ID:
            failures.append(f"profile.id must be {PROFILE_ID}")
        version = profile.get("version")
        if not isinstance(version, str) or not _SEMVER.fullmatch(version):
            failures.append("profile.version must be semantic")
        elif int(version.split(".")[0]) != SUPPORTED_PROFILE_MAJOR:
            failures.append(f"unsupported profile major version: {version}")

    capabilities = doc.get("capabilities")
    if not isinstance(capabilities, dict):
        failures.append("capabilities block is required")
    else:
        publishes = capabilities.get("publishes")
        if not isinstance(publishes, list):
            failures.append("capabilities.publishes must be a list")
        else:
            for event_type in publishes:
                if not isinstance(event_type, str) or not _EVENT_TYPE.fullmatch(event_type):
                    failures.append(f"invalid publish event type: {event_type!r}")
                elif event_type not in KNOWN_EVENT_TYPES:
                    failures.append(f"unknown publish event type: {event_type!r}")
        subscribes = capabilities.get("subscribes")
        if not isinstance(subscribes, list):
            failures.append("capabilities.subscribes must be a list")
        else:
            for entry in subscribes:
                if not isinstance(entry, dict):
                    failures.append("subscription entries must be objects")
                    continue
                et = entry.get("event_type")
                if not isinstance(et, str) or et not in KNOWN_EVENT_TYPES:
                    failures.append(f"unknown subscription event type: {et!r}")
                scope = entry.get("entity_scope")
                if scope == "*":
                    failures.append("wildcard subscription '*' is forbidden (no broadcast)")
                elif not isinstance(scope, str) or not _ENTITY_SCOPE.fullmatch(scope):
                    failures.append(f"invalid subscription entity_scope: {scope!r}")
        if capabilities.get("can_propose_work") not in (True, False):
            failures.append("capabilities.can_propose_work must be a boolean")
        # A junction can never grant execution authority.
        if capabilities.get("execution_authority") != "none":
            failures.append(
                "capabilities.execution_authority must be 'none'; "
                "a junction manifest cannot express execution authority"
            )

    health = doc.get("health_policy")
    if not isinstance(health, dict):
        failures.append("health_policy block is required")
    else:
        if health.get("min_state_to_publish") not in ("open", "restricted"):
            failures.append(
                "health_policy.min_state_to_publish must be open or restricted; "
                "closed/quarantined can never be a publishing floor"
            )
        if health.get("min_state_to_subscribe") not in ("open", "restricted", "closed"):
            failures.append("health_policy.min_state_to_subscribe is invalid")
        if health.get("degraded_egress") != "observation_only":
            failures.append("health_policy.degraded_egress must be 'observation_only'")
        if health.get("heartbeat_event") != HEARTBEAT_EVENT:
            failures.append(f"health_policy.heartbeat_event must be {HEARTBEAT_EVENT}")

    evidence = doc.get("evidence_policy")
    if not isinstance(evidence, dict):
        failures.append("evidence_policy block is required")
    else:
        if not isinstance(evidence.get("require_source_refs_for"), list):
            failures.append("evidence_policy.require_source_refs_for must be a list")
        if evidence.get("preserve_conflict_records") is not True:
            failures.append("evidence_policy.preserve_conflict_records must be true")
        if evidence.get("unresolved_identity_marker") != "unresolved":
            failures.append("evidence_policy.unresolved_identity_marker must be 'unresolved'")

    budgets = doc.get("budgets")
    if not isinstance(budgets, dict):
        failures.append("budgets block is required")
    else:
        rate = budgets.get("max_signals_per_minute")
        if not isinstance(rate, int) or isinstance(rate, bool) or not 1 <= rate <= 600:
            failures.append("budgets.max_signals_per_minute must be an integer in 1..600")
        size = budgets.get("max_payload_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_PAYLOAD_BYTES:
            failures.append(f"budgets.max_payload_bytes must be an integer in 1..{MAX_PAYLOAD_BYTES}")

    idem = doc.get("idempotency")
    if not isinstance(idem, dict):
        failures.append("idempotency block is required")
    else:
        if idem.get("dedupe_key_rule") != "sha256_canonical_json(source_module+event_type+entity_scope+payload)":
            failures.append("idempotency.dedupe_key_rule does not match the canonical rule")
        if idem.get("replay_safe") is not True:
            failures.append("idempotency.replay_safe must be true")

    return failures


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load and validate a manifest JSON file. Fail closed on any defect."""

    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    failures = validate_manifest(doc)
    if failures:
        raise JunctionValidationError([f"{path}: {failure}" for failure in failures])
    return doc
