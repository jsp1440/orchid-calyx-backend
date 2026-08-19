from __future__ import annotations

"""EXECUTOR PREFLIGHT HARDENING, Priority 3.

A deterministic, zero-credential harness exercising the full chain:

    MISSION
    -> durable program creation      (PersistentProgramRepository, real)
    -> admission                     (EngineeringAdmissionPolicy, real)
    -> claim                         (PersistentProgramWorker, real, real DB)
    -> convergence inspection        (classify_convergence, real, synthetic input)
    -> preflight result              (GitHubCodingAgentDispatchCycle, real)
    -> release                       (PersistentProgramWorker.release_preflight, real)

using an ephemeral in-memory SQLite database and zero live GitHub calls. No
production database is touched, no new scheduler or orchestrator is
introduced - this composes the exact classes the merged executor chain
already ships, the same way the real /programs route and dispatch cycle do.

Two things are deliberately represented with synthetic data rather than a
real network call, and this is stated plainly rather than glossed over:

1. GitHubRepositoryConvergenceInspector.inspect() makes real GitHub API
   calls (list open PRs/issues, resolve base_sha) via an injected
   GitHubTransport - there is no credential-free way to exercise that
   specific class's own HTTP logic. What IS exercised for real is
   classify_convergence() - the actual decision function that turns a
   RepositorySnapshot into a ConvergenceClass - fed a synthetic snapshot
   standing in for what a real inspection would return. The decision logic
   is real; only the network call that would produce its input is faked.

2. Actually dispatching to a coding-agent provider (GitHubCopilotCloudProvider)
   requires the same GitHubTransport and would create a real GitHub issue.
   The harness runs GitHubCodingAgentDispatchCycle.run_once(execute=False) -
   PREFLIGHT ONLY - which by design never reaches the provider at all (see
   github_agent_dispatch_cycle.py's run_once: the preflight branch returns
   before self.executor.execute() is called). This is architecturally
   significant, not a simplification: convergence inspection and dispatch
   only happen in execute mode. Preflight mode's job is narrower - it
   proves the mission would be admitted and classified, not that dispatch
   would succeed. A harness that claimed preflight exercises live dispatch
   would misrepresent the real control flow.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_agent_dispatch_cycle import (
    GitHubCodingAgentDispatchCycle,
    GitHubCodingRuntimePolicy,
    SqlAlchemyCodingJobLeaseGateway,
)
from app.calyx_orchestrator.github_coding_executor import (
    BudgetClass,
    ConvergenceClass,
    RepositorySnapshot,
    classify_convergence,
)
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
OWNER = "jsp1440"


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    with Session(engine) as session:
        yield session


class _NullDispatchStore:
    def get(self, *, program_job_id: str):
        return None

    def record(self, dispatch):  # pragma: no cover - preflight never reaches this
        raise AssertionError("record() must not be called during preflight")


@dataclass(frozen=True)
class SyntheticConvergenceEvidence:
    """Stands in for what GitHubRepositoryConvergenceInspector.inspect()
    would return after real (credentialed) GitHub API calls. Every field
    here is exactly what that class's RepositorySnapshot carries -
    classify_convergence() cannot tell the difference between this and a
    real inspection result, because the classification logic only ever
    looks at the snapshot, never at how it was produced."""

    related_issue_numbers: Sequence[int] = ()
    overlapping_pr_numbers: Sequence[int] = ()
    continuation_pr_numbers: Sequence[int] = ()
    convergence_pr_numbers: Sequence[int] = ()
    superseded_pr_numbers: Sequence[int] = ()
    implementation_complete: bool = False

    def as_snapshot(self, *, repository: str, base_sha: str) -> RepositorySnapshot:
        return RepositorySnapshot(
            repository=repository,
            base_ref="main",
            base_sha=base_sha,
            related_issue_numbers=tuple(self.related_issue_numbers),
            overlapping_pr_numbers=tuple(self.overlapping_pr_numbers),
            continuation_pr_numbers=tuple(self.continuation_pr_numbers),
            convergence_pr_numbers=tuple(self.convergence_pr_numbers),
            superseded_pr_numbers=tuple(self.superseded_pr_numbers),
            implementation_complete=self.implementation_complete,
        )


def enqueue_mission(
    db: Session,
    *,
    job_key: str = "harness-mission-001",
    branch: str = "agent/harness-mission-001",
    budget_class: str = "TINY",
    repository: str = REPOSITORY,
) -> str:
    """Durable program creation - mirrors exactly what a POST to the
    existing, owner-gated /programs route does."""
    repo = PersistentProgramRepository(db)
    program = repo.create_program(
        owner=OWNER,
        title="Preflight harness mission",
        objective="Exercise the full mission->admission->claim->preflight->release chain",
        jobs=[
            ProgramJobSpec(
                job_key=job_key,
                role_key="github_coding_agent",
                title="Harness mission",
                repository=repository,
                branch=branch,
                mutating=True,
                inputs={"budget_class": budget_class, "mission_id": job_key},
            )
        ],
        dependencies=[],
    )
    repo.start(owner=OWNER, program_id=program.program_id)
    return program.program_id


_DEFAULT_EVIDENCE = SyntheticConvergenceEvidence()


def run_zero_credential_preflight_harness(
    db: Session,
    *,
    evidence: SyntheticConvergenceEvidence | None = None,
    repository: str = REPOSITORY,
    base_sha: str = "a" * 40,
) -> dict[str, object]:
    """The harness entry point. Enqueues one mission, runs it through real
    admission/claim/preflight/release, and separately proves the real
    convergence-classification decision on synthetic evidence. Returns a
    dict of everything an operator or a future automated check would want
    to inspect: the preflight result, the convergence class, and proof
    that zero side effects occurred.

    Callable directly (this is the "harness"), or exercised as a pytest
    test (see below) - both use the exact same function.
    """
    evidence = evidence if evidence is not None else _DEFAULT_EVIDENCE
    enqueue_mission(db, repository=repository)

    policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({repository}),
        max_budget_class=BudgetClass.NORMAL,
    )
    cycle = GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=_NullDispatchStore(),
        executor=None,  # type: ignore[arg-type]  # unreached: preflight never calls it
        observer=None,  # type: ignore[arg-type]
        repairer=None,  # type: ignore[arg-type]
    )

    preflight_result = cycle.run_once(owner=OWNER, execute=False)

    convergence_class = classify_convergence(evidence.as_snapshot(repository=repository, base_sha=base_sha))

    return {
        "preflight_state": preflight_result.state,
        "preflight_repository": preflight_result.repository,
        "preflight_side_effects": preflight_result.side_effects,
        "convergence_class": convergence_class,
    }


def test_harness_exercises_the_full_chain_with_zero_side_effects(db: Session) -> None:
    outcome = run_zero_credential_preflight_harness(db)

    assert outcome["preflight_state"] == "preflight_ready"
    assert outcome["preflight_repository"] == REPOSITORY
    assert outcome["preflight_side_effects"] == ()
    assert outcome["convergence_class"] == ConvergenceClass.NEW


def test_harness_classifies_already_done_from_synthetic_evidence(db: Session) -> None:
    """implementation_complete evidence must classify ALREADY_DONE - proving
    the real classify_convergence() decision function, not a stub."""
    outcome = run_zero_credential_preflight_harness(
        db,
        evidence=SyntheticConvergenceEvidence(implementation_complete=True),
    )
    assert outcome["convergence_class"] == ConvergenceClass.ALREADY_DONE
    # Preflight itself is unaffected - convergence classification only
    # happens once execute=True reaches the executor, never in preflight.
    assert outcome["preflight_state"] == "preflight_ready"


def test_harness_classifies_continue_from_synthetic_evidence(db: Session) -> None:
    outcome = run_zero_credential_preflight_harness(
        db,
        evidence=SyntheticConvergenceEvidence(continuation_pr_numbers=(4242,)),
    )
    assert outcome["convergence_class"] == ConvergenceClass.CONTINUE


def test_harness_reports_rejected_admission_not_a_bare_idle(db: Session) -> None:
    """The harness must surface EXECUTOR PREFLIGHT HARDENING Priority 1's
    fix too - enqueuing a mission with no branch must produce an explicit
    diagnostic, not a silent idle, even through this harness entry point."""
    repo = PersistentProgramRepository(db)
    program = repo.create_program(
        owner=OWNER,
        title="Harness mission missing its branch",
        objective="Prove the harness surfaces rejected admission explicitly",
        jobs=[
            ProgramJobSpec(
                job_key="harness-mission-no-branch",
                role_key="github_coding_agent",
                title="Missing branch",
                repository=REPOSITORY,
                branch=None,
                mutating=True,
                inputs={"budget_class": "TINY", "mission_id": "harness-mission-no-branch"},
            )
        ],
        dependencies=[],
    )
    repo.start(owner=OWNER, program_id=program.program_id)

    policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({REPOSITORY}),
    )
    cycle = GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=_NullDispatchStore(),
        executor=None,  # type: ignore[arg-type]
        observer=None,  # type: ignore[arg-type]
        repairer=None,  # type: ignore[arg-type]
    )

    result = cycle.run_once(owner=OWNER, execute=False)

    assert result.state == "rejected_admission"
    assert result.reason == "MUTATING_JOB_REQUIRES_BRANCH"
