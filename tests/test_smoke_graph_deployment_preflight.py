from scripts.smoke_graph_deployment_preflight import evaluate_preflight


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
