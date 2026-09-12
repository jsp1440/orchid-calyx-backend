"""Deterministic, fail-closed anomaly rules for observation events.

Rules are deterministic and run before any adaptive/ML behavior. A detected
anomaly is bound to the EXISTING Verification Workbench review boundary by
producing an ``app.review_tasks.models.ReviewTaskInput`` — no parallel review
system is created. Anomalies never mutate authoritative scientific state; they
only open a review item.

The ``batch_key`` on each binding is the idempotency key
``sci-obs:{correlation_id}:{event_id}:{code}`` so re-processing the same event
never opens duplicate review tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.review_tasks.models import ReviewTaskInput

from .redaction import RedactionReport


class AnomalyCode:
    MISSING_SOURCE_ANCHOR = "MISSING_SOURCE_ANCHOR"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    PROTECTED_LOCALITY_EXPOSURE = "PROTECTED_LOCALITY_EXPOSURE"
    UNTRACEABLE_AI_CONCLUSION = "UNTRACEABLE_AI_CONCLUSION"
    PRODUCER_CONSUMER_MISMATCH = "PRODUCER_CONSUMER_MISMATCH"
    HARVEST_ABNORMAL_YIELD = "HARVEST_ABNORMAL_YIELD"
    STALE_TAXONOMY = "STALE_TAXONOMY"
    SUSPICIOUS_COORDINATES = "SUSPICIOUS_COORDINATES"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    DUPLICATE_REPLAY = "DUPLICATE_REPLAY"
    READINESS_REGRESSION = "READINESS_REGRESSION"


_RISK_CLASS = {
    AnomalyCode.PROTECTED_LOCALITY_EXPOSURE: "CRITICAL",
    AnomalyCode.UNTRACEABLE_AI_CONCLUSION: "HIGH",
    AnomalyCode.MISSING_PROVENANCE: "HIGH",
    AnomalyCode.MISSING_SOURCE_ANCHOR: "HIGH",
    AnomalyCode.CONFLICTING_EVIDENCE: "MEDIUM",
    AnomalyCode.PRODUCER_CONSUMER_MISMATCH: "MEDIUM",
    AnomalyCode.STALE_TAXONOMY: "MEDIUM",
    AnomalyCode.SUSPICIOUS_COORDINATES: "MEDIUM",
    AnomalyCode.HARVEST_ABNORMAL_YIELD: "LOW",
    AnomalyCode.READINESS_REGRESSION: "MEDIUM",
    AnomalyCode.DUPLICATE_REPLAY: "LOW",
}


@dataclass(slots=True)
class Anomaly:
    code: str
    reason: str
    correlation_id: str
    event_id: str
    risk_class: str = "MEDIUM"
    baseline_absent: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "reason": self.reason,
            "correlation_id": self.correlation_id,
            "event_id": self.event_id,
            "risk_class": self.risk_class,
            "baseline_absent": self.baseline_absent,
            "details": dict(self.details),
        }


def _anomaly(code: str, reason: str, event: dict[str, Any], **details: Any) -> Anomaly:
    return Anomaly(
        code=code,
        reason=reason,
        correlation_id=event.get("correlation_id", ""),
        event_id=event.get("event_id", ""),
        risk_class=_RISK_CLASS.get(code, "MEDIUM"),
        baseline_absent=bool(details.pop("baseline_absent", False)),
        details=details,
    )


def detect(
    event: dict[str, Any],
    *,
    redaction: RedactionReport | None = None,
    replayed: bool = False,
    prior_readiness_state: str | None = None,
) -> list[Anomaly]:
    """Return every deterministic anomaly implied by a single event.

    ``replayed`` is ``True`` when the store reported the event already existed
    (duplicate/replay). ``prior_readiness_state`` enables readiness-regression
    detection for ``module.readiness.changed`` events.
    """

    found: list[Anomaly] = []
    etype = event.get("event_type", "")
    source = event.get("source") or {}
    evidence = event.get("evidence") or {}
    conflict = event.get("conflict") or {}
    freshness = event.get("freshness") or {}
    safe = event.get("safe_status") or {}
    reason_code = safe.get("reason_code")

    if replayed:
        found.append(_anomaly(AnomalyCode.DUPLICATE_REPLAY, "Event id was replayed", event))

    if redaction is not None and redaction.protected_locality_detected:
        found.append(
            _anomaly(
                AnomalyCode.PROTECTED_LOCALITY_EXPOSURE,
                "Protected-locality fields were present in telemetry and redacted",
                event,
                redacted_paths=list(redaction.protected_locality_paths),
            )
        )

    if etype == "evidence.assertion.created":
        if not source.get("source_anchor_id"):
            found.append(
                _anomaly(AnomalyCode.MISSING_SOURCE_ANCHOR, "Assertion created without a source anchor", event)
            )
        if not source.get("source_id") and not source.get("source_record_id"):
            found.append(
                _anomaly(AnomalyCode.MISSING_PROVENANCE, "Assertion created without provenance", event)
            )

    # An AI-derived conclusion with no source anchor and no lineage is untraceable.
    if event.get("ai") and not source.get("source_anchor_id") and not event.get("parent_event_id"):
        if evidence.get("verification_state") not in {"withheld", "review_required"}:
            found.append(
                _anomaly(
                    AnomalyCode.UNTRACEABLE_AI_CONCLUSION,
                    "AI participated but the conclusion has no anchor or upstream lineage",
                    event,
                )
            )

    if etype == "api.contract.refused" and reason_code in {"PRODUCER_CONSUMER_MISMATCH", "CONTRACT_MISMATCH"}:
        found.append(
            _anomaly(AnomalyCode.PRODUCER_CONSUMER_MISMATCH, "Producer/consumer contract mismatch", event)
        )

    if etype == "harvest.run.completed" and reason_code in {"YIELD_ABNORMAL_HIGH", "YIELD_ABNORMAL_LOW"}:
        found.append(
            _anomaly(
                AnomalyCode.HARVEST_ABNORMAL_YIELD,
                f"Harvest yield flagged {reason_code}",
                event,
                baseline_absent=reason_code == "BASELINE_ABSENT" or bool((event.get("extensions") or {}).get("baseline_absent")),
            )
        )
    if reason_code == "BASELINE_ABSENT":
        # Not itself an anomaly; recorded so downstream knows the baseline gap.
        found.append(
            _anomaly(
                AnomalyCode.HARVEST_ABNORMAL_YIELD,
                "Harvest baseline absent until enough runs exist",
                event,
                baseline_absent=True,
            )
        )

    if freshness.get("state") == "stale" or reason_code == "STALE_TAXONOMY":
        found.append(_anomaly(AnomalyCode.STALE_TAXONOMY, "Stale taxonomy/dataset input", event))

    if reason_code == "SUSPICIOUS_COORDINATES" or (event.get("extensions") or {}).get("coordinate_valid") is False:
        found.append(
            _anomaly(AnomalyCode.SUSPICIOUS_COORDINATES, "Invalid or suspicious coordinates/elevation", event)
        )

    if conflict.get("status") in {"counterevidence_present", "contradiction"} or etype == "evidence.assertion.conflicted":
        found.append(
            _anomaly(
                AnomalyCode.CONFLICTING_EVIDENCE,
                "Conflicting/counterevidence present; preserved for review",
                event,
                counterevidence_ids=list(conflict.get("counterevidence_ids") or []),
            )
        )

    if etype == "module.readiness.changed":
        if reason_code == "READINESS_REGRESSED" or (
            prior_readiness_state == "ready" and (event.get("extensions") or {}).get("readiness_state") == "blocked"
        ):
            found.append(_anomaly(AnomalyCode.READINESS_REGRESSION, "Module readiness regressed", event))

    return found


def to_review_task_input(anomaly: Anomaly, *, display_policy: str = "INTERNAL_RESEARCH_ONLY") -> ReviewTaskInput:
    """Bind an anomaly to the canonical Verification Workbench review boundary.

    The ``batch_key`` is a stable idempotency key so the same anomaly on the
    same event never opens two review tasks.
    """

    batch_key = f"sci-obs:{anomaly.correlation_id}:{anomaly.event_id}:{anomaly.code}"
    embargoed = anomaly.code == AnomalyCode.PROTECTED_LOCALITY_EXPOSURE
    return ReviewTaskInput(
        orchestration_id=anomaly.correlation_id or "sci-obs",
        review_type=f"SCI_OBS_ANOMALY:{anomaly.code}",
        risk_class=anomaly.risk_class,
        routing_outcome="ROUTE_TO_VERIFICATION_WORKBENCH",
        required_capability="scientific_review",
        priority=90 if anomaly.risk_class in {"CRITICAL", "HIGH"} else 50,
        scientific_impact_score=0.9 if anomaly.risk_class == "CRITICAL" else 0.5,
        consensus_required=1,
        batch_key=batch_key,
        display_policy="SEALED_PARTNER" if embargoed else display_policy,
        embargoed=embargoed,
        metadata={
            "sci_obs_anomaly": anomaly.to_dict(),
            "authoritative_state_mutated": False,
        },
    )
