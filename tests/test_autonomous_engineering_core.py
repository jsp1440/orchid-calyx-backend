from app.calyx_orchestrator.engineering_core import (
    AGENT_ROLE_REGISTRY,
    AgentRole,
    EngineeringAdmissionPolicy,
    EngineeringWorkIdentity,
    TerminalOutcome,
    get_agent_role_spec,
)


def work(
    job_id: str,
    *,
    repository: str = "jsp1440/orchid-calyx-backend",
    branch: str | None = None,
    mutates_code: bool = False,
    status: str = "running",
) -> EngineeringWorkIdentity:
    return EngineeringWorkIdentity(
        job_id=job_id,
        role=AgentRole.BACKEND_ENGINEER,
        repository=repository,
        branch=branch,
        mutates_code=mutates_code,
        status=status,
    )


def test_phase_one_registry_has_six_roles() -> None:
    assert set(AGENT_ROLE_REGISTRY) == set(AgentRole)
    assert len(AGENT_ROLE_REGISTRY) == 6
    assert get_agent_role_spec("engineering_director").may_mutate_code is False
    assert get_agent_role_spec(AgentRole.FRONTEND_ENGINEER).may_mutate_code is True


def test_terminal_outcomes_are_structured() -> None:
    assert {item.value for item in TerminalOutcome} == {
        "DELIVERED",
        "BLOCKED",
        "NO_OP",
        "CANCELLED",
        "DEAD_LETTER",
    }


def test_global_capacity_is_six() -> None:
    policy = EngineeringAdmissionPolicy()
    active = [work(f"job-{index}", repository=f"repo-{index}") for index in range(6)]
    result = policy.evaluate(work("candidate", repository="new-repo"), active)
    assert result.admitted is False
    assert result.code == "GLOBAL_CAPACITY_REACHED"


def test_repository_capacity_is_two() -> None:
    policy = EngineeringAdmissionPolicy()
    active = [work("one"), work("two")]
    result = policy.evaluate(work("three"), active)
    assert result.admitted is False
    assert result.code == "REPOSITORY_CAPACITY_REACHED"


def test_only_one_mutating_job_may_own_a_branch() -> None:
    policy = EngineeringAdmissionPolicy()
    active = [work("one", branch="feature/core", mutates_code=True)]
    result = policy.evaluate(work("two", branch="feature/core", mutates_code=True), active)
    assert result.admitted is False
    assert result.code == "BRANCH_MUTATION_LOCKED"


def test_non_mutating_job_can_share_branch_identity() -> None:
    policy = EngineeringAdmissionPolicy()
    active = [work("one", branch="feature/core", mutates_code=True)]
    candidate = work("two", branch="feature/core", mutates_code=False)
    result = policy.evaluate(candidate, active)
    assert result.admitted is True
    assert result.code == "ADMITTED"


def test_mutating_job_requires_authoritative_branch() -> None:
    policy = EngineeringAdmissionPolicy()
    result = policy.evaluate(work("candidate", mutates_code=True), [])
    assert result.admitted is False
    assert result.code == "MUTATING_JOB_REQUIRES_BRANCH"


def test_duplicate_active_job_is_rejected() -> None:
    policy = EngineeringAdmissionPolicy()
    candidate = work("same")
    result = policy.evaluate(candidate, [candidate])
    assert result.admitted is False
    assert result.code == "DUPLICATE_ACTIVE_JOB"


def test_queued_jobs_do_not_consume_active_capacity() -> None:
    policy = EngineeringAdmissionPolicy()
    queued = [work(f"queued-{index}", status="queued") for index in range(10)]
    result = policy.evaluate(work("candidate"), queued)
    assert result.admitted is True
