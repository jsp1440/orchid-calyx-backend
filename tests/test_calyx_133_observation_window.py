from runtime.calyx_certification.observation_window import (
    validate_observation_window,
)


def test_stable_full_window_passes():
    result = validate_observation_window(
        {
            "started_at": "2026-08-04T00:00:00Z",
            "ended_at": "2026-08-04T00:10:00Z",
            "minimum_seconds": 300,
            "health_stable": True,
        }
    )
    assert result["observation_complete"] is True


def test_short_window_blocks():
    result = validate_observation_window(
        {
            "started_at": "2026-08-04T00:00:00Z",
            "ended_at": "2026-08-04T00:01:00Z",
            "minimum_seconds": 300,
            "health_stable": True,
        }
    )
    assert "observation_window_too_short" in result["blockers"]
