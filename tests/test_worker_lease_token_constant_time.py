"""Worker lease tokens are compared in constant time; a cleared or empty token never matches.

A claimed job's lease token is a bearer secret: whoever presents it may advance,
dry-run or complete the job. Three checks still compared it with ``!=``:

* ``EngineeringCompletionScheduler.advance_claimed`` (app/calyx_engineering)
* ``execute_deterministic_dry_run`` (app/calyx_orchestrator/dry_run_service.py)
* ``LeaseExecutionBridge._require_live_lease`` (app/calyx_orchestrator/execution_bridge.py)

Each now goes through ``app.security.credentials_match``. A wrong, non-ASCII or empty
presented token, and a stored token that is ``None`` or empty, raise the existing
stale-lease ``PermissionError`` (never a ``TypeError``). The source guard for these
files lives in ``tests/test_non_ascii_credentials.py``. Jobs are synthetic stand-ins.
"""

from __future__ import annotations

import hmac
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.calyx_engineering.completion_scheduler import (
    ENGINEERING_COMPLETION_JOB_TYPE,
    EngineeringCompletionScheduler,
)
from app.calyx_orchestrator import dry_run_service
from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge
from app.calyx_orchestrator.models import utcnow
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramJob

WORKER = "worker-1"
TOKEN = "11111111-2222-3333-4444-555555555555"

# (stored token, presented token) pairs that must never match.
MISMATCHES = [
    pytest.param(TOKEN, "00000000-0000-0000-0000-000000000000", id="same-length-wrong"),
    pytest.param(TOKEN, TOKEN[:-1], id="prefix"),
    pytest.param(TOKEN, "é" * len(TOKEN), id="non-ascii"),
    pytest.param(TOKEN, TOKEN + "é", id="valid-plus-non-ascii"),
    pytest.param(TOKEN, "", id="empty-presented"),
    pytest.param(None, "", id="cleared-stored-empty-presented"),
    pytest.param(None, TOKEN, id="cleared-stored"),
    pytest.param("", "", id="empty-both"),
]


@pytest.fixture
def digest_calls(monkeypatch) -> list[tuple[object, object]]:
    calls: list[tuple[object, object]] = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    return calls


class _Db:
    """A stand-in session: ``get`` returns the synthetic program job and program."""

    def __init__(self, job, program) -> None:
        self._rows = {CalyxProgramJob: job, CalyxProgram: program}

    def get(self, model, _key):
        return self._rows.get(model)


def _program_job(stored):
    job = SimpleNamespace(
        program_id="program-1",
        status="running",
        lease_owner=WORKER,
        lease_token=stored,
        lease_expires_at=utcnow() + timedelta(hours=1),
    )
    return job, SimpleNamespace(owner="owner-1")


# --- engineering completion scheduler ---------------------------------------------------


def _engineering_job(stored):
    return SimpleNamespace(
        job_type=ENGINEERING_COMPLETION_JOB_TYPE,
        lease_owner=WORKER,
        lease_token=stored,
        request_text="{not json",  # past the lease check the job payload is parsed
        attempt_count=0,
        max_attempts=3,
    )


def _advance(stored, presented):
    scheduler = EngineeringCompletionScheduler(db=None, client=None)
    return scheduler.advance_claimed(
        _engineering_job(stored), worker_id=WORKER, lease_token=presented
    )


@pytest.mark.parametrize(("stored", "presented"), MISMATCHES)
def test_completion_scheduler_lease_mismatch_is_stale(stored, presented):
    with pytest.raises(PermissionError, match="STALE_ENGINEERING_COMPLETION_LEASE"):
        _advance(stored, presented)


def test_completion_scheduler_lease_is_compared_in_constant_time(digest_calls):
    with pytest.raises(json.JSONDecodeError):  # the matching lease got past the check
        _advance(TOKEN, TOKEN)
    assert (TOKEN.encode(), TOKEN.encode()) in digest_calls


def test_completion_scheduler_other_worker_is_stale_even_with_the_token():
    job = _engineering_job(TOKEN)
    with pytest.raises(PermissionError, match="STALE_ENGINEERING_COMPLETION_LEASE"):
        EngineeringCompletionScheduler(db=None, client=None).advance_claimed(
            job, worker_id="worker-2", lease_token=TOKEN
        )


# --- dry-run service ----------------------------------------------------------------------


class _PastLeaseCheck(Exception):
    pass


def _dry_run(monkeypatch, stored, presented):
    def reached(*_args, **_kwargs):
        raise _PastLeaseCheck

    monkeypatch.setattr(
        dry_run_service, "governed_assignment_from_claimed_job", reached
    )
    job, program = _program_job(stored)
    return dry_run_service.execute_deterministic_dry_run(
        _Db(job, program),
        owner="owner-1",
        program_job_id="job-1",
        worker_id=WORKER,
        lease_token=presented,
    )


@pytest.mark.parametrize(("stored", "presented"), MISMATCHES)
def test_dry_run_lease_mismatch_is_stale(monkeypatch, stored, presented):
    with pytest.raises(PermissionError, match="STALE_PROGRAM_JOB_LEASE"):
        _dry_run(monkeypatch, stored, presented)


def test_dry_run_lease_is_compared_in_constant_time(monkeypatch, digest_calls):
    with pytest.raises(_PastLeaseCheck):
        _dry_run(monkeypatch, TOKEN, TOKEN)
    assert (TOKEN.encode(), TOKEN.encode()) in digest_calls


# --- lease execution bridge ---------------------------------------------------------------


def _require_live_lease(stored, presented):
    job, program = _program_job(stored)
    bridge = LeaseExecutionBridge(_Db(job, program))
    return bridge._require_live_lease(
        program_job_id="job-1", worker_id=WORKER, lease_token=presented
    ), (job, program)


@pytest.mark.parametrize(("stored", "presented"), MISMATCHES)
def test_execution_bridge_lease_mismatch_is_stale(stored, presented):
    with pytest.raises(PermissionError, match="STALE_PROGRAM_JOB_LEASE"):
        _require_live_lease(stored, presented)


def test_execution_bridge_lease_is_compared_in_constant_time(digest_calls):
    returned, expected = _require_live_lease(TOKEN, TOKEN)
    assert returned == expected
    assert (TOKEN.encode(), TOKEN.encode()) in digest_calls
