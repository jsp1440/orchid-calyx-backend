from runtime.calyx_certification.artifact_bundle import build_artifact_bundle


def test_complete_bundle_is_hashed_but_never_authorizes_production():
    result = build_artifact_bundle(
        run_id="run-1",
        commit_sha="abcdef123456",
        lane_results={"graph": {"certified": True}, "brain": {"certified": True}},
    )
    assert result["complete"] is True
    assert len(result["artifact_hash"]) == 64
    assert result["production_action_authorized"] is False


def test_failed_lane_blocks_bundle():
    result = build_artifact_bundle(
        run_id="run-2",
        commit_sha="abcdef123456",
        lane_results={"graph": {"certified": False}},
    )
    assert result["complete"] is False
    assert "graph:NOT_CERTIFIED" in result["blockers"]
