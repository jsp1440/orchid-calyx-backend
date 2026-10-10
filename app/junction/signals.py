"""Junction signal construction and validation (sci-obs-event-v1 + junction block).

A junction signal is a scientific observation event carrying an
``extensions.junction`` block — no parallel envelope, identity, or store. The
builder here produces the canonical ``sci-obs-event-v1`` JSON shape (the same
shape ``app.scientific_observability.models.ScientificObservationEvent.to_dict``
emits) and additionally covers the seven junction-added event types declared by
oc-junction-profile-v1, which the closed ``ObservationEventType`` enum does not
yet carry (enum extension is a contract-governance action, deferred to the
Brain contract owners).

``validate_signal`` is a direct port of the J0 reference validator: fail-closed
on any defect, including forbidden authority keys and the unresolved-identity
marker rule (scientific ambiguity is never silently resolved).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.kernel.identity import OCIDFactory, OCIDKind

from .manifest import ENTITY_SCOPE_PATTERN
from .profile import (
    CONSEQUENCE_CLASSES,
    FORBIDDEN_JUNCTION_KEYS,
    HEALTH_STATES,
    KNOWN_EVENT_TYPES,
    MAX_PAYLOAD_BYTES,
    MAX_TTL_HOPS,
    PROFILE_ID,
    SCI_OBS_SCHEMA_VERSION,
    JunctionValidationError,
    canonical_json,
    dedupe_key,
)

_OCID_EVENT = re.compile(r"^OC:EVENT:[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

ANCHOR_SNIPPET_MAX = 300


def build_signal(
    *,
    source_module: str,
    event_type: str,
    pipeline_stage: str,
    entity_scope: str,
    consequence_class: str = "observation",
    payload: dict[str, Any] | None = None,
    emitter_health: str = "open",
    taxon: dict[str, Any] | None = None,
    subject: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    conflict: dict[str, Any] | None = None,
    freshness: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
    safe_status: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    parent_event_id: str | None = None,
    sequence: int = 1,
    occurred_at: datetime | None = None,
    component_version: str | None = None,
    mission_id: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
    min_confidence: float | None = None,
    ttl_hops: int = MAX_TTL_HOPS,
) -> dict[str, Any]:
    """Build one junction signal envelope. Raises on any contract violation.

    The dedupe key and the unresolved-identity marker are computed here so
    emitters cannot forget them; everything else is asserted by
    ``validate_signal`` before the envelope is returned.
    """

    payload = payload or {}
    occurred = (occurred_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    recorded = datetime.now(timezone.utc)
    if recorded < occurred:  # mirrors the sci-obs envelope invariant
        raise JunctionValidationError(["recorded_at must be >= occurred_at"])
    if sequence < 1:
        raise JunctionValidationError(["sequence must be >= 1"])
    anchor = (source or {}).get("anchor_snippet")
    if isinstance(anchor, str) and len(anchor) > ANCHOR_SNIPPET_MAX:
        raise JunctionValidationError([f"source.anchor_snippet exceeds {ANCHOR_SNIPPET_MAX} chars"])

    # Scientific ambiguity is never silently resolved: an accepted name without
    # a canonical taxon id forces the explicit unresolved marker.
    taxon_identity_state: str | None = None
    if taxon and taxon.get("accepted_name") and not taxon.get("canonical_taxon_id"):
        taxon_identity_state = "unresolved"

    junction_block: dict[str, Any] = {
        "profile": PROFILE_ID,
        "consequence_class": consequence_class,
        "entity_scope": entity_scope,
        "dedupe_key": dedupe_key(
            source_module=source_module,
            event_type=event_type,
            entity_scope=entity_scope,
            payload=payload,
        ),
        "ttl_hops": ttl_hops,
        "emitter_health": emitter_health,
    }
    if taxon_identity_state is not None:
        junction_block["taxon_identity_state"] = taxon_identity_state
    if min_confidence is not None:
        junction_block["min_confidence"] = min_confidence

    event: dict[str, Any] = {
        "schema_version": SCI_OBS_SCHEMA_VERSION,
        "event_id": str(OCIDFactory.new(OCIDKind.EVENT)),
        "event_type": event_type,
        "occurred_at": occurred.isoformat(),
        "recorded_at": recorded.isoformat(),
        "correlation_id": correlation_id or str(OCIDFactory.new(OCIDKind.EVENT)),
        "parent_event_id": parent_event_id,
        "sequence": sequence,
        "mission_id": mission_id,
        "run_id": run_id,
        "request_id": request_id,
        "taxon": taxon,
        "subject": subject,
        "source": source,
        "pipeline": {
            "stage": pipeline_stage,
            "component": source_module,
            "component_version": component_version,
        },
        "evidence": evidence,
        "conflict": conflict,
        "freshness": freshness,
        "locality_classification": None,
        "actor": actor,
        "consumer": None,
        "safe_status": safe_status or {"status": "ok", "reason_code": None, "blocker": None, "error_code": None},
        "ai": None,
        "cost": None,
        "payload": payload,
        "extensions": {"junction": junction_block},
    }

    failures = validate_signal(event)
    if failures:
        raise JunctionValidationError(failures)
    return event


def validate_signal(event: Any) -> list[str]:
    """Validate one junction signal envelope. Fail closed on any defect."""

    failures: list[str] = []
    if not isinstance(event, dict):
        return ["signal is not a JSON object"]

    if event.get("schema_version") != SCI_OBS_SCHEMA_VERSION:
        failures.append(f"schema_version must be {SCI_OBS_SCHEMA_VERSION}")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not _OCID_EVENT.fullmatch(event_id):
        failures.append("event_id must be an OC:EVENT OCID")
    correlation_id = event.get("correlation_id")
    if not isinstance(correlation_id, str) or not _OCID_EVENT.fullmatch(correlation_id):
        failures.append("correlation_id must be an OC:EVENT OCID")
    parent = event.get("parent_event_id")
    if parent is not None:
        if not isinstance(parent, str) or not _OCID_EVENT.fullmatch(parent):
            failures.append("parent_event_id must be an OC:EVENT OCID or null")
        elif parent == event_id:
            failures.append("a signal cannot be its own parent (causation rule)")
    event_type = event.get("event_type")
    if not isinstance(event_type, str) or event_type not in KNOWN_EVENT_TYPES:
        failures.append(f"unknown event_type: {event_type!r}")
    sequence = event.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        failures.append("sequence must be an integer >= 1")
    for field_name in ("occurred_at", "recorded_at"):
        if not isinstance(event.get(field_name), str) or "T" not in event[field_name]:
            failures.append(f"{field_name} must be an ISO-8601 date-time string")
    safe_status = event.get("safe_status")
    if not isinstance(safe_status, dict) or not isinstance(safe_status.get("status"), str):
        failures.append("safe_status.status is required")

    junction = (event.get("extensions") or {}).get("junction")
    if not isinstance(junction, dict):
        failures.append("extensions.junction block is required for a junction signal")
        return failures

    if junction.get("profile") != PROFILE_ID:
        failures.append(f"extensions.junction.profile must be {PROFILE_ID}")
    if junction.get("consequence_class") not in CONSEQUENCE_CLASSES:
        failures.append("extensions.junction.consequence_class must be observation or action_request")
    scope = junction.get("entity_scope")
    if scope == "*":
        failures.append("entity_scope wildcard '*' is forbidden (no broadcast)")
    elif not isinstance(scope, str) or not ENTITY_SCOPE_PATTERN.fullmatch(scope):
        failures.append("extensions.junction.entity_scope is missing or invalid")
    key = junction.get("dedupe_key")
    if not isinstance(key, str) or not _SHA256.fullmatch(key):
        failures.append("extensions.junction.dedupe_key must be a sha256 hex digest")
    ttl = junction.get("ttl_hops")
    if not isinstance(ttl, int) or isinstance(ttl, bool) or not 0 <= ttl <= MAX_TTL_HOPS:
        failures.append(f"extensions.junction.ttl_hops must be an integer in 0..{MAX_TTL_HOPS}")
    if junction.get("emitter_health") not in HEALTH_STATES:
        failures.append("extensions.junction.emitter_health must be a known health state")

    forbidden = FORBIDDEN_JUNCTION_KEYS & set(junction)
    if forbidden:
        failures.append(
            "extensions.junction contains forbidden authority keys: " + ", ".join(sorted(forbidden))
        )

    confidence = junction.get("min_confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        failures.append("extensions.junction.min_confidence must be a number in 0..1 or null")

    # Scientific ambiguity is never silently resolved: an accepted name without
    # a canonical taxon id must carry the explicit unresolved marker.
    taxon = event.get("taxon") or {}
    if isinstance(taxon, dict) and taxon.get("accepted_name") and not taxon.get("canonical_taxon_id"):
        if junction.get("taxon_identity_state") != "unresolved":
            failures.append(
                "taxon.accepted_name without canonical_taxon_id requires "
                "extensions.junction.taxon_identity_state='unresolved'"
            )

    payload = event.get("payload") or {}
    if len(canonical_json(payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        failures.append(f"signal payload exceeds {MAX_PAYLOAD_BYTES} bytes")

    return failures
