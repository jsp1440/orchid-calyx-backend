"""SCI-OBS-001 first vertical proof — *Laelia anceps*.

Runnable, fixture-driven end-to-end proof of the observability foundation. It
constructs a correlation trace for a *Laelia anceps* occurrence assertion,
records it through the append-only store, and returns a structured report
proving each stop condition.

FIXTURE NOTICE: every value here is a LABELED FIXTURE. Nothing produced by this
module is a scientific finding, a verified assertion, or an occurrence record.
Coordinates and protected-locality values are deliberately absent to prove
fail-closed redaction. Run with:  ``python -m app.scientific_observability.proof_laelia_anceps``
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.kernel.identity import OCIDFactory, OCIDKind
from app.review_tasks.models import ReviewTaskInput

from .anomalies import AnomalyCode
from .models import (
    ConflictStatus,
    ObservationEventType,
    PipelineStage,
    SafeStatus,
    SafeStatusState,
    ScientificObservationEvent,
    VerificationState,
)
from .readiness import DimensionScore, DimensionState, build_readiness
from .service import ObservabilityService
from .store import ObservationStore

ACCEPTED_NAME = "Laelia anceps"
FIXTURE = True


def _t(base: datetime, secs: int) -> datetime:
    return base + timedelta(seconds=secs)


def build_trace() -> list[ScientificObservationEvent]:
    """Build the fixture correlation trace across the implemented stages."""

    corr = OCIDFactory.new(OCIDKind.EVENT)
    t0 = datetime(2026, 8, 25, 18, 0, 0, tzinfo=timezone.utc)

    started = ScientificObservationEvent(
        event_type=ObservationEventType.HARVEST_RUN_STARTED,
        pipeline_stage=PipelineStage.ACQUISITION,
        component="app/harvest/manager.py",
        correlation_id=corr,
        parent_event_id=None,
        sequence=1,
        occurred_at=t0,
        recorded_at=t0,
        mission_id="SCI-OBS-001",
        run_id="laelia-anceps-gbif-fixture-run",
        taxon={"canonical_taxon_id": None, "accepted_name": ACCEPTED_NAME, "rank": "species"},
        actor={"actor_id": "harvest-worker", "actor_type": "harvester"},
        safe_status=SafeStatus(status=SafeStatusState.OK, reason_code="RUN_STARTED"),
    )

    resolved = ScientificObservationEvent(
        event_type=ObservationEventType.TAXONOMY_NAME_RESOLVED,
        pipeline_stage=PipelineStage.TAXONOMY_EVIDENCE_RESOLUTION,
        component="app/routers/taxonomy_release_intake.py",
        correlation_id=corr,
        parent_event_id=started.event_id,
        sequence=2,
        occurred_at=_t(t0, 5),
        recorded_at=_t(t0, 5),
        taxon={"canonical_taxon_id": "fixture-taxon-laelia-anceps", "accepted_name": ACCEPTED_NAME, "rank": "species"},
        source={"source_id": "GBIF", "dataset": "GBIF Backbone", "dataset_version": "fixture"},
        freshness={"state": "fresh", "as_of": "2026-08-25T00:00:00+00:00"},
        safe_status=SafeStatus(status=SafeStatusState.OK, reason_code="NAME_ACCEPTED"),
    )

    assertion = ScientificObservationEvent(
        event_type=ObservationEventType.EVIDENCE_ASSERTION_CREATED,
        pipeline_stage=PipelineStage.TAXONOMY_EVIDENCE_RESOLUTION,
        component="app/evidence_aggregation",
        correlation_id=corr,
        parent_event_id=resolved.event_id,
        sequence=3,
        occurred_at=_t(t0, 10),
        recorded_at=_t(t0, 10),
        taxon={"canonical_taxon_id": "fixture-taxon-laelia-anceps", "accepted_name": ACCEPTED_NAME, "rank": "species"},
        subject={"kind": "assertion", "subject_id": str(OCIDFactory.new(OCIDKind.ASSERTION))},
        source={
            "source_id": "GBIF",
            "source_record_id": "fixture-occurrence-1",
            "source_anchor_id": "fixture-anchor-1",
            "anchor_snippet": "epiphytic on oak, montane (locality generalized)",
            "content_hash": "fixture-hash-1",
            "dataset": "GBIF Occurrence",
            "dataset_version": "fixture",
        },
        evidence={"claim_class": "occurrence", "directness": "direct", "confidence": 0.62,
                  "verification_state": VerificationState.UNVERIFIED.value},
        conflict={"status": ConflictStatus.NONE_OBSERVED.value, "counterevidence_ids": []},
        locality_classification={"sensitivity": "RESEARCH_RESTRICTED", "disclosure": "GENERALIZED"},
        safe_status=SafeStatus(status=SafeStatusState.OK, reason_code="ASSERTION_CREATED"),
        # Defense-in-depth: a protected coordinate that MUST be redacted before storage.
        extensions={"latitude": 19.4326, "longitude": -99.1332, "raw_prompt": "should never persist"},
    )

    denied = ScientificObservationEvent(
        event_type=ObservationEventType.LOCALITY_ACCESS_DENIED,
        pipeline_stage=PipelineStage.TAXONOMY_EVIDENCE_RESOLUTION,
        component="app/data_governance/disclosure.py",
        correlation_id=corr,
        parent_event_id=assertion.event_id,
        sequence=4,
        occurred_at=_t(t0, 12),
        recorded_at=_t(t0, 12),
        taxon={"canonical_taxon_id": "fixture-taxon-laelia-anceps", "accepted_name": ACCEPTED_NAME},
        locality_classification={"sensitivity": "SENSITIVE_CONSERVATION", "disclosure": "DENY"},
        safe_status=SafeStatus(status=SafeStatusState.WITHHELD, reason_code="CAPABILITY_REQUIRED",
                               blocker="protected_locality"),
    )

    conflicted = ScientificObservationEvent(
        event_type=ObservationEventType.EVIDENCE_ASSERTION_CONFLICTED,
        pipeline_stage=PipelineStage.TAXONOMY_EVIDENCE_RESOLUTION,
        component="app/evidence_aggregation",
        correlation_id=corr,
        parent_event_id=assertion.event_id,
        sequence=5,
        occurred_at=_t(t0, 14),
        recorded_at=_t(t0, 14),
        taxon={"canonical_taxon_id": "fixture-taxon-laelia-anceps", "accepted_name": ACCEPTED_NAME},
        subject=assertion.subject,
        evidence={"claim_class": "occurrence", "directness": "direct", "confidence": None,
                  "verification_state": VerificationState.CONFLICTED.value},
        conflict={"status": ConflictStatus.COUNTEREVIDENCE_PRESENT.value, "counterevidence_ids": ["fixture-counter-1"]},
        safe_status=SafeStatus(status=SafeStatusState.OK, reason_code="COUNTEREVIDENCE_PRESENT"),
    )

    produced = ScientificObservationEvent(
        event_type=ObservationEventType.API_CONTRACT_PRODUCED,
        pipeline_stage=PipelineStage.API_PRODUCER,
        component="app/scientific_observability/routes.py",
        correlation_id=corr,
        parent_event_id=conflicted.event_id,
        sequence=6,
        occurred_at=_t(t0, 16),
        recorded_at=_t(t0, 16),
        consumer={"module": "verification_workbench", "surface": "trace"},
        safe_status=SafeStatus(status=SafeStatusState.OK, reason_code="CONTRACT_PRODUCED"),
    )

    withheld = ScientificObservationEvent(
        event_type=ObservationEventType.FRONTEND_ASSERTION_WITHHELD,
        pipeline_stage=PipelineStage.FRONTEND_CONSUMER,
        component="src/components/calyx/CalyxVerificationWorkbench.tsx",
        correlation_id=corr,
        parent_event_id=produced.event_id,
        sequence=7,
        occurred_at=_t(t0, 18),
        recorded_at=_t(t0, 18),
        consumer={"module": "verification_workbench", "surface": "trace"},
        evidence={"verification_state": VerificationState.REVIEW_REQUIRED.value},
        safe_status=SafeStatus(status=SafeStatusState.WITHHELD, reason_code="WITHHELD_BY_POLICY",
                               blocker="conflicted_evidence_pending_review"),
    )

    return [started, resolved, assertion, denied, conflicted, produced, withheld]


def _readiness_for_proof() -> dict[str, Any]:
    """Calculated readiness for the fixture: some inputs present, some absent."""

    dims = {
        "engineering_health": DimensionScore(
            key="engineering_health", state=DimensionState.AVAILABLE, numerator=1, denominator=1),
        "integration_health": DimensionScore(
            key="integration_health", state=DimensionState.CONDITIONAL, numerator=1, denominator=2,
            missing_requirements=["frontend_consumer_contract_pinned"]),
        "data_readiness": DimensionScore(
            key="data_readiness", state=DimensionState.CONDITIONAL, numerator=2, denominator=8,
            missing_requirements=["traits", "pollinators", "mycorrhizae", "literature", "images", "provenance"]),
        "scientific_evidence_readiness": DimensionScore(
            key="scientific_evidence_readiness", state=DimensionState.BLOCKED, numerator=0, denominator=1,
            upstream_blockers=["conflicting_evidence_pending_review"]),
        "product_workflow_readiness": DimensionScore(
            key="product_workflow_readiness", state=DimensionState.CONDITIONAL, numerator=2, denominator=3,
            missing_requirements=["frontend_trace_consumer"]),
        "freshness": DimensionScore(
            key="freshness", state=DimensionState.AVAILABLE, numerator=1, denominator=1),
    }
    return build_readiness(
        dims,
        coverage_inputs={"taxonomy": True, "occurrences": True, "provenance": True,
                         "traits": False, "images": False},
    )


def run_proof() -> dict[str, Any]:
    """Execute the vertical proof and return an evidence report."""

    store = ObservationStore()
    svc = ObservabilityService(store)
    events = build_trace()
    corr = str(events[0].correlation_id)

    results = [svc.record(e) for e in events]

    # Replay the whole trace to prove idempotency.
    replay = [svc.record(e) for e in events]

    trace = svc.reconstruct_trace(corr)

    # Collect anomalies + workbench bindings.
    all_anomalies: list[dict[str, Any]] = []
    bindings: list[ReviewTaskInput] = []
    for r in results:
        all_anomalies.extend(a.to_dict() for a in r.anomalies)
        bindings.extend(r.review_bindings)

    # Distinct-state preservation checks.
    statuses = {e["safe_status"]["status"] for e in trace}
    confidences = [(e.get("evidence") or {}).get("confidence") for e in trace if e.get("evidence")]

    # Protected-locality redaction check on the stored assertion event.
    assertion_event = next(e for e in trace if e["event_type"] == "evidence.assertion.created")
    ext = assertion_event.get("extensions") or {}

    report = {
        "FIXTURE": FIXTURE,
        "fixture_notice": "Labeled fixture. Not a scientific finding or occurrence record.",
        "accepted_name": ACCEPTED_NAME,
        "correlation_id": corr,
        "proof": {
            "1_correlation_begins_at_acquisition": trace[0]["event_type"] == "harvest.run.started"
            and trace[0]["parent_event_id"] is None,
            "2_ids_propagate_each_stage": (
                # Every event shares one correlation id, and every non-root
                # event's parent resolves to a real earlier event in the trace
                # (a connected lineage DAG, not necessarily a single chain).
                len({e["correlation_id"] for e in trace}) == 1
                and trace[0]["parent_event_id"] is None
                and all(
                    e["parent_event_id"] in {p["event_id"] for p in trace}
                    for e in trace[1:]
                )
            ),
            "3_reconstructable_from_immutable_events": [e["event_id"] for e in trace],
            "4_provenance_and_anchor_survive": assertion_event["source"]["source_anchor_id"] == "fixture-anchor-1"
            and assertion_event["source"]["content_hash"] == "fixture-hash-1",
            "5_absence_withholding_counterevidence_distinct": {
                "safe_statuses_present": sorted(statuses),
                "confidence_unknown_preserved_as_null": None in confidences,
                "counterevidence_preserved": any(
                    (e.get("conflict") or {}).get("status") == "counterevidence_present" for e in trace
                ),
                "withheld_distinct_from_error": "withheld" in statuses,
            },
            "6_protected_locality_fail_closed": {
                "latitude_redacted": "latitude" not in ext,
                "longitude_redacted": "longitude" not in ext,
                "raw_prompt_redacted": ext.get("raw_prompt") == "__REDACTED__",
                "exposure_anomaly_raised": any(
                    a["code"] == AnomalyCode.PROTECTED_LOCALITY_EXPOSURE for a in all_anomalies
                ),
            },
            "7_mission_control_readiness": _readiness_for_proof(),
            "8_verification_workbench_anomaly": {
                "anomaly_count": len(all_anomalies),
                "bindings": [
                    {"review_type": b.review_type, "batch_key": b.batch_key,
                     "risk_class": b.risk_class, "embargoed": b.embargoed}
                    for b in bindings
                ],
                "handoff_idempotent": len({b.batch_key for b in bindings}) == len(bindings),
                "no_authoritative_mutation": all(
                    b.metadata["authoritative_state_mutated"] is False for b in bindings
                ),
            },
            "9_frontend_consumer": {
                "trace_surface_event_present": any(
                    e["event_type"] in ("frontend.assertion.rendered", "frontend.assertion.withheld")
                    for e in trace
                ),
                "next_bounded_lane": "SCI-OBS-005 frontend reviewer-safe trace surface",
            },
        },
        "replay_idempotency": {
            "events_recorded": len(store),
            "expected_unique_events": len(events),
            "all_replays_noop": all(r.created is False for r in replay),
        },
        "authority_boundary": {
            "publishes": False,
            "mutates_authoritative_state": False,
            "grants_scientific_authority": False,
        },
    }
    return report


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(run_proof(), indent=2, default=str))
