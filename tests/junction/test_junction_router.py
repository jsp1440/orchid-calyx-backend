"""J1 junction router tests — oc-junction-profile-v1 production integration.

Covers the contract semantics the J0 conformance suite defined, now against
the durable router: manifest registration (fail-closed), scoped subscriptions,
idempotent delivery, persistent cursors, bounded retries, dead-letter
handling, fail-closed authorization, health gating, emission budgets, cycle
detection, and the Vision Lab → Research Station end-to-end scientific
observation path with taxon identity, provenance, uncertainty, and conflicting
evidence preserved.

All state is local (tmp_path SQLite files); no production database, no
network, no scheduler, no queue.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.junction import (
    JunctionRouter,
    JunctionStateStore,
    JunctionValidationError,
    build_signal,
    load_manifest,
    validate_manifest,
    validate_signal,
)
from app.junction.durable_store import SQLiteObservationStore
from app.junction.modules import ResearchStationSubscriber, VisionLabPublisher
from app.scientific_observability.store import ObservationStore
from runtime.research_station_store import MemoryProjectRecordStore

MANIFEST_DIR = Path(__file__).resolve().parents[2] / "app" / "junction" / "manifests"

CATTLEYA = {
    "accepted_name": "Cattleya trianae Linden & Rchb.f.",
    "canonical_taxon_id": "OC:TAXON:00000000000000000000000000c471ea",
    "rank": "species",
}

IMAGE = {
    "image_id": "idigbio:uuid:0d73e8c1-2f4b-4a5d-9b23-3c7e1a4b6f82",
    "content_hash": "a" * 64,
    "license_code": "CC-BY-4.0",
    "canonical_uri": "https://example.idigbio.org/records/0d73e8c1",
    "source_dataset": "iDigBio",
    "source_collection": "Field Museum Herbarium",
}


def _vision_manifest() -> dict[str, Any]:
    return json.loads((MANIFEST_DIR / "vision-lab.json").read_text(encoding="utf-8"))


def _research_manifest() -> dict[str, Any]:
    return json.loads((MANIFEST_DIR / "research-station.json").read_text(encoding="utf-8"))


def _make_router(
    tmp_path: Path,
    *,
    health: dict[str, str] | None = None,
) -> tuple[JunctionRouter, JunctionStateStore]:
    store = SQLiteObservationStore(tmp_path / "observations.db")
    state = JunctionStateStore(tmp_path / "junction-state.db")
    health_map = health if health is not None else {"vision-lab": "open", "research-station": "open"}
    router = JunctionRouter(
        store=store,
        state=state,
        health_provider=lambda module: health_map.get(module, "closed"),
    )
    router.register_manifest(_vision_manifest())
    router.register_manifest(_research_manifest())
    return router, state


def _wired_router(
    tmp_path: Path,
    *,
    health: dict[str, str] | None = None,
) -> tuple[JunctionRouter, VisionLabPublisher, ResearchStationSubscriber]:
    router, _state = _make_router(tmp_path, health=health)
    publisher = VisionLabPublisher(router, component_version="1.0.0")
    subscriber = ResearchStationSubscriber(MemoryProjectRecordStore())
    router.subscribe("research-station", subscriber)
    return router, publisher, subscriber


def _observation(
    *,
    module: str = "vision-lab",
    event_type: str = "vision.image_verified",
    entity_scope: str = "domain:vision",
    consequence_class: str = "observation",
    emitter_health: str = "open",
    payload: dict[str, Any] | None = None,
    taxon: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return build_signal(
        source_module=module,
        event_type=event_type,
        pipeline_stage="api_producer",
        entity_scope=entity_scope,
        consequence_class=consequence_class,
        emitter_health=emitter_health,
        payload=payload or {"image_id": "img-1"},
        taxon=taxon,
        evidence=evidence
        if evidence is not None
        else {"evidence_refs": ["OC:EVIDENCE:0000000000000000000000000000000f"]},
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# Manifests: registration is fail-closed
# ---------------------------------------------------------------------------


def test_shipped_manifests_are_valid():
    assert validate_manifest(_vision_manifest()) == []
    assert validate_manifest(_research_manifest()) == []


def test_manifest_rejects_execution_authority_claim():
    manifest = _vision_manifest()
    manifest["capabilities"]["execution_authority"] = "scoped"
    with pytest.raises(JunctionValidationError):
        JunctionRouter(store=ObservationStore(), state=JunctionStateStore(":memory:")).register_manifest(manifest)


def test_manifest_rejects_wildcard_subscription():
    manifest = _research_manifest()
    manifest["capabilities"]["subscribes"] = [
        {"event_type": "vision.image_verified", "entity_scope": "*"}
    ]
    failures = validate_manifest(manifest)
    assert any("wildcard" in failure for failure in failures)


def test_manifest_rejects_unknown_event_type():
    manifest = _vision_manifest()
    manifest["capabilities"]["publishes"] = ["taxonomy.rewrite.now"]
    assert validate_manifest(manifest) != []


def test_manifest_loads_from_disk():
    manifest = load_manifest(MANIFEST_DIR / "vision-lab.json")
    assert manifest["module_id"] == "vision-lab"


# ---------------------------------------------------------------------------
# Fail-closed authorization at the port
# ---------------------------------------------------------------------------


def test_unregistered_module_cannot_publish(tmp_path):
    router, _state = _make_router(tmp_path)
    report = router.publish("ghost-module", _observation(module="ghost-module"))
    assert report["authorized"] is False
    assert report["reason"] == "MODULE_NOT_REGISTERED"
    assert len(router.store) == 0


def test_event_type_outside_manifest_is_denied(tmp_path):
    router, _state = _make_router(tmp_path)
    report = router.publish("vision-lab", _observation(event_type="coverage.gap_detected"))
    assert report["authorized"] is False
    assert report["reason"] == "PUBLICATION_NOT_IN_MANIFEST"


def test_emitter_identity_must_match_presenting_module(tmp_path):
    router, _state = _make_router(tmp_path)
    event = _observation(module="vision-lab")
    report = router.publish("research-station", event)  # forged component
    assert report["authorized"] is False
    assert report["reason"] in {"EMITTER_IDENTITY_MISMATCH", "PUBLICATION_NOT_IN_MANIFEST"}


def test_forbidden_authority_keys_rejected_at_port(tmp_path):
    router, _state = _make_router(tmp_path)
    event = _observation()
    event["extensions"]["junction"]["grant_execution"] = True
    report = router.publish("vision-lab", event)
    assert report["authorized"] is False
    assert report["reason"] == "INVALID_SIGNAL"
    assert any("forbidden authority keys" in failure for failure in report["failures"])


def test_unresolved_identity_marker_enforced(tmp_path):
    router, _state = _make_router(tmp_path)
    event = _observation(taxon={"accepted_name": "Cattleya cf. trianae", "rank": "species"})
    # Builder must have set the marker; strip it to prove the port enforces it.
    assert event["extensions"]["junction"]["taxon_identity_state"] == "unresolved"
    del event["extensions"]["junction"]["taxon_identity_state"]
    report = router.publish("vision-lab", event)
    assert report["authorized"] is False
    assert any("taxon_identity_state" in failure for failure in report["failures"])


def test_missing_provenance_denied_when_manifest_requires_it(tmp_path):
    router, _state = _make_router(tmp_path)
    event = _observation(evidence={})  # no source.source_record_id, no evidence.evidence_refs
    report = router.publish("vision-lab", event)
    assert report["authorized"] is False
    assert report["reason"] == "REQUIRED_PROVENANCE_ABSENT"


def test_unknown_health_is_fail_closed(tmp_path):
    router, _state = _make_router(tmp_path, health={"vision-lab": "gibberish"})
    report = router.publish(
        "vision-lab",
        _observation(evidence={"evidence_refs": ["OC:EVIDENCE:00000000000000000000000000000001"]}),
    )
    assert report["authorized"] is False
    assert report["reason"] == "EMITTER_CLOSED_HEARTBEAT_ONLY"


def test_halt_flag_stops_all_publication(tmp_path):
    router, _state = _make_router(tmp_path)
    router.set_halt(True)
    report = router.publish("vision-lab", _observation())
    assert report["reason"] == "JUNCTION_HALTED"


def test_revoked_manifest_stops_traffic(tmp_path):
    router, _state = _make_router(tmp_path)
    router.revoke_manifest("vision-lab")
    report = router.publish("vision-lab", _observation())
    assert report["reason"] == "MODULE_NOT_REGISTERED"


# ---------------------------------------------------------------------------
# Health gating: non-open states only ever narrow communication
# ---------------------------------------------------------------------------


def test_restricted_emitter_drops_action_request_with_audit(tmp_path):
    router, state = _make_router(tmp_path, health={"vision-lab": "restricted"})
    manifest = _vision_manifest()
    manifest["capabilities"]["can_propose_work"] = True
    router.revoke_manifest("vision-lab")
    router.register_manifest(manifest)
    event = _observation(consequence_class="action_request")
    report = router.publish("vision-lab", event)
    assert report["authorized"] is False
    assert report["reason"] == "EMITTER_RESTRICTED_OBSERVATION_ONLY"
    assert any(entry["reason"] == "EMITTER_RESTRICTED_OBSERVATION_ONLY" for entry in state.audit_trail())


def test_closed_emitter_heartbeat_only(tmp_path):
    router, _state = _make_router(tmp_path, health={"vision-lab": "closed"})
    heartbeat = _observation(event_type="module.readiness.changed", entity_scope="module:vision-lab")
    normal = _observation()
    assert router.publish("vision-lab", heartbeat)["authorized"] is True
    denied = router.publish("vision-lab", normal)
    assert denied["authorized"] is False
    assert denied["reason"] == "EMITTER_CLOSED_HEARTBEAT_ONLY"


def test_quarantined_emitter_publishes_nothing(tmp_path):
    router, _state = _make_router(tmp_path, health={"vision-lab": "quarantined"})
    heartbeat = _observation(event_type="module.readiness.changed", entity_scope="module:vision-lab")
    report = router.publish("vision-lab", heartbeat)
    assert report["authorized"] is False
    assert report["reason"] == "EMITTER_QUARANTINED"


# ---------------------------------------------------------------------------
# Scoped subscriptions: no broadcast
# ---------------------------------------------------------------------------


def test_delivery_is_subscription_matched_only(tmp_path):
    router, _state = _make_router(tmp_path)
    received: list[str] = []
    router.subscribe("research-station", lambda event: received.append(event["event_id"]))

    other = _research_manifest()
    other["module_id"] = "atlas"
    other["capabilities"]["subscribes"] = [
        {"event_type": "vision.image_verified", "entity_scope": "genus:Cattleya", "min_verification_state": None}
    ]
    router.register_manifest(other)
    atlas_received: list[str] = []
    router.subscribe("atlas", lambda event: atlas_received.append(event["event_id"]))

    event = _observation(entity_scope="domain:vision")
    report = router.publish("vision-lab", event)
    assert report["deliveries"]["research-station"] == "DELIVERED"
    assert report["deliveries"]["atlas"] == "NOT_MATCHING"  # different scope: no broadcast
    assert received == [event["event_id"]]
    assert atlas_received == []


def test_min_verification_state_floor(tmp_path):
    router, _state = _make_router(tmp_path)
    manifest = _research_manifest()
    manifest["capabilities"]["subscribes"] = [
        {
            "event_type": "vision.image_verified",
            "entity_scope": "domain:vision",
            "min_verification_state": "verified",
        }
    ]
    router.revoke_manifest("research-station")
    router.register_manifest(manifest)
    received: list[str] = []
    router.subscribe("research-station", lambda event: received.append(event["event_id"]))

    unverified = _observation(evidence={"verification_state": "unverified", "evidence_refs": ["r1"]})
    report = router.publish("vision-lab", unverified)
    assert report["deliveries"]["research-station"] == "BELOW_FLOOR"
    assert received == []


# ---------------------------------------------------------------------------
# Idempotent delivery and duplicate suppression
# ---------------------------------------------------------------------------


def test_replayed_event_is_store_noop_and_never_reapplied(tmp_path):
    router, _state = _make_router(tmp_path)
    received: list[str] = []
    router.subscribe("research-station", lambda event: received.append(event["event_id"]))

    event = _observation()
    first = router.publish("vision-lab", event)
    second = router.publish("vision-lab", copy.deepcopy(event))
    third = router.publish("vision-lab", copy.deepcopy(event))

    assert first["created"] is True
    assert second["created"] is False and third["created"] is False
    assert second["deliveries"]["research-station"] == "DUPLICATE_SUPPRESSED"
    assert third["deliveries"]["research-station"] == "DUPLICATE_SUPPRESSED"
    assert received == [event["event_id"]]  # applied exactly once
    assert len(router.store) == 1


def test_same_dedupe_key_never_applied_twice_across_event_ids(tmp_path):
    router, _state = _make_router(tmp_path)
    received: list[str] = []
    router.subscribe("research-station", lambda event: received.append(event["event_id"]))

    event_a = _observation(payload={"image_id": "img-1"})
    event_b = _observation(payload={"image_id": "img-1"})  # same semantic content
    assert event_a["event_id"] != event_b["event_id"]
    assert (
        event_a["extensions"]["junction"]["dedupe_key"]
        == event_b["extensions"]["junction"]["dedupe_key"]
    )
    router.publish("vision-lab", event_a)
    report_b = router.publish("vision-lab", event_b)
    assert report_b["deliveries"]["research-station"] == "DUPLICATE_SUPPRESSED"
    assert received == [event_a["event_id"]]


# ---------------------------------------------------------------------------
# Bounded retries and dead-letter handling
# ---------------------------------------------------------------------------


def test_bounded_retry_then_dead_letter(tmp_path):
    router, _state = _make_router(tmp_path)
    calls: list[str] = []

    def always_fails(event: dict[str, Any]) -> None:
        calls.append(event["event_id"])
        raise RuntimeError("subscriber store unavailable")

    router.subscribe("research-station", always_fails)
    event = _observation()
    outcomes = [router.publish("vision-lab", copy.deepcopy(event))["deliveries"]["research-station"] for _ in range(4)]
    assert outcomes == ["FAILED", "FAILED", "DEAD_LETTERED", "DEAD_LETTERED"]
    assert len(calls) == 3  # bounded: retried at most 3 times, then excluded

    dead = router.dead_letters("research-station")
    assert len(dead) == 1
    assert dead[0]["reason"] == "RETRY_BOUND_EXCEEDED"
    assert dead[0]["attempts"] == 3
    assert dead[0]["event"]["event_id"] == event["event_id"]  # retained in full


def test_dead_lettering_one_subscriber_never_affects_others(tmp_path):
    router, _state = _make_router(
        tmp_path,
        health={"vision-lab": "open", "research-station": "open", "atlas": "open"},
    )

    def always_fails(event: dict[str, Any]) -> None:
        raise RuntimeError("down")

    router.subscribe("research-station", always_fails)
    other = _research_manifest()
    other["module_id"] = "atlas"
    router.register_manifest(other)
    received: list[str] = []
    router.subscribe("atlas", lambda event: received.append(event["event_id"]))

    event = _observation()
    for _ in range(3):
        router.publish("vision-lab", copy.deepcopy(event))
    assert received == [event["event_id"]]  # healthy subscriber applied exactly once
    assert [d["subscriber"] for d in router.dead_letters()] == ["research-station"]


def test_failure_recovery_via_cursor_replay(tmp_path):
    router, _state = _make_router(tmp_path)
    applied: list[str] = []
    failures_remaining = 2

    def flaky(event: dict[str, Any]) -> None:
        nonlocal failures_remaining
        if failures_remaining > 0:
            failures_remaining -= 1
            raise RuntimeError("transient")
        applied.append(event["event_id"])

    router.subscribe("research-station", flaky)
    event = _observation()
    assert router.publish("vision-lab", event)["deliveries"]["research-station"] == "FAILED"
    assert router.publish("vision-lab", copy.deepcopy(event))["deliveries"]["research-station"] == "FAILED"

    recovery = router.recover("research-station")
    assert recovery["status"] == "recovered"
    assert recovery["delivered"] == 1
    assert applied == [event["event_id"]]
    assert router.dead_letters("research-station") == []

    again = router.recover("research-station")  # replay is idempotent
    assert again["delivered"] == 0
    assert applied == [event["event_id"]]


# ---------------------------------------------------------------------------
# Persistent cursors across restart
# ---------------------------------------------------------------------------


def test_cursor_and_dedupe_survive_restart(tmp_path):
    router, _state = _make_router(tmp_path)
    subscriber = ResearchStationSubscriber(MemoryProjectRecordStore())
    router.subscribe("research-station", subscriber)
    publisher = VisionLabPublisher(router)
    report = publisher.emit_image_verified(
        image=IMAGE, verified=True, taxon=CATTLEYA, confidence=0.62,
        evidence_refs=["OC:EVIDENCE:00000000000000000000000000000001"],
    )
    assert report["deliveries"]["research-station"] == "DELIVERED"
    assert len(subscriber.inbox()) == 1

    # Simulate restart: brand-new router over the same durable files.
    router2, _state2 = _make_router(tmp_path)
    subscriber2 = ResearchStationSubscriber(MemoryProjectRecordStore())
    router2.subscribe("research-station", subscriber2)
    recovery = router2.recover("research-station")
    assert recovery["delivered"] == 0  # cursor already past the event
    assert subscriber2.inbox() == []  # nothing re-applied
    assert len(router2.store) == 1  # event journal survived the restart


def test_closed_subscriber_buffers_at_cursor_then_recovers(tmp_path):
    health = {"vision-lab": "open", "research-station": "closed"}
    router, _state = _make_router(tmp_path, health=health)
    received: list[str] = []
    router.subscribe("research-station", lambda event: received.append(event["event_id"]))

    event = _observation()
    report = router.publish("vision-lab", event)
    assert report["deliveries"]["research-station"] == "BUFFERED"
    assert received == []
    assert router.recover("research-station")["status"] == "buffered"

    health["research-station"] = "open"  # health transitions come from outside
    recovery = router.recover("research-station")
    assert recovery["delivered"] == 1
    assert received == [event["event_id"]]


# ---------------------------------------------------------------------------
# Budgets and cycles
# ---------------------------------------------------------------------------


def test_emission_budget_exceeded_denies(tmp_path):
    router, _state = _make_router(tmp_path)
    manifest = _vision_manifest()
    manifest["budgets"]["max_signals_per_minute"] = 2
    router.revoke_manifest("vision-lab")
    router.register_manifest(manifest)
    results = [router.publish("vision-lab", _observation(payload={"n": i}))["reason"] for i in range(3)]
    assert results == ["AUTHORIZED", "AUTHORIZED", "EMISSION_BUDGET_EXCEEDED"]


def test_cycle_in_causation_chain_is_dropped(tmp_path):
    router, _state = _make_router(tmp_path)
    first = _observation()
    correlation = first["correlation_id"]
    assert router.publish("vision-lab", first)["authorized"] is True
    # Same (module, event_type, entity_scope) triple re-entering the chain.
    cycle = _observation(correlation_id=correlation)
    report = router.publish("vision-lab", cycle)
    assert report["authorized"] is False
    assert report["reason"] == "CYCLE_DETECTED"
    assert len(router.store) == 1


def test_ttl_zero_is_dropped_never_delivered(tmp_path):
    router, _state = _make_router(tmp_path)
    received: list[str] = []
    router.subscribe("research-station", lambda event: received.append(event["event_id"]))
    event = build_signal(
        source_module="vision-lab",
        event_type="vision.image_verified",
        pipeline_stage="api_producer",
        entity_scope="domain:vision",
        payload={"image_id": "img-9"},
        evidence={"evidence_refs": ["OC:EVIDENCE:00000000000000000000000000000009"]},
        ttl_hops=0,
    )
    report = router.publish("vision-lab", event)
    assert report["reason"] == "TTL_EXHAUSTED"
    assert received == []


# ---------------------------------------------------------------------------
# action_request: candidate work hint only, never execution
# ---------------------------------------------------------------------------


def test_action_request_becomes_candidate_work_hint_only(tmp_path):
    router, _state = _make_router(tmp_path)
    vision = _vision_manifest()
    vision["capabilities"]["can_propose_work"] = True
    router.revoke_manifest("vision-lab")
    router.register_manifest(vision)
    received: list[dict[str, Any]] = []
    router.subscribe("research-station", received.append)

    event = _observation(consequence_class="action_request")
    report = router.publish("vision-lab", event)
    assert report["authorized"] is True
    hints = report["candidate_work_hints"]
    assert len(hints) == 1
    assert hints[0]["review_required"] is True
    assert hints[0]["automatic_publication"] is False
    assert hints[0]["knowledge_graph_mutation"] is False
    assert hints[0]["taxonomy_mutation"] is False


def test_action_request_denied_without_can_propose_work(tmp_path):
    router, _state = _make_router(tmp_path)
    event = _observation(consequence_class="action_request")
    report = router.publish("vision-lab", event)
    assert report["reason"] == "WORK_PROPOSAL_NOT_PERMITTED"


# ---------------------------------------------------------------------------
# End-to-end: Vision Lab → Research Station scientific observation
# ---------------------------------------------------------------------------


def test_end_to_end_vision_to_research_preserves_scientific_context(tmp_path):
    router, publisher, subscriber = _wired_router(tmp_path)

    # Causation anchor: Vision Lab heartbeat; the verification cites it as parent.
    heartbeat = _observation(event_type="module.readiness.changed", entity_scope="module:vision-lab")
    assert router.publish("vision-lab", heartbeat)["authorized"] is True

    verified = publisher.emit_image_verified(
        image=IMAGE,
        verified=True,
        taxon=CATTLEYA,
        confidence=0.62,
        evidence_refs=["OC:EVIDENCE:00000000000000000000000000000001"],
        verification_state="review_required",
        model_provenance={"model": "fixture-vision-v1", "machine_generated": True},
        correlation_id=heartbeat["correlation_id"],
        parent_event_id=heartbeat["event_id"],
        sequence=2,
    )
    assert verified["authorized"] is True
    assert verified["deliveries"]["research-station"] == "DELIVERED"

    # Conflicting evidence stays a separate signal, never merged or averaged.
    # It is its own observation (own correlation): re-emitting the same
    # (module, event_type, entity_scope) triple into the same causation chain
    # would be dropped as a cycle by the contract's loop guard.
    conflicted = publisher.emit_image_verified(
        image=IMAGE,
        verified=False,
        taxon=CATTLEYA,
        confidence=0.41,
        evidence_refs=["OC:EVIDENCE:00000000000000000000000000000002"],
        verification_state="conflicted",
        conflict={
            "status": "counterevidence_present",
            "counterevidence_ids": ["OC:EVIDENCE:00000000000000000000000000000002"],
        },
    )
    assert conflicted["deliveries"]["research-station"] == "DELIVERED"

    inbox = subscriber.inbox()
    assert len(inbox) == 2  # conflicting assertions remain separate records

    first = inbox[0]
    assert first["correlation_id"] == heartbeat["correlation_id"]  # causation preserved
    assert first["parent_event_id"] == heartbeat["event_id"]
    assert first["taxon"]["accepted_name"] == CATTLEYA["accepted_name"]
    assert first["taxon"]["canonical_taxon_id"] == CATTLEYA["canonical_taxon_id"]
    assert first["taxon"]["rank"] == "species"
    assert first["source"]["source_record_id"] == IMAGE["image_id"]
    assert first["source"]["reference"] == IMAGE["canonical_uri"]
    assert first["evidence"]["confidence"] == 0.62
    assert first["evidence"]["evidence_refs"] == ["OC:EVIDENCE:00000000000000000000000000000001"]
    assert first["source_module"] == "vision-lab"

    second = inbox[1]
    assert second["event_id"] != first["event_id"]  # disagreement is not merged
    assert second["correlation_id"] != first["correlation_id"]
    assert second["conflict"]["status"] == "counterevidence_present"
    assert second["evidence"]["verification_state"] == "conflicted"


def test_end_to_end_uncertainty_and_unresolved_identity_preserved(tmp_path):
    router, publisher, subscriber = _wired_router(tmp_path)

    report = publisher.emit_image_verified(
        image=IMAGE,
        verified=True,
        taxon={"accepted_name": "Cattleya cf. trianae", "rank": "species"},  # no canonical id
        confidence=None,  # UNKNOWN — must stay null, never 0
        evidence_refs=["OC:EVIDENCE:00000000000000000000000000000003"],
        verification_state="unverified",
    )
    assert report["deliveries"]["research-station"] == "DELIVERED"

    (record,) = subscriber.inbox()
    assert record["evidence"]["confidence"] is None  # null ≠ 0
    assert record["evidence"]["verification_state"] == "unverified"
    assert record["taxon"]["accepted_name"] == "Cattleya cf. trianae"
    assert record["taxon"].get("canonical_taxon_id") is None
    assert record["junction"]["taxon_identity_state"] == "unresolved"


def test_signal_validator_matches_builder_roundtrip():
    event = _observation(taxon=CATTLEYA)
    assert validate_signal(event) == []
    parsed = json.loads(json.dumps(event))  # survives JSON round-trip
    assert validate_signal(parsed) == []
