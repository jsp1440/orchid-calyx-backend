from runtime.calyx_certification.emergency_halt import evaluate_emergency_halt


def test_accepts_complete_emergency_halt_record():
    result = evaluate_emergency_halt(
        {
            "signals": ["database_unhealthy"],
            "halt_requested": True,
            "reason": "database verification failed",
            "owner_notified": True,
            "automated_release_disabled": True,
        }
    )
    assert result["halt_required"] is True
    assert result["halt_record_valid"] is True


def test_rejects_halt_without_owner_notification():
    result = evaluate_emergency_halt(
        {
            "signals": [],
            "halt_requested": True,
            "reason": "manual halt",
            "owner_notified": False,
            "automated_release_disabled": True,
        }
    )
    assert "owner_notification_missing" in result["blockers"]
