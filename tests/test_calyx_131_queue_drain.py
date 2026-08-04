from runtime.calyx_certification.queue_drain import validate_queue_drain


def test_zero_jobs_is_drained():
    result = validate_queue_drain(
        {
            "queue_name": "calyx-certification",
            "pending_jobs": 0,
            "active_jobs": 0,
            "dead_letter_jobs": 0,
        }
    )
    assert result["queue_drained"] is True


def test_pending_job_blocks():
    result = validate_queue_drain(
        {
            "queue_name": "calyx-certification",
            "pending_jobs": 1,
            "active_jobs": 0,
            "dead_letter_jobs": 0,
        }
    )
    assert "queue_not_drained:pending_jobs" in result["blockers"]
