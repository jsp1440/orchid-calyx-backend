from runtime.calyx_certification.certification_snapshot import build_certification_snapshot


def test_ready_bundle_builds_certified_snapshot():
    result = build_certification_snapshot(
        {"artifact_hash": "a", "certified": True, "blockers": []},
        {"status": "ready", "blockers": []},
    )
    assert result["certified"] is True
    assert result["production_action_authorized"] is False


def test_blocker_prevents_certification():
    result = build_certification_snapshot(
        {"artifact_hash": "a", "certified": True, "blockers": []},
        {"status": "blocked", "blockers": ["live_preflight_missing"]},
    )
    assert result["certified"] is False
