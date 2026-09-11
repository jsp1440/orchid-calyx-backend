from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "swarm_anthropic_direct.py"

spec = importlib.util.spec_from_file_location("swarm_anthropic_direct", SCRIPT)
assert spec and spec.loader
direct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(direct)


def test_direct_executor_blocks_workflow_writes() -> None:
    path = direct._safe_path(".github/workflows/orchid-completion-lane.yml")
    assert direct._writable(path) is False


def test_direct_executor_blocks_paths_outside_repository() -> None:
    with pytest.raises(ValueError):
        direct._safe_path("../../etc/passwd")


def test_direct_executor_allows_normal_source_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    path = direct._safe_path("app/example.py")
    assert direct._writable(path) is True
    result = direct._tool_write_file({"path": "app/example.py", "content": "x = 1\n"})
    assert "WROTE app/example.py" in result
    assert path.read_text() == "x = 1\n"


def test_direct_executor_rejects_arbitrary_validation_command() -> None:
    result = direct._tool_run_check({"name": "curl", "target": "example.com"})
    assert result == "ERROR: unsupported check: curl"


def test_direct_executor_builds_anthropic_messages_request() -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                }
            ).encode()

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode())
        captured["timeout"] = timeout
        return Response()

    with patch.object(direct.urlrequest, "urlopen", fake_urlopen):
        response = direct._anthropic_message(
            api_key="test-key",
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=100,
            timeout=30,
        )

    assert captured["url"] == direct.ANTHROPIC_URL
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["tools"]
    assert response["usage"]["input_tokens"] == 10


def test_direct_executor_toolset_has_no_arbitrary_shell() -> None:
    names = {tool["name"] for tool in direct.TOOLS}
    assert names == {
        "read_file",
        "list_files",
        "search_text",
        "write_file",
        "run_check",
    }


def test_direct_executor_blocks_governor_self_modification() -> None:
    for raw in (
        "scripts/swarm_governor_precheck.py",
        "scripts/swarm_governor_github_ledger.py",
        "scripts/swarm_anthropic_direct.py",
        "runtime/swarm/governor.py",
    ):
        assert direct._writable(direct._safe_path(raw)) is False


def test_max_turns_uses_direct_executor_error_for_settlement() -> None:
    text = SCRIPT.read_text()
    assert 'error_kind = "max_turns"' in text
    assert 'raise DirectExecutorError("direct executor reached max turns")' in text


def test_direct_executor_full_success_path_without_live_provider(
    tmp_path, monkeypatch
) -> None:
    packet = tmp_path / "packet.md"
    packet.write_text("Implement a bounded test change.\n")
    execution_file = tmp_path / "execution.json"
    github_output = tmp_path / "github_output.txt"

    responses = iter(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "write_file",
                        "input": {
                            "path": "app/example.py",
                            "content": "VALUE = 1\n",
                        },
                    }
                ],
                "usage": {"input_tokens": 25, "output_tokens": 10},
            },
            {
                "content": [{"type": "text", "text": "Implementation complete."}],
                "usage": {"input_tokens": 15, "output_tokens": 5},
            },
        ]
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "_prepare_branch", lambda *args, **kwargs: "dryrun/999")
    monkeypatch.setattr(
        direct,
        "_open_draft_pr",
        lambda *args, **kwargs: "https://example.invalid/pr/1",
    )
    monkeypatch.setattr(
        direct,
        "_anthropic_message",
        lambda **kwargs: next(responses),
    )

    argv = [
        "swarm_anthropic_direct.py",
        "--issue-number",
        "1264",
        "--title",
        "Synthetic canary",
        "--packet-file",
        str(packet),
        "--model",
        "claude-haiku-4-5",
        "--max-turns",
        "4",
        "--base",
        "oc-autonomous-integration",
        "--execution-file",
        str(execution_file),
    ]
    monkeypatch.setattr(direct.sys, "argv", argv)

    assert direct.main() == 0
    result = json.loads(execution_file.read_text())
    assert result["subtype"] == "success"
    assert result["is_error"] is False
    assert result["num_turns"] == 2
    assert result["pr_url"] == "https://example.invalid/pr/1"
    assert result["modelUsage"]["claude-haiku-4-5"]["inputTokens"] == 40
    assert result["modelUsage"]["claude-haiku-4-5"]["outputTokens"] == 15
    assert (tmp_path / "app" / "example.py").read_text() == "VALUE = 1\n"

    output_text = github_output.read_text()
    assert "conclusion=success" in output_text
    assert f"execution_file={execution_file}" in output_text
    assert "pr_url=https://example.invalid/pr/1" in output_text


def test_direct_executor_max_turns_writes_structured_failure_without_live_provider(
    tmp_path, monkeypatch
) -> None:
    packet = tmp_path / "packet.md"
    packet.write_text("Keep asking for a tool forever.\n")
    execution_file = tmp_path / "execution.json"

    def tool_response(**kwargs):
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-loop",
                    "name": "list_files",
                    "input": {"pattern": "*.py"},
                }
            ],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "1000")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "_prepare_branch", lambda *args, **kwargs: "dryrun/1000")
    monkeypatch.setattr(direct, "_anthropic_message", tool_response)
    monkeypatch.setattr(direct, "_open_draft_pr", lambda *args, **kwargs: "")

    argv = [
        "swarm_anthropic_direct.py",
        "--issue-number",
        "1264",
        "--title",
        "Synthetic max-turn canary",
        "--packet-file",
        str(packet),
        "--model",
        "claude-haiku-4-5",
        "--max-turns",
        "2",
        "--execution-file",
        str(execution_file),
    ]
    monkeypatch.setattr(direct.sys, "argv", argv)

    assert direct.main() == 1
    result = json.loads(execution_file.read_text())
    assert result["subtype"] == "error"
    assert result["error"] == "max_turns"
    assert result["num_turns"] == 2
    assert len(result["modelUsage"]) == 1
