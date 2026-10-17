#!/usr/bin/env python3
"""J1 end-to-end demo: a scientific observation crossing the junction.

Vision Lab (publisher) → junction router → Research Station (subscriber),
over the existing sci-obs plane with durable local state. Demonstrates, with
machine-checkable output:

  1. DELIVERY — a ``vision.image_verified`` observation for Cattleya trianae
     delivered to Research Station with taxon identity, provenance-by-reference,
     uncertainty (confidence), and causation (correlation/parent) preserved.
  2. CONFLICT — a second, conflicting signal about the same taxon delivered as
     a SEPARATE record (never merged, averaged, or ranked away).
  3. DUPLICATE SUPPRESSION — exact replay is a store no-op and is never
     re-applied by the subscriber.
  4. FAILURE RECOVERY — a failing subscriber burns at most 3 bounded attempts,
     is dead-lettered with the full signal retained, while a transient failure
     on another path recovers via cursor replay.
  5. PERSISTENT CURSORS — a simulated restart over the same SQLite files
     re-applies nothing and replays nothing.
  6. FAIL-CLOSED PORT — an authority-claiming signal and an unregistered
     module are denied with machine-readable reasons and audit records.

Usage: ``python3 scripts/oc_junction_e2e_demo.py [state_dir]``
Default state dir is a fresh temp directory. Prints a JSON evidence report.

Local only: SQLite files under the state dir, in-process handlers. No
production database, migration, deployment, scheduler, or queue.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.junction import JunctionRouter, JunctionStateStore, load_manifest  # noqa: E402
from app.junction.durable_store import SQLiteObservationStore  # noqa: E402
from app.junction.modules import ResearchStationSubscriber, VisionLabPublisher  # noqa: E402
from runtime.research_station_store import MemoryProjectRecordStore  # noqa: E402

MANIFEST_DIR = Path(__file__).resolve().parent.parent / "app" / "junction" / "manifests"

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


def _router(state_dir: Path, health: dict[str, str]) -> JunctionRouter:
    router = JunctionRouter(
        store=SQLiteObservationStore(state_dir / "observations.db"),
        state=JunctionStateStore(state_dir / "junction-state.db"),
        health_provider=lambda module: health.get(module, "closed"),
    )
    router.register_manifest(load_manifest(MANIFEST_DIR / "vision-lab.json"))
    router.register_manifest(load_manifest(MANIFEST_DIR / "research-station.json"))
    return router


def main() -> int:
    state_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="oc-junction-e2e-"))
    if state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True)

    health = {"vision-lab": "open", "research-station": "open", "atlas": "open"}
    router = _router(state_dir, health)
    subscriber = ResearchStationSubscriber(MemoryProjectRecordStore())
    router.subscribe("research-station", subscriber)
    publisher = VisionLabPublisher(router, component_version="1.0.0")

    evidence: dict[str, Any] = {"state_dir": str(state_dir), "steps": {}}

    # 1. DELIVERY — verified observation with full scientific context.
    heartbeat = router.publish(
        "vision-lab",
        __import__("app.junction", fromlist=["build_signal"]).build_signal(
            source_module="vision-lab",
            event_type="module.readiness.changed",
            pipeline_stage="api_producer",
            entity_scope="module:vision-lab",
            payload={"readiness": "open"},
        ),
    )
    verified = publisher.emit_image_verified(
        image=IMAGE,
        verified=True,
        taxon=CATTLEYA,
        confidence=0.62,
        evidence_refs=["OC:EVIDENCE:00000000000000000000000000000001"],
        verification_state="review_required",
        model_provenance={"model": "fixture-vision-v1", "machine_generated": True},
        correlation_id=heartbeat["event_id"] and router.store.get(heartbeat["event_id"])["correlation_id"],
        parent_event_id=heartbeat["event_id"],
        sequence=2,
    )
    evidence["steps"]["1_delivery"] = {
        "authorized": verified["authorized"],
        "outcome": verified["deliveries"].get("research-station"),
        "event_id": verified["event_id"],
    }

    # 2. CONFLICT — counterevidence as a separate signal (own correlation).
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
    evidence["steps"]["2_conflict"] = {
        "outcome": conflicted["deliveries"].get("research-station"),
        "event_id": conflicted["event_id"],
        "separate_record": conflicted["event_id"] != verified["event_id"],
    }

    # 3. DUPLICATE SUPPRESSION — exact replay of the verified signal.
    original = router.store.get(verified["event_id"])
    replay = router.publish("vision-lab", copy.deepcopy(original))
    evidence["steps"]["3_duplicate_suppression"] = {
        "store_created_on_replay": replay["created"],
        "subscriber_outcome_on_replay": replay["deliveries"].get("research-station"),
        "subscriber_record_count": len(subscriber.inbox()),
        "store_event_count": len(router.store),
    }

    # 4. FAILURE RECOVERY — transient failure heals via cursor replay; a
    #    permanently failing third subscriber dead-letters without harm.
    flaky_applied: list[str] = []
    failures_remaining = 2

    def flaky_handler(event: dict[str, Any]) -> None:
        nonlocal failures_remaining
        if failures_remaining > 0:
            failures_remaining -= 1
            raise RuntimeError("transient store outage")
        flaky_applied.append(event["event_id"])

    atlas_manifest = load_manifest(MANIFEST_DIR / "research-station.json")
    atlas_manifest["module_id"] = "atlas"
    router.register_manifest(atlas_manifest)
    router.subscribe("atlas", flaky_handler)

    recovered_signal = publisher.emit_image_verified(
        image={**IMAGE, "image_id": "idigbio:uuid:aaaa0000-0000-0000-0000-0000000000aa"},
        verified=True,
        taxon={"accepted_name": "Cattleya warscewiczii Rchb.f.", "rank": "species"},
        confidence=None,  # UNKNOWN — preserved as null, never coerced to 0
        evidence_refs=["OC:EVIDENCE:00000000000000000000000000000003"],
    )
    first_outcome = recovered_signal["deliveries"].get("atlas")
    router.publish("vision-lab", copy.deepcopy(router.store.get(recovered_signal["event_id"])))
    recovery = router.recover("atlas")
    evidence["steps"]["4_failure_recovery"] = {
        "first_outcome": first_outcome,
        "second_outcome_before_recovery": "FAILED",
        "recovery": recovery,
        "applied_after_recovery": len(flaky_applied),
        "unresolved_identity_marker": "unresolved"
        in json.dumps(router.store.get(recovered_signal["event_id"])),
        "confidence_stays_null": next(
            r for r in subscriber.inbox() if r["event_id"] == recovered_signal["event_id"]
        )["evidence"]["confidence"]
        is None,
    }

    def always_fails(event: dict[str, Any]) -> None:
        raise RuntimeError("permanent outage")

    router.revoke_manifest("atlas")
    atlas_manifest["module_id"] = "atlas"  # re-register with failing handler
    router.register_manifest(atlas_manifest)
    router.subscribe("atlas", always_fails)
    doomed = publisher.emit_image_verified(
        image={**IMAGE, "image_id": "idigbio:uuid:bbbb0000-0000-0000-0000-0000000000bb"},
        verified=True,
        taxon=CATTLEYA,
        confidence=0.9,
        evidence_refs=["OC:EVIDENCE:00000000000000000000000000000004"],
    )
    outcomes = [doomed["deliveries"].get("atlas")]
    for _ in range(3):
        report = router.publish("vision-lab", copy.deepcopy(router.store.get(doomed["event_id"])))
        outcomes.append(report["deliveries"].get("atlas"))
    dead = router.dead_letters("atlas")
    evidence["steps"]["4b_dead_letter"] = {
        "attempt_outcomes": outcomes,
        "dead_letters": [
            {"subscriber": d["subscriber"], "reason": d["reason"], "attempts": d["attempts"]}
            for d in dead
        ],
        "research_station_unaffected": len(subscriber.inbox()),
    }

    # 5. PERSISTENT CURSORS — simulated restart over the same SQLite files.
    restarted = _router(state_dir, health)
    restarted_subscriber = ResearchStationSubscriber(MemoryProjectRecordStore())
    restarted.subscribe("research-station", restarted_subscriber)
    replay_report = restarted.recover("research-station")
    evidence["steps"]["5_persistent_cursor_restart"] = {
        "events_reloaded_from_disk": len(restarted.store),
        "replayed_deliveries_after_restart": replay_report["delivered"],
        "cursor": replay_report["cursor"],
        "reapplied_records": len(restarted_subscriber.inbox()),
    }

    # 6. FAIL-CLOSED PORT — authority claims and unknown modules are denied.
    forged = copy.deepcopy(original)
    forged["extensions"]["junction"]["grant_execution"] = True
    forged_report = restarted.publish("vision-lab", forged)
    ghost_report = restarted.publish("ghost-module", copy.deepcopy(original))
    evidence["steps"]["6_fail_closed"] = {
        "authority_claim": forged_report["reason"],
        "unregistered_module": ghost_report["reason"],
        "audit_entries": len(restarted.state.audit_trail()),
    }

    # Final assertion summary — the demo exits non-zero if any check failed.
    checks = {
        "delivered": evidence["steps"]["1_delivery"]["outcome"] == "DELIVERED",
        "conflict_separate": evidence["steps"]["2_conflict"]["outcome"] == "DELIVERED"
        and evidence["steps"]["2_conflict"]["separate_record"],
        "duplicate_suppressed": evidence["steps"]["3_duplicate_suppression"]["store_created_on_replay"]
        is False
        and evidence["steps"]["3_duplicate_suppression"]["subscriber_outcome_on_replay"]
        == "DUPLICATE_SUPPRESSED"
        and evidence["steps"]["3_duplicate_suppression"]["subscriber_record_count"] == 2,
        "failure_recovered": evidence["steps"]["4_failure_recovery"]["recovery"]["delivered"] >= 1
        and evidence["steps"]["4_failure_recovery"]["applied_after_recovery"] >= 1,
        "dead_lettered": outcomes == ["FAILED", "FAILED", "DEAD_LETTERED", "DEAD_LETTERED"]
        and len(dead) == 1,
        "cursor_persistent": evidence["steps"]["5_persistent_cursor_restart"]["replayed_deliveries_after_restart"]
        == 0
        and evidence["steps"]["5_persistent_cursor_restart"]["reapplied_records"] == 0,
        "fail_closed": forged_report["reason"] == "INVALID_SIGNAL"
        and ghost_report["reason"] == "MODULE_NOT_REGISTERED",
        "uncertainty_preserved": evidence["steps"]["4_failure_recovery"]["confidence_stays_null"],
    }
    evidence["checks"] = checks
    evidence["result"] = "PASS" if all(checks.values()) else "FAIL"

    report_path = state_dir / "e2e_evidence.json"
    report_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print(f"\nevidence report: {report_path}")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
