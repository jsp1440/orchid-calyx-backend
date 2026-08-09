from __future__ import annotations

from datetime import timedelta

import pytest

from app.calyx_orchestrator.git_proposal_execution_plan import GitProposalExecutionPlanner
from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationError,
    GitProposalMutationExecutor,
    _require_dependency_closed_prefix,
)
from tests.test_calyx_git_proposal_execution_plan_114r import (
    BASE_COMMIT,
    BASE_REF,
    NOW,
    PATCH_AFTER,
    REPOSITORY,
    _authorization,
    _manifest,
    _store,
)

COMMIT_SHA = "9" * 40


class FakeMutationAdapter:
    def __init__(
        self,
        *,
        fail_action: str | None = None,
        wrong_push: bool = False,
        wrong_base_ref: bool = False,
        pull_request_number: int | bool = 1234,
    ) -> None:
        self.fail_action = fail_action
        self.wrong_push = wrong_push
        self.wrong_base_ref = wrong_base_ref
        self.pull_request_number = pull_request_number
        self.calls: list[str] = []

    def apply_proposal_operation(self, *, plan_digest: str, operation):
        assert len(plan_digest) == 64
        self.calls.append(operation.action)
        if operation.action == self.fail_action:
            raise RuntimeError("FAKE_REMOTE_FAILURE")
        common = {
            "action": operation.action,
            "status": "created",
            "repository": REPOSITORY,
            "branch": "autonomy/proposal/work-123",
        }
        if operation.action == "create_branch":
            return {**common, "base_commit_sha": BASE_COMMIT}
        if operation.action == "create_commit":
            return {
                **common,
                "parent_commit_sha": BASE_COMMIT,
                "commit_sha": COMMIT_SHA,
                "patch_program_job_id": operation.parameters["patch_program_job_id"],
                "change_hashes": [
                    {"path": "app/example.py", "after_sha256": PATCH_AFTER}
                ],
            }
        if operation.action == "push_branch":
            return {
                **common,
                "commit_sha": "8" * 40 if self.wrong_push else COMMIT_SHA,
            }
        if operation.action == "open_pull_request":
            return {
                **common,
                "head_branch": "autonomy/proposal/work-123",
                "base_ref": "release/other" if self.wrong_base_ref else BASE_REF,
                "base_commit_sha": BASE_COMMIT,
                "head_commit_sha": COMMIT_SHA,
                "pull_request_number": self.pull_request_number,
            }
        raise AssertionError(operation.action)


def _execution_inputs():
    store, patch_job_id = _store()
    gate, request, grant = _authorization(store, patch_job_id)
    manifest = _manifest(patch_job_id)
    plan = GitProposalExecutionPlanner.build(
        manifest_snapshot=manifest,
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    return store, gate, request, grant, manifest, plan, patch_job_id


def _execute(adapter: FakeMutationAdapter):
    store, gate, request, grant, manifest, plan, patch_job_id = _execution_inputs()
    receipt = GitProposalMutationExecutor(
        adapter=adapter,
        repository_allowlist=(REPOSITORY,),
    ).execute(
        plan=plan,
        manifest_snapshot=manifest,
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    return receipt, patch_job_id


def test_current_main_executor_completes_exact_evidence_bound_flow() -> None:
    adapter = FakeMutationAdapter()
    receipt, patch_job_id = _execute(adapter)
    assert adapter.calls == [
        "create_branch",
        "create_commit",
        "push_branch",
        "open_pull_request",
    ]
    snapshot = receipt.snapshot()
    assert snapshot["schema"] == "calyx-git-proposal-mutation-receipt-v3"
    assert snapshot["patch_program_job_id"] == patch_job_id
    assert snapshot["base_ref"] == BASE_REF
    assert snapshot["status"] == "completed"
    assert snapshot["merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["production_database_mutation_authorized"] is False
    assert snapshot["production_graph_mutation_authorized"] is False


def test_dependency_policy_rejects_sparse_or_reordered_actions() -> None:
    _require_dependency_closed_prefix(("create_branch", "create_commit"))
    with pytest.raises(PermissionError, match="ACTION_DEPENDENCY_INVALID"):
        _require_dependency_closed_prefix(("create_branch", "open_pull_request"))
    with pytest.raises(PermissionError, match="ACTION_DEPENDENCY_INVALID"):
        _require_dependency_closed_prefix(("create_commit", "create_branch"))


def test_authorization_is_reverified_before_each_remote_mutation() -> None:
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    times = iter(
        (
            NOW + timedelta(minutes=1),
            NOW + timedelta(minutes=2),
            NOW + timedelta(minutes=3),
            NOW + timedelta(minutes=16),
        )
    )
    gate._clock = lambda: next(times)
    adapter = FakeMutationAdapter()
    executor = GitProposalMutationExecutor(
        adapter=adapter,
        repository_allowlist=(REPOSITORY,),
    )
    with pytest.raises(GitProposalMutationError) as raised:
        executor.execute(
            plan=plan,
            manifest_snapshot=manifest,
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )
    assert raised.value.code == "GIT_AUTHORIZATION_GRANT_EXPIRED_OR_INVALID"
    assert raised.value.receipt.completed_actions == (
        "create_branch",
        "create_commit",
    )
    assert adapter.calls == ["create_branch", "create_commit"]


def test_wrong_push_commit_preserves_specific_failure_code() -> None:
    adapter = FakeMutationAdapter(wrong_push=True)
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    with pytest.raises(GitProposalMutationError) as raised:
        GitProposalMutationExecutor(
            adapter=adapter,
            repository_allowlist=(REPOSITORY,),
        ).execute(
            plan=plan,
            manifest_snapshot=manifest,
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )
    assert raised.value.code == "GIT_PROPOSAL_EXECUTOR_PUSH_COMMIT_MISMATCH"
    assert raised.value.receipt.failure_code == raised.value.code
    assert raised.value.receipt.completed_actions == (
        "create_branch",
        "create_commit",
    )


def test_remote_failure_preserves_message_and_verified_completed_actions() -> None:
    adapter = FakeMutationAdapter(fail_action="push_branch")
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    with pytest.raises(GitProposalMutationError) as raised:
        GitProposalMutationExecutor(
            adapter=adapter,
            repository_allowlist=(REPOSITORY,),
        ).execute(
            plan=plan,
            manifest_snapshot=manifest,
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )
    assert raised.value.code == "FAKE_REMOTE_FAILURE"
    assert raised.value.receipt.status == "partial_failure"
    assert raised.value.receipt.completed_actions == (
        "create_branch",
        "create_commit",
    )


def test_pull_request_base_ref_must_match_reviewed_plan() -> None:
    adapter = FakeMutationAdapter(wrong_base_ref=True)
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    with pytest.raises(GitProposalMutationError) as raised:
        GitProposalMutationExecutor(
            adapter=adapter,
            repository_allowlist=(REPOSITORY,),
        ).execute(
            plan=plan,
            manifest_snapshot=manifest,
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )
    assert raised.value.code == "GIT_PROPOSAL_EXECUTOR_PR_TARGET_MISMATCH"
    assert raised.value.receipt.completed_actions == (
        "create_branch",
        "create_commit",
        "push_branch",
    )


def test_boolean_pull_request_number_is_rejected_with_specific_code() -> None:
    adapter = FakeMutationAdapter(pull_request_number=True)
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    with pytest.raises(GitProposalMutationError) as raised:
        GitProposalMutationExecutor(
            adapter=adapter,
            repository_allowlist=(REPOSITORY,),
        ).execute(
            plan=plan,
            manifest_snapshot=manifest,
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )
    assert raised.value.code == "GIT_PROPOSAL_EXECUTOR_PR_NUMBER_INVALID"
    assert raised.value.receipt.completed_actions == (
        "create_branch",
        "create_commit",
        "push_branch",
    )
