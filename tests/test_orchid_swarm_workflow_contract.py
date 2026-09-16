from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml"


def test_swarm_workflow_uses_bounded_parallel_matrix():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "max-parallel: 12" in text
    assert "default: \"8\"" in text
    assert "oc_swarm_controller.py" in text
    assert "orchid-completion-lane.yml" in text


def test_swarm_workflow_targets_integration_not_main():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "INTEGRATION_BRANCH: oc-autonomous-integration" in text
    # Trusted controls are pinned to the controller event revision. The canonical
    # dispatch runs on oc-autonomous-integration, so that revision is the
    # integration head; a mixed checkout of a mutable branch is never used.
    assert "ref: ${{ github.sha }}" in text
    assert "ref: main" not in text
    assert "gh pr merge" not in text
    assert "production deploy: disabled" in text.lower()


def test_swarm_claims_only_queue_leases_and_reports_resources():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python3 -m scripts.oc_swarm_claim" in text
    claim = (ROOT / "scripts" / "oc_swarm_claim.py").read_text(encoding="utf-8")
    for label in ("oc-queued", "oc-running", "oc-owner-gate", "oc-blocked",
                  "oc-runtime-backoff", "oc-repair-backoff"):
        assert label in claim
    assert "Dependency/resource lease claimed" in claim
    assert "resource conflicts suppressed" in text


def test_swarm_summary_parses_plan_as_json_not_a_quoted_json_string():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '<<<"$PLAN"' in text
    assert '<<<\\"$PLAN\\"' not in text


def test_no_api_mode_dispatches_only_provider_free_workers():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--provider-free-only" in text
    assert "provider_free_workers:" in text
    assert "oc_swarm_provider_free_worker.py" in text
    # The paid lane is gated on providers being enabled AND a provider-dependent
    # claim existing; provider-free claims never reach it.
    assert "needs.plan.outputs.provider_launch_count != '0' && needs.plan.outputs.provider_blocked == 'false'" in text
    assert "needs.plan.outputs.provider_blocked == 'true'" in text
    assert "--files-json '[]'" in text


def test_every_launched_wave_gets_one_bounded_refill_attempt():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "needs.plan.outputs.launch_count != '0'" in text
    assert "current >= maximum" in text
    # The refill wave targets the revision that launched the wave and falls
    # back to the canonical integration branch for event-driven runs.
    assert '--ref "$refill_ref"' in text
    assert 'refill_ref="$INTEGRATION_BRANCH"' in text
