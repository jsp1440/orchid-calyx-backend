from runtime.calyx_certification.change_window_policy import evaluate_change_window


def test_accepts_time_inside_owner_approved_window():
    result = evaluate_change_window(
        {
            "window_start": "2026-08-04T00:00:00Z",
            "window_end": "2026-08-04T02:00:00Z",
            "evaluated_at": "2026-08-04T01:00:00Z",
            "owner_window_approved": True,
        }
    )
    assert result["within_approved_window"] is True


def test_rejects_time_outside_window():
    result = evaluate_change_window(
        {
            "window_start": "2026-08-04T00:00:00Z",
            "window_end": "2026-08-04T02:00:00Z",
            "evaluated_at": "2026-08-04T03:00:00Z",
            "owner_window_approved": True,
        }
    )
    assert "outside_approved_change_window" in result["blockers"]
