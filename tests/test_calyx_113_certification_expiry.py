from datetime import datetime, timezone

from runtime.calyx_certification.certification_expiry import (
    evaluate_certification_expiry,
)


def test_future_expiry_is_current():
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    result = evaluate_certification_expiry(
        {"expires_at": "2026-08-05T00:00:00Z"}, now
    )
    assert result["current"] is True


def test_past_expiry_blocks():
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    result = evaluate_certification_expiry(
        {"expires_at": "2026-08-03T00:00:00Z"}, now
    )
    assert "certification_expired" in result["blockers"]
