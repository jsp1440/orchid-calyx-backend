import pytest

from app.calyx_orchestrator.github_coding_executor import (
    BudgetClass,
    ConvergenceClass,
    DispatchRequest,
)
from app.calyx_orchestrator.provider_free_coding_adapter import (
    PROVIDER_FREE_EXECUTOR,
    DeterministicWorkerReceipt,
    ProviderFreeCodingAdapter,
)


def request():
    return DispatchRequest(
        mission_id="mission-1",
        repository="orchid-calyx-backend",
        objective="bounded deterministic repair",
        acceptance_criteria=("tests pass",),
        validation_commands=("pytest -q",),
        budget_class=BudgetClass.TINY,
        convergence_class=ConvergenceClass.NEW,
        base_ref="oc-autonomous-integration",
        base_sha="a" * 40,
        related_issue_numbers=(700,),
        overlapping_pr_numbers=(),
        continuation_pr_numbers=(),
        convergence_pr_numbers=(),
        superseded_pr_numbers=(),
        retry_count=0,
    )


def receipt(**kw):
    base = {
        "branch": "oc-auto-mission-1",
        "issue_number": 700,
        "pull_request_number": 1490,
        "pull_request_url": "https://github.com/jsp1440/orchid-calyx-backend/pull/1490",
        "head_sha": "b" * 40,
        "validation_evidence": ("pytest:passed",),
    }
    base.update(kw)
    return DeterministicWorkerReceipt(**base)


def test_provider_free_adapter_preserves_governed_identity():
    adapter = ProviderFreeCodingAdapter(lambda _: receipt())
    result = adapter.dispatch(request())
    assert result.provider == "provider-free"
    assert result.executor_class == PROVIDER_FREE_EXECUTOR
    assert result.repository == "orchid-calyx-backend"
    assert result.base_sha == "a" * 40
    assert result.draft is True
    assert result.pull_request_number == 1490


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"branch": ""}, "PROVIDER_FREE_WORKER_BRANCH_REQUIRED"),
        ({"issue_number": 0}, "PROVIDER_FREE_WORKER_GITHUB_LINEAGE_REQUIRED"),
        ({"pull_request_number": 0}, "PROVIDER_FREE_WORKER_GITHUB_LINEAGE_REQUIRED"),
        ({"head_sha": "short"}, "PROVIDER_FREE_WORKER_HEAD_SHA_INVALID"),
        ({"pull_request_url": "not-github"}, "PROVIDER_FREE_WORKER_PR_URL_INVALID"),
    ],
)
def test_provider_free_adapter_fails_closed_on_invalid_receipts(override, error):
    adapter = ProviderFreeCodingAdapter(lambda _: receipt(**override))
    with pytest.raises(ValueError, match=error):
        adapter.dispatch(request())
