"""Durable retry backoff and dead-letter follow-up records for program jobs.

A program job whose executor attempt fails is returned to ``queued`` with its
lease released immediately, and a structured backoff record is written to the
job's ``evidence_json``. The persisted scheduler reads that record and keeps
the job out of the runnable set until the backoff has elapsed, so one failing
job neither holds a lease until expiry nor consumes scheduler capacity that
other jobs could use.

The record lives in an existing column so no schema migration is required.
It is replaced by the authoritative evidence when the job later completes.

Everything here is pure, deterministic and provider-free.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

RETRY_BACKOFF_SCHEMA = "calyx.program-job-retry-backoff.v1"
DEAD_LETTER_REPAIR_SCHEMA = "calyx.program-dead-letter-repair.v1"
DEAD_LETTER_OWNER_ACTION_SCHEMA = "calyx.program-dead-letter-owner-action.v1"
OWNER_ACTION_BLOCKER = "OWNER_ACTION_REQUIRED:DEAD_LETTER"
RETRY_BACKOFF_BASE_SECONDS = 60
RETRY_BACKOFF_MAX_SECONDS = 3600
DEAD_LETTER_BLOCKER = "PROGRAM_JOB_ATTEMPTS_EXHAUSTED"
DEAD_LETTER_REPAIR_JOB_KEY_PREFIX = "dead-letter-repair:"
MAX_RECORDED_FAILURES = 10
MAX_ERROR_CODE_CHARS = 512


def retry_backoff_seconds(attempt_count: int) -> int:
    """Exponential backoff after ``attempt_count`` failed attempts, capped."""
    if attempt_count < 1:
        return 0
    exponent = min(attempt_count - 1, 32)
    return min(RETRY_BACKOFF_BASE_SECONDS * (2**exponent), RETRY_BACKOFF_MAX_SECONDS)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _loads(evidence_json: str | None) -> Any:
    if not evidence_json:
        return None
    try:
        return json.loads(evidence_json)
    except (TypeError, ValueError):
        return None


def prior_failures(evidence_json: str | None) -> list[dict[str, Any]]:
    """Failure history carried by an existing backoff record, if any."""
    record = _loads(evidence_json)
    if not isinstance(record, dict) or record.get("schema") != RETRY_BACKOFF_SCHEMA:
        return []
    failures = record.get("failures")
    if not isinstance(failures, list):
        return []
    return [item for item in failures if isinstance(item, dict)]


def build_retry_backoff_record(
    *,
    attempt_count: int,
    error_code: str,
    exception_type: str,
    now: datetime,
    previous_evidence_json: str | None = None,
) -> dict[str, Any]:
    delay = retry_backoff_seconds(attempt_count)
    failed_at = _as_utc(now)
    failures = prior_failures(previous_evidence_json)
    failures.append(
        {
            "attempt": attempt_count,
            "error_code": str(error_code)[:MAX_ERROR_CODE_CHARS],
            "exception_type": str(exception_type)[:120],
            "failed_at": failed_at.isoformat(),
        }
    )
    return {
        "schema": RETRY_BACKOFF_SCHEMA,
        "attempt_count": attempt_count,
        "backoff_seconds": delay,
        "not_before": (failed_at + timedelta(seconds=delay)).isoformat(),
        "failures": failures[-MAX_RECORDED_FAILURES:],
    }


def retry_not_before(evidence_json: str | None) -> datetime | None:
    """Return the backoff deadline recorded on a queued job, or ``None``.

    Only a record carrying this module's schema counts. Anything else, including
    unparseable text, is not a backoff record and leaves the job schedulable as
    it was before this module existed.
    """
    record = _loads(evidence_json)
    if not isinstance(record, dict) or record.get("schema") != RETRY_BACKOFF_SCHEMA:
        return None
    raw = record.get("not_before")
    if not isinstance(raw, str):
        return None
    try:
        return _as_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


def in_retry_backoff(status: str, evidence_json: str | None, now: datetime) -> bool:
    if status != "queued":
        return False
    deadline = retry_not_before(evidence_json)
    return deadline is not None and deadline > _as_utc(now)


def dead_letter_repair_job_key(program_job_id: str) -> str:
    return f"{DEAD_LETTER_REPAIR_JOB_KEY_PREFIX}{program_job_id}"


def dead_letter_repair_fingerprint(program_job_id: str) -> str:
    return hashlib.sha256(
        f"{DEAD_LETTER_REPAIR_SCHEMA}|{program_job_id}".encode()
    ).hexdigest()


def is_owner_action_record(job_key: str, input_json: str | None) -> bool:
    """Whether a program job row is a dead-letter follow-up record."""
    if job_key.startswith(DEAD_LETTER_REPAIR_JOB_KEY_PREFIX):
        return True
    record = _loads(input_json)
    return isinstance(record, dict) and record.get("record_kind") == "owner_action"
