from pathlib import Path


WORKFLOW = Path(".github/workflows/orchid-completion-lane.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_repair_backoff_blocks_completion_lane_before_provider_execution() -> None:
    text = _workflow_text()
    lease = text[text.index("- name: Verify scheduler lease") : text.index("- name: Load issue context")]
    assert 'if [[ "$labels" == *oc-repair-backoff* ]]' in lease
    assert lease.index("oc-repair-backoff") < lease.index('elif [[ "$labels" == *oc-running* ]]')
    assert "--remove-label oc-running --remove-label oc-queued --remove-label oc-repair --remove-label oc-validating" in lease
    assert 'echo "execute=false" >> "$GITHUB_OUTPUT"' in lease


def test_repair_backoff_is_authoritative_during_worker_settlement() -> None:
    text = _workflow_text()
    settle = text[text.index("- name: Classify result, dispatch validation, release slot") :]
    guard = 'if [[ "$latest_labels" == *oc-repair-backoff* ]]'
    first_requeue = "--add-label oc-queued"
    assert guard in settle
    assert settle.index(guard) < settle.index(first_requeue)
    assert "--remove-label oc-running --remove-label oc-queued --remove-label oc-repair --remove-label oc-validating" in settle
    assert "exit 0" in settle[settle.index(guard) : settle.index(first_requeue)]


def test_all_no_durable_pr_requeue_paths_are_behind_repair_backoff_guard() -> None:
    text = _workflow_text()
    settle = text[text.index("- name: Classify result, dispatch validation, release slot") :]
    guard_pos = settle.index('if [[ "$latest_labels" == *oc-repair-backoff* ]]')
    for marker in (
        'elif [[ "$CLAUDE_FALLBACK" == "true" && "$GEMINI_OUTCOME" == "success" ]]',
        'elif [[ "$GEMINI_FALLBACK" == "true" && "$OPENAI_OUTCOME" == "success" ]]',
        'Preferred provider completed without a durable integration PR.',
    ):
        assert settle.index(marker) > guard_pos
