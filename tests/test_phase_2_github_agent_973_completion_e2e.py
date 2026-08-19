from __future__ import annotations

"""#973 completion - proves the real observer and real repairer (not test
fakes standing in for the AgentObservationGateway/RepairRequestGateway
protocols) drive a real GitHubCodingAgentDispatchCycle.run_once() through
its actual lifecycle branches, against a fake zero-credential GitHubTransport.
This is the "genuinely constructible from production code" proof: every
collaborator here except the transport and the lease/store layer (which have
their own dedicated real-persistence tests elsewhere) is the exact class
that would run in production.
"""

from dataclasses import dataclass, field

import pytest

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_dispatch_cycle import (
    EXECUTE_CONFIRMATION,
    ClaimedGitHubCodingJob,
    GitHubCodingAgentDispatchCycle,
    GitHubCodingRuntimePolicy,
)
from app.calyx_orchestrator.github_agent_lifecycle import (
    AgentLifecycleState,
    GitHubAgentDispatchRecord,
)
from app.calyx_orchestrator.github_agent_observation_gateway import (
    COPILOT_BOT_LOGIN,
    GitHubIssueLinkedPullRequestObserver,
)
from app.calyx_orchestrator.github_agent_repair_gateway import (
    GitHubCommentRepairGateway,
)
from app.calyx_orchestrator.github_coding_executor import MAX_SAME_FAILURE_RETRIES
from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
)
from app.calyx_orchestrator.program_worker import ClaimDiagnostic

REPOSITORY = "jsp1440/orchid-calyx-backend"
OWNER = "jsp1440"


@dataclass
class FakeTransport:
    responses: list[GitHubTransportResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, *, json_body=None, params=None):
        del json_body, params
        self.calls.append((method, path))
        return self.responses.pop(0)


def bound_assignment() -> GovernedAssignment:
    return GovernedAssignment(
        assignment_id="job-1",
        program_id="program-1",
        job_key="MISSION-1",
        role_key="github_coding_agent",
        objective="Implement mission",
        inputs={
            "job": {
                "repository": REPOSITORY,
                "branch": "agent/mission-001",
                "mutating_intent": True,
                "budget_class": "TINY",
                "mission_id": "MISSION-1",
            },
            "governance": {},
        },
        evidence_uris=(),
    )


@dataclass
class Leases:
    completions: list[tuple[TerminalOutcome, dict, str | None]] = field(default_factory=list)
    released: int = 0

    def claim(self, *, owner: str) -> ClaimedGitHubCodingJob | None:
        return ClaimedGitHubCodingJob(
            program_job_id="job-1",
            worker_id="worker-1",
            lease_token="lease-1",
            assignment=bound_assignment(),
        )

    def diagnose(self, *, owner: str) -> ClaimDiagnostic:  # pragma: no cover - claim() never returns None here
        return ClaimDiagnostic(outcome="IDLE_NO_CANDIDATE")

    def release_preflight(self, claimed: ClaimedGitHubCodingJob) -> None:
        self.released += 1

    def complete(self, claimed, *, outcome, evidence, blocker=None, human_action=None) -> None:
        self.completions.append((outcome, evidence, blocker))


@dataclass
class Store:
    current: GitHubAgentDispatchRecord | None

    def get(self, *, program_job_id: str) -> GitHubAgentDispatchRecord | None:
        return self.current

    def record(self, dispatch: GitHubAgentDispatchRecord) -> GitHubAgentDispatchRecord:
        self.current = dispatch
        return dispatch


def existing_dispatch(**kwargs) -> GitHubAgentDispatchRecord:
    values = {
        "program_job_id": "job-1",
        "mission_id": "MISSION-1",
        "repository": REPOSITORY,
        "base_sha": "a" * 40,
        "provider": "github-copilot-cloud-agent",
        "issue_number": 402,
        "state": AgentLifecycleState.AWAITING_PR,
    }
    values.update(kwargs)
    return GitHubAgentDispatchRecord(**values)


def real_cycle(transport: FakeTransport, store: Store, leases: Leases) -> GitHubCodingAgentDispatchCycle:
    policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({REPOSITORY}),
    )
    return GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=leases,
        store=store,
        executor=None,  # type: ignore[arg-type]  # unreached: an existing dispatch record short-circuits creation
        observer=GitHubIssueLinkedPullRequestObserver(
            transport=transport,
            required_checks=RequiredCiCheckPolicy(required_checks=frozenset({"validate"})),
        ),
        repairer=GitHubCommentRepairGateway(transport=transport),
    )


def pr_payload(*, head_sha: str, draft: bool = True, merged: bool = False, state: str = "open"):
    return {
        "number": 404,
        "draft": draft,
        "merged": merged,
        "state": state,
        "html_url": f"https://github.com/{REPOSITORY}/pull/404",
        "user": {"login": COPILOT_BOT_LOGIN},
        "base": {"repo": {"full_name": REPOSITORY}},
        "head": {"sha": head_sha},
    }


def test_real_observer_resolves_linked_pr_and_waits_on_pending_ci() -> None:
    transport = FakeTransport(
        [
            GitHubTransportResponse(
                200,
                [
                    {
                        "event": "cross-referenced",
                        "source": {
                            "type": "issue",
                            "issue": {
                                "number": 404,
                                "user": {"login": COPILOT_BOT_LOGIN},
                                "pull_request": {},
                                "repository": {"full_name": REPOSITORY},
                            },
                        },
                    }
                ],
            ),
            GitHubTransportResponse(200, pr_payload(head_sha="b" * 40)),
            GitHubTransportResponse(200, {"check_runs": []}),
        ]
    )
    store = Store(existing_dispatch())
    leases = Leases()

    result = real_cycle(transport, store, leases).run_once(owner=OWNER)

    assert result.state == "ci_pending"
    assert result.pull_request_number == 404
    assert leases.released == 1
    assert leases.completions == []


def test_real_observer_and_real_ci_policy_reach_owner_review_ready() -> None:
    transport = FakeTransport(
        [
            GitHubTransportResponse(200, pr_payload(head_sha="c" * 40)),
            GitHubTransportResponse(
                200, {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "success"}]}
            ),
        ]
    )
    store = Store(existing_dispatch(pull_request_number=404, state=AgentLifecycleState.CI_PENDING))
    leases = Leases()

    result = real_cycle(transport, store, leases).run_once(owner=OWNER)

    assert result.state == "ready_for_owner_review"
    assert result.action == "owner_review"
    assert leases.completions == []  # never self-marks delivered - owner merge is the only path


def test_real_ci_failure_triggers_a_real_repair_comment_via_the_transport() -> None:
    transport = FakeTransport(
        [
            GitHubTransportResponse(200, pr_payload(head_sha="d" * 40)),
            GitHubTransportResponse(
                200, {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "failure"}]}
            ),
            GitHubTransportResponse(201, {"html_url": f"https://github.com/{REPOSITORY}/pull/404#issuecomment-1"}),
        ]
    )
    store = Store(existing_dispatch(pull_request_number=404, state=AgentLifecycleState.CI_PENDING))
    leases = Leases()

    result = real_cycle(transport, store, leases).run_once(
        owner=OWNER, execute=True, confirmation=EXECUTE_CONFIRMATION
    )

    assert result.action == "repair_requested"
    assert store.current is not None
    assert store.current.repair_attempts == 1
    assert transport.calls[-1] == ("POST", f"/repos/{REPOSITORY}/issues/404/comments")


def test_infrastructure_failure_waits_without_contacting_the_agent() -> None:
    transport = FakeTransport(
        [
            GitHubTransportResponse(200, pr_payload(head_sha="e" * 40)),
            GitHubTransportResponse(
                200, {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "cancelled"}]}
            ),
        ]
    )
    store = Store(existing_dispatch(pull_request_number=404, state=AgentLifecycleState.CI_PENDING))
    leases = Leases()

    result = real_cycle(transport, store, leases).run_once(
        owner=OWNER, execute=True, confirmation=EXECUTE_CONFIRMATION
    )

    assert result.state == "ci_pending"
    assert result.reason == "CI_INFRASTRUCTURE_FAILURE_DOES_NOT_CONSUME_REPAIR_BUDGET"
    assert store.current is not None
    assert store.current.repair_attempts == 0
    assert len(transport.calls) == 2  # PR lookup + check-runs only - no repair comment posted


def test_same_deterministic_failure_stops_after_max_repair_attempts() -> None:
    """Drive the same required-check failure class through repeated cycles;
    the ceiling must escalate rather than repair a fourth time."""
    store = Store(
        existing_dispatch(
            pull_request_number=404,
            state=AgentLifecycleState.CI_PENDING,
            repair_attempts=MAX_SAME_FAILURE_RETRIES,
            last_failure_class="required_ci_failure:validate",
        )
    )
    transport = FakeTransport(
        [
            GitHubTransportResponse(200, pr_payload(head_sha="f" * 40)),
            GitHubTransportResponse(
                200, {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "failure"}]}
            ),
        ]
    )
    leases = Leases()

    result = real_cycle(transport, store, leases).run_once(
        owner=OWNER, execute=True, confirmation=EXECUTE_CONFIRMATION
    )

    assert result.action == "escalate"
    assert result.state == "blocked"
    assert leases.completions[0][0] == TerminalOutcome.BLOCKED
    # No repair comment was posted - the ceiling stopped it before contacting the agent again.
    assert all(call[0] != "POST" for call in transport.calls)


def test_merge_remains_owner_only_real_observer_never_self_marks_delivered() -> None:
    transport = FakeTransport(
        [GitHubTransportResponse(200, pr_payload(head_sha="1" * 40, merged=True, draft=False, state="closed"))]
    )
    store = Store(
        existing_dispatch(
            pull_request_number=404,
            state=AgentLifecycleState.READY_FOR_OWNER_REVIEW,
            head_sha="g" * 40,
        )
    )
    leases = Leases()

    result = real_cycle(transport, store, leases).run_once(owner=OWNER)

    assert result.state == "merged"
    assert result.action == "mark_delivered"
    assert leases.completions[0][0] == TerminalOutcome.DELIVERED
    assert leases.completions[0][1]["owner_governed_merge_observed"] is True
    # The only way this ever fires is an *observed* merged=True from GitHub -
    # nothing in this chain has merge authority of its own.


def test_moved_or_replaced_pr_number_fails_closed_via_lifecycle_guard() -> None:
    """If the durable record already carries a different bound PR number
    than what a (misbehaving) observer reports, reconcile_agent_lifecycle's
    own identity guard rejects it - defense in depth on top of the real
    observer's own "always re-read the exact known number" design."""
    from app.calyx_orchestrator.github_agent_lifecycle import (
        PullRequestObservation,
        reconcile_agent_lifecycle,
    )

    record = existing_dispatch(pull_request_number=404, state=AgentLifecycleState.CI_PENDING)
    moved = PullRequestObservation(repository=REPOSITORY, issue_number=402, pull_request_number=999)

    with pytest.raises(PermissionError, match="GITHUB_AGENT_OBSERVATION_PR_MISMATCH"):
        reconcile_agent_lifecycle(record, moved)
