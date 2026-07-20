from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Protocol


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InterpretationRepository(Protocol):
    def packet_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None: ...
    def packets_by_ids(self, packet_ids: tuple[int, ...]) -> list[dict[str, Any]]: ...
    def save_packet(self, record: dict[str, Any]) -> dict[str, Any]: ...
    def interpretation_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None: ...
    def interpretation(self, interpretation_id: int) -> dict[str, Any] | None: ...
    def save_interpretation(self, record: dict[str, Any]) -> dict[str, Any]: ...
    def routing_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None: ...
    def routing_decision(self, routing_decision_id: int) -> dict[str, Any] | None: ...
    def save_routing_decision(self, record: dict[str, Any]) -> dict[str, Any]: ...
    def assertion_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None: ...
    def save_assertion(self, record: dict[str, Any]) -> dict[str, Any]: ...
    def save_correction(self, record: dict[str, Any]) -> dict[str, Any]: ...
    def audit(self, event_type: str, artifact_type: str, artifact_id: int, details: dict[str, Any], actor: str) -> None: ...
    def history(self, artifact_type: str, artifact_id: int) -> list[dict[str, Any]]: ...


class MemoryInterpretationRepository:
    """Deterministic repository used by domain tests; production uses PostgreSQL."""

    def __init__(self) -> None:
        self.packets: list[dict[str, Any]] = []
        self.interpretations: list[dict[str, Any]] = []
        self.routing_decisions: list[dict[str, Any]] = []
        self.assertions: list[dict[str, Any]] = []
        self.corrections: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._id = 1

    def _next_id(self) -> int:
        value = self._id
        self._id += 1
        return value

    @staticmethod
    def _find(records: list[dict[str, Any]], field: str, value: Any) -> dict[str, Any] | None:
        return next((deepcopy(record) for record in reversed(records) if record[field] == value), None)

    def packet_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self._find(self.packets, "fingerprint", fingerprint)

    def packets_by_ids(self, packet_ids: tuple[int, ...]) -> list[dict[str, Any]]:
        wanted = set(packet_ids)
        return [deepcopy(record) for record in self.packets if record["packet_id"] in wanted]

    def save_packet(self, record: dict[str, Any]) -> dict[str, Any]:
        saved = deepcopy(record)
        saved["packet_id"] = self._next_id()
        saved["version"] = 1 + max((x["version"] for x in self.packets if x["packet_key"] == saved["packet_key"]), default=0)
        saved["created_at"] = utc_now()
        self.packets.append(saved)
        return deepcopy(saved)

    def interpretation_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self._find(self.interpretations, "fingerprint", fingerprint)

    def interpretation(self, interpretation_id: int) -> dict[str, Any] | None:
        return self._find(self.interpretations, "interpretation_id", interpretation_id)

    def save_interpretation(self, record: dict[str, Any]) -> dict[str, Any]:
        saved = deepcopy(record)
        saved["interpretation_id"] = self._next_id()
        saved["version"] = 1 + max((x["version"] for x in self.interpretations if x["interpretation_key"] == saved["interpretation_key"]), default=0)
        saved["created_at"] = utc_now()
        self.interpretations.append(saved)
        return deepcopy(saved)

    def save_routing_decision(self, record: dict[str, Any]) -> dict[str, Any]:
        existing = self.routing_by_fingerprint(record["fingerprint"])
        if existing:
            return existing
        saved = deepcopy(record)
        saved["routing_decision_id"] = self._next_id()
        saved["created_at"] = utc_now()
        self.routing_decisions.append(saved)
        return deepcopy(saved)

    def routing_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self._find(self.routing_decisions, "fingerprint", fingerprint)

    def routing_decision(self, routing_decision_id: int) -> dict[str, Any] | None:
        return self._find(self.routing_decisions, "routing_decision_id", routing_decision_id)

    def assertion_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self._find(self.assertions, "fingerprint", fingerprint)

    def save_assertion(self, record: dict[str, Any]) -> dict[str, Any]:
        saved = deepcopy(record)
        saved["assertion_id"] = self._next_id()
        saved["version"] = 1 + max((x["version"] for x in self.assertions if x["assertion_key"] == saved["assertion_key"]), default=0)
        saved["created_at"] = utc_now()
        self.assertions.append(saved)
        return deepcopy(saved)

    def save_correction(self, record: dict[str, Any]) -> dict[str, Any]:
        saved = deepcopy(record)
        saved["correction_id"] = self._next_id()
        saved["version"] = 1 + max((x["version"] for x in self.corrections if x["correction_key"] == saved["correction_key"]), default=0)
        saved["created_at"] = utc_now()
        self.corrections.append(saved)
        return deepcopy(saved)

    def audit(self, event_type: str, artifact_type: str, artifact_id: int, details: dict[str, Any], actor: str = "system") -> None:
        self.events.append({"event_id": self._next_id(), "event_type": event_type, "artifact_type": artifact_type, "artifact_id": artifact_id, "actor": actor, "details": deepcopy(details), "created_at": utc_now()})

    def history(self, artifact_type: str, artifact_id: int) -> list[dict[str, Any]]:
        return [deepcopy(event) for event in self.events if event["artifact_type"] == artifact_type and event["artifact_id"] == artifact_id]
