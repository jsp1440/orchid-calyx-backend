"""J1 junction router: the smallest durable implementation of oc-junction-profile-v1.

The router is a delivery-and-policy port over the existing scientific
observability plane. It introduces NO scheduler, NO queue, NO executor, and NO
second event system:

- events live in the append-only observation store
  (``app.scientific_observability.store.ObservationStore``; ``event_id`` is the
  idempotency key, redaction runs before any write);
- delivery state (cursors, applied dedupe keys, attempts, dead letters, audit)
  lives in ``app.junction.state.JunctionStateStore``;
- delivery is synchronous in-process at publish time, plus explicit cursor
  recovery. Retries reuse the same ``event_id`` and ``dedupe_key``.

Fail-closed authorization: an unregistered module, an unknown or malformed
signal, an unknown health state, a revoked manifest, or a halted junction all
deny — never a permissive default. Non-open health states only ever NARROW
communication, never widen it.

Authority boundary: delivering a signal authorizes nothing. A delivered
``action_request`` becomes at most a candidate work hint
(``review_required=True``, ``automatic_publication=False``,
``knowledge_graph_mutation=False``, ``taxonomy_mutation=False``) for the
existing engine-side fail-closed bridge pattern. The engine disposes.

Contract: Orchid-Continuum-Brain ``contracts/oc_junction_profile_v1.json``
(J0, Brain PR #221). Validation semantics are ported from the J0 reference
validator ``scripts/oc_junction_validate.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from app.scientific_observability.store import ObservationStore, get_default_store

from .manifest import validate_manifest
from .profile import (
    HEALTH_STATES,
    HEARTBEAT_EVENT,
    MAX_RETRY_ATTEMPTS,
    VERIFICATION_STATE_RANK,
    JunctionValidationError,
    canonical_json,
)
from .signals import validate_signal
from .state import JunctionStateStore

#: Handler contract: receive the stored signal; raise to signal a failed
#: delivery (bounded retry applies). Must apply the signal idempotently.
SignalHandler = Callable[[dict[str, Any]], None]

#: Health provider contract: return the module's current junction health state
#: ("open" | "restricted" | "closed" | "quarantined"). Health transitions are
#: produced by the existing health/readiness/certification components; the
#: router only consumes them. Unknown states are treated as "closed".
HealthProvider = Callable[[str], str]

# Outcomes after which a subscriber's cursor may advance past an event.
_CURSOR_ADVANCING = frozenset(
    {"DELIVERED", "DUPLICATE_SUPPRESSED", "NOT_MATCHING", "BELOW_FLOOR", "DEAD_LETTERED"}
)


def _closed_health(_module_id: str) -> str:
    """Fail-closed default: a module with no health signal is closed."""

    return "closed"


class JunctionRouter:
    """Manifest-authorized, scoped, idempotent, durable junction delivery."""

    def __init__(
        self,
        *,
        store: ObservationStore | None = None,
        state: JunctionStateStore,
        health_provider: HealthProvider | None = None,
        halted: bool = False,
    ) -> None:
        self._store = store if store is not None else get_default_store()
        self._state = state
        self._health = health_provider or _closed_health
        self._halted = halted
        self._manifests: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, SignalHandler] = {}

    # -- registry -------------------------------------------------------------

    def register_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Register one module manifest. Fail closed on any defect."""

        failures = validate_manifest(manifest)
        if failures:
            raise JunctionValidationError(failures)
        module_id = manifest["module_id"]
        self._manifests[module_id] = manifest
        self._state.audit(actor=module_id, action="MANIFEST_REGISTERED", reason=None)
        return manifest

    def revoke_manifest(self, module_id: str) -> bool:
        """Kill switch: revoking a manifest stops that module's traffic at the port."""

        existed = self._manifests.pop(module_id, None) is not None
        self._handlers.pop(module_id, None)
        self._state.audit(actor=module_id, action="MANIFEST_REVOKED", reason=None if existed else "NOT_REGISTERED")
        return existed

    def subscribe(self, module_id: str, handler: SignalHandler) -> None:
        """Attach a delivery handler for a registered module."""

        if module_id not in self._manifests:
            raise JunctionValidationError([f"module {module_id!r} has no registered manifest"])
        self._handlers[module_id] = handler

    def set_halt(self, halted: bool) -> None:
        """Global junction halt: a policy flag, not an autonomous transition."""

        self._halted = bool(halted)
        self._state.audit(actor="junction", action="HALT_SET", reason=str(self._halted))

    @property
    def store(self) -> ObservationStore:
        return self._store

    @property
    def state(self) -> JunctionStateStore:
        return self._state

    # -- health ----------------------------------------------------------------

    def _health_of(self, module_id: str) -> str:
        try:
            state = self._health(module_id)
        except Exception:
            return "closed"  # fail-closed: unreadable health is not open
        return state if state in HEALTH_STATES else "closed"

    # -- matching ----------------------------------------------------------------

    @staticmethod
    def subscription_matches(subscription: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
        """Scoped matching: exact entity_scope, or domain:<first event segment>.

        No wildcard exists, so fan-out is O(matching subscribers), never broadcast.
        """

        if subscription.get("event_type") != event.get("event_type"):
            return False
        signal_scope = (event.get("extensions") or {}).get("junction", {}).get("entity_scope")
        if subscription.get("entity_scope") == signal_scope:
            return True
        domain = str(event.get("event_type", "")).split(".")[0]
        return subscription.get("entity_scope") == f"domain:{domain}"

    # -- publish -------------------------------------------------------------------

    def publish(self, module_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """Authorize, append (idempotent), and deliver one junction signal.

        Every denial is recorded in the durable audit trail with a
        machine-readable reason. A denied signal is never appended and never
        delivered.
        """

        report: dict[str, Any] = {
            "module_id": module_id,
            "event_id": event.get("event_id") if isinstance(event, dict) else None,
            "authorized": False,
            "reason": None,
            "failures": [],
            "created": False,
            "deliveries": {},
            "candidate_work_hints": [],
        }

        def deny(reason: str, failures: list[str] | None = None) -> dict[str, Any]:
            report["reason"] = reason
            report["failures"] = failures or []
            self._state.audit(
                actor=module_id,
                action="PUBLISH_DENIED",
                reason=reason,
                detail={"event_id": report["event_id"], "failures": failures or []},
            )
            return report

        if self._halted:
            return deny("JUNCTION_HALTED")
        manifest = self._manifests.get(module_id)
        if manifest is None:
            return deny("MODULE_NOT_REGISTERED")
        failures = validate_signal(event)
        if failures:
            return deny("INVALID_SIGNAL", failures)

        event_type = event["event_type"]
        junction = event["extensions"]["junction"]

        # Emitter authenticity: the envelope's pipeline component must be the
        # authenticated module identity presenting the signal at the port.
        component = (event.get("pipeline") or {}).get("component")
        if component != module_id:
            return deny("EMITTER_IDENTITY_MISMATCH")

        # Health gate: the port's view of current health dominates any claimed
        # emitter_health. Non-open states only ever narrow communication.
        health = self._health_of(module_id)
        if health == "quarantined":
            return deny("EMITTER_QUARANTINED")
        if health == "closed" and event_type != HEARTBEAT_EVENT:
            return deny("EMITTER_CLOSED_HEARTBEAT_ONLY")
        if health == "restricted" and junction["consequence_class"] != "observation":
            return deny("EMITTER_RESTRICTED_OBSERVATION_ONLY")

        capabilities = manifest["capabilities"]
        if event_type not in capabilities["publishes"]:
            return deny("PUBLICATION_NOT_IN_MANIFEST")
        if junction["consequence_class"] == "action_request" and capabilities["can_propose_work"] is not True:
            return deny("WORK_PROPOSAL_NOT_PERMITTED")

        required_refs = manifest["evidence_policy"].get("require_source_refs_for") or []
        if event_type in required_refs:
            source = event.get("source") or {}
            evidence = event.get("evidence") or {}
            if not source.get("source_record_id") and not evidence.get("evidence_refs"):
                return deny("REQUIRED_PROVENANCE_ABSENT")

        payload = event.get("payload") or {}
        if len(canonical_json(payload).encode("utf-8")) > manifest["budgets"]["max_payload_bytes"]:
            return deny("PAYLOAD_BUDGET_EXCEEDED")

        if junction["ttl_hops"] <= 0:
            return deny("TTL_EXHAUSTED")

        # Cycle guard: a signal whose causation chain already contains the same
        # (module, event_type, entity_scope) triple is dropped as a cycle. The
        # event's own id is excluded so idempotent replay is never a "cycle".
        for prior in self._store.by_correlation(event["correlation_id"]):
            if prior.get("event_id") == event["event_id"]:
                continue
            prior_junction = (prior.get("extensions") or {}).get("junction") or {}
            triple = (
                (prior.get("pipeline") or {}).get("component"),
                prior.get("event_type"),
                prior_junction.get("entity_scope"),
            )
            if triple == (module_id, event_type, junction["entity_scope"]):
                return deny("CYCLE_DETECTED")

        # Emission budget: per-module per-minute. Exceeding it denies the
        # signal; the emitter's degradation itself is produced by the existing
        # health/governor components, not by this router.
        window = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        emitted = self._state.count_emission(module_id, window)
        if emitted > manifest["budgets"]["max_signals_per_minute"]:
            return deny("EMISSION_BUDGET_EXCEEDED")

        stored, created, _redaction = self._store.append(event)
        report["authorized"] = True
        report["reason"] = "AUTHORIZED"
        report["created"] = created

        positions = {stored_event["event_id"]: index for index, stored_event in enumerate(self._store.all())}
        position = positions[stored["event_id"]]
        for subscriber_id in sorted(self._handlers):
            if subscriber_id == module_id:
                continue  # a module never receives its own signal back
            subscriber_manifest = self._manifests.get(subscriber_id)
            if subscriber_manifest is None:
                continue
            outcome = self._deliver(subscriber_id, subscriber_manifest, stored)
            report["deliveries"][subscriber_id] = outcome
            if outcome in _CURSOR_ADVANCING:
                # Never skip backlog: advance only to beyond the furthest
                # position this subscriber has actually processed.
                self._state.set_cursor(
                    subscriber_id, max(self._state.get_cursor(subscriber_id), position + 1)
                )
            if outcome == "DELIVERED" and junction["consequence_class"] == "action_request":
                # Delivery can at most become a candidate work hint for the
                # existing engine bridge. It never creates execution.
                hint = {
                    "subscriber": subscriber_id,
                    "event_id": stored["event_id"],
                    "review_required": True,
                    "automatic_publication": False,
                    "knowledge_graph_mutation": False,
                    "taxonomy_mutation": False,
                }
                report["candidate_work_hints"].append(hint)
                self._state.audit(actor=subscriber_id, action="CANDIDATE_WORK_HINT", reason=None, detail=hint)
        return report

    # -- delivery ------------------------------------------------------------------

    def _deliver(
        self, subscriber_id: str, manifest: dict[str, Any], event: dict[str, Any]
    ) -> str:
        """Attempt one delivery. Never raises; every outcome is machine-readable."""

        event_id = event["event_id"]
        junction = event["extensions"]["junction"]
        dedupe = junction["dedupe_key"]

        if self._state.is_dead_lettered(subscriber_id, event_id):
            return "DEAD_LETTERED"  # excluded from further automatic delivery

        matched: Mapping[str, Any] | None = None
        for entry in manifest["capabilities"]["subscribes"]:
            if self.subscription_matches(entry, event):
                matched = entry
                break
        if matched is None:
            return "NOT_MATCHING"

        floor = matched.get("min_verification_state")
        if floor is not None:
            state_name = (event.get("evidence") or {}).get("verification_state") or "unknown"
            if VERIFICATION_STATE_RANK.get(state_name, 0) < VERIFICATION_STATE_RANK.get(floor, 0):
                return "BELOW_FLOOR"

        # A non-open subscriber narrows to buffering: ingress waits at the
        # cursor, nothing is delivered, no attempt is burned.
        if self._health_of(subscriber_id) in ("closed", "quarantined"):
            return "BUFFERED"

        if self._state.is_applied(subscriber_id, dedupe):
            return "DUPLICATE_SUPPRESSED"  # detected, counted, never re-applied

        attempts = self._state.get_attempts(subscriber_id, event_id)
        if attempts >= MAX_RETRY_ATTEMPTS:
            self._dead_letter(subscriber_id, event, attempts, "RETRY_BOUND_EXCEEDED")
            return "DEAD_LETTERED"

        try:
            self._handlers[subscriber_id](event)
        except Exception as exc:  # bounded retry: same event_id, same dedupe_key
            attempts = self._state.record_attempt(subscriber_id, event_id, type(exc).__name__)
            self._state.audit(
                actor=subscriber_id,
                action="DELIVERY_FAILED",
                reason=type(exc).__name__,
                detail={"event_id": event_id, "attempts": attempts},
            )
            if attempts >= MAX_RETRY_ATTEMPTS:
                self._dead_letter(subscriber_id, event, attempts, "RETRY_BOUND_EXCEEDED")
                return "DEAD_LETTERED"
            return "FAILED"

        self._state.mark_applied(subscriber_id, dedupe, event_id)
        return "DELIVERED"

    def _dead_letter(
        self, subscriber_id: str, event: dict[str, Any], attempts: int, reason: str
    ) -> None:
        self._state.dead_letter(subscriber=subscriber_id, event=event, attempts=attempts, reason=reason)
        self._state.audit(
            actor=subscriber_id,
            action="DEAD_LETTERED",
            reason=reason,
            detail={"event_id": event["event_id"], "attempts": attempts},
        )

    # -- recovery ---------------------------------------------------------------------

    def recover(self, subscriber_id: str) -> dict[str, Any]:
        """Replay from the subscriber's durable cursor, applying idempotently.

        A closed or quarantined subscriber's ingress stays buffered at the
        cursor: nothing is delivered, no attempt is burned, the cursor does not
        move. Replay stops at the first failed delivery so per-subscriber
        application order is preserved; the next recovery resumes there.
        """

        report: dict[str, Any] = {
            "subscriber": subscriber_id,
            "status": "recovered",
            "delivered": 0,
            "duplicates_suppressed": 0,
            "dead_lettered": 0,
            "buffered": 0,
            "skipped": 0,
            "cursor": self._state.get_cursor(subscriber_id),
        }
        manifest = self._manifests.get(subscriber_id)
        if manifest is None or subscriber_id not in self._handlers:
            report["status"] = "not_registered"
            return report
        if self._health_of(subscriber_id) in ("closed", "quarantined"):
            report["status"] = "buffered"
            return report

        events = self._store.all()
        cursor = report["cursor"]
        for position in range(cursor, len(events)):
            outcome = self._deliver(subscriber_id, manifest, events[position])
            if outcome in _CURSOR_ADVANCING:
                self._state.set_cursor(subscriber_id, position + 1)
                report["cursor"] = position + 1
                if outcome == "DELIVERED":
                    report["delivered"] += 1
                elif outcome == "DUPLICATE_SUPPRESSED":
                    report["duplicates_suppressed"] += 1
                elif outcome == "DEAD_LETTERED":
                    report["dead_lettered"] += 1
                else:
                    report["skipped"] += 1
            else:
                if outcome == "BUFFERED":
                    report["buffered"] += 1
                report["status"] = "stopped_at_failure" if outcome == "FAILED" else "buffered"
                break
        return report

    def dead_letters(self, subscriber_id: str | None = None) -> list[dict[str, Any]]:
        """Surfaced for review: full retained signals with reason codes."""

        return self._state.dead_letters(subscriber_id)
