from __future__ import annotations

import pytest

from app.calyx_orchestrator.git_proposal_execution_plan import (
    GitProposalExecutionPlanner,
)


def test_dependency_closed_action_prefixes_are_allowed() -> None:
    for actions in (
        ("create_branch",),
        ("create_branch", "create_commit"),
        ("create_branch", "create_commit", "push_branch"),
        ("create_branch", "create_commit", "push_branch", "open_pull_request"),
    ):
        GitProposalExecutionPlanner._require_dependency_closed_actions(actions)


@pytest.mark.parametrize(
    "actions",
    [
        ("create_commit",),
        ("push_branch",),
        ("open_pull_request",),
        ("create_branch", "push_branch"),
        ("create_branch", "open_pull_request"),
        ("create_branch", "create_commit", "open_pull_request"),
    ],
)
def test_sparse_or_out_of_dependency_actions_fail_closed(actions: tuple[str, ...]) -> None:
    with pytest.raises(PermissionError, match="ACTION_PREREQUISITE_MISSING"):
        GitProposalExecutionPlanner._require_dependency_closed_actions(actions)


def test_unknown_action_fails_closed() -> None:
    with pytest.raises(PermissionError, match="ACTION_SET_INVALID"):
        GitProposalExecutionPlanner._require_dependency_closed_actions(
            ("create_branch", "merge_pull_request")
        )
