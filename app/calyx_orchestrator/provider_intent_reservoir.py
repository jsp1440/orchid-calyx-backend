"""Deterministic metacognitive provider-intent reservoir.

This module records *why* an external capability is wanted before budget
admission.  It performs no provider calls and grants no authority.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from hashlib import sha256


@dataclass(frozen=True)
class ProviderIntent:
    objective: str
    capability: str
    deterministic_insufficiency: str
    provider: str | None = None
    alternatives: tuple[str, ...] = ()
    expected_gain: str = ""
    estimated_marginal_cost_usd: float | None = None
    urgency: str = "normal"
    blocking: bool = False
    deterministic_fallback: str = "defer enrichment; continue independent deterministic work"
    affected_tasks: tuple[str, ...] = ()
    sensitive_locality: bool = False
    contains_secret: bool = False

    def validate(self) -> None:
        required = {
            "objective": self.objective,
            "capability": self.capability,
            "deterministic_insufficiency": self.deterministic_insufficiency,
            "expected_gain": self.expected_gain,
            "deterministic_fallback": self.deterministic_fallback,
        }
        missing = [key for key, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError("provider intent missing: " + ", ".join(missing))
        if self.sensitive_locality:
            raise ValueError("provider intent must not contain sensitive locality")
        if self.contains_secret:
            raise ValueError("provider intent must not contain secrets")
        if self.estimated_marginal_cost_usd is not None and self.estimated_marginal_cost_usd < 0:
            raise ValueError("estimated marginal cost must be non-negative")

    @property
    def dedupe_key(self) -> str:
        material = "|".join(
            (self.capability.strip().lower(), self.objective.strip().lower(),
             self.deterministic_insufficiency.strip().lower())
        )
        return sha256(material.encode("utf-8")).hexdigest()


@dataclass
class ReservoirEntry:
    intent: ProviderIntent
    state: str = "PRESERVED"
    duplicate_count: int = 1
    task_refs: set[str] = field(default_factory=set)
    cached_result_ref: str | None = None

    def public_record(self) -> dict:
        record = asdict(self.intent)
        record["dedupe_key"] = self.intent.dedupe_key
        record["state"] = self.state
        record["duplicate_count"] = self.duplicate_count
        record["task_refs"] = sorted(self.task_refs)
        record["cached_result_ref"] = self.cached_result_ref
        return record


class ProviderRequestReservoir:
    """In-memory deterministic policy core; persistence adapters may wrap it."""

    def __init__(self) -> None:
        self._entries: dict[str, ReservoirEntry] = {}
        self._cache: dict[str, str] = {}

    def preserve(self, intent: ProviderIntent) -> ReservoirEntry:
        intent.validate()
        key = intent.dedupe_key
        if key in self._cache:
            return ReservoirEntry(
                intent=intent, state="CACHED", task_refs=set(intent.affected_tasks),
                cached_result_ref=self._cache[key],
            )
        current = self._entries.get(key)
        if current:
            current.duplicate_count += 1
            current.task_refs.update(intent.affected_tasks)
            current.state = "DEDUPLICATED"
            return current
        entry = ReservoirEntry(intent=intent, task_refs=set(intent.affected_tasks))
        self._entries[key] = entry
        return entry

    def mark_provider_free_resolved(self, key: str, result_ref: str) -> None:
        entry = self._entries[key]
        entry.state = "PROVIDER_FREE_RESOLVED"
        entry.cached_result_ref = result_ref
        self._cache[key] = result_ref

    def authorize(self, keys: Iterable[str], *, authorization_envelope: bool) -> list[ReservoirEntry]:
        """Authorization is fail-closed; batching/piggyback cannot create authority."""
        if not authorization_envelope:
            raise PermissionError("provider authorization envelope required")
        result = []
        for key in keys:
            entry = self._entries[key]
            if entry.state in {"PROVIDER_FREE_RESOLVED", "CACHED"}:
                continue
            entry.state = "AUTHORIZED"
            result.append(entry)
        return result

    def batches(self) -> dict[str, list[ReservoirEntry]]:
        """Group unresolved work by capability, never merely by provider."""
        grouped: dict[str, list[ReservoirEntry]] = {}
        for entry in self._entries.values():
            if entry.state in {"PROVIDER_FREE_RESOLVED", "CACHED"}:
                continue
            grouped.setdefault(entry.intent.capability, []).append(entry)
        return grouped

    def deny_without_blocking_program(self, key: str) -> ReservoirEntry:
        entry = self._entries[key]
        entry.state = "DEFERRED"
        return entry

    def records(self) -> list[dict]:
        return [self._entries[key].public_record() for key in sorted(self._entries)]
