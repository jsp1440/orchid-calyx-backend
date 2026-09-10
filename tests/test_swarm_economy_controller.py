from decimal import Decimal

from runtime.swarm.retry import classify_retry
from runtime.swarm.telemetry import TaskEconomics
from runtime.swarm.work_packet import build_work_packet


def test_work_packet_deduplicates_and_extracts_file_hints():
    body = """
Requirements:
- Update scripts/foo.py
- Update scripts/foo.py
- Must keep NO_API_MODE fail closed.
Do not deploy production.
"""
    packet = build_work_packet(
        issue_number="9",
        title="Workflow repair",
        body=body,
        labels="oc-queued oc-queued",
    )
    assert packet.file_hints == ("scripts/foo.py",)
    assert packet.labels == ("oc-queued",)
    assert "NO_API_MODE" in packet.render()
    assert "Do not deploy production." in packet.constraints


def test_work_packet_is_bounded_and_fingerprinted():
    body = "\n".join(f"line {i} " + ("x" * 400) for i in range(50))
    packet = build_work_packet(issue_number="10", title="Large issue", body=body)
    assert len(packet.summary) <= 5000
    assert len(packet.fingerprint) == 16
    assert packet.estimated_prompt_tokens > 0


def test_deterministic_first_for_ci_failure():
    packet = build_work_packet(
        issue_number="11",
        title="Fix CI failure",
        body="ruff lint is failing",
    )
    assert packet.execution_class == "deterministic-first"


def test_explicit_model_required_overrides_deterministic_signal():
    packet = build_work_packet(
        issue_number="12",
        title="Fix CI failure",
        body="lint issue",
        labels="oc-model-required",
    )
    assert packet.execution_class == "model"


def test_transient_retry_does_not_consume_model_retry():
    d = classify_retry(failure_class="ci-infrastructure", retry_count=0)
    assert d.action == "retry-workflow"
    assert d.consumes_model_retry is False


def test_reasoning_failure_gets_only_one_model_retry():
    first = classify_retry(failure_class="reasoning", retry_count=0, max_retries=1)
    second = classify_retry(failure_class="reasoning", retry_count=1, max_retries=1)
    assert first.action == "model-repair-once"
    assert second.action == "stop"


def test_provider_error_fails_closed():
    assert (
        classify_retry(failure_class="provider-error", retry_count=0).action == "stop"
    )


def test_cost_per_completed_task_only_for_durable_success():
    good = TaskEconomics(
        issue_task_id="1085",
        provider="anthropic",
        model="claude-sonnet-5",
        attempts=1,
        turns=3,
        input_tokens=1000,
        output_tokens=500,
        elapsed_seconds=60,
        actual_cost_usd=Decimal("0.75"),
        estimated_cost_usd=Decimal("1.00"),
        tests_passed=True,
        durable_pr_created=True,
        outcome="success",
    )
    failed = TaskEconomics(
        issue_task_id="1086",
        provider="anthropic",
        model="claude-sonnet-5",
        attempts=1,
        turns=1,
        input_tokens=1000,
        output_tokens=100,
        elapsed_seconds=30,
        actual_cost_usd=Decimal("0.20"),
        estimated_cost_usd=Decimal("1.00"),
        tests_passed=False,
        durable_pr_created=False,
        outcome="failed",
    )
    assert good.cost_per_completed_task == Decimal("0.75")
    assert failed.cost_per_completed_task is None
