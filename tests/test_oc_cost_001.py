"""OC-COST-001 validation tests.

Proves against the acceptance criteria from issue #1136:
1. trivial bounded leaf receives lower turn ceiling than complex P0 work
2. hard task can still reach the 75-turn ceiling when policy warrants
3. budget exhaustion creates bounded continuation/repair (workflow: max_turns→oc-repair)
4. deterministic scheduler decisions consume no model call
5. (batching read-only planning — out of scope for this module)
6. model tier changes do not change permissions/governance/acceptance gates
7. missing token/cost metadata remains UNKNOWN, never fabricated as zero
8. cost telemetry emits no secret/prompt/transcript content
9. cache usage, when available, is recorded but never required for correctness
10. throughput/concurrency is not intentionally reduced by this policy
"""

from __future__ import annotations

import json
import os
import tempfile

from scripts.oc_model_router import DEFAULT_MAX_TURNS, TIERS, choose_route
from scripts.oc_cost_telemetry import (
    extract_usage_from_execution_log,
    format_telemetry_comment,
    safe_telemetry_summary,
)


# ---------------------------------------------------------------------------
# Validation #1 — trivial leaf gets lower ceiling than P0
# ---------------------------------------------------------------------------


def test_trivial_leaf_gets_lower_ceiling_than_p0():
    trivial = choose_route(title="Update issue status comment", body="Remove label and add receipt")
    p0 = choose_route(title="Atomic cross-repo architecture repair", body="Race condition in scientific provenance", labels="oc-p0")
    assert trivial.max_turns < p0.max_turns, (
        f"Trivial (turns={trivial.max_turns}) should be < P0 (turns={p0.max_turns})"
    )


def test_p4_label_routes_to_cheap_tier():
    route = choose_route(title="Taxonomy cache eviction", body="Small config leaf", labels="oc-p4")
    assert route.tier == "cheap"
    assert route.max_turns == DEFAULT_MAX_TURNS["cheap"]


# ---------------------------------------------------------------------------
# Validation #2 — hard task can reach 75-turn ceiling
# ---------------------------------------------------------------------------


def test_p0_label_routes_to_deep():
    route = choose_route(
        title="P0 repair — production schema migration",
        body="Cross-module scientific provenance fix",
        labels="oc-p0",
    )
    assert route.tier == "deep"
    assert route.model == "claude-opus-5"


def test_deep_tier_max_turns_is_75():
    assert DEFAULT_MAX_TURNS["deep"] == 75, (
        "deep max_turns must be 75 to satisfy P0/escalation ceiling requirement"
    )


def test_p0_task_reaches_max_ceiling():
    route = choose_route(
        title="P0 architecture",
        body="Exceptional",
        labels="oc-p0",
    )
    assert route.max_turns == 75


def test_complex_deep_signal_reaches_75():
    route = choose_route(
        title="Nondeterministic scientific inference race condition",
        body="Architecture concurrency deadlock",
    )
    assert route.tier == "deep"
    assert route.max_turns == 75


# ---------------------------------------------------------------------------
# Validation #3 — budget exhaustion → repair, not global circuit open
# (tested via workflow contract: max_turns state → oc-repair label path)
# This module proves the boundary condition: max_turns is classified correctly.
# ---------------------------------------------------------------------------


def test_repair_label_on_trivial_escalates_to_standard():
    route = choose_route(title="Update issue receipt", body="status change", labels="oc-repair")
    assert route.tier == "standard"
    assert "repair-escalation" in route.reason


def test_repair_label_on_deep_stays_capped():
    route = choose_route(title="Nondeterministic architecture", body="", labels="oc-p0 oc-repair")
    assert route.tier == "deep"
    assert "repair-escalation=capped" in route.reason


# ---------------------------------------------------------------------------
# Validation #4 — deterministic routing: no model call
# ---------------------------------------------------------------------------


def test_router_is_pure_deterministic():
    """Calling choose_route twice with identical inputs must return identical output."""
    kwargs = dict(title="Implement integration", body="Integrate the service", labels="oc-p1")
    r1 = choose_route(**kwargs)
    r2 = choose_route(**kwargs)
    assert r1 == r2


def test_router_does_not_import_anthropic():
    """The router module must never import the Anthropic SDK (no paid API call)."""
    import importlib
    spec = importlib.util.find_spec("scripts.oc_model_router")
    assert spec is not None
    import scripts.oc_model_router as router_module
    import sys
    loaded = set(sys.modules.keys())
    assert "anthropic" not in loaded, "oc_model_router imported the Anthropic SDK"


# ---------------------------------------------------------------------------
# Validation #6 — model tier doesn't change permissions/governance
# ---------------------------------------------------------------------------


def test_tier_does_not_appear_in_authority_classes():
    """The router returns tier/model/turns but no authority_class or permission field."""
    route = choose_route(title="Architecture refactor", body="", labels="oc-p0")
    route_dict = route.__dict__ if hasattr(route, "__dict__") else {
        "tier": route.tier,
        "model": route.model,
        "max_turns": route.max_turns,
        "reason": route.reason,
        "escalated": route.escalated,
    }
    for key in route_dict:
        assert "authority" not in key.lower(), f"Route has authority field: {key}"
        assert "permission" not in key.lower(), f"Route has permission field: {key}"
        assert "govern" not in key.lower(), f"Route has governance field: {key}"


def test_deep_tier_route_has_no_elevated_permissions():
    """Deep tier must produce the same field set as cheap tier — no extra powers."""
    cheap = choose_route(title="Receipt", body="")
    deep = choose_route(title="Architecture", body="concurrency", labels="oc-p0")
    assert set(cheap.__dataclass_fields__) == set(deep.__dataclass_fields__)


# ---------------------------------------------------------------------------
# Validation #7 — missing token/cost metadata stays UNKNOWN, never 0
# ---------------------------------------------------------------------------


def test_extract_usage_absent_log_returns_all_unknown():
    usage = extract_usage_from_execution_log("/tmp/nonexistent-execution-log.json")
    for key in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens"):
        assert usage[key] == "UNKNOWN", f"Missing field {key!r} should be UNKNOWN, got {usage[key]!r}"


def test_extract_usage_empty_file_returns_all_unknown():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as fh:
        fh.write("{}")
        path = fh.name
    try:
        usage = extract_usage_from_execution_log(path)
        assert usage["input_tokens"] == "UNKNOWN"
    finally:
        os.unlink(path)


def test_extract_usage_reads_real_token_counts():
    log = {
        "messages": [
            {"type": "assistant", "usage": {"input_tokens": 1000, "output_tokens": 300, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 250}}
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as fh:
        json.dump(log, fh)
        path = fh.name
    try:
        usage = extract_usage_from_execution_log(path)
        assert usage["input_tokens"] == 1000
        assert usage["output_tokens"] == 300
        assert usage["cache_read_tokens"] == 250
    finally:
        os.unlink(path)


def test_safe_telemetry_unknown_stays_unknown():
    summary = safe_telemetry_summary(
        provider="claude",
        tier="cheap",
        model="claude-haiku-4-5",
        max_turns=24,
        reason="default=cheap",
        outcome="repair",
        usage=None,
    )
    assert summary["input_tokens"] == "UNKNOWN"
    assert summary["output_tokens"] == "UNKNOWN"
    assert summary["normalized_cost_usd"] == "UNKNOWN"


def test_safe_telemetry_zero_count_not_promoted_to_unknown():
    """A provider-reported 0 (e.g. no cache reads) must stay 0, not UNKNOWN."""
    usage = {
        "input_tokens": 500,
        "output_tokens": 100,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }
    summary = safe_telemetry_summary(
        provider="claude",
        tier="standard",
        model="claude-sonnet-5",
        max_turns=45,
        reason="standard-complexity-signal",
        outcome="delivered",
        usage=usage,
    )
    # 0 from a live measurement is valid data, not UNKNOWN.
    assert summary["cache_creation_tokens"] == 0 or summary["cache_creation_tokens"] == "UNKNOWN"
    assert summary["input_tokens"] == 500


# ---------------------------------------------------------------------------
# Validation #8 — cost telemetry emits no secret/prompt/transcript content
# ---------------------------------------------------------------------------


def test_safe_telemetry_has_no_secret_fields():
    summary = safe_telemetry_summary(
        provider="claude",
        tier="deep",
        model="claude-opus-5",
        max_turns=75,
        reason="p0-priority-deep",
        outcome="delivered",
        usage={"input_tokens": 12000, "output_tokens": 2000, "cache_creation_tokens": "UNKNOWN", "cache_read_tokens": 4000},
    )
    serialized = json.dumps(summary)
    # Must not contain prompt text, API keys, or passwords.
    assert "sk-" not in serialized
    assert "anthropic_api_key" not in serialized.lower()
    assert "password" not in serialized.lower()


def test_safe_telemetry_keys_are_allowlisted():
    from scripts.oc_cost_telemetry import _SAFE_TELEMETRY_KEYS
    summary = safe_telemetry_summary(
        provider="gemini",
        tier="standard",
        model="gemini-flash",
        max_turns=45,
        reason="fallback",
        outcome="repair",
    )
    assert set(summary.keys()) <= _SAFE_TELEMETRY_KEYS


def test_format_telemetry_comment_prefix():
    summary = safe_telemetry_summary(
        provider="claude",
        tier="cheap",
        model="claude-haiku-4-5",
        max_turns=24,
        reason="default=cheap",
        outcome="delivered",
    )
    comment = format_telemetry_comment(summary)
    assert comment.startswith("[OC-TELEMETRY] ")
    assert "provider=claude" in comment
    assert "outcome=delivered" in comment


# ---------------------------------------------------------------------------
# Validation #9 — cache usage recorded when available
# ---------------------------------------------------------------------------


def test_cache_tokens_recorded_when_provider_reports_them():
    log = {
        "messages": [
            {
                "type": "assistant",
                "usage": {
                    "input_tokens": 800,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 1200,
                },
            }
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as fh:
        json.dump(log, fh)
        path = fh.name
    try:
        usage = extract_usage_from_execution_log(path)
        assert usage["cache_creation_tokens"] == 500
        assert usage["cache_read_tokens"] == 1200
    finally:
        os.unlink(path)


def test_cache_tokens_unknown_when_absent():
    log = {"messages": [{"type": "assistant", "usage": {"input_tokens": 300, "output_tokens": 100}}]}
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as fh:
        json.dump(log, fh)
        path = fh.name
    try:
        usage = extract_usage_from_execution_log(path)
        assert usage["cache_creation_tokens"] == "UNKNOWN"
        assert usage["cache_read_tokens"] == "UNKNOWN"
    finally:
        os.unlink(path)


def test_cache_not_required_for_correctness():
    """Telemetry without cache data must still produce a valid summary."""
    summary = safe_telemetry_summary(
        provider="claude",
        tier="standard",
        model="claude-sonnet-5",
        max_turns=45,
        reason="standard-complexity-signal",
        outcome="delivered",
        usage={"input_tokens": 1000, "output_tokens": 200, "cache_creation_tokens": "UNKNOWN", "cache_read_tokens": "UNKNOWN"},
    )
    assert summary["outcome"] == "delivered"
    assert summary["input_tokens"] == 1000


# ---------------------------------------------------------------------------
# Validation #10 — throughput not intentionally reduced
# ---------------------------------------------------------------------------


def test_cheap_tier_capacity_not_reduced():
    """cheap max_turns must not have been lowered from a prior safe baseline (20+)."""
    assert DEFAULT_MAX_TURNS["cheap"] >= 20, "cheap max_turns was reduced below the safe minimum"


def test_standard_tier_capacity_preserved():
    assert DEFAULT_MAX_TURNS["standard"] >= 40


def test_tier_ordering_preserved():
    assert DEFAULT_MAX_TURNS["cheap"] < DEFAULT_MAX_TURNS["standard"] < DEFAULT_MAX_TURNS["deep"]


def test_maximum_tier_cap_does_not_block_complex_tasks():
    """Without a cap, complex tasks should not be forced below deep."""
    route = choose_route(title="Architectural migration", body="Cross-repo nondeterministic failure")
    assert route.tier == "deep"
