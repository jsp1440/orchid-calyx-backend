from runtime.calyx_certification.cross_lane_integration import (
    REQUIRED_LANES,
    validate_cross_lane_integration,
)


def test_all_lanes_integrate_with_unique_artifacts():
    evidence = {
        "lanes": {
            lane: {"certified": True, "artifact_hash": f"hash-{index}"}
            for index, lane in enumerate(REQUIRED_LANES)
        }
    }
    result = validate_cross_lane_integration(evidence)
    assert result["integrated"] is True
    assert result["owner_authorization_required"] is True


def test_duplicate_or_missing_artifacts_block_integration():
    evidence = {
        "lanes": {
            lane: {"certified": True, "artifact_hash": "same-hash"}
            for lane in REQUIRED_LANES
        }
    }
    result = validate_cross_lane_integration(evidence)
    assert result["integrated"] is False
    assert "ARTIFACT_HASH_CARDINALITY_MISMATCH" in result["blockers"]
