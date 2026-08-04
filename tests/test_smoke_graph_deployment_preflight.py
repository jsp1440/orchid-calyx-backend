import inspect

from scripts.smoke_graph_deployment_preflight import (
    build_evidence,
    evaluate_preflight,
    main,
)


def test_evaluate_preflight_ready():
    ready, blockers = evaluate_preflight(
        {"ready_for_live_resumable_dry_run": True, "blockers": []}
    )
    assert ready is True
    assert blockers == []


def test_evaluate_preflight_preserves_blockers():
    ready, blockers = evaluate_preflight(
        {
            "ready_for_live_resumable_dry_run": False,
            "blockers": ["persistent_mount_not_configured"],
        }
    )
    assert ready is False
    assert blockers == ["persistent_mount_not_configured"]


def test_evaluate_preflight_fails_closed_without_blocker():
    ready, blockers = evaluate_preflight(
        {"ready_for_live_resumable_dry_run": False, "blockers": []}
    )
    assert ready is False
    assert blockers == ["preflight_not_ready_without_reported_blocker"]


def test_build_evidence_records_safe_stop_and_hash():
    evidence = build_evidence(
        report={"ready_for_live_resumable_dry_run": True, "blockers": []},
        ready=True,
        blockers=[],
        health_status=200,
        owner_session_status=200,
        preflight_status=200,
    )
    assert evidence["ready_for_live_resumable_dry_run"] is True
    assert evidence["dry_run_started"] is False
    assert evidence["production_action_authorized"] is False
    assert len(evidence["artifact_hash"]) == 64


def test_build_evidence_deduplicates_blockers():
    evidence = build_evidence(
        report={},
        ready=False,
        blockers=["blocked", "blocked"],
        health_status=200,
        owner_session_status=401,
        preflight_status=0,
    )
    assert evidence["blockers"] == ["blocked"]


def test_main_uses_bearer_session_token_endpoint():
    source = inspect.getsource(main)
    assert '"/api/mission-control/owner/session-token"' in source
    assert '"/api/mission-control/owner/session"' not in source
