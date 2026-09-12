"""SCI-OBS-001 — end-to-end vertical proof assertions for Laelia anceps."""

from __future__ import annotations

from app.scientific_observability.proof_laelia_anceps import run_proof


def test_vertical_proof_passes_every_stop_condition():
    report = run_proof()
    proof = report["proof"]

    assert report["FIXTURE"] is True
    assert proof["1_correlation_begins_at_acquisition"] is True
    assert proof["2_ids_propagate_each_stage"] is True
    assert len(proof["3_reconstructable_from_immutable_events"]) == 7
    assert proof["4_provenance_and_anchor_survive"] is True

    distinct = proof["5_absence_withholding_counterevidence_distinct"]
    assert distinct["confidence_unknown_preserved_as_null"] is True
    assert distinct["counterevidence_preserved"] is True
    assert distinct["withheld_distinct_from_error"] is True

    locality = proof["6_protected_locality_fail_closed"]
    assert locality["latitude_redacted"] is True
    assert locality["longitude_redacted"] is True
    assert locality["raw_prompt_redacted"] is True
    assert locality["exposure_anomaly_raised"] is True

    readiness = proof["7_mission_control_readiness"]
    assert readiness["publication_authority"] is False
    assert readiness["overall_state"] == "blocked"  # scientific_evidence dim is blocked
    # unknown is not zero: pollinators never queried -> unavailable
    assert readiness["component_coverage"]["pollinators"]["state"] == "unavailable"

    wb = proof["8_verification_workbench_anomaly"]
    assert wb["anomaly_count"] >= 1
    assert wb["handoff_idempotent"] is True
    assert wb["no_authoritative_mutation"] is True

    assert proof["9_frontend_consumer"]["trace_surface_event_present"] is True

    replay = report["replay_idempotency"]
    assert replay["events_recorded"] == replay["expected_unique_events"] == 7
    assert replay["all_replays_noop"] is True

    assert report["authority_boundary"]["mutates_authoritative_state"] is False
