"""Prompt caching in the direct Anthropic executor must change billing only.

These tests pin the properties that make provider prefix caching safe for
scientific work: the cached prefix is byte-stable and task-independent, history
is append-only, a changed evidence byte can never be served from cache, one
task's history can never be read by another, and the operator switch restores
the uncached request exactly.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


direct = _load("swarm_anthropic_direct")
bench = _load("oc_prompt_cache_benchmark")

PACKET_A = "OC-SWARM task A: repair occurrence projection.\n" * 30
PACKET_B = "OC-SWARM task B: lexicon contract tests.\n" * 30


def _body(history, cache=True):
    return direct._request_body(
        model="m", messages=history, max_tokens=100, cache=cache
    )


def _static_prefix(body):
    return json.dumps(
        {"tools": body["tools"], "system": body["system"]}, sort_keys=True
    )


def test_cached_request_marks_static_prefix_and_history_tail() -> None:
    body = _body([{"role": "user", "content": PACKET_A}])
    assert body["system"] == [
        {
            "type": "text",
            "text": direct.EXECUTOR_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"] is direct.TOOLS
    # Never more than the provider's four breakpoints.
    markers = json.dumps(body).count('"cache_control"')
    assert markers == 2


def test_disabled_cache_sends_no_markers_and_same_instructions() -> None:
    body = _body([{"role": "user", "content": PACKET_A}], cache=False)
    assert "cache_control" not in json.dumps(body)
    assert body["system"] == direct.EXECUTOR_SYSTEM


@pytest.mark.parametrize("raw", ["off", "OFF", "0", "false", "no", "disabled", " off "])
def test_operator_can_disable_prompt_cache(raw) -> None:
    assert direct.prompt_cache_enabled(raw) is False


@pytest.mark.parametrize("raw", ["on", "1", "true", ""])
def test_prompt_cache_defaults_on(raw) -> None:
    assert direct.prompt_cache_enabled(raw) is True


def test_static_prefix_is_identical_across_tasks_and_turns() -> None:
    """Nothing per-task, per-run or per-turn sits before the system breakpoint."""
    histories = bench.synthetic_tool_loop(5, PACKET_A) + bench.synthetic_tool_loop(
        5, PACKET_B
    )
    prefixes = {_static_prefix(_body(history)) for history in histories}
    assert len(prefixes) == 1


def test_history_is_append_only_between_turns() -> None:
    histories = bench.synthetic_tool_loop(8, PACKET_A)
    for earlier, later in itertools.pairwise(histories):
        assert later[: len(earlier)] == earlier


def test_changed_evidence_byte_is_never_served_from_cache() -> None:
    """A file that changed between turns must be re-read, not replayed from cache."""
    terms = bench.DEFAULT_TERMS["deep"]
    model = bench.ProviderCacheModel(terms.minimum_cacheable_tokens)
    history = bench.synthetic_tool_loop(6, PACKET_A)[-1]
    model.bill(_body(history))

    stale = json.loads(json.dumps(history))
    # Mutate one byte of the third tool result (an earlier read_file).
    results = [
        m for m in stale if m["role"] == "user" and isinstance(m["content"], list)
    ]
    target = results[2]["content"][0]
    target["content"] = target["content"][:-1] + "!"
    positions = bench.render_positions(_body(stale))
    changed_at = next(
        i
        for i, (a, b) in enumerate(
            zip(bench.render_positions(_body(history)), positions)
        )
        if a["key"] != b["key"]
    )
    usage = model.bill(_body(stale))
    assert usage["cache_read_input_tokens"] <= positions[changed_at - 1]["tokens"]
    assert usage["cache_read_input_tokens"] < positions[-1]["tokens"]


def test_one_task_never_reads_another_tasks_history() -> None:
    terms = bench.DEFAULT_TERMS["deep"]
    model = bench.ProviderCacheModel(terms.minimum_cacheable_tokens)
    for history in bench.synthetic_tool_loop(6, PACKET_A):
        model.bill(_body(history))
    static_tokens = bench.render_positions(
        _body([{"role": "user", "content": PACKET_B}])
    )[len(direct.TOOLS)]["tokens"]
    for history in bench.synthetic_tool_loop(6, PACKET_B)[:1]:
        usage = model.bill(_body(history))
        assert usage["cache_read_input_tokens"] <= static_tokens


def test_below_minimum_prefix_is_neither_written_nor_read() -> None:
    model = bench.ProviderCacheModel(minimum_tokens=10**9)
    for history in bench.synthetic_tool_loop(4, PACKET_A):
        usage = model.bill(_body(history))
        assert usage["cache_creation_input_tokens"] == 0
        assert usage["cache_read_input_tokens"] == 0


def test_benchmark_reports_reduction_only_when_cache_enabled() -> None:
    result = bench.benchmark(turns=12)
    for row in result["tiers"].values():
        assert row["before"]["cache_read_input_tokens"] == 0
        assert row["before"]["cache_creation_input_tokens"] == 0
        assert (
            row["after"]["billed_input_token_equivalent"]
            < row["before"]["billed_input_token_equivalent"]
        )
        # Caching never changes how much context the model processes.
        assert (
            row["after"]["processed_input_tokens"]
            == row["before"]["processed_input_tokens"]
        )
    assert result["basis"].startswith("modelled")


def _run_executor(monkeypatch, tmp_path, responses, *, cache_env=None):
    packet = tmp_path / "packet.md"
    packet.write_text(PACKET_A)
    execution_file = tmp_path / "execution.json"
    github_output = tmp_path / "github_output"
    sent = []

    def fake_message(**kwargs):
        sent.append(kwargs)
        return next(responses)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    if cache_env is None:
        monkeypatch.delenv(direct.PROMPT_CACHE_ENV, raising=False)
    else:
        monkeypatch.setenv(direct.PROMPT_CACHE_ENV, cache_env)
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "_prepare_branch", lambda *a, **k: "dryrun/999")
    monkeypatch.setattr(
        direct, "_open_draft_pr", lambda *a, **k: "https://example.invalid/pr/1"
    )
    monkeypatch.setattr(direct, "_anthropic_message", fake_message)
    monkeypatch.setattr(
        direct.sys,
        "argv",
        [
            "swarm_anthropic_direct.py",
            "--issue-number", "1264",
            "--title", "Synthetic canary",
            "--packet-file", str(packet),
            "--model", "claude-haiku-4-5",
            "--max-turns", "4",
            "--execution-file", str(execution_file),
        ],
    )  # fmt: skip
    code = direct.main()
    return code, json.loads(execution_file.read_text()), github_output.read_text(), sent


def _write_then_stop():
    return iter(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "w1",
                        "name": "write_file",
                        "input": {"path": "app/example.py", "content": "VALUE = 1\n"},
                    }
                ],
                "usage": {
                    "input_tokens": 30,
                    "output_tokens": 10,
                    "cache_creation_input_tokens": 1500,
                    "cache_read_input_tokens": 0,
                },
            },
            {
                "content": [{"type": "text", "text": "done"}],
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 80,
                    "cache_read_input_tokens": 1500,
                },
            },
        ]
    )


def test_executor_records_cache_usage_in_receipt_and_outputs(
    monkeypatch, tmp_path, capsys
) -> None:
    code, result, outputs, sent = _run_executor(
        monkeypatch, tmp_path, _write_then_stop()
    )
    assert code == 0
    usage = result["modelUsage"]["claude-haiku-4-5"]
    assert usage == {
        "inputTokens": 42,
        "outputTokens": 15,
        "cacheCreationInputTokens": 1580,
        "cacheReadInputTokens": 1500,
    }
    assert result["promptCache"] == "enabled"
    assert "cache_read_input_tokens=1500" in outputs
    receipt = next(
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("[OC-DIRECT-RECEIPT]")
    )
    assert '"cacheReadInputTokens": 1500' in receipt
    assert all(call["cache"] is True for call in sent)
    # The packet is the first user turn; instructions travel as `system`.
    assert sent[0]["messages"][0] == {"role": "user", "content": PACKET_A}


def test_executor_honours_operator_cache_switch(monkeypatch, tmp_path) -> None:
    code, result, _, sent = _run_executor(
        monkeypatch, tmp_path, _write_then_stop(), cache_env="off"
    )
    assert code == 0
    assert result["promptCache"] == "disabled"
    assert all(call["cache"] is False for call in sent)
