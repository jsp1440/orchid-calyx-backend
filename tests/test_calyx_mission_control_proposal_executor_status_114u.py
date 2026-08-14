from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.git_proposal_mutation_journal import (
    DurableGitProposalMutationJournal,
    GitProposalMutationJournalEventRecord,
)
from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationReceipt,
    GitProposalOperationEvidence,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256
from app.database import Base
from app.mission_control_briefing.proposal_execution_status import (
    proposal_execution_mission_control_status,
)
from app.mission_control_briefing.proposal_executor_status import (
    proposal_executor_mission_control_status,
)
from app.mission_control_briefing.routes import router

REPOSITORY = "jsp1440/orchid-calyx-backend"
OWNER = "principal:owner"
PLAN_A = "a" * 64
PLAN_B = "b" * 64
BASE_SHA = "1" * 40
COMMIT_SHA = "2" * 40


def _db(*, with_journal: bool = True) -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    if with_journal:
        Base.metadata.create_all(
            engine,
            tables=[GitProposalMutationJournalEventRecord.__table__],
        )
    return Session(engine)


def _evidence(action: str, payload: dict[str, object]) -> GitProposalOperationEvidence:
    return GitProposalOperationEvidence(
        action=action,
        status=str(payload["status"]),
        evidence_digest=canonical_sha256(payload),
        payload=payload,
    )


def _active_receipt() -> GitProposalMutationReceipt:
    branch = "autonomy/proposal/status-fixture"
    branch_payload = {
        "action": "create_branch",
        "status": "created",
        "repository": REPOSITORY,
        "branch": branch,
        "base_commit_sha": BASE_SHA,
    }
    commit_payload = {
        "action": "create_commit",
        "status": "created",
        "repository": REPOSITORY,
        "branch": branch,
        "parent_commit_sha": BASE_SHA,
        "commit_sha": COMMIT_SHA,
        "patch_program_job_id": "patch-active",
        "change_hashes": [],
        "tree_sha": "3" * 40,
    }
    return GitProposalMutationReceipt(
        plan_digest=PLAN_A,
        patch_program_job_id="patch-active",
        repository=REPOSITORY,
        proposed_branch=branch,
        base_commit_sha=BASE_SHA,
        base_ref="main",
        status="in_progress",
        completed_actions=("create_branch", "create_commit"),
        operation_evidence=(
            _evidence("create_branch", branch_payload),
            _evidence("create_commit", commit_payload),
        ),
        failure_code=None,
    )


def _completed_receipt() -> GitProposalMutationReceipt:
    branch = "autonomy/proposal/completed-fixture"
    payloads = (
        {
            "action": "create_branch",
            "status": "created",
            "repository": REPOSITORY,
            "branch": branch,
            "base_commit_sha": BASE_SHA,
        },
        {
            "action": "create_commit",
            "status": "created",
            "repository": REPOSITORY,
            "branch": branch,
            "parent_commit_sha": BASE_SHA,
            "commit_sha": COMMIT_SHA,
            "patch_program_job_id": "patch-completed",
            "change_hashes": [],
            "tree_sha": "3" * 40,
        },
        {
            "action": "push_branch",
            "status": "created",
            "repository": REPOSITORY,
            "branch": branch,
            "commit_sha": COMMIT_SHA,
        },
        {
            "action": "open_pull_request",
            "status": "created",
            "repository": REPOSITORY,
            "branch": branch,
            "head_branch": branch,
            "base_ref": "main",
            "base_commit_sha": BASE_SHA,
            "head_commit_sha": COMMIT_SHA,
            "pull_request_number": 1234,
            "pull_request_url": "https://github.com/jsp1440/orchid-calyx-backend/pull/1234",
            "draft": True,
        },
    )
    return GitProposalMutationReceipt(
        plan_digest=PLAN_B,
        patch_program_job_id="patch-completed",
        repository=REPOSITORY,
        proposed_branch=branch,
        base_commit_sha=BASE_SHA,
        base_ref="main",
        status="completed",
        completed_actions=(
            "create_branch",
            "create_commit",
            "push_branch",
            "open_pull_request",
        ),
        operation_evidence=tuple(_evidence(str(item["action"]), item) for item in payloads),
        failure_code=None,
    )


def test_mission_control_status_is_read_only_and_blocked_by_default() -> None:
    status = proposal_executor_mission_control_status({})
    assert status["schema"] == "calyx-mission-control-proposal-executor-status-v1"
    assert status["status"] == "blocked"
    assert status["read_only"] is True
    assert status["mutation_performed"] is False
    assert status["secret_material_exposed"] is False
    assert status["evidence_chain_complete_through_policy"] is True
    assert status["live_credential_registration_active"] is False
    assert status["policy"]["enabled"] is False
    assert status["policy"]["external_side_effects"] is False
    assert "executor_disabled" in status["policy"]["blockers"]


def test_enabled_configuration_remains_blocked_without_credential_readiness() -> None:
    status = proposal_executor_mission_control_status(
        {
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true",
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER": OWNER,
            "CALYX_GITHUB_PROPOSAL_REPOSITORIES": REPOSITORY,
        }
    )
    assert status["status"] == "blocked"
    assert status["policy"]["credential_ready"] is False
    assert status["policy"]["external_side_effects"] is False
    assert "credential_not_ready" in status["policy"]["blockers"]


def test_status_never_widens_authority_even_when_all_readiness_inputs_are_true() -> None:
    status = proposal_executor_mission_control_status(
        {
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true",
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER": OWNER,
            "CALYX_GITHUB_PROPOSAL_REPOSITORIES": REPOSITORY,
        },
        credential_ready=True,
    )
    assert status["status"] == "ready"
    assert status["policy"]["ready_for_owner_authorized_draft_pr"] is True
    assert status["authority"]["draft_pull_request_only"] is True
    for field in (
        "merge_authorized",
        "automatic_merge_authorized",
        "deployment_authorized",
        "publication_authorized",
        "taxonomy_activation_authorized",
        "production_database_mutation_authorized",
        "production_graph_mutation_authorized",
        "credential_disclosure_authorized",
        "spending_authorized",
    ):
        assert status["authority"][field] is False
    assert status["mutation_performed"] is False


def test_invalid_repository_configuration_is_reported_fail_closed() -> None:
    status = proposal_executor_mission_control_status(
        {
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true",
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER": OWNER,
            "CALYX_GITHUB_PROPOSAL_REPOSITORIES": "org/repo name",
        },
        credential_ready=True,
    )
    assert status["status"] == "blocked"
    assert status["policy"]["valid"] is False
    assert status["policy"]["external_side_effects"] is False


def test_execution_status_fails_closed_when_journal_table_is_unavailable() -> None:
    with _db(with_journal=False) as session:
        status = proposal_execution_mission_control_status(session)
    assert status["journal_available"] is False
    assert status["journal_error"] == "durable_mutation_journal_table_unavailable"
    assert status["active_execution"] is None
    assert status["read_only"] is True
    assert status["mutation_performed_by_status_read"] is False
    assert status["secret_material_exposed"] is False


def test_execution_status_surfaces_active_operation_and_exact_provenance() -> None:
    with _db() as session:
        DurableGitProposalMutationJournal(session).record(_active_receipt(), event_index=1)
        status = proposal_execution_mission_control_status(session)
    active = status["active_execution"]
    assert status["journal_available"] is True
    assert active is not None
    assert active["plan_digest"] == PLAN_A
    assert active["patch_program_job_id"] == "patch-active"
    assert active["repository"] == REPOSITORY
    assert active["base_ref"] == "main"
    assert active["base_commit_sha"] == BASE_SHA
    assert active["commit_sha"] == COMMIT_SHA
    assert active["completed_actions"] == ["create_branch", "create_commit"]
    assert active["current_remote_operation"] == "push_branch"
    assert active["terminal"] is False
    assert active["remote_side_effects_recorded"] is True


def test_execution_status_surfaces_completed_draft_pr_without_secret_or_write() -> None:
    with _db() as session:
        DurableGitProposalMutationJournal(session).record(_completed_receipt(), event_index=1)
        status = proposal_execution_mission_control_status(session)
    latest = status["latest_execution"]
    assert latest is not None
    assert latest["status"] == "completed"
    assert latest["current_remote_operation"] is None
    assert latest["terminal"] is True
    assert latest["draft_pull_request"] == {
        "number": 1234,
        "url": "https://github.com/jsp1440/orchid-calyx-backend/pull/1234",
        "draft": True,
    }
    assert status["active_execution"] is None
    assert status["mutation_performed_by_status_read"] is False
    assert status["secret_material_exposed"] is False


def test_execution_status_prefers_newest_active_plan_but_preserves_recent_history() -> None:
    with _db() as session:
        journal = DurableGitProposalMutationJournal(session)
        journal.record(_completed_receipt(), event_index=1)
        journal.record(_active_receipt(), event_index=1)
        status = proposal_execution_mission_control_status(session)
    assert status["recent_execution_count"] == 2
    assert status["latest_execution"]["plan_digest"] == PLAN_A
    assert status["active_execution"]["plan_digest"] == PLAN_A
    assert [item["plan_digest"] for item in status["recent_executions"]] == [
        PLAN_A,
        PLAN_B,
    ]


def test_authenticated_briefing_router_exposes_proposal_executor_route() -> None:
    paths = {route.path for route in router.routes}
    assert "/api/mission-control/briefing/proposal-executor" in paths
