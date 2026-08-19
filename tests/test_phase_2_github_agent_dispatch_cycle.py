from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.executor import (
    ExecutionReceipt,
    ExecutionState,
    GovernedAssignment,
    canonical_checksum,
)
from app.calyx_orchestrator.github_agent_dispatch_cycle import (
    EXECUTE_CONFIRMATION,
    ClaimedGitHubCodingJob,
    GitHubCodingAgentDispatchCycle,
    GitHubCodingRuntimePolicy,
)
from app.calyx_orchestrator.github_agent_lifecycle import (
    AgentLifecycleState,
    GitHubAgentDispatchRecord,
    PullRequestObservation,
)
from app.calyx_orchestrator.github_coding_executor import BudgetClass
from app.calyx_orchestrator.program_worker import ClaimDiagnostic

REPOSITORY = "jsp1440/orchid-calyx-backend"


def assignment(*, budget: str = "NORMAL", branch: str | None = None) -> GovernedAssignment:
    inputs = {
        "program": {"program_id": "program-1"},
        "job": {
            "program_job_id": "job-1",
            "job_key": "MISSION-1",
            "role_key": "github_coding_agent",
            "title": "Implement mission",
            "repository": REPOSITORY,
            "branch": branch,
            "mutating_intent": True,
            "attempt_count": 1,
            "mission_id": "MISSION-1",
            "objective": "Implement mission",
            "budget_class": budget,
        },
        "governance": {
            "external_execution_authorized": False,
            "repository_code_execution_authorized": False,
        },
    }
    return GovernedAssignment(
        assignment_id="job-1",
        program_id="program-1",
        job_key="MISSION-1",
        role_key="github_coding_agent",
        objective="Implement mission",
        inputs=inputs,
        evidence_uris=("calyx:program-job/job-1",),
    )


def claim(*, branch: str | None = None) -> ClaimedGitHubCodingJob:
    return ClaimedGitHubCodingJob(
        program_job_id="job-1",
        worker_id="worker-1",
        lease_token="lease-1",
        assignment=assignment(branch=branch),
    )


@dataclass
class Leases:
    next_claim: ClaimedGitHubCodingJob | None = field(default_factory=claim)
    next_diagnostic: ClaimDiagnostic = field(
        default_factory=lambda: ClaimDiagnostic(outcome="IDLE_NO_CANDIDATE")
    )
    claim_calls: int = 0
    released: int = 0
    completions: list[tuple[TerminalOutcome, dict[str, object], str | None]] = field(
        default_factory=list
    )

    def claim(self, *, owner: str) -> ClaimedGitHubCodingJob | None:
        self.claim_calls += 1
        return self.next_claim

    def diagnose(self, *, owner: str) -> ClaimDiagnostic:
        return self.next_diagnostic

    def release_preflight(self, claimed: ClaimedGitHubCodingJob) -> None:
        assert claimed.program_job_id == "job-1"
        self.released += 1

    def complete(
        self,
        claimed: ClaimedGitHubCodingJob,
        *,
        outcome: TerminalOutcome,
        evidence: dict[str, object],
        blocker: str | None = None,
        human_action: str | None = None,
    ) -> None:
        del human_action
        assert claimed.program_job_id == "job-1"
        self.completions.append((outcome, evidence, blocker))


@dataclass
class Store:
    current: GitHubAgentDispatchRecord | None = None
    writes: int = 0

    def get(self, *, program_job_id: str) -> GitHubAgentDispatchRecord | None:
        assert program_job_id == "job-1"
        return self.current

    def record(self, dispatch: GitHubAgentDispatchRecord) -> GitHubAgentDispatchRecord:
        self.current = dispatch
        self.writes += 1
        return dispatch


@dataclass
class Executor:
    status: str = "agent_assigned"
    calls: int = 0
    saw_authorization: bool = False

    def execute(self, governed: GovernedAssignment) -> ExecutionReceipt:
        self.calls += 1
        governance = governed.inputs["governance"]
        assert isinstance(governance, dict)
        self.saw_authorization = bool(governance["external_execution_authorized"])
        if self.status == "already_done":
            output = {
                "status": "already_done",
                "mission_id": "MISSION-1",
                "repository": REPOSITORY,
            }
        else:
            output = {
                "status": "agent_assigned",
                "mission_id": "MISSION-1",
                "repository": REPOSITORY,
                "base_sha": "a" * 40,
                "provider": "github-copilot-cloud-agent",
                "issue_number": 1001,
            }
        return ExecutionReceipt(
            assignment_id=governed.assignment_id,
            program_id=governed.program_id,
            job_key=governed.job_key,
            executor_key="fake",
            state=ExecutionState.DELIVERED,
            outcome=TerminalOutcome.DELIVERED,
            input_checksum=governed.verified_input_checksum(),
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=governed.evidence_uris,
        )


@dataclass
class Observer:
    value: PullRequestObservation
    calls: int = 0

    def observe(self, dispatch: GitHubAgentDispatchRecord) -> PullRequestObservation:
        self.calls += 1
        return self.value


@dataclass
class Repairer:
    calls: int = 0

    def request_repair(
        self,
        dispatch: GitHubAgentDispatchRecord,
        *,
        failure_class: str,
    ) -> str:
        self.calls += 1
        return f"github-pr:{dispatch.repository}#{dispatch.pull_request_number}:repair:{failure_class}"


def policy(*, enabled: bool = True, max_budget: BudgetClass = BudgetClass.NORMAL):
    return GitHubCodingRuntimePolicy(
        enabled=enabled,
        owner_allowlist=frozenset({"owner-1"}),
        repository_allowlist=frozenset({REPOSITORY}),
        max_budget_class=max_budget,
    )


def dispatch_record(**kwargs) -> GitHubAgentDispatchRecord:
    values = {
        "program_job_id": "job-1",
        "mission_id": "MISSION-1",
        "repository": REPOSITORY,
        "base_sha": "a" * 40,
        "provider": "github-copilot-cloud-agent",
        "issue_number": 1001,
    }
    values.update(kwargs)
    return GitHubAgentDispatchRecord(**values)


def cycle(
    *,
    leases: Leases,
    store: Store,
    executor: Executor | None = None,
    observation: PullRequestObservation | None = None,
    repairer: Repairer | None = None,
    runtime_policy: GitHubCodingRuntimePolicy | None = None,
) -> GitHubCodingAgentDispatchCycle:
    return GitHubCodingAgentDispatchCycle(
        policy=runtime_policy or policy(),
        leases=leases,
        store=store,
        executor=executor or Executor(),
        observer=Observer(
            observation
            or PullRequestObservation(repository=REPOSITORY, issue_number=1001)
        ),
        repairer=repairer or Repairer(),
    )


def test_disabled_policy_never_claims_work() -> None:
    leases = Leases()
    with pytest.raises(PermissionError, match="RUNTIME_DISABLED"):
        cycle(
            leases=leases,
            store=Store(),
            runtime_policy=policy(enabled=False),
        ).run_once(owner="owner-1")
    assert leases.claim_calls == 0


def test_preflight_claims_and_releases_without_provider_side_effect() -> None:
    leases = Leases()
    executor = Executor()
    result = cycle(leases=leases, store=Store(), executor=executor).run_once(
        owner="owner-1"
    )
    assert result.state == "preflight_ready"
    assert result.side_effects == ()
    assert leases.released == 1
    assert executor.calls == 0


def test_execute_requires_exact_confirmation_before_claim() -> None:
    leases = Leases()
    with pytest.raises(PermissionError, match="EXECUTE_CONFIRMATION_REQUIRED"):
        cycle(leases=leases, store=Store()).run_once(owner="owner-1", execute=True)
    assert leases.claim_calls == 0


def test_first_execute_dispatches_once_persists_and_releases_job() -> None:
    leases = Leases()
    store = Store()
    executor = Executor()
    result = cycle(leases=leases, store=store, executor=executor).run_once(
        owner="owner-1",
        execute=True,
        confirmation=EXECUTE_CONFIRMATION,
    )
    assert result.state == "agent_assigned"
    assert result.issue_number == 1001
    assert executor.calls == 1
    assert executor.saw_authorization is True


def test_dispatch_creation_persists_the_job_s_reserved_branch() -> None:
    """The mission's admission-reserved branch (CalyxProgramJob.branch, not
    anything the provider itself reports - see github_copilot_cloud_provider,
    which always returns branch=None) must be durably persisted onto the
    dispatch record at creation time."""
    leases = Leases(next_claim=claim(branch="agent/mission-001"))
    store = Store()
    executor = Executor()

    cycle(leases=leases, store=store, executor=executor).run_once(
        owner="owner-1",
        execute=True,
        confirmation=EXECUTE_CONFIRMATION,
    )

    assert store.current is not None
    assert store.current.branch == "agent/mission-001"
    assert store.current is not None
    assert store.current.state == AgentLifecycleState.AGENT_ASSIGNED
    assert leases.released == 1
    assert leases.completions == []


def test_already_done_completes_no_op_without_dispatch_record() -> None:
    leases = Leases()
    store = Store()
    result = cycle(
        leases=leases,
        store=store,
        executor=Executor(status="already_done"),
    ).run_once(
        owner="owner-1",
        execute=True,
        confirmation=EXECUTE_CONFIRMATION,
    )
    assert result.state == "already_done"
    assert store.current is None
    assert leases.completions[0][0] == TerminalOutcome.NO_OP


def test_green_existing_pr_waits_for_owner_merge_and_releases_lease_only() -> None:
    leases = Leases()
    store = Store(
        dispatch_record(
            state=AgentLifecycleState.CI_PENDING,
            pull_request_number=1002,
            pull_request_url=f"https://github.com/{REPOSITORY}/pull/1002",
        )
    )
    result = cycle(
        leases=leases,
        store=store,
        observation=PullRequestObservation(
            repository=REPOSITORY,
            issue_number=1001,
            pull_request_number=1002,
            draft=True,
            head_sha="b" * 40,
            required_checks_known=True,
            required_checks_succeeded=("focused",),
        ),
    ).run_once(owner="owner-1")
    assert result.state == "ready_for_owner_review"
    assert result.action == "owner_review"
    assert leases.released == 1
    assert leases.completions == []


def test_observed_owner_merge_is_only_path_to_delivered_completion() -> None:
    leases = Leases()
    store = Store(
        dispatch_record(
            state=AgentLifecycleState.READY_FOR_OWNER_REVIEW,
            pull_request_number=1002,
            pull_request_url=f"https://github.com/{REPOSITORY}/pull/1002",
            head_sha="b" * 40,
        )
    )
    result = cycle(
        leases=leases,
        store=store,
        observation=PullRequestObservation(
            repository=REPOSITORY,
            issue_number=1001,
            pull_request_number=1002,
            merged=True,
            draft=False,
            head_sha="b" * 40,
            required_checks_known=True,
        ),
    ).run_once(owner="owner-1")
    assert result.state == "merged"
    assert result.action == "mark_delivered"
    assert leases.released == 0
    assert leases.completions[0][0] == TerminalOutcome.DELIVERED
    assert leases.completions[0][1]["owner_governed_merge_observed"] is True


def test_repair_preflight_does_not_contact_agent() -> None:
    leases = Leases()
    repairer = Repairer()
    store = Store(
        dispatch_record(
            state=AgentLifecycleState.CI_PENDING,
            pull_request_number=1002,
        )
    )
    result = cycle(
        leases=leases,
        store=store,
        repairer=repairer,
        observation=PullRequestObservation(
            repository=REPOSITORY,
            issue_number=1001,
            pull_request_number=1002,
            draft=True,
            required_checks_known=True,
            required_checks_failed=("focused",),
            failure_class="ruff",
        ),
    ).run_once(owner="owner-1")
    assert result.reason == "REPAIR_REQUIRED_PREFLIGHT_ONLY"
    assert repairer.calls == 0
    assert leases.released == 1


def test_execute_repair_contacts_agent_once_and_increments_budget() -> None:
    leases = Leases()
    repairer = Repairer()
    store = Store(
        dispatch_record(
            state=AgentLifecycleState.CI_PENDING,
            pull_request_number=1002,
        )
    )
    result = cycle(
        leases=leases,
        store=store,
        repairer=repairer,
        observation=PullRequestObservation(
            repository=REPOSITORY,
            issue_number=1001,
            pull_request_number=1002,
            draft=True,
            required_checks_known=True,
            required_checks_failed=("focused",),
            failure_class="ruff",
        ),
    ).run_once(
        owner="owner-1",
        execute=True,
        confirmation=EXECUTE_CONFIRMATION,
    )
    assert result.action == "repair_requested"
    assert repairer.calls == 1
    assert store.current is not None
    assert store.current.repair_attempts == 1
    assert leases.released == 1


def test_budget_above_policy_releases_claim_and_fails_closed() -> None:
    leases = Leases(next_claim=replace_claim_budget("DEEP"))
    with pytest.raises(PermissionError, match="BUDGET_CLASS_EXCEEDS_POLICY"):
        cycle(leases=leases, store=Store()).run_once(owner="owner-1")
    assert leases.released == 1


def replace_claim_budget(budget: str) -> ClaimedGitHubCodingJob:
    governed = assignment(budget=budget)
    return ClaimedGitHubCodingJob(
        program_job_id="job-1",
        worker_id="worker-1",
        lease_token="lease-1",
        assignment=governed,
    )
