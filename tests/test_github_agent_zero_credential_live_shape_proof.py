from __future__ import annotations

"""Zero-credential proof of the complete one-shot live-execution path,
requested before any live authorization is sought. Every orchestration
class used here is the real production class - PersistentProgramRepository,
PersistentProgramWorker (via the real composition factory), the real
convergence inspector, the real GitHubCopilotCloudProvider, the real
GitHubIssueLinkedPullRequestObserver, the real GitHubCommentRepairGateway,
the real reconcile_agent_lifecycle state machine. The only thing standing in
for anything is the GitHubTransport itself (the external network boundary)
and, for the durable store, an ephemeral in-memory SQLite database - neither
is the central orchestration state machine, consistent with what was asked
("mocks/fakes should represent only external boundaries").

test_full_chain_from_mission_creation_through_owner_review_ready is the
single new proof this file adds beyond what already exists: that a dispatch
record real execute=True creates is the exact same record real subsequent
observation calls correctly read back and reconcile through pending CI to
green CI - end to end, starting from nothing but a durably-created mission.
That specific link (real execute -> real observe of what execute just
created) was not previously exercised anywhere; every existing test either
starts from a seeded dispatch record or never advances past dispatch
creation.

test_failed_ci_bounded_repair_and_ceiling_escalation and
test_observed_merge_reaches_durable_completion cover the remaining phases
(failed CI, bounded repair, the same-failure ceiling, an observed owner
merge reaching durable completion) using the same real classes, seeded from
a durably-created dispatch record rather than re-deriving one through a
second full chain - a CI failure and a CI success cannot both be
demonstrated from one single PR/head, so this is the natural place to
branch, not a shortcut around "real classes only." (Priorities 1-3's merged
harness and #989's completion e2e suite already prove these same phases in
this same style; this file's job is specifically the mission-to-observation
link those did not cover, plus keeping all phases enumerated in one place
that a reviewer can read straight through.)
"""

from dataclasses import dataclass, field

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_composition import (
    build_production_github_coding_agent_dispatch_cycle,
)
from app.calyx_orchestrator.github_agent_dispatch_cycle import (
    EXECUTE_CONFIRMATION,
    GitHubCodingRuntimePolicy,
)
from app.calyx_orchestrator.github_agent_dispatch_store import (
    DurableGitHubAgentDispatchStore,
    GitHubAgentDispatchRecordRow,
)
from app.calyx_orchestrator.github_agent_lifecycle import (
    AgentLifecycleState,
    GitHubAgentDispatchRecord,
)
from app.calyx_orchestrator.github_agent_observation_gateway import COPILOT_BOT_LOGIN
from app.calyx_orchestrator.github_agent_one_shot_operator import (
    OneShotExecutionRequest,
    execute_one_shot_mission,
)
from app.calyx_orchestrator.github_coding_executor import (
    MAX_SAME_FAILURE_RETRIES,
    BudgetClass,
)
from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
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

REPOSITORY = "jsp1440/Orchid-Continuum-Brain"
OWNER = "jsp1440"


@dataclass
class FakeTransport:
    """Stands in only for the external GitHub network boundary."""

    responses: list[GitHubTransportResponse] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, *, json_body=None, params=None):
        del json_body, params
        self.calls.append((method, path))
        return self.responses.pop(0)

    def queue(self, response: GitHubTransportResponse) -> None:
        self.responses.append(response)


def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
            GitHubAgentDispatchRecordRow.__table__,
        ],
    )
    return Session(engine)


def enqueue_mission(db: Session, *, job_key: str) -> str:
    repo = PersistentProgramRepository(db)
    program = repo.create_program(
        owner=OWNER,
        title="Zero-credential live-shape proof",
        objective="Prove the complete one-shot path with real classes and a fake transport only",
        jobs=[
            ProgramJobSpec(
                job_key=job_key,
                role_key="github_coding_agent",
                title="Live-shape proof mission",
                repository=REPOSITORY,
                branch=f"agent/{job_key}",
                mutating=True,
                inputs={"budget_class": "TINY", "mission_id": job_key},
            )
        ],
        dependencies=[],
    )
    repo.start(owner=OWNER, program_id=program.program_id)
    db.commit()
    job = db.query(CalyxProgramJob).filter(CalyxProgramJob.job_key == job_key).one()
    return job.program_job_id


def runtime_policy() -> GitHubCodingRuntimePolicy:
    return GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({REPOSITORY}),
        max_budget_class=BudgetClass.TINY,
    )


def required_checks() -> RequiredCiCheckPolicy:
    return RequiredCiCheckPolicy(required_checks=frozenset({"validate"}))


def real_cycle(db: Session, transport: FakeTransport):
    return build_production_github_coding_agent_dispatch_cycle(
        db=db, transport=transport, policy=runtime_policy(), required_checks=required_checks()
    )


def pr_payload(*, number: int, head_sha: str, draft: bool = True, merged: bool = False, state: str = "open"):
    return {
        "number": number,
        "draft": draft,
        "merged": merged,
        "state": state,
        "html_url": f"https://github.com/{REPOSITORY}/pull/{number}",
        "user": {"login": COPILOT_BOT_LOGIN},
        "base": {"repo": {"full_name": REPOSITORY}},
        "head": {"sha": head_sha},
    }


def cross_referenced_event(*, pr_number: int):
    return {
        "event": "cross-referenced",
        "source": {
            "type": "issue",
            "issue": {
                "number": pr_number,
                "user": {"login": COPILOT_BOT_LOGIN},
                "pull_request": {},
                "repository": {"full_name": REPOSITORY},
            },
        },
    }


def test_full_chain_from_mission_creation_through_owner_review_ready() -> None:
    db = db_session()
    program_job_id = enqueue_mission(db, job_key="chain-mission-001")

    # 1-2. mission -> convergence -> admission -> claim -> preflight
    preflight_transport = FakeTransport()
    preflight = real_cycle(db, preflight_transport).run_once(owner=OWNER, execute=False)
    assert preflight.state == "preflight_ready"
    assert preflight_transport.calls == []  # no dispatch exists yet - preflight never touches the network

    # 3. execute authorization evaluation -> provider dispatch shape (via the
    # one-shot operator, proving its identity pre-check against the real job
    # just created, then the real convergence + admission + claim + dispatch)
    execute_transport = FakeTransport()
    execute_transport.queue(GitHubTransportResponse(200, {"object": {"sha": "a" * 40}}))
    execute_transport.queue(GitHubTransportResponse(200, []))
    execute_transport.queue(GitHubTransportResponse(200, []))
    execute_transport.queue(GitHubTransportResponse(201, {"number": 5001}))
    dispatched = execute_one_shot_mission(
        db=db,
        transport=execute_transport,
        request=OneShotExecutionRequest(
            owner=OWNER,
            repository=REPOSITORY,
            expected_program_job_id=program_job_id,
            budget_class=BudgetClass.TINY,
            required_checks=required_checks(),
            confirmation=EXECUTE_CONFIRMATION,
        ),
    )
    assert dispatched.state == "agent_assigned"
    assert dispatched.issue_number == 5001

    # 4. PR observation - no linked PR yet
    observe_transport_1 = FakeTransport()
    observe_transport_1.queue(GitHubTransportResponse(200, []))
    result_1 = real_cycle(db, observe_transport_1).run_once(owner=OWNER, execute=False)
    assert result_1.state == AgentLifecycleState.AWAITING_PR.value

    # 5. PR observation - linked PR found, CI pending
    observe_transport_2 = FakeTransport()
    observe_transport_2.queue(GitHubTransportResponse(200, [cross_referenced_event(pr_number=5002)]))
    observe_transport_2.queue(GitHubTransportResponse(200, pr_payload(number=5002, head_sha="b" * 40)))
    observe_transport_2.queue(GitHubTransportResponse(200, {"check_runs": []}))
    result_2 = real_cycle(db, observe_transport_2).run_once(owner=OWNER, execute=False)
    assert result_2.state == AgentLifecycleState.CI_PENDING.value
    assert result_2.pull_request_number == 5002

    # 6. PR observation - CI green -> ready_for_owner_review
    observe_transport_3 = FakeTransport()
    observe_transport_3.queue(GitHubTransportResponse(200, pr_payload(number=5002, head_sha="c" * 40)))
    observe_transport_3.queue(
        GitHubTransportResponse(200, {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "success"}]})
    )
    result_3 = real_cycle(db, observe_transport_3).run_once(owner=OWNER, execute=False)
    assert result_3.state == AgentLifecycleState.READY_FOR_OWNER_REVIEW.value
    assert result_3.action == "owner_review"


def _seeded_dispatch_program(db: Session, *, job_key: str) -> str:
    """Seed a durable dispatch record the same way test_phase_2_github_agent_973_completion_e2e.py
    does - a real record, real store, real lifecycle state, only its creation
    is fast-forwarded rather than re-derived from a second full execute
    chain (already proven possible above)."""
    program_job_id = enqueue_mission(db, job_key=job_key)
    store = DurableGitHubAgentDispatchStore(db)
    store.record(
        GitHubAgentDispatchRecord(
            program_job_id=program_job_id,
            mission_id=job_key,
            repository=REPOSITORY,
            base_sha="a" * 40,
            provider="github-copilot-cloud-agent",
            issue_number=9001,
            state=AgentLifecycleState.CI_PENDING,
            pull_request_number=9002,
        )
    )
    return program_job_id


def test_failed_ci_bounded_repair_and_ceiling_escalation() -> None:
    db = db_session()
    program_job_id = _seeded_dispatch_program(db, job_key="repair-mission-001")

    # 7. failed CI -> bounded repair, repeated up to the existing ceiling
    for attempt in range(1, MAX_SAME_FAILURE_RETRIES + 1):
        transport = FakeTransport()
        transport.queue(GitHubTransportResponse(200, pr_payload(number=9002, head_sha=f"{attempt}" * 40)))
        transport.queue(
            GitHubTransportResponse(
                200, {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "failure"}]}
            )
        )
        transport.queue(GitHubTransportResponse(201, {"html_url": f"https://github.com/{REPOSITORY}/pull/9002#issuecomment-{attempt}"}))
        result = real_cycle(db, transport).run_once(owner=OWNER, execute=True, confirmation=EXECUTE_CONFIRMATION)
        assert result.action == "repair_requested"
        assert transport.calls[-1] == ("POST", f"/repos/{REPOSITORY}/issues/9002/comments")

    # same deterministic failure again, budget now exhausted -> escalate/blocked
    final_transport = FakeTransport()
    final_transport.queue(GitHubTransportResponse(200, pr_payload(number=9002, head_sha="f" * 40)))
    final_transport.queue(
        GitHubTransportResponse(
            200, {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "failure"}]}
        )
    )
    escalated = real_cycle(db, final_transport).run_once(owner=OWNER, execute=True, confirmation=EXECUTE_CONFIRMATION)
    assert escalated.action == "escalate"
    assert escalated.state == AgentLifecycleState.BLOCKED.value
    # No further repair comment was posted once the ceiling was reached.
    assert all(call[0] != "POST" for call in final_transport.calls)
    assert escalated.program_job_id == program_job_id


def test_observed_merge_reaches_durable_completion() -> None:
    db = db_session()
    program_job_id = _seeded_dispatch_program(db, job_key="merge-mission-001")

    transport = FakeTransport()
    transport.queue(GitHubTransportResponse(200, pr_payload(number=9002, head_sha="d" * 40, merged=True, draft=False, state="closed")))
    result = real_cycle(db, transport).run_once(owner=OWNER, execute=False)

    assert result.state == AgentLifecycleState.MERGED.value
    assert result.action == "mark_delivered"
    # Durable completion is DELIVERED only because GitHub itself reported
    # merged=True - nothing in this chain merged anything. Verify the real
    # durable job row, not just the in-memory result object.
    job = db.get(CalyxProgramJob, program_job_id)
    db.refresh(job)
    assert job.outcome == TerminalOutcome.DELIVERED.value
    assert job.status == "completed"
    assert job.lease_owner is None
