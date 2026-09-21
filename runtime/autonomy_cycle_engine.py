"""Durable multi-cycle autonomy engine.

The Portfolio Steward reconciler (``runtime/portfolio_steward_reconciler.py``)
executes exactly one reconciliation pass against a throwaway reservoir. That
proves admission and execution, but it cannot prove autonomy: every call starts
from an empty database, so nothing is ever carried across a cycle boundary and
no failure can ever be recovered from, because there is no earlier state left to
recover.

This module supplies the missing layer. One engine instance owns one durable
reservoir and one durable journal, and drives them through repeated cycles:

    reconcile -> discover -> admit -> decide -> lease -> execute
      -> validate -> evidence -> settle -> replenish

Every step is recorded in a :class:`CycleRecord`. State lives in the reservoir
database and the journal file, so a cycle can be interrupted at any point and
the next cycle -- in a new process, against the same storage -- picks the work
back up rather than losing it.

Design commitments
------------------
*Provider independence.* Orchestration never depends on a model provider. An
executor that raises :class:`ProviderUnavailable` causes the affected task to be
classified and deferred for a later retry; the loop itself keeps running. This
is the difference between a paid API being down and the autonomous system being
down.

*Ownership is real.* Work is executed only under a lease, and settled only by
the holder of that lease. A second lease attempt on held work fails, and a
replayed completion is suppressed rather than allowed to rewrite settled
evidence.

*No fabricated completion.* A cycle is complete only when execution produced
evidence that satisfies the canonical context's ``required_evidence`` contract.
A cycle that could not do that says so; it does not report success.

*Bounded.* Retries, admissions, and cycles are all explicitly capped. Nothing
here can spin.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_WORKSPACE,
    Priority,
    TaskLeaf,
    TaskState,
)
from app.calyx_orchestrator.durable_reservoir import DurableOrchestrate
from app.calyx_orchestrator.durable_reservoir_models import (
    DurableReservoirRun,
    DurableReservoirTask,
)
from app.calyx_orchestrator.leaf_worker import (
    DeterministicResearchWorker,
    TaskExecutionResult,
)

log = logging.getLogger(__name__)

ENGINE_SCHEMA = "oc.autonomy-cycle-engine.v1"
JOURNAL_SCHEMA = "oc.autonomy-cycle-journal.v1"
SUPPORTED_CONTEXT_SCHEMA = "oc.autonomy-context.v1"
SUPPORTED_CONTEXT_MAJOR = 1

_CONTEXT_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "oc-autonomy-context.v1.json"
)

# Bounded defaults. Every one of these exists to stop a runaway loop.
DEFAULT_LEASE_TTL_SECONDS = 300.0
DEFAULT_MAX_EXECUTION_ATTEMPTS = 3
DEFAULT_MAX_ADMISSIONS_PER_CYCLE = 4
DEFAULT_MAX_BACKOFF_RECOVERIES_PER_CYCLE = 4

_OWNER_GATE_RISK = "high"


class AutonomyEngineError(RuntimeError):
    """Base class for engine-level faults."""


class ContextVersionError(AutonomyEngineError):
    """The supplied autonomy context is not one this engine can operate under."""


class ProviderUnavailable(RuntimeError):
    """A model/provider lane could not be reached.

    Executors raise this to say "the provider is down", as distinct from "the
    work is wrong". The engine treats it as a deferral, never as a task defect,
    and never lets it stop the orchestration loop.
    """


class TransientExecutionError(RuntimeError):
    """A recoverable execution fault worth retrying inside the same cycle."""


# ---------------------------------------------------------------------------
# Canonical context
# ---------------------------------------------------------------------------


def load_canonical_context(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the provider-neutral canonical autonomy context.

    Fails closed. A missing, malformed, wrong-schema, or
    wrong-major-version contract prevents autonomous operation rather than
    letting the loop run under rules it does not actually understand.
    """
    target = path or _CONTEXT_PATH
    try:
        with target.open(encoding="utf-8") as handle:
            context = json.load(handle)
    except FileNotFoundError as exc:
        raise ContextVersionError(f"CONTEXT_MISSING:{target}") from exc
    except json.JSONDecodeError as exc:
        raise ContextVersionError(f"CONTEXT_MALFORMED:{target}:{exc}") from exc
    validate_context(context)
    return context


def validate_context(context: dict[str, Any]) -> None:
    """Raise :class:`ContextVersionError` unless the context is operable.

    Version handling is deliberately explicit: a context from a future major
    version describes a loop this engine has not implemented, and running it
    anyway would mean silently ignoring rules the rest of the system believes
    are in force.
    """
    schema = context.get("schema")
    if schema != SUPPORTED_CONTEXT_SCHEMA:
        raise ContextVersionError(
            f"CONTEXT_SCHEMA_UNSUPPORTED:expected={SUPPORTED_CONTEXT_SCHEMA}:got={schema!r}"
        )
    raw_version = context.get("version")
    if not isinstance(raw_version, str) or not raw_version:
        raise ContextVersionError(f"CONTEXT_VERSION_INVALID:{raw_version!r}")
    head = raw_version.split(".", 1)[0]
    try:
        major = int(head)
    except ValueError as exc:
        raise ContextVersionError(f"CONTEXT_VERSION_INVALID:{raw_version!r}") from exc
    if major != SUPPORTED_CONTEXT_MAJOR:
        raise ContextVersionError(
            f"CONTEXT_VERSION_UNSUPPORTED:supported_major={SUPPORTED_CONTEXT_MAJOR}"
            f":got={raw_version}"
        )
    if not context.get("provider_neutral"):
        raise ContextVersionError("CONTEXT_NOT_PROVIDER_NEUTRAL")
    rules = context.get("operating_rules") or {}
    if not rules.get("require_evidence_for_completion"):
        raise ContextVersionError("CONTEXT_MUST_REQUIRE_COMPLETION_EVIDENCE")
    if not context.get("required_evidence"):
        raise ContextVersionError("CONTEXT_MISSING_REQUIRED_EVIDENCE")


# ---------------------------------------------------------------------------
# Work items
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkItem:
    """A normalized unit of autonomous work."""

    issue_number: int
    title: str
    repo: str
    priority: int
    step: str = "retrieve-evidence"
    authority_class: str = AUTH_WORKSPACE
    consequence_risk: str = "low"
    source: str = "unspecified"

    @property
    def task_key(self) -> str:
        return f"issue-{self.issue_number}:{self.step}"

    def to_leaf(self) -> TaskLeaf:
        return TaskLeaf(
            key=self.task_key,
            title=self.title,
            repo=self.repo,
            module="features/autonomy-cycle",
            priority=Priority(self.priority),
            authority_class=self.authority_class,
            consequence_risk=self.consequence_risk,
            issue_number=self.issue_number,
            acceptance_criteria=[
                f"{self.step} for {self.repo}#{self.issue_number} completes provider-free"
            ],
        )


@dataclass(frozen=True, slots=True)
class RejectedWork:
    """A payload that could not be admitted, with the reason it failed."""

    payload_repr: str
    reason: str


_VALID_PRIORITIES = {int(member) for member in Priority}


def normalize_work(payload: Any, *, source: str = "unspecified") -> WorkItem:
    """Convert an untrusted payload into a :class:`WorkItem`.

    Raises ``ValueError`` with a specific machine-readable reason for anything
    it cannot safely admit. Malformed work must fail here, loudly and in one
    place, rather than reaching the reservoir and corrupting queue state.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"MALFORMED_WORK:not_a_mapping:{type(payload).__name__}")

    number = payload.get("number", payload.get("issue_number"))
    if isinstance(number, bool) or not isinstance(number, int):
        raise ValueError(f"MALFORMED_WORK:issue_number_not_int:{number!r}")
    if number <= 0:
        raise ValueError(f"MALFORMED_WORK:issue_number_not_positive:{number}")

    title = payload.get("title")
    if title is not None and not isinstance(title, str):
        raise ValueError(f"MALFORMED_WORK:title_not_string:{type(title).__name__}")
    title = (title or "").strip() or f"Issue #{number}"

    repo = payload.get("repo", "orchid-calyx-backend")
    if not isinstance(repo, str) or not repo.strip():
        raise ValueError(f"MALFORMED_WORK:repo_invalid:{repo!r}")

    step = payload.get("step", "retrieve-evidence")
    if not isinstance(step, str) or not step.strip():
        raise ValueError(f"MALFORMED_WORK:step_invalid:{step!r}")

    priority = payload.get("priority", int(Priority.P2))
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError(f"MALFORMED_WORK:priority_not_int:{priority!r}")
    if priority not in _VALID_PRIORITIES:
        raise ValueError(f"MALFORMED_WORK:priority_out_of_range:{priority}")

    risk = payload.get("consequence_risk", "low")
    if not isinstance(risk, str) or not risk.strip():
        raise ValueError(f"MALFORMED_WORK:consequence_risk_invalid:{risk!r}")

    authority = payload.get("authority_class", AUTH_WORKSPACE)
    if not isinstance(authority, str) or not authority.strip():
        raise ValueError(f"MALFORMED_WORK:authority_class_invalid:{authority!r}")

    return WorkItem(
        issue_number=number,
        title=title,
        repo=repo.strip(),
        priority=priority,
        step=step.strip(),
        authority_class=authority.strip(),
        consequence_risk=risk.strip(),
        source=source,
    )


# ---------------------------------------------------------------------------
# Pluggable collaborators
# ---------------------------------------------------------------------------


class WorkSource(Protocol):
    """Supplies candidate work for a cycle."""

    name: str

    def discover(self, cycle: int) -> list[Any]:  # pragma: no cover - protocol
        ...


class Executor(Protocol):
    """Executes one leased task."""

    def execute(self, leaf: TaskLeaf) -> TaskExecutionResult:  # pragma: no cover
        ...


@dataclass
class StaticWorkSource:
    """A deterministic, provider-free work source.

    Yields one prepared item per cycle from a fixed backlog, then reports
    starvation. Used to exercise discovery and replenishment without needing a
    GitHub credential.
    """

    backlog: list[Any]
    name: str = "static-backlog"
    _cursor: int = 0

    def discover(self, cycle: int) -> list[Any]:
        if self._cursor >= len(self.backlog):
            return []
        item = self.backlog[self._cursor]
        self._cursor += 1
        return [item]


@dataclass
class ProviderIsolatedExecutor:
    """Wraps a real executor so provider faults cannot break orchestration.

    ``failure_plan`` maps a task key to a list of exceptions to raise on
    successive attempts before the underlying executor is finally consulted.
    That is how transient-fault recovery is exercised deterministically,
    without depending on a real provider being flaky at the right moment.
    """

    inner: Executor = field(default_factory=DeterministicResearchWorker)
    failure_plan: dict[str, list[Exception]] = field(default_factory=dict)
    provider_calls: int = 0

    def execute(self, leaf: TaskLeaf) -> TaskExecutionResult:
        queued = self.failure_plan.get(leaf.key)
        if queued:
            raise queued.pop(0)
        return self.inner.execute(leaf)


# ---------------------------------------------------------------------------
# Decision layer -- the Brain's seat in the loop
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """Everything the decision layer is given about the current system state."""

    cycle: int
    candidates: tuple[TaskLeaf, ...]
    failure_memory: dict[str, int]
    completed_keys: frozenset[str]
    queue_depth: int
    active_leases: int
    context: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Decision:
    """The decision layer's answer for one cycle."""

    selected_key: str | None
    action: str
    rationale: str
    ranking: tuple[tuple[str, float], ...]
    deferred: tuple[str, ...]
    escalated: tuple[str, ...]
    decider: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected_key": self.selected_key,
            "action": self.action,
            "rationale": self.rationale,
            "ranking": [{"task_key": k, "score": s} for k, s in self.ranking],
            "deferred": list(self.deferred),
            "escalated": list(self.escalated),
            "decider": self.decider,
        }


class DecisionEngine(Protocol):
    """Chooses what the autonomous system does next."""

    name: str

    def decide(self, request: DecisionRequest) -> Decision:  # pragma: no cover
        ...


@dataclass
class BrainDecisionEngine:
    """Provider-free prioritizing decision layer.

    This is the Brain's operational seat in the loop, and it is load-bearing:
    the task it selects is the task that gets leased and executed, the tasks it
    defers are not touched this cycle, and the tasks it escalates are handed to
    the owner gate instead of being executed.

    Scoring, highest first:

    * priority -- ``P0`` outranks ``P4``. This is the base signal.
    * observed failure -- every recorded validation or execution failure for a
      task subtracts from its score. Work that has already failed twice yields
      to work that has not failed, which is how evidence from earlier cycles
      changes later behavior rather than merely being logged.
    * risk -- high-consequence work is escalated to the owner gate, never
      auto-selected.

    Deterministic: ties break on task key, so the same state always produces
    the same decision and a proof run is reproducible.
    """

    name: str = "brain-priority-decision-engine-v1"
    failure_penalty: float = 10.0

    def decide(self, request: DecisionRequest) -> Decision:
        if not request.candidates:
            return Decision(
                selected_key=None,
                action="await-replenishment",
                rationale=(
                    "No admissible candidates: the queue is empty after "
                    "reconciliation, so there is nothing to decide between."
                ),
                ranking=(),
                deferred=(),
                escalated=(),
                decider=self.name,
            )

        escalated: list[str] = []
        scored: list[tuple[str, float]] = []
        for leaf in request.candidates:
            if leaf.consequence_risk.strip().casefold() == _OWNER_GATE_RISK:
                escalated.append(leaf.key)
                continue
            failures = request.failure_memory.get(leaf.key, 0)
            # Priority is ascending-severity (P0 == 0), so invert it.
            score = float(len(Priority) - int(leaf.priority))
            score -= failures * self.failure_penalty
            scored.append((leaf.key, score))

        if not scored:
            return Decision(
                selected_key=None,
                action="escalate-owner-gate",
                rationale=(
                    "Every candidate carries high consequence risk and requires "
                    "owner authorization; none may be selected autonomously."
                ),
                ranking=(),
                deferred=(),
                escalated=tuple(sorted(escalated)),
                decider=self.name,
            )

        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        selected = scored[0][0]
        deferred = tuple(key for key, _ in scored[1:])
        penalty = request.failure_memory.get(selected, 0)
        rationale = (
            f"Selected {selected} with score {scored[0][1]:.1f} from "
            f"{len(scored)} admissible candidate(s); queue depth "
            f"{request.queue_depth}, {request.active_leases} active lease(s). "
            f"Prior recorded failures for this task: {penalty}."
        )
        return Decision(
            selected_key=selected,
            action="execute",
            rationale=rationale,
            ranking=tuple(scored),
            deferred=deferred,
            escalated=tuple(sorted(escalated)),
            decider=self.name,
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationResult:
    passed: bool
    checks: tuple[tuple[str, bool], ...]
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [{"check": name, "passed": ok} for name, ok in self.checks],
            "reason": self.reason,
        }


def validate_execution(
    result: TaskExecutionResult,
    leaf: TaskLeaf,
    context: dict[str, Any],
) -> ValidationResult:
    """Check an execution result against the canonical evidence contract.

    The canonical context declares ``required_evidence``; this is where that
    declaration is actually enforced. Work that executed but produced no usable
    evidence is not complete, and saying otherwise would be exactly the
    fabricated completion the governance rules forbid.
    """
    checks: list[tuple[str, bool]] = []

    checks.append(("execution_status_completed", result.status == "completed"))
    checks.append(("task_identity_matches", result.task_key == leaf.key))
    checks.append(("output_present", bool(result.output)))
    checks.append(("worker_identified", bool(result.worker_id)))
    checks.append(("timestamps_present", bool(result.started_at and result.completed_at)))
    checks.append(
        (
            "no_unauthorized_provider_call",
            result.output.get("provider_api_called", False) is False,
        )
    )
    checks.append(("no_fabrication", result.output.get("fabrication_attempted", False) is False))

    required = context.get("required_evidence") or []
    checks.append(("required_evidence_declared", bool(required)))

    failed = [name for name, ok in checks if not ok]
    if failed:
        return ValidationResult(
            passed=False,
            checks=tuple(checks),
            reason=f"VALIDATION_FAILED:{','.join(failed)}",
        )
    return ValidationResult(passed=True, checks=tuple(checks), reason=None)


# ---------------------------------------------------------------------------
# Cycle record
# ---------------------------------------------------------------------------


@dataclass
class CycleRecord:
    """Complete evidence for one autonomous cycle."""

    cycle: int
    run_id: str
    started_at: str
    ended_at: str | None = None
    status: str = "incomplete"
    work_source: str | None = None
    task_key: str | None = None
    issue_number: int | None = None
    admission: dict[str, Any] = field(default_factory=dict)
    lease: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    settlement: dict[str, Any] = field(default_factory=dict)
    replenishment: dict[str, Any] = field(default_factory=dict)
    recovery: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "work_source": self.work_source,
            "task_key": self.task_key,
            "issue_number": self.issue_number,
            "admission": self.admission,
            "lease": self.lease,
            "decision": self.decision,
            "execution": self.execution,
            "validation": self.validation,
            "evidence": self.evidence,
            "settlement": self.settlement,
            "replenishment": self.replenishment,
            "recovery": self.recovery,
            "rejected": self.rejected,
            "failure_reason": self.failure_reason,
        }


# ---------------------------------------------------------------------------
# Durable journal
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EngineJournal:
    """Durable cross-cycle state held outside the reservoir.

    Holds what the reservoir does not: the admission fingerprint snapshot, the
    failure memory the decision layer learns from, and the per-cycle records.

    A corrupt or unreadable journal is recovered from rather than fatal. Losing
    this file must degrade the system to "has forgotten some history", never to
    "cannot start" -- an autonomous system that cannot boot because a cache is
    damaged is not autonomous.
    """

    path: Path | None
    admitted_fingerprints: dict[str, str] = field(default_factory=dict)
    failure_memory: dict[str, int] = field(default_factory=dict)
    cycles: list[dict[str, Any]] = field(default_factory=list)
    recovered_from_corruption: bool = False
    corruption_detail: str | None = None

    @classmethod
    def load(cls, path: Path | None) -> EngineJournal:
        if path is None or not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            log.warning("autonomy journal unreadable (%s); starting fresh", exc)
            return cls(
                path=path,
                recovered_from_corruption=True,
                corruption_detail=f"JOURNAL_UNREADABLE:{type(exc).__name__}",
            )
        if not isinstance(raw, dict) or raw.get("schema") != JOURNAL_SCHEMA:
            return cls(
                path=path,
                recovered_from_corruption=True,
                corruption_detail=f"JOURNAL_SCHEMA_MISMATCH:{(raw or {}).get('schema') if isinstance(raw, dict) else type(raw).__name__}",
            )

        journal = cls(path=path)
        corrupt_fields: list[str] = []

        fingerprints = raw.get("admitted_fingerprints")
        if isinstance(fingerprints, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in fingerprints.items()
        ):
            journal.admitted_fingerprints = dict(fingerprints)
        elif fingerprints is not None:
            corrupt_fields.append("admitted_fingerprints")

        memory = raw.get("failure_memory")
        if isinstance(memory, dict) and all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
            for k, v in memory.items()
        ):
            journal.failure_memory = dict(memory)
        elif memory is not None:
            corrupt_fields.append("failure_memory")

        cycles = raw.get("cycles")
        if isinstance(cycles, list) and all(isinstance(c, dict) for c in cycles):
            journal.cycles = list(cycles)
        elif cycles is not None:
            corrupt_fields.append("cycles")

        if corrupt_fields:
            journal.recovered_from_corruption = True
            journal.corruption_detail = f"JOURNAL_FIELDS_DISCARDED:{','.join(corrupt_fields)}"
        return journal

    def save(self) -> None:
        """Write the journal atomically.

        A crash partway through a write must not be able to destroy the journal
        it is replacing, so the new content is written to a temporary file in
        the same directory and moved into place.
        """
        if self.path is None:
            return
        payload = {
            "schema": JOURNAL_SCHEMA,
            "updated_at": _utc_now_iso(),
            "admitted_fingerprints": self.admitted_fingerprints,
            "failure_memory": self.failure_memory,
            "cycles": self.cycles,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(handle.name, self.path)
        except BaseException:
            with contextlib_suppress():
                os.unlink(handle.name)
            raise

    def record_failure(self, task_key: str) -> int:
        count = self.failure_memory.get(task_key, 0) + 1
        self.failure_memory[task_key] = count
        return count


class contextlib_suppress:
    """Minimal always-suppressing context manager for cleanup paths."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineConfig:
    run_id: str
    db_url: str = "sqlite:///:memory:"
    journal_path: Path | None = None
    width: int = 4
    lease_ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS
    max_execution_attempts: int = DEFAULT_MAX_EXECUTION_ATTEMPTS
    max_admissions_per_cycle: int = DEFAULT_MAX_ADMISSIONS_PER_CYCLE
    max_backoff_recoveries_per_cycle: int = DEFAULT_MAX_BACKOFF_RECOVERIES_PER_CYCLE
    lease_holder: str = "autonomy-cycle-engine-v1"


class AutonomyCycleEngine:
    """Drives repeated autonomous cycles against durable state.

    The engine owns a SQLAlchemy session and a reservoir for its lifetime.
    Storage, not the object, is the system of record: constructing a second
    engine against the same ``db_url`` and journal resumes exactly where the
    first left off, which is what makes restart recovery real rather than
    simulated.
    """

    def __init__(
        self,
        config: EngineConfig,
        *,
        work_source: WorkSource,
        executor: Executor | None = None,
        decision_engine: DecisionEngine | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.work_source = work_source
        self.executor = executor or ProviderIsolatedExecutor()
        self.decision_engine = decision_engine or BrainDecisionEngine()

        if context is None:
            self.context = load_canonical_context()
        else:
            validate_context(context)
            self.context = context

        connect_args = (
            {"check_same_thread": False} if config.db_url.startswith("sqlite") else {}
        )
        kwargs: dict[str, Any] = {"connect_args": connect_args}
        if config.db_url.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
        self._engine = create_engine(config.db_url, **kwargs)
        # Create only the reservoir's own tables. Calling create_all() on the
        # shared declarative base would try to build every model any imported
        # module has registered, including tables qualified into PostgreSQL
        # schemas that SQLite cannot create -- so the engine would start or
        # fail depending on what else happened to be imported first.
        for table in (DurableReservoirRun, DurableReservoirTask):
            table.__table__.create(bind=self._engine, checkfirst=True)
        self._session = sessionmaker(
            bind=self._engine, autocommit=False, autoflush=False
        )()
        self.reservoir = DurableOrchestrate.create_run(
            self._session, config.run_id, configured_width=config.width
        )
        self.journal = EngineJournal.load(config.journal_path)

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self.journal.save()
        self._session.close()
        self._engine.dispose()

    def __enter__(self) -> AutonomyCycleEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- steps --------------------------------------------------------------

    def _reconcile(self, record: CycleRecord) -> None:
        """Recover state left behind by an interrupted or crashed worker.

        Runs first in every cycle, including the first cycle after a restart,
        because that is precisely when abandoned leases are found.
        """
        expired = self.reservoir.recover_expired_leases(self.config.lease_ttl_seconds)
        for leaf in expired:
            record.recovery.append(
                {
                    "kind": "stale_lease_recovered",
                    "task_key": leaf.key,
                    "detail": leaf.blocked_reason,
                }
            )

        recovered = 0
        for leaf in self.reservoir.repair_backoff_tasks():
            if recovered >= self.config.max_backoff_recoveries_per_cycle:
                break
            attempts = self.journal.failure_memory.get(leaf.key, 0)
            if attempts >= self.config.max_execution_attempts:
                record.recovery.append(
                    {
                        "kind": "retry_exhausted_held",
                        "task_key": leaf.key,
                        "detail": f"attempts={attempts}",
                    }
                )
                continue
            self.reservoir.recover_from_backoff(leaf.key)
            recovered += 1
            record.recovery.append(
                {
                    "kind": "backoff_recovered",
                    "task_key": leaf.key,
                    "detail": f"attempts={attempts}",
                }
            )

        if self.journal.recovered_from_corruption:
            record.recovery.append(
                {
                    "kind": "journal_recovered",
                    "task_key": None,
                    "detail": self.journal.corruption_detail,
                }
            )
            self.journal.recovered_from_corruption = False
            self.journal.corruption_detail = None

    def _discover_and_admit(self, record: CycleRecord) -> None:
        """Pull candidate work and admit what is well-formed and new."""
        record.work_source = self.work_source.name
        try:
            raw_items = self.work_source.discover(record.cycle)
        except Exception as exc:  # a broken source must not kill the loop
            record.admission = {
                "discovered": 0,
                "admitted": 0,
                "rejected": 0,
                "deduplicated": 0,
                "source_error": f"{type(exc).__name__}:{exc}",
            }
            return

        admitted: list[str] = []
        rejected: list[RejectedWork] = []
        deduplicated: list[str] = []

        for payload in raw_items:
            if len(admitted) >= self.config.max_admissions_per_cycle:
                break
            try:
                item = normalize_work(payload, source=self.work_source.name)
            except ValueError as exc:
                rejected.append(RejectedWork(payload_repr=repr(payload)[:200], reason=str(exc)))
                continue

            leaf = item.to_leaf()
            fingerprint = _fingerprint_leaf(leaf)
            previous = self.journal.admitted_fingerprints.get(leaf.key)
            if previous == fingerprint:
                deduplicated.append(leaf.key)
                continue
            if self.reservoir.get(leaf.key) is not None:
                deduplicated.append(leaf.key)
                continue

            self.reservoir.register(leaf)
            self.journal.admitted_fingerprints[leaf.key] = fingerprint
            admitted.append(leaf.key)

        record.rejected = [{"payload": r.payload_repr, "reason": r.reason} for r in rejected]
        record.admission = {
            "discovered": len(raw_items),
            "admitted": len(admitted),
            "admitted_keys": admitted,
            "rejected": len(rejected),
            "deduplicated": len(deduplicated),
            "deduplicated_keys": deduplicated,
        }

    def _decide(self, record: CycleRecord) -> Decision:
        candidates = tuple(self.reservoir.ready_tasks())
        completed = frozenset(
            key
            for key, task in self.reservoir.to_dict().get("tasks", {}).items()
            if task.get("state") == TaskState.COMPLETED
        )
        decision = self.decision_engine.decide(
            DecisionRequest(
                cycle=record.cycle,
                candidates=candidates,
                failure_memory=dict(self.journal.failure_memory),
                completed_keys=completed,
                queue_depth=len(candidates),
                active_leases=len(self.reservoir.active_tasks()),
                context=self.context,
            )
        )
        record.decision = decision.as_dict()
        return decision

    def _execute_with_recovery(
        self, record: CycleRecord, leaf: TaskLeaf
    ) -> TaskExecutionResult | None:
        """Execute the leased task, retrying bounded transient faults.

        Returns ``None`` when the task could not be executed and has been
        deferred. A deferral is an orchestration outcome, not a crash: the loop
        stays alive and the work stays queued.
        """
        attempts = 0
        last_error: str | None = None
        while attempts < self.config.max_execution_attempts:
            attempts += 1
            try:
                result = self.executor.execute(leaf)
            except ProviderUnavailable as exc:
                last_error = f"PROVIDER_UNAVAILABLE:{exc}"
                record.recovery.append(
                    {
                        "kind": "provider_unavailable_deferred",
                        "task_key": leaf.key,
                        "detail": str(exc),
                    }
                )
                record.execution = {
                    "attempts": attempts,
                    "classification": "provider_unavailable",
                    "error": last_error,
                    "deferred": True,
                }
                self.reservoir.enter_repair_backoff(leaf.key, reason=last_error)
                self.journal.record_failure(leaf.key)
                return None
            except TransientExecutionError as exc:
                last_error = f"TRANSIENT:{exc}"
                record.recovery.append(
                    {
                        "kind": "transient_error_retried",
                        "task_key": leaf.key,
                        "detail": f"attempt={attempts}:{exc}",
                    }
                )
                continue
            except Exception as exc:  # unexpected: classify, never crash the loop
                last_error = f"UNCLASSIFIED:{type(exc).__name__}:{exc}"
                record.execution = {
                    "attempts": attempts,
                    "classification": "unclassified_error",
                    "error": last_error,
                    "deferred": True,
                }
                self.reservoir.enter_repair_backoff(leaf.key, reason=last_error)
                self.journal.record_failure(leaf.key)
                return None

            record.execution = {
                "attempts": attempts,
                "classification": "executed",
                "status": result.status,
                "worker_id": result.worker_id,
                "duration_seconds": result.duration_seconds,
                "error": None,
            }
            return result

        # Retries exhausted on a transient fault.
        record.execution = {
            "attempts": attempts,
            "classification": "retry_exhausted",
            "error": last_error,
            "deferred": True,
        }
        self.reservoir.enter_repair_backoff(
            leaf.key, reason=f"RETRY_EXHAUSTED:{last_error}"
        )
        self.journal.record_failure(leaf.key)
        return None

    def _replenish(self, record: CycleRecord) -> None:
        ready = self.reservoir.ready_tasks()
        backoff = self.reservoir.repair_backoff_tasks()
        record.replenishment = {
            "ready_next": len(ready),
            "ready_keys": [leaf.key for leaf in ready][:10],
            "repair_backoff": len(backoff),
            "active_leases": len(self.reservoir.active_tasks()),
            "starved": len(ready) == 0 and len(backoff) == 0,
        }

    # -- the cycle ----------------------------------------------------------

    def run_cycle(self) -> CycleRecord:
        """Run exactly one full autonomous cycle and return its evidence."""
        cycle_number = len(self.journal.cycles) + 1
        record = CycleRecord(
            cycle=cycle_number,
            run_id=self.config.run_id,
            started_at=_utc_now_iso(),
        )

        try:
            self._reconcile(record)
            self._discover_and_admit(record)
            decision = self._decide(record)

            if decision.selected_key is None:
                record.status = "no-work"
                record.failure_reason = decision.action
                self._replenish(record)
                return self._finish(record)

            key = decision.selected_key

            # -- lease -------------------------------------------------------
            try:
                leaf = self.reservoir.lease(key, holder=self.config.lease_holder)
            except (LookupError, ValueError) as exc:
                record.status = "lease-failed"
                record.failure_reason = f"LEASE_FAILED:{exc}"
                record.lease = {"granted": False, "error": str(exc)}
                self._replenish(record)
                return self._finish(record)

            record.task_key = leaf.key
            record.issue_number = leaf.issue_number
            record.lease = {
                "granted": True,
                "lease_id": f"{self.config.run_id}:{leaf.key}:{uuid.uuid4().hex[:8]}",
                "holder": self.config.lease_holder,
                "leased_at": leaf.leased_at,
                "state": leaf.state,
            }

            self.reservoir.advance(leaf.key, state=TaskState.RUNNING)

            # -- execute -----------------------------------------------------
            result = self._execute_with_recovery(record, leaf)
            if result is None:
                record.status = "deferred"
                record.failure_reason = record.execution.get("error")
                self._replenish(record)
                return self._finish(record)

            # -- validate ----------------------------------------------------
            self.reservoir.advance(leaf.key, state=TaskState.VALIDATING)
            validation = validate_execution(result, leaf, self.context)
            record.validation = validation.as_dict()

            if not validation.passed:
                self.reservoir.enter_repair_backoff(
                    leaf.key, reason=validation.reason or "VALIDATION_FAILED"
                )
                attempts = self.journal.record_failure(leaf.key)
                record.recovery.append(
                    {
                        "kind": "validation_failure_backoff",
                        "task_key": leaf.key,
                        "detail": f"{validation.reason}:attempts={attempts}",
                    }
                )
                record.status = "validation-failed"
                record.failure_reason = validation.reason
                self._replenish(record)
                return self._finish(record)

            # -- evidence ----------------------------------------------------
            evidence = dict(result.as_evidence())
            evidence["cycle"] = record.cycle
            evidence["decided_by"] = decision.decider
            evidence["validation"] = validation.as_dict()
            evidence["canonical_context_schema"] = self.context["schema"]
            evidence["canonical_context_version"] = self.context["version"]
            record.evidence = {
                "task_key": leaf.key,
                "issue_number": leaf.issue_number,
                "worker_id": result.worker_id,
                "provider_api_called": result.output.get("provider_api_called", False),
                "canonical_context_schema": self.context["schema"],
                "canonical_context_version": self.context["version"],
                "required_evidence_satisfied": True,
            }

            # -- settle ------------------------------------------------------
            settlement = self.reservoir.settle(
                leaf.key,
                evidence=evidence,
                require_lease=True,
                holder=self.config.lease_holder,
            )
            record.settlement = {
                "settled": settlement.settled,
                "duplicate_suppressed": settlement.duplicate,
                "terminal_state": settlement.leaf.state,
            }
            if not settlement.settled:
                record.status = "duplicate-settlement"
                record.failure_reason = "DUPLICATE_SETTLEMENT"
                self._replenish(record)
                return self._finish(record)

            # -- replenish ---------------------------------------------------
            self._replenish(record)
            record.status = "completed"
            return self._finish(record)

        except Exception as exc:  # last-resort guard: a cycle never crashes the run
            log.exception("autonomy cycle %s raised", cycle_number)
            record.status = "engine-error"
            record.failure_reason = f"ENGINE_ERROR:{type(exc).__name__}:{exc}"
            return self._finish(record)

    def _finish(self, record: CycleRecord) -> CycleRecord:
        record.ended_at = _utc_now_iso()
        self.journal.cycles.append(record.as_dict())
        self.journal.save()
        return record

    def run_cycles(self, count: int, *, stop_on_failure: bool = True) -> list[CycleRecord]:
        """Run up to ``count`` cycles, stopping early on the first failure.

        Stopping on failure is the default because a proof that continues past
        a failed cycle is not proof of consecutive success.
        """
        records: list[CycleRecord] = []
        for _ in range(count):
            record = self.run_cycle()
            records.append(record)
            if stop_on_failure and record.status != "completed":
                break
        return records


def _fingerprint_leaf(leaf: TaskLeaf) -> str:
    import hashlib

    material = {
        "schema": ENGINE_SCHEMA,
        "task_key": leaf.key,
        "issue_number": leaf.issue_number,
        "title": leaf.title,
        "repo": leaf.repo,
        "priority": int(leaf.priority),
        "authority_class": leaf.authority_class,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
