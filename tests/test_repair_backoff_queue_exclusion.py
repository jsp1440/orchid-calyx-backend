from pathlib import Path

WORKFLOW = Path(".github/workflows/orchid-continuous-completion.yml")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[begin:finish]


def test_repair_backoff_strips_all_execution_labels():
    text = workflow_text()
    heal = section(text, "- name: Heal portfolio queue invariants", "- name: Manage Claude runtime circuit")
    assert "--label oc-repair-backoff --label oc-queued" in heal
    assert "--label oc-repair-backoff --label oc-running" in heal
    assert "--label oc-repair-backoff --label oc-repair" in heal
    assert '--remove-label oc-queued --remove-label oc-running --remove-label oc-repair' in heal


def test_orphan_repair_healer_excludes_repair_backoff():
    text = workflow_text()
    heal = section(text, "- name: Heal portfolio queue invariants", "- name: Manage Claude runtime circuit")
    repairs = heal[heal.index("mapfile -t repairs") :]
    assert '"$labels" != *oc-repair-backoff*' in repairs
    assert "--add-label oc-queued" in repairs


def test_entering_repair_backoff_releases_execution_labels():
    text = workflow_text()
    dispatch = section(text, "- name: Dispatch priority-aware portfolio workers", "- name: Maintain integration-to-main owner gate")
    start = dispatch.index("if (( attempts >= MAX_REPAIR_ATTEMPTS )); then")
    parking = dispatch[start : dispatch.index("continue", start)]
    assert "--remove-label oc-running" in parking
    assert "--remove-label oc-queued" in parking
    assert "--remove-label oc-repair" in parking
    assert "--add-label oc-repair-backoff" in parking


def test_stale_reclaim_never_requeues_repair_backoff():
    text = workflow_text()
    reclaim = section(text, "- name: Reclaim abandoned lanes", "- name: Validate and integrate delivered worker PRs")
    assert "--json number,updatedAt,labels" in reclaim
    assert 'if [[ "$labels" == *oc-repair-backoff* ]]; then' in reclaim


def test_dispatch_failure_rechecks_repair_backoff():
    text = workflow_text()
    dispatch = section(text, "- name: Dispatch priority-aware portfolio workers", "- name: Maintain integration-to-main owner gate")
    assert 'if [[ "$latest_labels" == *oc-repair-backoff* ]]; then' in dispatch
