from pathlib import Path


LEGACY = Path(".github/workflows/orchid-continuous-completion.yml")
SWARM = Path(".github/workflows/orchid-swarm-controller.yml")
CANARY = Path(".github/workflows/orchid-gemini-runtime-canary.yml")


def section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[begin:finish]


def test_legacy_scheduler_is_a_manual_swarm_redirect_only():
    text = LEGACY.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "pull_request:" not in text
    assert "issues:" not in text
    assert "oc_portfolio_scheduler.py" not in text
    assert "orchid-completion-lane.yml" not in text
    assert "gh workflow run orchid-swarm-controller.yml" in text
    assert "--ref oc-autonomous-integration" in text


def test_swarm_reconciles_only_legacy_provider_backoff():
    text = SWARM.read_text(encoding="utf-8")
    reconcile = section(
        text,
        "- name: Reconcile retired provider backoff into governed queue",
        "- name: Build repository snapshot",
    )
    assert "steps.no_api.outputs.blocked == 'true'" in reconcile
    assert "--label oc-runtime-backoff" in reconcile
    assert "--remove-label oc-runtime-backoff --add-label oc-queued" in reconcile
    assert "oc-repair-backoff" not in reconcile


def test_provider_recovery_canary_never_requeues_repair_backoff():
    text = CANARY.read_text(encoding="utf-8")
    recovery = section(
        text,
        'if [[ "$state" == PASSED && "$GITHUB_EVENT_NAME" == issues ]]; then',
        '[[ "$state" == PASSED ]]',
    )
    assert "--json number,labels" in recovery
    assert 'if [[ "$labels" == *oc-repair-backoff* ]]; then' in recovery
    guarded = recovery[
        recovery.index('if [[ "$labels" == *oc-repair-backoff* ]]; then') :
        recovery.index("continue", recovery.index('if [[ "$labels" == *oc-repair-backoff* ]]; then'))
    ]
    assert "--remove-label oc-runtime-backoff" in guarded
    assert "--remove-label oc-queued" in guarded
    assert "--add-label oc-queued" not in guarded
