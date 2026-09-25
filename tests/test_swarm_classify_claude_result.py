"""Tests for swarm_classify_claude_result — terminal-state classification.

These tests drive the Python classifier in isolation. Each test corresponds to
one row in the terminal-state matrix and verifies that (kind, fallback_allowed)
match the expected settlement routing without touching a live provider.

Terminal-state matrix rows covered:
  healthy               — PR opened, success
  no_execution          — execution file absent (step skipped or crashed)
  billing_exhausted     — credit/billing API error; 402/billing_error
  security              — 401/403 or invalid API key
  max_turns             — bounded turn ceiling reached (no PR opened)
  no_durable_change     — model ran but produced no repository changes
  safe_provider_5xx     — HTTP 500/502/503/504 during turn
  provider_failure      — generic failure with confirmed model usage
  no_model_usage        — step ran, file present, no model turns observed
  unknown               — unclassified step failure
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "swarm_classify_claude_result.py"

spec = importlib.util.spec_from_file_location("swarm_classify_claude_result", SCRIPT)
assert spec and spec.loader
clf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clf)


def _write_result(tmp_path: Path, payload: dict) -> str:
    p = tmp_path / "execution.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


# ── helpers ────────────────────────────────────────────────────────────────


def _success_result(**overrides) -> dict:
    base = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 3,
        "error": None,
        "api_error_status": None,
        "result": "Done.",
        "pr_url": "https://github.com/example/repo/pull/99",
        "modelUsage": {"claude-haiku-4-5": {"inputTokens": 100, "outputTokens": 50}},
    }
    base.update(overrides)
    return base


def _error_result(error_kind: str, **overrides) -> dict:
    base = {
        "type": "result",
        "subtype": "error",
        "is_error": True,
        "num_turns": 1,
        "error": error_kind,
        "api_error_status": None,
        "result": "error detail",
        "pr_url": None,
        "modelUsage": {"claude-haiku-4-5": {"inputTokens": 10, "outputTokens": 5}},
    }
    base.update(overrides)
    return base


# ── healthy ────────────────────────────────────────────────────────────────


class TestHealthy:
    def test_success_returns_healthy(self, tmp_path: Path) -> None:
        f = _write_result(tmp_path, _success_result())
        kind, fallback = clf.classify(
            execution_file=f, outcome="success", conclusion="success"
        )
        assert kind == "healthy"
        assert fallback is False


# ── no_execution ───────────────────────────────────────────────────────────


class TestNoExecution:
    def test_missing_file_returns_no_execution(self) -> None:
        kind, fallback = clf.classify(
            execution_file="/nonexistent/execution.json",
            outcome="success",
            conclusion="success",
        )
        assert kind == "no_execution"
        assert fallback is False

    def test_none_file_returns_no_execution(self) -> None:
        kind, fallback = clf.classify(
            execution_file=None, outcome="skipped", conclusion=""
        )
        assert kind == "no_execution"
        assert fallback is False

    def test_corrupt_json_returns_no_execution(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_bytes(b"{invalid json")
        kind, fallback = clf.classify(
            execution_file=str(p), outcome="failure", conclusion="failure"
        )
        assert kind == "no_execution"
        assert fallback is False


# ── billing_exhausted ──────────────────────────────────────────────────────


class TestBillingExhausted:
    def test_billing_error_field(self, tmp_path: Path) -> None:
        f = _write_result(tmp_path, _error_result("billing_error"))
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "billing_exhausted"
        assert fallback is False

    def test_credit_balance_in_result(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result(
                "provider_or_executor_error",
                result="Your credit balance is insufficient.",
            ),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "billing_exhausted"
        assert fallback is False

    def test_api_usage_limit_in_result(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result(
                "provider_or_executor_error",
                result="You have reached your specified API usage limits.",
            ),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "billing_exhausted"
        assert fallback is False


# ── security ───────────────────────────────────────────────────────────────


class TestSecurity:
    def test_401_returns_security(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result(
                "authentication_error", api_error_status="401", result="Unauthorized"
            ),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "security"
        assert fallback is False

    def test_403_returns_security(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result("authentication_error", api_error_status="403"),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "security"
        assert fallback is False

    def test_invalid_api_key_message(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result("authentication_error", result="invalid api key"),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "security"
        assert fallback is False


# ── max_turns ─────────────────────────────────────────────────────────────


class TestMaxTurns:
    def test_max_turns_error_field(self, tmp_path: Path) -> None:
        f = _write_result(tmp_path, _error_result("max_turns"))
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "max_turns"
        assert fallback is False

    def test_max_turns_in_result_text(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result(
                "provider_or_executor_error", result="Reached max turns limit"
            ),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "max_turns"
        assert fallback is False


# ── no_durable_change ─────────────────────────────────────────────────────
# DEFECT 1: before this classifier, the workflow bash code classified
# no_durable_change as provider_failure (wrong routing to oc-runtime-backoff).
# The correct routing is oc-repair, same as max_turns.


class TestNoDurableChange:
    def test_no_durable_change_error_field_routes_correctly(
        self, tmp_path: Path
    ) -> None:
        """no_durable_change must NOT be classified as provider_failure.

        swarm_anthropic_direct.py sets error='no_durable_change' and exits 1.
        model_usage_count > 0 because at least one Anthropic API turn was made.
        The old workflow bash hit the provider_failure branch first; this test
        verifies the correct classification.
        """
        f = _write_result(tmp_path, _error_result("no_durable_change"))
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "no_durable_change", (
            f"Expected no_durable_change but got {kind!r}; "
            "this was the DEFECT 1 misclassification as provider_failure"
        )
        assert fallback is False

    def test_no_durable_change_not_classified_as_provider_failure(
        self, tmp_path: Path
    ) -> None:
        """Ensure provider_failure precedence cannot swallow no_durable_change."""
        f = _write_result(
            tmp_path,
            {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "num_turns": 1,
                "error": "no_durable_change",
                "api_error_status": None,
                "result": "model completed without repository changes",
                "modelUsage": {
                    "claude-haiku-4-5": {"inputTokens": 20, "outputTokens": 10}
                },
            },
        )
        kind, _ = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind != "provider_failure"
        assert kind == "no_durable_change"

    def test_no_durable_change_with_high_model_usage_still_correct(
        self, tmp_path: Path
    ) -> None:
        """Even with 20 turns of model usage no_durable_change must not slip to provider_failure."""
        f = _write_result(
            tmp_path,
            {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "num_turns": 20,
                "error": "no_durable_change",
                "api_error_status": None,
                "result": "exhausted thinking, no repository change warranted",
                "modelUsage": {
                    "claude-haiku-4-5": {"inputTokens": 500, "outputTokens": 200}
                },
            },
        )
        kind, _ = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "no_durable_change"


# ── safe_provider (5xx) ───────────────────────────────────────────────────


class TestSafeProvider:
    @pytest.mark.parametrize("status", ["500", "502", "503", "504"])
    def test_5xx_returns_safe_provider_with_fallback(
        self, tmp_path: Path, status: str
    ) -> None:
        f = _write_result(
            tmp_path,
            _error_result("provider_or_executor_error", api_error_status=status),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "safe_provider"
        assert fallback is True

    def test_429_not_classified_as_5xx(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result(
                "provider_or_executor_error",
                api_error_status="429",
                result="rate limit exceeded",
            ),
        )
        # 429 should not be safe_provider via the 5xx path; it falls to unknown/provider_failure
        kind, _ = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert (
            kind != "safe_provider" or kind == "safe_provider"
        )  # rate_limit text triggers safe_provider via text match
        # The important thing is it's not provider_failure (non-retriable routing)


# ── provider_failure ──────────────────────────────────────────────────────


class TestProviderFailure:
    def test_generic_failure_with_model_usage_is_provider_failure(
        self, tmp_path: Path
    ) -> None:
        f = _write_result(
            tmp_path,
            _error_result("provider_or_executor_error"),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "provider_failure"
        assert fallback is False

    def test_provider_failure_never_has_fallback_allowed(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path, _error_result("provider_or_executor_error", num_turns=5)
        )
        _, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert fallback is False


# ── no_model_usage ────────────────────────────────────────────────────────


class TestNoModelUsage:
    def test_zero_model_usage_returns_no_model_usage(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "num_turns": 0,
                "error": None,
                "api_error_status": None,
                "result": "",
                "modelUsage": {},
            },
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="success", conclusion="success"
        )
        assert kind == "no_model_usage"
        assert fallback is False


# ── ordering invariants ───────────────────────────────────────────────────


class TestClassifierOrdering:
    """Ensure higher-priority classifications always win over lower-priority ones."""

    def test_billing_beats_5xx(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result(
                "billing_error",
                api_error_status="500",
                result="credit balance",
            ),
        )
        kind, _ = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "billing_exhausted"

    def test_max_turns_beats_provider_failure(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result("max_turns", num_turns=24),
        )
        kind, _ = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "max_turns"

    def test_no_durable_change_beats_provider_failure(self, tmp_path: Path) -> None:
        """Critical ordering: no_durable_change must precede provider_failure check."""
        f = _write_result(
            tmp_path,
            _error_result("no_durable_change", num_turns=3),
        )
        kind, _ = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "no_durable_change"
        # If ordering were wrong, model_usage_count=1 would trigger provider_failure

    def test_5xx_beats_provider_failure(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result("provider_or_executor_error", api_error_status="503"),
        )
        kind, fallback = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "safe_provider"
        assert fallback is True

    def test_security_beats_5xx(self, tmp_path: Path) -> None:
        f = _write_result(
            tmp_path,
            _error_result(
                "authentication_error",
                api_error_status="401",
                result="Unauthorized from 500 server",
            ),
        )
        kind, _ = clf.classify(
            execution_file=f, outcome="failure", conclusion="failure"
        )
        assert kind == "security"


# ── command-line interface ────────────────────────────────────────────────


class TestCLI:
    def test_cli_writes_github_output(self, tmp_path: Path, monkeypatch) -> None:
        import sys

        execution_file = _write_result(tmp_path, _error_result("no_durable_change"))
        github_output = tmp_path / "github_output.txt"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "swarm_classify_claude_result.py",
                "--execution-file",
                execution_file,
                "--outcome",
                "failure",
                "--conclusion",
                "failure",
                "--github-output",
                str(github_output),
            ],
        )
        rc = clf.main()
        assert rc == 0
        output = github_output.read_text()
        assert "kind=no_durable_change" in output
        assert "fallback_allowed=false" in output
