"""Recording service: validate → redact → append (idempotent) → detect anomalies.

This is the single entry point instrumentation call sites use. It ties the
envelope, the append-only store, the redaction pass, and the deterministic
anomaly rules together, and produces Verification-Workbench bindings for any
anomaly found. It performs no authoritative mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.review_tasks.models import ReviewTaskInput

from . import anomalies as anomaly_rules
from .anomalies import Anomaly
from .models import ScientificObservationEvent
from .store import ObservationStore, get_default_store


@dataclass(slots=True)
class RecordResult:
    event: dict[str, Any]
    created: bool
    anomalies: list[Anomaly] = field(default_factory=list)
    review_bindings: list[ReviewTaskInput] = field(default_factory=list)
    redaction: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "created": self.created,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "review_bindings": [
                {
                    "review_type": b.review_type,
                    "risk_class": b.risk_class,
                    "batch_key": b.batch_key,
                    "embargoed": b.embargoed,
                    "display_policy": b.display_policy,
                }
                for b in self.review_bindings
            ],
            "redaction": self.redaction,
        }


class ObservabilityService:
    def __init__(self, store: ObservationStore | None = None) -> None:
        # An empty ObservationStore is falsy (it defines __len__), so an
        # explicit ``is None`` check is required — ``store or ...`` would
        # silently discard a freshly-constructed empty store.
        self._store = store if store is not None else get_default_store()

    @property
    def store(self) -> ObservationStore:
        return self._store

    def record(
        self,
        event: ScientificObservationEvent,
        *,
        prior_readiness_state: str | None = None,
    ) -> RecordResult:
        """Record one observation event and evaluate anomalies.

        Idempotent: replaying an event id returns the stored event with
        ``created=False`` and raises a ``DUPLICATE_REPLAY`` anomaly.
        """

        serialized = event.to_dict()
        stored, created, redaction = self._store.append(serialized)
        found = anomaly_rules.detect(
            stored,
            redaction=redaction,
            replayed=not created,
            prior_readiness_state=prior_readiness_state,
        )
        bindings = [anomaly_rules.to_review_task_input(a) for a in found]
        return RecordResult(
            event=stored,
            created=created,
            anomalies=found,
            review_bindings=bindings,
            redaction=redaction.to_dict(),
        )

    def reconstruct_trace(self, correlation_id: str) -> list[dict[str, Any]]:
        return self._store.by_correlation(correlation_id)
