from pathlib import Path

from app.calyx_orchestrator.service import (
    AUTONOMY_POLICY_CLASSES,
    EXECUTABLE_POLICY_CLASSES,
    MAX_RETRY_DELAY_SECONDS,
    retry_delay_seconds,
)


def test_retry_backoff_is_exponential_and_bounded():
    assert retry_delay_seconds(0) == 0
    assert retry_delay_seconds(1) == 60
    assert retry_delay_seconds(2) == 120
    assert retry_delay_seconds(3) == 240
    assert retry_delay_seconds(20) == MAX_RETRY_DELAY_SECONDS


def test_only_safe_policy_classes_are_worker_executable():
    assert AUTONOMY_POLICY_CLASSES == {
        "read_only_research",
        "candidate_generation",
        "review_required",
        "owner_only",
    }
    assert EXECUTABLE_POLICY_CLASSES == {"read_only_research", "candidate_generation"}
    assert "review_required" not in EXECUTABLE_POLICY_CLASSES
    assert "owner_only" not in EXECUTABLE_POLICY_CLASSES


def test_migration_is_additive_and_contains_retry_indexes():
    sql = Path("migrations/20260804_calyx_autonomy_004.sql").read_text(encoding="utf-8")
    upper = sql.upper()
    assert "ADD COLUMN IF NOT EXISTS POLICY_CLASS" in upper
    assert "ADD COLUMN IF NOT EXISTS NEXT_ATTEMPT_AT" in upper
    assert "ADD COLUMN IF NOT EXISTS DEADLINE_AT" in upper
    assert "IX_CALYX_JOBS_RETRY_READY" in upper
    for forbidden in ("DROP TABLE", "TRUNCATE", "DELETE FROM"):
        assert forbidden not in upper


def test_run_lifecycle_documents_prohibited_autonomous_boundaries():
    text = Path("docs/operations/CALYX-AUTONOMY-004-RUN-LIFECYCLE.md").read_text(
        encoding="utf-8"
    )
    assert "scientific publication" in text
    assert "merge pull requests" in text
    assert "Private chain-of-thought is not accepted or stored" in text
    assert "does not apply it to production" in text
