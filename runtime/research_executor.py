"""Durable research-request executor for the BUILD-051 intake.

The GitHub research bridge persists an accepted request and stops at
``queued_waiting_for_executor``, with the blocker "No live research
executor/result-return worker is activated." That is honest, and it is where
the scientific path currently ends: intake, not execution.

This module is the missing step. It is deliberately ordinary — a claim, a
state transition, a run, a write-back — because every property that matters
here is a durability property, not an intelligence one. Claiming a job,
enforcing exactly-once, expiring a lease and deduplicating feedback are jobs
for deterministic code. The scientific reasoning belongs to the runner behind
:class:`ResearchRunner`, and nothing in this file decides anything scientific.

WHAT THIS MODULE MAY NOT DO
---------------------------
It has no publication, taxonomy-activation or Knowledge-Graph mutation
authority, and acquires none by being called from a worker. It moves a request
through its states and records what the runner returned. If a runner reports
that evidence was not found, that is recorded as found-nothing — never
softened into a result, and never replaced by a model's guess.

STATE MACHINE
-------------
``queued_waiting_for_executor`` → ``queued`` → ``running`` → ``completed``
                                                          ↘ ``blocked``

``queued_waiting_for_executor`` is the intake's own resting state, so the
executor admits it as claimable rather than requiring a separate promotion
step that nothing currently performs. Both are treated as claimable, and the
transition history records which one the request was claimed from.

LEASES
------
A worker that dies mid-run must not leave a request that reads as running
forever. Every claim takes a lease with an explicit expiry; a ``running``
request whose lease has expired is claimable again, and each reclaim increments
``attempts`` so a request that repeatedly kills its worker becomes visible
rather than invisible. The lease is stored with the request, so recovery needs
no separate coordination service.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

# --------------------------------------------------------------------- states

QUEUED_WAITING_FOR_EXECUTOR = "queued_waiting_for_executor"
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
BLOCKED = "blocked"

#: States a worker may claim. The intake's resting state is included because
#: nothing else promotes it, and requiring a promotion nobody performs would
#: leave the queue permanently empty while looking correctly configured.
CLAIMABLE_STATES = frozenset({QUEUED_WAITING_FOR_EXECUTOR, QUEUED})

#: States from which no further work is done. Replay against one of these is a
#: no-op that returns what is already recorded.
TERMINAL_STATES = frozenset({COMPLETED, BLOCKED})

DEFAULT_LEASE_SECONDS = 900


class BlockerCode:
    """Blocker codes a request may terminate with.

    Kept as named constants because they are written into durable records and
    read by other systems. ``RETRYABLE`` marks the ones where the request may
    legitimately be requeued; the rest describe a condition that re-running
    will not change.
    """

    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RUNNER_FAILED = "RUNNER_FAILED"
    RUNNER_TIMEOUT = "RUNNER_TIMEOUT"
    TAXON_UNRESOLVED = "TAXON_UNRESOLVED"
    LEASE_LOST = "LEASE_LOST"

    RETRYABLE = frozenset({EVIDENCE_UNAVAILABLE, RUNNER_TIMEOUT, LEASE_LOST})

    @classmethod
    def is_retryable(cls, code: str) -> bool:
        return code in cls.RETRYABLE


def _utc(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


# -------------------------------------------------------------------- outcome


@dataclass(frozen=True)
class RunOutcome:
    """What a runner did, in terms the executor can record without judgement."""

    state: str
    artifact_ids: tuple[str, ...] = ()
    evidence_summary: Mapping[str, Any] | None = None
    blocker_code: str | None = None
    blocker_detail: str | None = None

    @classmethod
    def completed(
        cls,
        *,
        artifact_ids: Iterable[str],
        evidence_summary: Mapping[str, Any] | None = None,
    ) -> RunOutcome:
        ids = tuple(str(value) for value in artifact_ids if str(value).strip())
        if not ids:
            # A completion with nothing to point at is indistinguishable from a
            # claim that work happened. Runners that found no evidence must
            # block with INSUFFICIENT_EVIDENCE rather than complete emptily.
            raise ValueError("a completed run must produce at least one artifact id")
        return cls(state=COMPLETED, artifact_ids=ids, evidence_summary=evidence_summary)

    @classmethod
    def blocked(
        cls,
        *,
        code: str,
        detail: str,
        evidence_summary: Mapping[str, Any] | None = None,
    ) -> RunOutcome:
        if not code.strip():
            raise ValueError("a blocked run must name a blocker code")
        return cls(
            state=BLOCKED,
            blocker_code=code,
            blocker_detail=detail,
            evidence_summary=evidence_summary,
        )


class ResearchRunner(Protocol):
    """The scientific half, kept behind a boundary this module does not cross."""

    def run(self, request: Mapping[str, Any]) -> RunOutcome: ...


# ---------------------------------------------------------------------- store


class RequestStore(Protocol):
    """Durable storage for research requests.

    ``claim`` must be atomic: two workers calling it concurrently must never
    receive the same request. Implementations back this with row locking; the
    in-memory one is single-process by construction.
    """

    def claim(
        self, *, worker_id: str, lease_seconds: int, now: datetime
    ) -> dict[str, Any] | None: ...

    def get(self, request_id: str) -> dict[str, Any] | None: ...

    def save(self, record: Mapping[str, Any]) -> dict[str, Any]: ...


def _claimable(record: Mapping[str, Any], now: datetime) -> bool:
    """True when a request may be claimed, including an expired-lease reclaim."""
    state = str(record.get("status") or "")
    if state in CLAIMABLE_STATES:
        return True
    if state != RUNNING:
        return False
    # A running request whose worker died. The lease is what distinguishes
    # "in progress" from "abandoned"; without it the two look identical.
    expires_at = record.get("lease_expires_at")
    if not expires_at:
        return False
    try:
        return _utc(datetime.fromisoformat(str(expires_at))) <= now
    except ValueError:
        # An unparseable lease is not evidence that the request is live.
        return True


class MemoryRequestStore:
    """In-process store, used where no database is configured and in tests."""

    def __init__(self, records: Sequence[Mapping[str, Any]] | None = None) -> None:
        self._records: list[dict[str, Any]] = [dict(item) for item in (records or ())]

    def all(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._records]

    def claim(
        self, *, worker_id: str, lease_seconds: int, now: datetime
    ) -> dict[str, Any] | None:
        for record in self._records:
            if not _claimable(record, now):
                continue
            record.update(
                _claim_fields(record, worker_id=worker_id, lease_seconds=lease_seconds, now=now)
            )
            return dict(record)
        return None

    def get(self, request_id: str) -> dict[str, Any] | None:
        for record in self._records:
            if record.get("id") == request_id:
                return dict(record)
        return None

    def save(self, record: Mapping[str, Any]) -> dict[str, Any]:
        for index, existing in enumerate(self._records):
            if existing.get("id") == record.get("id"):
                self._records[index] = dict(record)
                return dict(record)
        self._records.append(dict(record))
        return dict(record)


def _claim_fields(
    record: Mapping[str, Any], *, worker_id: str, lease_seconds: int, now: datetime
) -> dict[str, Any]:
    """The mutation a claim performs, shared by every store implementation."""
    previous = str(record.get("status") or "")
    attempts = int(record.get("attempts") or 0) + 1
    history = list(record.get("transitions") or ())
    history.append(
        {
            "from": previous,
            "to": RUNNING,
            "at": _iso(now),
            "worker_id": worker_id,
            "reason": "lease_expired_reclaim" if previous == RUNNING else "claimed",
        }
    )
    return {
        "status": RUNNING,
        # The intake's blocker described the absence of this worker. Once one
        # has the request, leaving that text in place would keep asserting a
        # condition that no longer holds.
        "blocker": None,
        "worker_id": worker_id,
        "attempts": attempts,
        "lease_expires_at": _iso(now + timedelta(seconds=lease_seconds)),
        "claimed_at": _iso(now),
        "updated_at": _iso(now),
        "transitions": history,
    }


class PostgresRequestStore:
    """Row-locked store over ``oc_admin.build051_research_requests``.

    Claiming uses ``FOR UPDATE SKIP LOCKED`` so a second worker passes over a
    row the first is already taking rather than blocking on it or, worse,
    reading it as available.
    """

    TABLE = "oc_admin.build051_research_requests"

    def __init__(self, db_execute: Callable[[Callable[[Any], Any]], Any]) -> None:
        self._db_execute = db_execute

    def claim(
        self, *, worker_id: str, lease_seconds: int, now: datetime
    ) -> dict[str, Any] | None:
        def _work(cur):
            if cur is None:
                return None
            cur.execute(
                f"""
                SELECT payload
                FROM {self.TABLE}
                WHERE payload->>'status' IN %s
                   OR (
                        payload->>'status' = %s
                        AND payload->>'lease_expires_at' IS NOT NULL
                        AND (payload->>'lease_expires_at')::timestamptz <= %s
                      )
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (tuple(sorted(CLAIMABLE_STATES)), RUNNING, now),
            )
            row = cur.fetchone()
            if row is None:
                return None
            record = dict(row["payload"])
            record.update(
                _claim_fields(record, worker_id=worker_id, lease_seconds=lease_seconds, now=now)
            )
            _write(cur, self.TABLE, record)
            return record

        return self._db_execute(_work)

    def get(self, request_id: str) -> dict[str, Any] | None:
        def _work(cur):
            if cur is None:
                return None
            cur.execute(
                f"SELECT payload FROM {self.TABLE} WHERE id = %s",
                (request_id,),
            )
            row = cur.fetchone()
            return dict(row["payload"]) if row else None

        return self._db_execute(_work)

    def save(self, record: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(record)

        def _work(cur):
            if cur is None:
                return payload
            _write(cur, self.TABLE, payload)
            return payload

        return self._db_execute(_work)


def _write(cur, table: str, record: Mapping[str, Any]) -> None:
    from psycopg.types.json import Jsonb

    cur.execute(
        f"UPDATE {table} SET payload = %s, updated_at = NOW() WHERE id = %s",
        (Jsonb(dict(record)), record["id"]),
    )


# ------------------------------------------------------------------- executor


@dataclass
class ExecutionReport:
    """What one executor pass did, for a caller that has to report truthfully."""

    claimed: bool
    request_id: str | None = None
    state: str | None = None
    blocker_code: str | None = None
    artifact_ids: tuple[str, ...] = ()
    replayed: bool = False
    notes: list[str] = field(default_factory=list)


class ResearchExecutor:
    """Moves one request from claimable to terminal, exactly once."""

    def __init__(
        self,
        *,
        store: RequestStore,
        runner: ResearchRunner,
        worker_id: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        feedback: Callable[[Mapping[str, Any]], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        self._worker_id = worker_id or f"research-executor-{uuid.uuid4().hex[:12]}"
        self._lease_seconds = int(lease_seconds)
        self._feedback = feedback
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def execute_once(self) -> ExecutionReport:
        """Claim at most one request and drive it to a terminal state."""
        now = _utc(self._clock())
        record = self._store.claim(
            worker_id=self._worker_id, lease_seconds=self._lease_seconds, now=now
        )
        if record is None:
            return ExecutionReport(claimed=False, notes=["no claimable request"])

        request_id = str(record.get("id") or "")
        try:
            outcome = self._runner.run(dict(record))
        except Exception as exc:  # noqa: BLE001 - a runner fault is a blocker, not a crash
            # A worker that dies here would leave the request running until its
            # lease expired. Recording the fault is what turns an outage into a
            # readable state instead of a silence.
            outcome = RunOutcome.blocked(
                code=BlockerCode.RUNNER_FAILED,
                detail=f"{type(exc).__name__}: {exc}",
            )

        finished = self._finish(record, outcome, now=_utc(self._clock()))
        self._notify(finished)
        return ExecutionReport(
            claimed=True,
            request_id=request_id,
            state=str(finished.get("status")),
            blocker_code=finished.get("blocker_code"),
            artifact_ids=tuple(finished.get("artifact_ids") or ()),
        )

    def execute_request(self, request_id: str) -> ExecutionReport:
        """Run one named request, or report what it already resolved to.

        Replay is a no-op against a terminal request. Re-running would mint a
        second set of artifacts for one question and post a second answer to
        the same issue, which is how one request becomes two findings.
        """
        existing = self._store.get(request_id)
        if existing is None:
            return ExecutionReport(claimed=False, notes=[f"no such request: {request_id}"])
        if str(existing.get("status")) in TERMINAL_STATES:
            return ExecutionReport(
                claimed=False,
                request_id=request_id,
                state=str(existing.get("status")),
                blocker_code=existing.get("blocker_code"),
                artifact_ids=tuple(existing.get("artifact_ids") or ()),
                replayed=True,
                notes=["already terminal; no work performed"],
            )
        return self.execute_once()

    def _finish(
        self, record: Mapping[str, Any], outcome: RunOutcome, *, now: datetime
    ) -> dict[str, Any]:
        finished = dict(record)
        history = list(finished.get("transitions") or ())
        history.append(
            {
                "from": RUNNING,
                "to": outcome.state,
                "at": _iso(now),
                "worker_id": self._worker_id,
                "reason": outcome.blocker_code or "completed",
            }
        )
        finished.update(
            {
                "status": outcome.state,
                "transitions": history,
                "updated_at": _iso(now),
                "completed_at": _iso(now),
                # The lease is released explicitly. Leaving a stale expiry on a
                # terminal record would make it look reclaimable.
                "lease_expires_at": None,
                "worker_id": self._worker_id,
                "artifact_ids": list(outcome.artifact_ids),
                "evidence_summary": dict(outcome.evidence_summary or {}),
                "blocker_code": outcome.blocker_code,
                "blocker": outcome.blocker_detail,
                "blocker_retryable": (
                    BlockerCode.is_retryable(outcome.blocker_code)
                    if outcome.blocker_code
                    else None
                ),
            }
        )
        return self._store.save(finished)

    def _notify(self, record: Mapping[str, Any]) -> None:
        if self._feedback is None:
            return
        try:
            self._feedback(dict(record))
        except Exception:  # noqa: BLE001
            # Feedback is a courtesy to the requester, not part of the record.
            # A failed comment must not undo a completed research request.
            pass
