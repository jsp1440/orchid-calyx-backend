import pytest

from runtime.github_connector_dispatcher import (
    AuditedGitHubDispatcher,
    GitHubDispatchCommand,
)


REPOSITORY = "jsp1440/orchid-calyx-backend"


def dispatcher() -> AuditedGitHubDispatcher:
    return AuditedGitHubDispatcher((REPOSITORY,))


def test_dispatcher_executes_allowlisted_branch_creation_once():
    calls = []
    command = GitHubDispatchCommand(
        repository=REPOSITORY,
        operation="create_branch",
        payload={"branch_name": "calyx/draft/example", "base_ref": "main"},
    )

    def execute(item):
        calls.append(item)
        return {"branch": item.payload["branch_name"]}

    active = dispatcher()
    first = active.dispatch(command, execute)
    second = active.dispatch(command, execute)
    assert first == second
    assert len(calls) == 1
    assert first.status == "executed"


def test_dispatcher_allows_only_draft_pull_requests_targeting_main():
    active = dispatcher()
    valid = GitHubDispatchCommand(
        repository=REPOSITORY,
        operation="create_draft_pull_request",
        payload={"head": "calyx/draft/example", "base": "main", "draft": True},
    )
    receipt = active.dispatch(valid, lambda command: {"number": 999, "draft": True})
    assert receipt.result["draft"] is True

    with pytest.raises(PermissionError):
        active.dispatch(
            GitHubDispatchCommand(
                repository=REPOSITORY,
                operation="create_draft_pull_request",
                payload={"head": "x", "base": "main", "draft": False},
                draft=False,
            ),
            lambda command: {},
        )


def test_dispatcher_rejects_unapproved_repository_and_operations():
    active = dispatcher()
    with pytest.raises(PermissionError):
        active.dispatch(
            GitHubDispatchCommand(
                repository="other/repository",
                operation="create_branch",
                payload={"branch_name": "x", "base_ref": "main"},
            ),
            lambda command: {},
        )
    with pytest.raises(PermissionError):
        active.dispatch(
            GitHubDispatchCommand(
                repository=REPOSITORY,
                operation="merge_pull_request",
                payload={"number": 1},
            ),
            lambda command: {},
        )


def test_dispatcher_status_proves_consequential_actions_are_disabled():
    status = dispatcher().status()
    assert status["automatic_merge"] is False
    assert status["automatic_deploy"] is False
    assert status["scientific_publication"] is False
    assert status["production_deletion"] is False
    assert status["external_communication"] is False
