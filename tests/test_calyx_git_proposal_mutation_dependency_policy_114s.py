from app.calyx_orchestrator.git_proposal_mutation_executor import (
    _actions_form_dependency_prefix,
)


def test_dependency_policy_accepts_only_nonempty_prefixes() -> None:
    assert _actions_form_dependency_prefix(("create_branch",))
    assert _actions_form_dependency_prefix(("create_branch", "create_commit"))
    assert _actions_form_dependency_prefix(
        ("create_branch", "create_commit", "push_branch", "open_pull_request")
    )


def test_dependency_policy_rejects_gaps_reordering_and_empty_set() -> None:
    assert not _actions_form_dependency_prefix(())
    assert not _actions_form_dependency_prefix(("create_commit",))
    assert not _actions_form_dependency_prefix(("create_branch", "push_branch"))
    assert not _actions_form_dependency_prefix(("create_branch", "open_pull_request"))
    assert not _actions_form_dependency_prefix(("create_commit", "create_branch"))
