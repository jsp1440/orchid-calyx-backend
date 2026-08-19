"""A narrowly bounded, one-shot live-execution surface for the GitHub coding
agent, prepared but never invoked live in this pass.

`GitHubCodingAgentDispatchCycle.run_once(execute=True, ...)` already exists,
is fully tested, and already enforces the durable safety gates
(`GitHubCodingRuntimePolicy`'s owner/repository allowlists and budget-class
ceiling, the exact `EXECUTE_CONFIRMATION` string, and
`_authorize_assignment`'s explicit `automatic_merge_authorized=False`/
`deployment_authorized=False`/`publication_authorized=False`/
`production_graph_mutation_authorized=False`). This module does not
re-implement or weaken any of that. It adds exactly one thing the owner
asked for that did not exist: a single-call operator surface, distinct from
#992's recurring/looping worker, that requires every identity value to be
supplied explicitly and verifies - before ever touching the transport - that
the specific mission the owner reviewed is the only thing that could
possibly be claimed, rather than trusting the scheduler to rank the
"right" candidate first.

This module never constructs a `GitHubTransport` from environment
variables or any other implicit source - the caller supplies one. Per
Orchid-Continuum-Brain OPS-0011, no production code anywhere constructs a
real one yet; inventing that here would be exactly the separate,
still-missing, owner-gated credential step, not something to add as a side
effect of preparing this surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .github_agent_ci_policy import RequiredCiCheckPolicy
from .github_agent_composition import (
    build_production_github_coding_agent_dispatch_cycle,
)
from .github_agent_dispatch_cycle import (
    EXECUTE_CONFIRMATION,
    DispatchCycleResult,
    GitHubCodingRuntimePolicy,
)
from .github_coding_executor import GITHUB_CODING_ROLE, BudgetClass
from .github_proposal_mutation_adapter import GitHubTransport
from .program_models import CalyxProgram, CalyxProgramJob


class OneShotExecutionError(PermissionError):
    """Raised whenever this surface fails closed - a missing/inconsistent
    identity value, an unexpected claimable candidate, or a mismatch between
    the mission the owner authorized and the mission the cycle actually
    processed."""


@dataclass(frozen=True, slots=True)
class OneShotExecutionRequest:
    """Every value here must be supplied explicitly by the caller - none has
    a default, and none is read from an environment variable. `budget_class`
    and `required_checks` are typed rather than raw strings so an invalid
    value fails at construction, not deep inside the dispatch cycle."""

    owner: str
    repository: str
    expected_program_job_id: str
    budget_class: BudgetClass
    required_checks: RequiredCiCheckPolicy
    confirmation: str

    def validate(self) -> None:
        if not self.owner.strip():
            raise OneShotExecutionError("ONE_SHOT_OWNER_REQUIRED")
        if not self.repository.strip():
            raise OneShotExecutionError("ONE_SHOT_REPOSITORY_REQUIRED")
        if not self.expected_program_job_id.strip():
            raise OneShotExecutionError("ONE_SHOT_EXPECTED_PROGRAM_JOB_ID_REQUIRED")
        if not self.required_checks.required_checks:
            raise OneShotExecutionError("ONE_SHOT_REQUIRED_CHECKS_REQUIRED")
        if self.confirmation != EXECUTE_CONFIRMATION:
            raise OneShotExecutionError("ONE_SHOT_CONFIRMATION_MISMATCH")


def _queued_github_coding_candidates(
    db: Session, *, owner: str, repository: str
) -> list[CalyxProgramJob]:
    query = select(CalyxProgramJob).join(
        CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id
    ).where(
        CalyxProgram.owner == owner,
        CalyxProgram.status == "running",
        CalyxProgram.paused.is_(False),
        CalyxProgramJob.status == "queued",
        CalyxProgramJob.outcome.is_(None),
        CalyxProgramJob.role_key == GITHUB_CODING_ROLE,
        CalyxProgramJob.repository == repository,
    )
    return list(db.scalars(query).all())


def execute_one_shot_mission(
    *,
    db: Session,
    transport: GitHubTransport,
    request: OneShotExecutionRequest,
) -> DispatchCycleResult:
    """Execute exactly one mission, exactly once. Not a loop; calling this
    function twice performs two independent authorization checks and, if
    both pass, two dispatch-cycle calls - there is no batching or retry
    inside this function itself.

    Fails closed, before any GitHub call, on: missing/blank identity values,
    a confirmation string that does not match `EXECUTE_CONFIRMATION` exactly,
    zero or more than one queued `github_coding_agent` job for this
    owner+repository (this surface refuses to guess which job the scheduler
    would rank first), or the one queued job's identity not matching
    `expected_program_job_id`. The claim/execute call itself still goes
    through every existing gate in `GitHubCodingRuntimePolicy` and
    `GitHubCodingAgentDispatchCycle` unchanged - this function only adds an
    identity pre-check in front of them, never a bypass.
    """
    request.validate()

    candidates = _queued_github_coding_candidates(
        db, owner=request.owner, repository=request.repository
    )
    if len(candidates) != 1:
        raise OneShotExecutionError(
            f"ONE_SHOT_EXPECTED_EXACTLY_ONE_CANDIDATE:{len(candidates)}"
        )
    if candidates[0].program_job_id != request.expected_program_job_id:
        raise OneShotExecutionError(
            f"ONE_SHOT_UNEXPECTED_CANDIDATE:{candidates[0].program_job_id}"
        )

    runtime_policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({request.owner}),
        repository_allowlist=frozenset({request.repository}),
        max_budget_class=request.budget_class,
    )
    cycle = build_production_github_coding_agent_dispatch_cycle(
        db=db,
        transport=transport,
        policy=runtime_policy,
        required_checks=request.required_checks,
    )

    result = cycle.run_once(
        owner=request.owner,
        execute=True,
        confirmation=request.confirmation,
    )
    if result.program_job_id != request.expected_program_job_id:
        raise OneShotExecutionError(
            f"ONE_SHOT_EXECUTED_UNEXPECTED_JOB:{result.program_job_id!r}"
        )
    return result
