from runtime.calyx_certification.status import build_certification_status


def test_status_is_ready_only_when_every_lane_is_green():
    result = build_certification_status(
        graph={"available": True, "ready": True},
        brain={"available": True, "full_chain_certified": True},
        autonomy={
            "available": True,
            "worker_enabled": True,
            "queue_depth": 2,
            "retry_count": 0,
            "dead_letter_count": 0,
            "stale_approval_count": 0,
        },
        monitoring={"available": True, "operational": True, "lag_seconds": 30},
    )
    assert result["certification_ready"] is True
    assert result["owner_authorization_required"] is True


def test_status_exposes_blockers_and_unavailable_dependencies():
    result = build_certification_status(
        graph={"available": True, "ready": False},
        brain={"available": False, "reason": "not deployed", "full_chain_certified": False},
        autonomy={"available": True, "worker_enabled": False, "dead_letter_count": 1},
        monitoring={"available": True, "operational": False},
    )
    assert result["certification_ready"] is False
    assert {item["code"] for item in result["blockers"]} >= {
        "GRAPH_NOT_READY",
        "BRAIN_NOT_CERTIFIED",
        "WORKER_NOT_ENABLED",
        "DEAD_LETTER_PRESENT",
        "MONITORING_NOT_OPERATIONAL",
    }
    assert result["unavailable_dependencies"] == [
        {"lane": "brain", "reason": "not deployed"}
    ]
