"""Versioned list-price cost estimation for execution receipts.

The price table is checked against the published structure (cache write and
read multipliers), every model the autonomy engine can route to must be
priced, amounts are checked by hand, and the estimate is shown never to pose
as billed or actual spend.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pricing = _load("oc_provider_pricing", REPO_ROOT / "runtime" / "swarm" / "pricing.py")
cost_cli = _load("oc_execution_cost", REPO_ROOT / "scripts" / "oc_execution_cost.py")
direct = _load(
    "swarm_anthropic_direct", REPO_ROOT / "scripts" / "swarm_anthropic_direct.py"
)
router = _load("oc_model_router", REPO_ROOT / "scripts" / "oc_model_router.py")

TABLE = pricing.load_table()
RAW = json.loads(pricing.PRICING_PATH.read_text())


def test_table_is_versioned_and_sourced() -> None:
    assert RAW["schema"] == "oc.provider-pricing.v1"
    assert TABLE.version
    assert TABLE.source_url.startswith("https://")
    assert TABLE.retrieved_at


def test_every_routable_model_is_priced() -> None:
    routable = set(router.DEFAULT_MODELS.values()) | {
        "claude-sonnet-4-20250514",  # calyx_engineering repair provider default
        "claude-haiku-4-5",  # hosted acceptance checker
    }
    assert {m for m in routable if TABLE.resolve(m) is None} == set()


# Published structure: 5m writes 1.25x input, 1h writes 2x input, reads 0.1x
# except the models the pricing page footnotes.
READ_MULTIPLIER = {
    "claude-fable-5-1": "0.025",
    "claude-opus-5-5": "0.05",
    "claude-sonnet-5-5": "0.05",
}


@pytest.mark.parametrize("model_id", sorted(RAW["models"]))
def test_cache_rates_follow_published_multipliers(model_id) -> None:
    spec = TABLE.models[model_id]
    rate_sets = [spec["rates"]] + ([spec["long"][1]] if spec["long"] else [])
    for rates in rate_sets:
        assert rates["cache_write_5m"] == rates["input"] * Decimal("1.25")
        assert rates["cache_write_1h"] == rates["input"] * 2
        if model_id == "claude-fable-5":
            assert rates["cache_read"] == rates["input"] * Decimal("0.1")
        else:
            expected = Decimal(READ_MULTIPLIER.get(model_id, "0.1"))
            assert rates["cache_read"] == rates["input"] * expected


def test_hand_computed_request_cost() -> None:
    usage = {
        "input_tokens": 1_000,
        "output_tokens": 2_000,
        "cache_creation_input_tokens": 10_000,
        "cache_read_input_tokens": 100_000,
    }
    cost = pricing.price_request("claude-opus-5", usage, TABLE)
    # 1000*5 + 2000*25 + 10000*6.25 + 100000*0.50 per million
    assert cost.usd == Decimal("0.1675")
    assert cost.approximations == ("cache_write_ttl_assumed_5m",)


def test_one_hour_cache_writes_use_the_one_hour_rate() -> None:
    usage = {
        "cache_creation_input_tokens": 3_000,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 1_000,
            "ephemeral_1h_input_tokens": 2_000,
        },
    }
    cost = pricing.price_request("claude-haiku-4-5", usage, TABLE)
    assert cost.usd == Decimal("0.00525")  # 1000*1.25 + 2000*2
    assert cost.approximations == ()


def test_long_prompt_rate_is_resolved_per_request_including_cache_reads() -> None:
    small = {
        "input_tokens": 10_000,
        "cache_read_input_tokens": 50_000,
        "output_tokens": 1_000,
    }
    large = {
        "input_tokens": 10_000,
        "cache_read_input_tokens": 95_000,
        "output_tokens": 1_000,
    }
    small_cost = pricing.price_request("claude-haiku-5-5", small, TABLE)
    large_cost = pricing.price_request("claude-haiku-5-5", large, TABLE)
    assert small_cost.components["input"] == Decimal("0.001")  # base 0.10
    assert large_cost.components["input"] == Decimal("0.005")  # over 100k: 0.50

    # Two 60k-token requests stay at the base rate; one 120k request does not.
    two = pricing.estimate("claude-haiku-5-5", [{"input_tokens": 60_000}] * 2, TABLE)
    one = pricing.estimate("claude-haiku-5-5", [{"input_tokens": 120_000}], TABLE)
    assert two.subtotal == Decimal("0.012")
    assert one.subtotal == Decimal("0.06")


def test_alias_is_exact_never_a_prefix() -> None:
    assert TABLE.resolve("claude-sonnet-4-20250514") == "claude-sonnet-4"
    assert TABLE.resolve("claude-sonnet-4-5") == "claude-sonnet-4-5"
    assert TABLE.resolve("claude-sonnet-4-9") is None
    assert TABLE.resolve("claude-opus-5-5-20260101") is None


def test_unknown_model_keeps_run_estimate_unknown() -> None:
    est = pricing.estimate(
        "claude-sonnet-5",
        [{"input_tokens": 1_000}],
        TABLE,
    )
    est.add(pricing.price_request("claude-unknown", {"input_tokens": 1_000}, TABLE))
    block = est.to_jsonable()
    assert block["estimated_usd"] is None
    assert block["complete"] is False
    assert block["priced_subtotal_usd"] == "0.002000"
    assert block["requests_unpriced"] == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"speed": "fast"},
        {"service_tier": "batch"},
        {"service_tier": "priority"},
        {"inference_geo": "eu"},
    ],
)
def test_unmodelled_modifiers_are_unpriced(extra) -> None:
    cost = pricing.price_request(
        "claude-opus-5", {"input_tokens": 1_000, **extra}, TABLE
    )
    assert cost.priced is False
    assert cost.usd is None


def test_us_inference_multiplier_only_on_eligible_models() -> None:
    usage = {"input_tokens": 1_000_000, "inference_geo": "us"}
    assert pricing.price_request("claude-opus-5", usage, TABLE).usd == Decimal("5.5")
    assert pricing.price_request("claude-haiku-4-5", usage, TABLE).usd == Decimal(1)


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": -1},
        {"input_tokens": True},
        {"input_tokens": "10"},
        {
            "cache_creation_input_tokens": 5,
            "cache_creation": {"ephemeral_5m_input_tokens": 4},
        },
    ],
)
def test_malformed_usage_is_unpriced(usage) -> None:
    assert pricing.price_request("claude-opus-5", usage, TABLE).priced is False


def test_pre_long_context_models_flag_oversized_prompts() -> None:
    cost = pricing.price_request("claude-sonnet-4", {"input_tokens": 250_000}, TABLE)
    assert "prompt_over_200000_priced_at_standard_rate" in cost.approximations


def test_estimate_never_poses_as_billed() -> None:
    block = pricing.estimate(
        "claude-opus-5", [{"input_tokens": 10}], TABLE
    ).to_jsonable()
    assert block["basis"] == "list_price_estimate"
    assert block["billed_usd"] is None
    assert block["billed_basis"].startswith("unavailable")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.update(schema="other"),
        lambda t: t["models"]["claude-opus-5"]["rates"].pop("cache_read"),
        lambda t: t["models"]["claude-opus-5"]["rates"].update(input="-1"),
        lambda t: t["models"]["claude-opus-5"].update(
            aliases=["claude-sonnet-4-20250514"]
        ),
        lambda t: t["source"].pop("retrieved_at"),
    ],
)
def test_malformed_tables_are_rejected(mutate) -> None:
    table = copy.deepcopy(RAW)
    mutate(table)
    with pytest.raises(pricing.PricingError):
        pricing.parse_table(table)


def test_estimate_is_not_promoted_to_actual_cost_in_task_economics() -> None:
    telemetry = _load(
        "oc_swarm_telemetry", REPO_ROOT / "runtime" / "swarm" / "telemetry.py"
    )
    block = pricing.estimate(
        "claude-sonnet-5", [{"input_tokens": 1_000}], TABLE
    ).to_jsonable()
    economics = telemetry.TaskEconomics(
        issue_task_id="1",
        provider="anthropic",
        model="claude-sonnet-5",
        attempts=1,
        turns=1,
        input_tokens=1_000,
        output_tokens=0,
        elapsed_seconds=None,
        actual_cost_usd=None,
        estimated_cost_usd=Decimal(block["estimated_usd"]),
        tests_passed=True,
        durable_pr_created=True,
        outcome="success",
    )
    assert economics.cost_per_completed_task is None
    assert economics.to_jsonable()["estimated_cost_usd"] == "0.002000"


# --- executor and CLI -------------------------------------------------------


def _run_executor(monkeypatch, tmp_path, responses, model="claude-sonnet-5"):
    packet = tmp_path / "packet.md"
    packet.write_text("task")
    execution_file = tmp_path / "execution.json"
    github_output = tmp_path / "github_output"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "_prepare_branch", lambda *a, **k: "dryrun/999")
    monkeypatch.setattr(
        direct, "_open_draft_pr", lambda *a, **k: "https://example.invalid/pr/1"
    )
    monkeypatch.setattr(direct, "_anthropic_message", lambda **k: next(responses))
    monkeypatch.setattr(
        direct.sys,
        "argv",
        [
            "swarm_anthropic_direct.py", "--issue-number", "7", "--title", "t",
            "--packet-file", str(packet), "--model", model, "--max-turns", "4",
            "--execution-file", str(execution_file),
        ],
    )  # fmt: skip
    code = direct.main()
    return code, json.loads(execution_file.read_text()), github_output.read_text()


def _responses():
    return iter(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "w1",
                        "name": "write_file",
                        "input": {"path": "app/x.py", "content": "X = 1\n"},
                    }
                ],
                "usage": {
                    "input_tokens": 1_000,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 3_000,
                },
            },
            {
                "content": [{"type": "text", "text": "done"}],
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 3_000,
                },
            },
        ]
    )


def test_executor_writes_verifiable_cost_block(monkeypatch, tmp_path) -> None:
    code, result, outputs = _run_executor(monkeypatch, tmp_path, _responses())
    assert code == 0
    cost = result["cost"]
    # (1000*2 + 200*10 + 3000*2.5) + (50*2 + 20*10 + 3000*0.2) per million
    assert cost["estimated_usd"] == "0.012400"
    assert cost["basis"] == "list_price_estimate"
    assert cost["billed_usd"] is None
    assert cost["pricing_version"] == TABLE.version
    assert len(result["requestUsage"]) == 2
    assert result["total_cost_usd"] is None  # still no billed/client-reported total
    assert "estimated_cost_usd=0.012400" in outputs
    assert "cost_basis=list_price_estimate" in outputs
    assert cost_cli.verify_execution(result) == []


def test_verify_detects_tampered_cost(monkeypatch, tmp_path) -> None:
    _, result, _ = _run_executor(monkeypatch, tmp_path, _responses())
    result["cost"]["estimated_usd"] = "0.000001"
    assert cost_cli.verify_execution(result)
    result = json.loads(json.dumps(result))
    result["requestUsage"][0]["input_tokens"] = 1
    assert cost_cli.verify_execution(result)


def test_pricing_failure_never_fails_the_run(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(direct, "PRICING_MODULE", tmp_path / "missing.py")
    code, result, outputs = _run_executor(monkeypatch, tmp_path, _responses())
    assert code == 0
    assert result["cost"]["basis"] == "unavailable"
    assert result["cost"]["estimated_usd"] is None
    assert "cost_basis=unavailable" in outputs


def test_unpriced_model_run_reports_unknown_cost(monkeypatch, tmp_path) -> None:
    _, result, _ = _run_executor(
        monkeypatch, tmp_path, _responses(), model="claude-future-9"
    )
    assert result["cost"]["estimated_usd"] is None
    assert result["cost"]["complete"] is False


def test_legacy_receipt_without_request_usage_is_unpriceable() -> None:
    legacy = {
        "modelUsage": {"claude-sonnet-5": {"inputTokens": 100, "outputTokens": 10}}
    }
    cost = cost_cli.price_execution(legacy)
    assert cost["basis"] == "unavailable"
    assert cost["estimated_usd"] is None
