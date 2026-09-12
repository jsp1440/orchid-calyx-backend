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


@pytest.mark.parametrize("malformed", [None, {}, {"path": "app/example.py"},
                                      {"path": "app/example.py", "content": None}, []])
def test_direct_executor_full_success_path_without_live_provider(
    tmp_path, monkeypatch, malformed
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
    if malformed is not None:
        responses = iter([{
            "content": [{"type": "tool_use", "id": "malformed-write",
                         "name": "write_file", "input": malformed}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }, *responses])

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
    assert result["num_turns"] == (2 if malformed is None else 3)
    assert result["pr_url"] == "https://example.invalid/pr/1"
    assert result["modelUsage"]["claude-haiku-4-5"]["inputTokens"] == (40 if malformed is None else 43)
    assert result["modelUsage"]["claude-haiku-4-5"]["outputTokens"] == (15 if malformed is None else 17)
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
    monkeypatch.setattr(
        direct, "_prepare_branch", lambda *args, **kwargs: "dryrun/1000"
    )
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


def test_direct_executor_honors_24_turn_route_budget_without_live_provider(
    tmp_path, monkeypatch
) -> None:
    packet = tmp_path / "packet.md"
    packet.write_text("Exercise full cheap-tier turn budget.\n")
    execution_file = tmp_path / "execution.json"
    calls = {"count": 0}

    def tool_response(**kwargs):
        calls["count"] += 1
        if calls["count"] < 24:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"tool-{calls['count']}",
                        "name": "list_files",
                        "input": {"pattern": "*.py"},
                    }
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        return {
            "content": [{"type": "text", "text": "Done."}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "1001")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        direct, "_prepare_branch", lambda *args, **kwargs: "dryrun/1001"
    )
    monkeypatch.setattr(direct, "_anthropic_message", tool_response)
    monkeypatch.setattr(
        direct,
        "_open_draft_pr",
        lambda *args, **kwargs: "https://example.invalid/pr/24",
    )

    argv = [
        "swarm_anthropic_direct.py",
        "--issue-number",
        "1264",
        "--title",
        "Synthetic 24-turn canary",
        "--packet-file",
        str(packet),
        "--model",
        "claude-haiku-4-5",
        "--max-turns",
        "24",
        "--execution-file",
        str(execution_file),
    ]
    monkeypatch.setattr(direct.sys, "argv", argv)

    assert direct.main() == 0
    result = json.loads(execution_file.read_text())
    assert result["num_turns"] == 24
    assert calls["count"] == 24


def test_direct_executor_hard_caps_requested_turns_at_24() -> None:
    text = SCRIPT.read_text()
    assert "bounded_turns = min(max(args.max_turns, 1), 24)" in text


def test_direct_executor_no_change_writes_structured_failure_without_live_provider(
    tmp_path, monkeypatch
) -> None:
    packet = tmp_path / "packet.md"
    packet.write_text("Inspect only; make no changes.\n")
    execution_file = tmp_path / "execution.json"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "1002")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        direct, "_prepare_branch", lambda *args, **kwargs: "dryrun/1002"
    )
    monkeypatch.setattr(
        direct,
        "_anthropic_message",
        lambda **kwargs: {
            "content": [{"type": "text", "text": "No changes required."}],
            "usage": {"input_tokens": 2, "output_tokens": 2},
        },
    )
    monkeypatch.setattr(direct, "_open_draft_pr", lambda *args, **kwargs: "")

    argv = [
        "swarm_anthropic_direct.py",
        "--issue-number",
        "1264",
        "--title",
        "Synthetic no-change canary",
        "--packet-file",
        str(packet),
        "--model",
        "claude-haiku-4-5",
        "--max-turns",
        "4",
        "--execution-file",
        str(execution_file),
    ]
    monkeypatch.setattr(direct.sys, "argv", argv)

    assert direct.main() == 1
    result = json.loads(execution_file.read_text())
    assert result["subtype"] == "error"
    assert result["error"] == "no_durable_change"
    assert result["num_turns"] == 1
    assert result["modelUsage"]["claude-haiku-4-5"]["inputTokens"] == 2


def test_direct_executor_salvages_partial_changes_on_max_turns(
    tmp_path, monkeypatch
) -> None:
    """DEFECT 2: Partial file writes are salvage-committed when max_turns is hit.

    Before this fix the except handler wrote the error result and exited 1
    without inspecting the git working tree.  Any files the model wrote via
    write_file were silently lost.  After the fix a best-effort git add/commit/push
    is attempted for max_turns and provider_or_executor_error.
    """
    packet = tmp_path / "packet.md"
    packet.write_text("Keep asking for a tool forever.\n")
    execution_file = tmp_path / "execution.json"

    salvage_calls: list[list[str]] = []

    def fake_run(cmd, *, timeout=120, check=False):
        salvage_calls.append(cmd)

        class FakeResult:
            returncode = 0
            stdout = (
                "M app/partial.py\n" if cmd == ["git", "status", "--porcelain"] else ""
            )
            stderr = ""

        return FakeResult()

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
    monkeypatch.setenv("GITHUB_RUN_ID", "2000")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        direct, "_prepare_branch", lambda *args, **kwargs: "dryrun/2000"
    )
    monkeypatch.setattr(direct, "_anthropic_message", tool_response)
    monkeypatch.setattr(direct, "_open_draft_pr", lambda *args, **kwargs: "")
    monkeypatch.setattr(direct, "_run", fake_run)

    argv = [
        "swarm_anthropic_direct.py",
        "--issue-number",
        "1264",
        "--title",
        "Synthetic salvage test",
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
    assert result["error"] == "max_turns"

    # Salvage sequence must include git status, add, commit, and push.
    cmd_names = [c[0] if c else "" for c in salvage_calls]
    assert "git" in cmd_names

    status_calls = [c for c in salvage_calls if c == ["git", "status", "--porcelain"]]
    assert len(status_calls) >= 1, (
        "git status --porcelain must be called during salvage"
    )

    add_calls = [c for c in salvage_calls if c[:2] == ["git", "add"]]
    assert add_calls, "git add must be called when dirty working tree is found"

    commit_calls = [c for c in salvage_calls if c[:2] == ["git", "commit"]]
    assert commit_calls, "git commit must be called during salvage"

    push_calls = [c for c in salvage_calls if c[:2] == ["git", "push"]]
    assert push_calls, "git push must be called during salvage"

    # The partial_branch field must appear in the result JSON after a successful salvage.
    assert "partial_branch" in result, (
        "execution result must include partial_branch field; got " + str(result.keys())
    )
    assert result["partial_branch"] == "dryrun/2000"


def test_direct_executor_no_salvage_on_clean_working_tree(
    tmp_path, monkeypatch
) -> None:
    """Salvage should skip git add/commit if the working tree is clean."""
    packet = tmp_path / "packet.md"
    packet.write_text("Keep asking for a tool forever.\n")
    execution_file = tmp_path / "execution.json"

    salvage_calls: list[list[str]] = []

    def fake_run(cmd, *, timeout=120, check=False):
        salvage_calls.append(cmd)

        class FakeResult:
            returncode = 0
            stdout = ""  # empty = clean working tree
            stderr = ""

        return FakeResult()

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
    monkeypatch.setenv("GITHUB_RUN_ID", "2001")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        direct, "_prepare_branch", lambda *args, **kwargs: "dryrun/2001"
    )
    monkeypatch.setattr(direct, "_anthropic_message", tool_response)
    monkeypatch.setattr(direct, "_open_draft_pr", lambda *args, **kwargs: "")
    monkeypatch.setattr(direct, "_run", fake_run)

    argv = [
        "swarm_anthropic_direct.py",
        "--issue-number",
        "1264",
        "--title",
        "Synthetic clean salvage test",
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
    assert result["error"] == "max_turns"

    add_calls = [c for c in salvage_calls if c[:2] == ["git", "add"]]
    assert not add_calls, "git add must NOT be called on a clean working tree"

    assert result.get("partial_branch") is None


def test_direct_executor_no_salvage_on_auth_error(tmp_path, monkeypatch) -> None:
    """Authentication errors do not produce partial work worth salvaging."""
    packet = tmp_path / "packet.md"
    packet.write_text("auth test\n")
    execution_file = tmp_path / "execution.json"

    run_calls: list[list[str]] = []

    def fake_run(cmd, *, timeout=120, check=False):
        run_calls.append(cmd)

        class FakeResult:
            returncode = 0
            stdout = "M app/partial.py\n"
            stderr = ""

        return FakeResult()

    def auth_error(**kwargs):
        raise direct.AnthropicHTTPError(
            401, {"error": {"type": "authentication_error", "message": "Unauthorized"}}
        )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "2002")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        direct, "_prepare_branch", lambda *args, **kwargs: "dryrun/2002"
    )
    monkeypatch.setattr(direct, "_anthropic_message", auth_error)
    monkeypatch.setattr(direct, "_open_draft_pr", lambda *args, **kwargs: "")
    monkeypatch.setattr(direct, "_run", fake_run)

    argv = [
        "swarm_anthropic_direct.py",
        "--issue-number",
        "1264",
        "--title",
        "Synthetic auth test",
        "--packet-file",
        str(packet),
        "--model",
        "claude-haiku-4-5",
        "--max-turns",
        "4",
        "--execution-file",
        str(execution_file),
    ]
    monkeypatch.setattr(direct.sys, "argv", argv)

    assert direct.main() == 1
    result = json.loads(execution_file.read_text())
    assert result["error"] == "authentication_error"

    status_calls = [c for c in run_calls if c == ["git", "status", "--porcelain"]]
    assert not status_calls, "salvage must NOT run for authentication_error"
    assert result.get("partial_branch") is None


def test_prepare_branch_configures_git_identity(monkeypatch) -> None:
    calls: list[tuple[list[str], int, bool]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *, timeout=120, check=False):
        calls.append((cmd, timeout, check))
        return Result()

    monkeypatch.setattr(direct, "_run", fake_run)

    branch = direct._prepare_branch("1355", "12345", "oc-autonomous-integration")

    assert branch == "claude-direct/issue-1355-12345"
    commands = [cmd for cmd, _, _ in calls]
    assert [
        "git",
        "config",
        "user.name",
        "orchid-continuum-orchestrator[bot]",
    ] in commands
    assert [
        "git",
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    ] in commands


def test_small_edit_replaces_exactly_one_match(tmp_path, monkeypatch):
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    target = tmp_path / "example.py"
    target.write_text("before\nVALUE = 1\nafter\n")
    direct._tool_write_file({"path": "example.py", "old_text": "VALUE = 1", "content": "VALUE = 2"})
    assert target.read_text() == "before\nVALUE = 2\nafter\n"


@pytest.mark.parametrize("old_text", ["", "missing", "x", None])
def test_invalid_small_edit_never_changes_the_file(tmp_path, monkeypatch, old_text):
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    target = tmp_path / "example.py"
    target.write_text("x\nx\n")
    with pytest.raises(ValueError):
        direct._tool_write_file({"path": "example.py", "old_text": old_text, "content": "replacement"})
    assert target.read_text() == "x\nx\n"


def test_small_edit_preserves_protected_path_boundary():
    assert direct._tool_write_file({"path": "scripts/swarm_anthropic_direct.py",
                                    "old_text": "anything", "content": "anything"}).startswith("ERROR: protected")


def test_durable_execution_summary_excludes_model_text_and_retains_usage(tmp_path, capsys):
    payload = {"type": "result", "subtype": "error", "num_turns": 2,
               "modelUsage": {"model": {"inputTokens": 100, "outputTokens": 30}},
               "error": "max_turns", "result": "private model output"}
    direct._write_result(tmp_path / "receipt.json", payload)
    output = capsys.readouterr().out
    assert "private model output" not in output
    receipt = json.loads(output.split("[OC-DIRECT-RECEIPT] ")[1])
    assert receipt["modelUsage"] == payload["modelUsage"]
    assert receipt["error"] == "max_turns" and receipt["num_turns"] == 2
