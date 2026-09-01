from pathlib import Path  # noqa: I001 -- standalone workflow contract test keeps only stdlib Path


WORKFLOW = Path(".github/workflows/orchid-continuous-completion.yml")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[begin:finish]


def test_repair_backoff_invariant_strips_execution_eligibility():
    text = workflow_text()
    heal = section(
        text,
        "- name: Heal portfolio queue invariants",
        "- name: Manage Claude runtime circuit",
    )
    assert "--label oc-repair-backoff --label oc-queued" in heal
    assert "--label oc-repair-backoff --label oc-running" in heal
    assert "--label oc-repair-backoff --label oc-repair" in heal
    assert (
        'gh issue edit "$issue" --repo "$REPO" --remove-label oc-queued '
        "--remove-label oc-running --remove-label oc-repair"
    ) in heal


def test_orphaned_repair_healer_never_requeues_repair_backoff():
    text = workflow_text()
    heal = section(
        text,
        "- name: Heal portfolio queue invariants",
        "- name: Manage Claude runtime circuit",
    )
    repair_branch = heal[heal.index("mapfile -t repairs") :]
    assert '"$labels" != *oc-repair-backoff*' in repair_branch
    assert "--add-label oc-queued" in repair_branch


def test_runtime_recovery_does_not_requeue_repair_backoff():
    text = workflow_text()
    runtime = section(
        text,
        "- name: Manage Claude runtime circuit",
        "- name: Dispatch priority-aware portfolio workers",
    )
    assert "--json number,labels" in runtime
    assert 'if [[ "$labels" == *oc-repair-backoff* ]]; then' in runtime
    guarded = runtime[
        runtime.index('if [[ "$labels" == *oc-repair-backoff* ]]; then') :
        runtime.index("continue", runtime.index('if [[ "$labels" == *oc-repair-backoff* ]]; then'))
    ]
    assert "--remove-label oc-runtime-backoff" in guarded
    assert "--remove-label oc-queued" in guarded
    assert "--add-label oc-queued" not in guarded


def test_stale_lease_reclaim_respects_repair_backoff():
    text = workflow_text()
    reclaim = section(
        text,
        "- name: Reclaim abandoned lanes",
        "- name: Validate and integrate delivered worker PRs",
    )
    assert "--json number,updatedAt,labels" in reclaim
    assert 'if [[ "$labels" == *oc-repair-backoff* ]]; then' in reclaim
    backed_off = reclaim[
        reclaim.index('if [[ "$labels" == *oc-repair-backoff* ]]; then') :
        reclaim.index("continue", reclaim.index('if [[ "$labels" == *oc-repair-backoff* ]]; then'))
    ]
    assert "--remove-label oc-running" in backed_off
    assert "--remove-label oc-queued" in backed_off
    assert "--add-label oc-queued" not in backed_off


def test_entering_repair_backoff_releases_all_execution_labels():
    text = workflow_text()
    dispatch = section(
        text,
        "- name: Dispatch priority-aware portfolio workers",
        "- name: Maintain integration-to-main owner gate",
    )
    limit = dispatch.index("if (( attempts >= MAX_REPAIR_ATTEMPTS )); then")
    parking = dispatch[limit : dispatch.index("continue", limit)]
    assert "--remove-label oc-running" in parking
    assert "--remove-label oc-queued" in parking
    assert "--remove-label oc-repair" in parking
    assert "--add-label oc-repair-backoff" in parking


def test_dispatch_rechecks_repair_backoff_immediately_before_leasing():
    text = workflow_text()
    dispatch = section(
        text,
        "- name: Dispatch priority-aware portfolio workers",
        "- name: Maintain integration-to-main owner gate",
    )
    state_read = dispatch.index('labels=$(gh issue view "$issue"')
    backoff_guard = dispatch.index('[[ "$labels" == *oc-repair-backoff* ]] && continue', state_read)
    lease = dispatch.index('gh issue edit "$issue" --repo "$REPO" --remove-label oc-queued --remove-label oc-validating --add-label oc-running', state_read)
    assert state_read < backoff_guard < lease


def test_dispatch_failure_cannot_requeue_concurrent_repair_backoff():
    text = workflow_text()
    dispatch = section(
        text,
        "- name: Dispatch priority-aware portfolio workers",
        "- name: Maintain integration-to-main owner gate",
    )
    failure = dispatch[dispatch.index("else\n              latest_labels") :]
    assert 'if [[ "$latest_labels" == *oc-repair-backoff* ]]; then' in failure
    guarded = failure[
        failure.index('if [[ "$latest_labels" == *oc-repair-backoff* ]]; then') :
        failure.index("else", failure.index('if [[ "$latest_labels" == *oc-repair-backoff* ]]; then'))
    ]
    assert "--remove-label oc-running" in guarded
    assert "--remove-label oc-queued" in guarded
    assert "--add-label oc-queued" not in guarded
