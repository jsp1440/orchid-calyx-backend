"""The provider-request reservoir.

Not a second scheduler. It holds no timers and starts nothing; the existing
controller calls into it. What it provides is memory: a denied or deferred
provider request stays with its reasoning, so a later pass can consolidate it
with an identical request, resolve it from evidence that has since landed, serve
it from cache, or batch it with compatible work — instead of re-deriving it and
re-denying it every cycle.

Grouping is by **capability**, not by provider. Two requests that want the same
capability are one question however they would be answered, and that is what
makes consolidation and batching correct rather than merely convenient.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .capabilities import is_provider_capability
from .intent import ProviderIntentRecord

RESERVOIR_SCHEMA = "oc.provider-reservoir.v1"


class ReservoirState(str, Enum):
    """Where a request has got to. Terminal states are the last three."""

    REQUESTED = "REQUESTED"
    PRESERVED = "PRESERVED"
    DEFERRED = "DEFERRED"
    AUTHORIZED = "AUTHORIZED"
    RESOLVED_DETERMINISTICALLY = "RESOLVED_DETERMINISTICALLY"
    EXECUTED = "EXECUTED"
    CACHED = "CACHED"


_TERMINAL = frozenset(
    {
        ReservoirState.RESOLVED_DETERMINISTICALLY,
        ReservoirState.EXECUTED,
        ReservoirState.CACHED,
    }
)


@dataclass
class ReservoirEntry:
    """One consolidated request and everything waiting on it."""

    key: str
    intent: ProviderIntentRecord
    state: ReservoirState = ReservoirState.REQUESTED
    affected_tasks: list[int] = field(default_factory=list)
    duplicate_count: int = 1
    result: Any = None
    resolution_note: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": RESERVOIR_SCHEMA,
            "key": self.key,
            "state": self.state.value,
            "capability": self.intent.capability,
            "blocking": self.intent.blocking,
            "affected_tasks": sorted(set(self.affected_tasks)),
            "duplicate_count": self.duplicate_count,
            "resolution_note": self.resolution_note,
            "intent": self.intent.to_record(),
        }


@dataclass(frozen=True)
class AuthorizationEnvelope:
    """A budget authorization that already exists.

    The reservoir never creates one of these. It is handed an envelope that some
    authorized path obtained, and its only power is to let compatible work ride
    inside it. ``capabilities`` is what the authorization actually covers, and
    ``remaining_slots`` is how much of it is unspent — piggybacking outside
    either is bypassing the budget control, not economising within it.
    """

    envelope_id: str
    capabilities: frozenset[str]
    remaining_slots: int

    def admits(self, capability: str) -> bool:
        return capability in self.capabilities and self.remaining_slots > 0


class ProviderRequestReservoir:
    """Consolidates, defers, re-evaluates and caches provider requests."""

    def __init__(self, *, cache: dict[str, Any] | None = None) -> None:
        self._entries: dict[str, ReservoirEntry] = {}
        self._cache: dict[str, Any] = dict(cache or {})

    # -- submission ----------------------------------------------------------

    def submit(self, intent: ProviderIntentRecord) -> ReservoirEntry:
        """Preserve a request, consolidating it with an identical one.

        A cached result short-circuits: the same question already has an answer,
        and buying it again is pure waste.
        """
        if not is_provider_capability(intent.capability):
            raise ValueError(
                f"capability {intent.capability!r} is deterministic; it belongs in the "
                "provider-free lane, not the reservoir"
            )
        key = intent.consolidation_key
        existing = self._entries.get(key)
        if existing is not None:
            existing.duplicate_count += 1
            existing.affected_tasks = sorted(
                set(existing.affected_tasks) | set(intent.affected_tasks)
            )
            # A later request that blocks upgrades a previously optional one;
            # the reverse must not downgrade a blocking request to optional.
            if intent.blocking and not existing.intent.blocking:
                existing.intent = intent
            return existing

        entry = ReservoirEntry(
            key=key,
            intent=intent,
            affected_tasks=sorted(set(intent.affected_tasks)),
        )
        if key in self._cache:
            entry.state = ReservoirState.CACHED
            entry.result = self._cache[key]
            entry.resolution_note = "served from cache; no provider call made"
        else:
            entry.state = ReservoirState.PRESERVED
        self._entries[key] = entry
        return entry

    # -- inspection ----------------------------------------------------------

    def entries(self) -> list[ReservoirEntry]:
        return list(self._entries.values())

    def get(self, key: str) -> ReservoirEntry | None:
        return self._entries.get(key)

    def pending(self) -> list[ReservoirEntry]:
        """Requests still wanting a provider, cheapest-to-resolve ordering aside."""
        return [e for e in self._entries.values() if e.state not in _TERMINAL]

    def blocking_tasks(self) -> set[int]:
        """Tasks that a still-unresolved *blocking* request holds up.

        A task appears here only when something it genuinely cannot proceed
        without is unresolved. Optional enrichment never puts a task in this set,
        which is what keeps the system work-conserving.
        """
        held: set[int] = set()
        for entry in self.pending():
            if entry.intent.blocking:
                held.update(entry.affected_tasks)
        return held

    # -- re-evaluation before spending ---------------------------------------

    def reevaluate(self, resolver: Callable[[ProviderIntentRecord], Any]) -> list[str]:
        """Try to answer preserved requests from local evidence before spending.

        ``resolver`` returns an answer when the repository can now supply the
        capability deterministically — because evidence landed, a fixture was
        written, or a cache filled since the request was made — and ``None``
        otherwise. This runs before authorization, so a request that has become
        answerable locally never reaches a provider at all.
        """
        resolved: list[str] = []
        for entry in list(self._entries.values()):
            if entry.state in _TERMINAL:
                continue
            answer = resolver(entry.intent)
            if answer is None:
                continue
            entry.state = ReservoirState.RESOLVED_DETERMINISTICALLY
            entry.result = answer
            entry.resolution_note = (
                "resolved without a provider on re-evaluation; local evidence now suffices"
            )
            self._cache[entry.key] = answer
            resolved.append(entry.key)
        return resolved

    # -- batching ------------------------------------------------------------

    def batches(self) -> dict[str, list[ReservoirEntry]]:
        """Group unresolved requests by capability.

        By capability rather than by provider: what makes two requests safe to
        answer together is that they want the same thing, not that the same
        vendor would answer them.
        """
        grouped: dict[str, list[ReservoirEntry]] = {}
        for entry in self.pending():
            grouped.setdefault(entry.intent.capability, []).append(entry)
        for items in grouped.values():
            items.sort(key=lambda e: e.key)
        return grouped

    def defer(self, key: str, note: str = "") -> ReservoirEntry:
        entry = self._entries[key]
        if entry.state in _TERMINAL:
            return entry
        entry.state = ReservoirState.DEFERRED
        entry.resolution_note = note or "deferred; no authorization available this pass"
        return entry

    # -- authorization and piggybacking --------------------------------------

    def piggyback(
        self, key: str, envelope: AuthorizationEnvelope
    ) -> tuple[bool, str]:
        """Ride an authorization that already exists, or decline and say why.

        This can only ever spend less than the caller already had permission to
        spend. It cannot create authorization, widen one, or exceed its capacity
        — an envelope that does not name this capability, or has no slot left, is
        a refusal. Anything else would be bypassing the budget control while
        appearing to economise.
        """
        entry = self._entries[key]
        if entry.state in _TERMINAL:
            return False, f"already {entry.state.value}"
        if not envelope.admits(entry.intent.capability):
            if entry.intent.capability not in envelope.capabilities:
                return False, (
                    f"capability {entry.intent.capability!r} is outside authorization "
                    f"{envelope.envelope_id}; piggybacking may not widen an envelope"
                )
            return False, (
                f"authorization {envelope.envelope_id} has no remaining slot; "
                "piggybacking may not exceed its capacity"
            )
        entry.state = ReservoirState.AUTHORIZED
        entry.resolution_note = f"piggybacked on existing authorization {envelope.envelope_id}"
        return True, entry.resolution_note

    # -- results -------------------------------------------------------------

    def record_result(self, key: str, result: Any) -> ReservoirEntry:
        """Record an answer, distribute it, and cache it against a repeat request."""
        entry = self._entries[key]
        entry.state = ReservoirState.EXECUTED
        entry.result = result
        self._cache[entry.key] = result
        if not entry.resolution_note:
            entry.resolution_note = "executed"
        return entry

    def results_for_task(self, task: int) -> dict[str, Any]:
        """Every answer available to one task, however it was obtained."""
        return {
            entry.intent.capability: entry.result
            for entry in self._entries.values()
            if task in entry.affected_tasks and entry.result is not None
        }

    def cache_snapshot(self) -> dict[str, Any]:
        return dict(self._cache)

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": RESERVOIR_SCHEMA,
            "entries": [e.to_record() for e in sorted(self._entries.values(), key=lambda e: e.key)],
            "pending_count": len(self.pending()),
            "blocking_tasks": sorted(self.blocking_tasks()),
        }
