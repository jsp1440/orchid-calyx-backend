"""SCI-OBS-001 — envelope, append-only store, redaction, anomaly, readiness tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.kernel.identity import OCIDFactory, OCIDKind
from app.scientific_observability.anomalies import AnomalyCode, detect, to_review_task_input
from app.scientific_observability.exporter import export, export_enabled, to_otel_span
from app.scientific_observability.models import (
    ObservationEventType,
    ObservationValidationError,
    PipelineStage,
    SafeStatus,
    SafeStatusState,
    ScientificObservationEvent,
)
from app.scientific_observability.readiness import (
    DimensionScore,
    DimensionState,
    build_readiness,
)
from app.scientific_observability.redaction import redact_event_dict
from app.scientific_observability.service import ObservabilityService
from app.scientific_observability.store import ObservationStore


def _event(**kw) -> ScientificObservationEvent:
    defaults = dict(
        event_type=ObservationEventType.EVIDENCE_ASSERTION_CREATED,
        pipeline_stage=PipelineStage.TAXONOMY_EVIDENCE_RESOLUTION,
        component="app/evidence_aggregation",
        safe_status=SafeStatus(status=SafeStatusState.OK, reason_code="ASSERTION_CREATED"),
    )
    defaults.update(kw)
    return ScientificObservationEvent(**defaults)


# --- schema / envelope validation -----------------------------------------

def test_envelope_serializes_to_contract_shape():
    ev = _event()
    d = ev.to_dict()
    assert d["schema_version"] == "sci-obs-event-v1"
    assert d["event_id"].startswith("OC:EVENT:")
    assert d["correlation_id"].startswith("OC:EVENT:")
    assert d["pipeline"]["stage"] == "taxonomy_evidence_resolution"
    assert d["safe_status"]["status"] == "ok"


def test_event_id_must_be_event_ocid():
    with pytest.raises(ObservationValidationError):
        _event(event_id=OCIDFactory.new(OCIDKind.ASSERTION))


def test_parent_cannot_equal_self_and_must_be_event_kind():
    eid = OCIDFactory.new(OCIDKind.EVENT)
    with pytest.raises(ObservationValidationError):
        _event(event_id=eid, parent_event_id=eid)
    with pytest.raises(ObservationValidationError):
        _event(parent_event_id=OCIDFactory.new(OCIDKind.PUBLICATION))


def test_timestamps_must_be_tz_aware_and_ordered():
    with pytest.raises(ObservationValidationError):
        _event(occurred_at=datetime(2026, 1, 1))  # naive
    later = datetime.now(timezone.utc)
    with pytest.raises(ObservationValidationError):
        _event(occurred_at=later, recorded_at=later - timedelta(seconds=5))


def test_anchor_snippet_length_bounded():
    with pytest.raises(ObservationValidationError):
        _event(source={"anchor_snippet": "x" * 301})


# --- append-only + idempotency --------------------------------------------

def test_append_is_idempotent_on_event_id():
    store = ObservationStore()
    ev = _event()
    stored1, created1, _ = store.append(ev.to_dict())
    stored2, created2, _ = store.append(ev.to_dict())
    assert created1 is True and created2 is False
    assert len(store) == 1
    assert stored1["event_id"] == stored2["event_id"]


def test_store_never_mutates_existing_event():
    store = ObservationStore()
    ev = _event()
    store.append(ev.to_dict())
    tampered = ev.to_dict()
    tampered["safe_status"]["status"] = "error"
    stored, created, _ = store.append(tampered)
    assert created is False
    assert stored["safe_status"]["status"] == "ok"  # original preserved


# --- trace/lineage reconstruction -----------------------------------------

def test_trace_reconstructs_in_sequence_order():
    store = ObservationStore()
    corr = OCIDFactory.new(OCIDKind.EVENT)
    e1 = _event(correlation_id=corr, event_type=ObservationEventType.HARVEST_RUN_STARTED,
                pipeline_stage=PipelineStage.ACQUISITION, component="app/harvest/manager.py", sequence=1)
    e2 = _event(correlation_id=corr, parent_event_id=e1.event_id, sequence=2)
    e3 = _event(correlation_id=corr, parent_event_id=e2.event_id, sequence=3)
    for e in (e3, e1, e2):  # insert out of order
        store.append(e.to_dict())
    trace = store.by_correlation(str(corr))
    assert [t["sequence"] for t in trace] == [1, 2, 3]
    assert trace[1]["parent_event_id"] == str(e1.event_id)


# --- redaction / secret scanning / protected locality ---------------------

def test_redaction_strips_protected_locality_and_secrets():
    raw = {
        "event_id": "OC:EVENT:" + "a" * 32,
        "extensions": {
            "latitude": 19.4,
            "longitude": -99.1,
            "exact_locality": "Sealed ravine",
            "country": "Mexico",          # generalized — kept
            "api_key": "sk-secret",
            "notes": "ok",
            "image_bytes": b"...",
        },
    }
    clean, report = redact_event_dict(raw)
    ext = clean["extensions"]
    assert "latitude" not in ext and "longitude" not in ext and "exact_locality" not in ext
    assert "image_bytes" not in ext
    assert ext["country"] == "Mexico"       # generalized location preserved
    assert ext["notes"] == "ok"
    assert ext["api_key"] == "__REDACTED__"
    assert report.protected_locality_detected is True
    assert report.secret_detected is True


def test_store_stores_only_redacted_copy():
    store = ObservationStore()
    ev = _event(extensions={"latitude": 1.23, "password": "hunter2"})
    stored, _, report = store.append(ev.to_dict())
    assert "latitude" not in stored["extensions"]
    assert stored["extensions"]["password"] == "__REDACTED__"
    assert report.protected_locality_detected is True


# --- anomalies -------------------------------------------------------------

def test_missing_provenance_and_anchor_anomalies():
    ev = _event(source=None)
    found = {a.code for a in detect(ev.to_dict())}
    assert AnomalyCode.MISSING_SOURCE_ANCHOR in found
    assert AnomalyCode.MISSING_PROVENANCE in found


def test_conflicting_evidence_preserved_as_anomaly():
    ev = _event(
        event_type=ObservationEventType.EVIDENCE_ASSERTION_CONFLICTED,
        conflict={"status": "counterevidence_present", "counterevidence_ids": ["c1"]},
        evidence={"verification_state": "conflicted", "confidence": None},
    )
    codes = {a.code for a in detect(ev.to_dict())}
    assert AnomalyCode.CONFLICTING_EVIDENCE in codes


def test_protected_locality_exposure_anomaly_from_redaction():
    store = ObservationStore()
    ev = _event(source={"source_id": "GBIF", "source_anchor_id": "a1"},
                extensions={"latitude": 1.0})
    stored, _, report = store.append(ev.to_dict())
    codes = {a.code for a in detect(stored, redaction=report)}
    assert AnomalyCode.PROTECTED_LOCALITY_EXPOSURE in codes


def test_duplicate_replay_anomaly():
    svc = ObservabilityService(ObservationStore())
    ev = _event(source={"source_id": "GBIF", "source_anchor_id": "a1"})
    svc.record(ev)
    result2 = svc.record(ev)
    assert result2.created is False
    assert any(a.code == AnomalyCode.DUPLICATE_REPLAY for a in result2.anomalies)


def test_ai_metadata_without_raw_prompt_and_untraceable_rule():
    ev = _event(
        event_type=ObservationEventType.AI_PROVIDER_USED,
        pipeline_stage=PipelineStage.NORMALIZATION,
        component="app/data_governance/model_gate.py",
        ai={"provider": "anthropic", "model": "x", "prompt_template_version": "tpl-3"},
        source=None,
        evidence={"verification_state": "unverified"},
    )
    d = ev.to_dict()
    assert "raw_prompt" not in d["ai"] and "prompt_text" not in d["ai"]
    codes = {a.code for a in detect(d)}
    assert AnomalyCode.UNTRACEABLE_AI_CONCLUSION in codes


# --- Verification Workbench binding idempotency ---------------------------

def test_review_binding_batch_key_is_stable_and_marks_no_mutation():
    ev = _event(source=None)
    anomaly = detect(ev.to_dict())[0]
    b1 = to_review_task_input(anomaly)
    b2 = to_review_task_input(anomaly)
    assert b1.batch_key == b2.batch_key
    assert b1.routing_outcome == "ROUTE_TO_VERIFICATION_WORKBENCH"
    assert b1.metadata["authoritative_state_mutated"] is False


def test_protected_locality_binding_is_embargoed():
    store = ObservationStore()
    ev = _event(source={"source_id": "s", "source_anchor_id": "a"}, extensions={"latitude": 1.0})
    stored, _, report = store.append(ev.to_dict())
    anomaly = [a for a in detect(stored, redaction=report)
               if a.code == AnomalyCode.PROTECTED_LOCALITY_EXPOSURE][0]
    binding = to_review_task_input(anomaly)
    assert binding.embargoed is True
    assert binding.display_policy == "SEALED_PARTNER"


# --- readiness: numerator/denominator, unknown != zero --------------------

def test_readiness_unknown_is_not_zero():
    unknown = DimensionScore(key="data_readiness", state=DimensionState.UNAVAILABLE,
                             numerator=None, denominator=None)
    assert unknown.score is None  # NOT 0.0


def test_readiness_numerator_denominator_calculation():
    dim = DimensionScore(key="data_readiness", state=DimensionState.CONDITIONAL,
                         numerator=3, denominator=8, missing_requirements=["pollinators"])
    assert dim.score == 0.375
    payload = build_readiness(
        {"data_readiness": dim},
        coverage_inputs={"taxonomy": True, "occurrences": True, "images": False},
    )
    assert payload["overall_state"] == "conditional"
    assert payload["publication_authority"] is False
    cov = payload["component_coverage"]
    assert cov["taxonomy"]["state"] == "available"
    assert cov["images"]["state"] == "unknown"       # queried & absent
    assert cov["pollinators"]["state"] == "unavailable"  # never queried, not zero


# --- exporter disabled by default -----------------------------------------

def test_exporter_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SCI_OBS_EXPORT_ENABLED", raising=False)
    assert export_enabled() is False
    assert export([_event().to_dict()]) == 0


def test_exporter_otel_shape_when_enabled(monkeypatch):
    monkeypatch.setenv("SCI_OBS_EXPORT_ENABLED", "true")
    captured: list = []
    n = export([_event().to_dict()], sink=captured.extend)
    assert n == 1
    span = captured[0]
    assert span["trace_id"].startswith("OC:EVENT:")
    assert span["span_id"].startswith("OC:EVENT:")
