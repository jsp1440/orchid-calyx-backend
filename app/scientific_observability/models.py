"""SCI-OBS-001 ScientificObservationEvent envelope and vocabulary.

An observation event is an append-only, vendor-neutral record that *something
was observed* about the scientific pipeline. It reuses the canonical kernel
identity (``app.kernel.identity``): ``event_id`` and ``correlation_id`` are
``OC:EVENT`` OCIDs and ``parent_event_id`` is a causation link, mirroring
``app.kernel.events.ScientificEvent``.

Observation events are strictly non-authoritative. Recording one NEVER
authorizes taxonomy publication, Knowledge Graph mutation, evidence promotion,
or scientific-conclusion publication.

Canonical contract: Orchid-Continuum-Brain
``contracts/scientific_observation_event_v1.schema.json`` (``sci-obs-event-v1``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from app.kernel.identity import OCID, OCIDFactory, OCIDKind

SCHEMA_VERSION = "sci-obs-event-v1"


class ObservationEventType(str, Enum):
    """Initial SCI-OBS event vocabulary (see vocabulary_v1 contract)."""

    HARVEST_RUN_STARTED = "harvest.run.started"
    HARVEST_RUN_COMPLETED = "harvest.run.completed"
    HARVEST_RUN_BLOCKED = "harvest.run.blocked"
    TAXONOMY_NAME_RESOLVED = "taxonomy.name.resolved"
    TAXONOMY_NAME_CONFLICT_DETECTED = "taxonomy.name.conflict_detected"
    EVIDENCE_ASSERTION_CREATED = "evidence.assertion.created"
    EVIDENCE_ASSERTION_VERIFIED = "evidence.assertion.verified"
    EVIDENCE_ASSERTION_CONFLICTED = "evidence.assertion.conflicted"
    EVIDENCE_ASSERTION_WITHHELD = "evidence.assertion.withheld"
    ARTIFACT_CREATED = "artifact.created"
    GRAPH_WRITE_REQUESTED = "graph.write.requested"
    GRAPH_WRITE_ACCEPTED = "graph.write.accepted"
    GRAPH_WRITE_REFUSED = "graph.write.refused"
    API_CONTRACT_PRODUCED = "api.contract.produced"
    API_CONTRACT_REFUSED = "api.contract.refused"
    FRONTEND_ASSERTION_RENDERED = "frontend.assertion.rendered"
    FRONTEND_ASSERTION_WITHHELD = "frontend.assertion.withheld"
    LOCALITY_ACCESS_DENIED = "locality.access.denied"
    AI_PROVIDER_USED = "ai.provider.used"
    AI_PROVIDER_FALLBACK = "ai.provider.fallback"
    AI_PROVIDER_BLOCKED = "ai.provider.blocked"
    MODULE_READINESS_CHANGED = "module.readiness.changed"


class SafeStatusState(str, Enum):
    """Distinct, never-collapsed operation states."""

    OK = "ok"
    BLOCKED = "blocked"
    WITHHELD = "withheld"
    REFUSED = "refused"
    DEGRADED = "degraded"
    ERROR = "error"
    UNKNOWN = "unknown"


class PipelineStage(str, Enum):
    SOURCE = "source"
    ACQUISITION = "acquisition"
    NORMALIZATION = "normalization"
    TAXONOMY_EVIDENCE_RESOLUTION = "taxonomy_evidence_resolution"
    ARTIFACT_GRAPH_BOUNDARY = "artifact_graph_boundary"
    API_PRODUCER = "api_producer"
    FRONTEND_CONSUMER = "frontend_consumer"


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REVIEW_REQUIRED = "review_required"
    CONFLICTED = "conflicted"
    WITHHELD = "withheld"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ConflictStatus(str, Enum):
    NONE_OBSERVED = "none_observed"
    COUNTEREVIDENCE_PRESENT = "counterevidence_present"
    CONTRADICTION = "contradiction"
    UNKNOWN = "unknown"


class ObservationValidationError(ValueError):
    """Raised when an observation envelope violates its contract."""


ANCHOR_SNIPPET_MAX = 300


@dataclass(frozen=True, slots=True)
class SafeStatus:
    status: SafeStatusState = SafeStatusState.OK
    reason_code: str | None = None
    blocker: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "blocker": self.blocker,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class ScientificObservationEvent:
    """Immutable observation envelope (``sci-obs-event-v1``).

    ``None`` on a field means UNKNOWN/ABSENT and must never be coerced to ``0``
    or ``False`` by any consumer.
    """

    event_type: ObservationEventType
    pipeline_stage: PipelineStage
    component: str
    safe_status: SafeStatus = field(default_factory=SafeStatus)
    event_id: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.EVENT))
    correlation_id: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.EVENT))
    parent_event_id: OCID | None = None
    sequence: int = 1
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    component_version: str | None = None
    mission_id: str | None = None
    run_id: str | None = None
    request_id: str | None = None
    # Structured attribute bags kept as plain dicts to match the JSON contract.
    taxon: Mapping[str, Any] | None = None
    subject: Mapping[str, Any] | None = None
    source: Mapping[str, Any] | None = None
    evidence: Mapping[str, Any] | None = None
    conflict: Mapping[str, Any] | None = None
    freshness: Mapping[str, Any] | None = None
    locality_classification: Mapping[str, Any] | None = None
    actor: Mapping[str, Any] | None = None
    consumer: Mapping[str, Any] | None = None
    ai: Mapping[str, Any] | None = None
    cost: Mapping[str, Any] | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_id.kind is not OCIDKind.EVENT:
            raise ObservationValidationError("event_id must be an OC:EVENT OCID")
        if self.correlation_id.kind is not OCIDKind.EVENT:
            raise ObservationValidationError("correlation_id must be an OC:EVENT OCID")
        if self.parent_event_id is not None:
            if self.parent_event_id.kind is not OCIDKind.EVENT:
                raise ObservationValidationError("parent_event_id must be an OC:EVENT OCID")
            if self.parent_event_id == self.event_id:
                raise ObservationValidationError("event cannot be its own parent")
        if self.sequence < 1:
            raise ObservationValidationError("sequence must be >= 1")
        for name, value in (("occurred_at", self.occurred_at), ("recorded_at", self.recorded_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ObservationValidationError(f"{name} must be timezone-aware")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(timezone.utc))
        object.__setattr__(self, "recorded_at", self.recorded_at.astimezone(timezone.utc))
        if self.recorded_at < self.occurred_at:
            raise ObservationValidationError("recorded_at must be >= occurred_at")
        anchor = (self.source or {}).get("anchor_snippet") if self.source else None
        if isinstance(anchor, str) and len(anchor) > ANCHOR_SNIPPET_MAX:
            raise ObservationValidationError(
                f"source.anchor_snippet exceeds {ANCHOR_SNIPPET_MAX} chars"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the canonical ``sci-obs-event-v1`` JSON shape."""

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "correlation_id": str(self.correlation_id),
            "parent_event_id": str(self.parent_event_id) if self.parent_event_id else None,
            "sequence": self.sequence,
            "mission_id": self.mission_id,
            "run_id": self.run_id,
            "request_id": self.request_id,
            "taxon": dict(self.taxon) if self.taxon else None,
            "subject": dict(self.subject) if self.subject else None,
            "source": dict(self.source) if self.source else None,
            "pipeline": {
                "stage": self.pipeline_stage.value,
                "component": self.component,
                "component_version": self.component_version,
            },
            "evidence": dict(self.evidence) if self.evidence else None,
            "conflict": dict(self.conflict) if self.conflict else None,
            "freshness": dict(self.freshness) if self.freshness else None,
            "locality_classification": dict(self.locality_classification)
            if self.locality_classification
            else None,
            "actor": dict(self.actor) if self.actor else None,
            "consumer": dict(self.consumer) if self.consumer else None,
            "safe_status": self.safe_status.to_dict(),
            "ai": dict(self.ai) if self.ai else None,
            "cost": dict(self.cost) if self.cost else None,
            "extensions": dict(self.extensions),
        }
        return payload
