from __future__ import annotations

import copy
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


@pytest.mark.parametrize(
    "declaration",
    [
        "",
        "other@" + "a" * 40,
        "claude-direct/issue-2-99@" + "a" * 40,
        "claude-direct/issue-1-99@main",
    ],
)
def test_resume_rejects_unbound_or_wrong_issue_head(declaration):
    with pytest.raises(direct.DirectExecutorError):
        direct._resume_from_packet("OC-SWARM-RESUME: " + declaration, "1")


def test_resume_packet_requires_unique_exact_head():
    marker = "OC-SWARM-RESUME: claude-direct/issue-1-99@" + "a" * 40
    assert direct._resume_from_packet("ordinary work", "1") is None
    assert direct._resume_from_packet(marker, "1") == (
        "claude-direct/issue-1-99",
        "a" * 40,
    )
    with pytest.raises(direct.DirectExecutorError):
        direct._resume_from_packet(marker + "\n" + marker, "1")


def test_resume_real_git_retains_partial_work_and_new_control_plane(
    tmp_path, monkeypatch
):
    import subprocess

    def git(cwd, *args):
        return subprocess.run(
            ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
        ).stdout.strip()

    remote = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", str(remote))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", str(remote), str(seed))
    git(seed, "config", "user.name", "fixture")
    git(seed, "config", "user.email", "fixture@example.invalid")
    git(seed, "checkout", "-b", "oc-autonomous-integration")
    (seed / "app").mkdir()
    (seed / "app/example.py").write_text("VALUE = 1\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "base")
    git(seed, "push", "origin", "oc-autonomous-integration")
    branch = "claude-direct/issue-1-99"
    git(seed, "checkout", "-b", branch)
    (seed / "app/example.py").write_text("VALUE = 2\n")
    git(seed, "commit", "-am", "partial")
    partial = git(seed, "rev-parse", "HEAD")
    git(seed, "push", "origin", branch)
    git(seed, "checkout", "oc-autonomous-integration")
    (seed / "current-control-plane.txt").write_text("repaired executor\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "new control plane")
    current = git(seed, "rev-parse", "HEAD")
    git(seed, "push", "origin", "oc-autonomous-integration")
    worker = tmp_path / "worker"
    git(
        tmp_path,
        "clone",
        "--branch",
        "oc-autonomous-integration",
        str(remote),
        str(worker),
    )
    monkeypatch.setattr(direct, "REPO_ROOT", worker)
    assert (
        direct._prepare_branch(
            "1", "100", "oc-autonomous-integration", resume=(branch, partial)
        )
        == branch
    )
    assert (worker / "app/example.py").read_text() == "VALUE = 2\n"
    assert (worker / "current-control-plane.txt").read_text() == "repaired executor\n"
    assert direct.RETAINED == {"app/example.py"}
    git(worker, "merge-base", "--is-ancestor", partial, "HEAD")
    git(worker, "merge-base", "--is-ancestor", current, "HEAD")


@pytest.mark.parametrize(
    "moved,protected", [(False, False), (True, False), (False, True)]
)
def test_resume_preserves_partial_branch_and_current_integration(
    monkeypatch, moved, protected
):
    from subprocess import CompletedProcess

    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        stdout = ""
        if cmd[1] == "rev-parse":
            stdout = "b" * 40 if moved else "a" * 40
        elif cmd[1:3] == ["diff", "--name-only"]:
            stdout = ".github/workflows/unsafe.yml" if protected else "app/example.py"
        return CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(direct, "_run", run)
    if moved or protected:
        with pytest.raises(direct.DirectExecutorError):
            direct._prepare_branch(
                "1",
                "100",
                "oc-autonomous-integration",
                resume=("claude-direct/issue-1-99", "a" * 40),
            )
        assert not any(c[1] == "checkout" for c in calls)
    else:
        assert (
            direct._prepare_branch(
                "1",
                "100",
                "oc-autonomous-integration",
                resume=("claude-direct/issue-1-99", "a" * 40),
            )
            == "claude-direct/issue-1-99"
        )
        assert [
            "git",
            "merge",
            "--no-edit",
            "origin/oc-autonomous-integration",
        ] in calls
        assert not any("--force" in c for c in calls)


def test_validation_receipt_retains_exit_code_without_command_output(
    monkeypatch, capsys
):
    from subprocess import CompletedProcess

    monkeypatch.setattr(
        direct,
        "_run",
        lambda cmd, **kwargs: CompletedProcess(cmd, 1, "private test output", ""),
    )
    result = direct._tool_run_check(
        {"name": "pytest", "target": "tests/test_example.py"}
    )
    logged = capsys.readouterr().out
    assert '"exit_code": 1' in logged
    assert '"check": "pytest"' in logged
    assert "private test output" not in logged
    assert "private test output" in result


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


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        {},
        {"path": "app/example.py"},
        {"path": "app/example.py", "content": None},
        [],
    ],
)
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
        responses = iter(
            [
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "malformed-write",
                            "name": "write_file",
                            "input": malformed,
                        }
                    ],
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                },
                *responses,
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
    assert result["num_turns"] == (2 if malformed is None else 3)
    assert result["pr_url"] == "https://example.invalid/pr/1"
    assert result["modelUsage"]["claude-haiku-4-5"]["inputTokens"] == (
        40 if malformed is None else 43
    )
    assert result["modelUsage"]["claude-haiku-4-5"]["outputTokens"] == (
        15 if malformed is None else 17
    )
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
                "app/partial.py\n"
                if cmd == ["git", "diff", "--cached", "--name-only"]
                else ""
            )
            stderr = ""

        return FakeResult()

    turns = {"n": 0}

    def tool_response(**kwargs):
        turns["n"] += 1
        call = (
            {
                "name": "write_file",
                "input": {"path": "app/partial.py", "content": "x = 1\n"},
            }
            if turns["n"] == 1
            else {"name": "list_files", "input": {"pattern": "*.py"}}
        )
        return {
            "content": [{"type": "tool_use", "id": f"tool-{turns['n']}", **call}],
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

    add_calls = [c for c in salvage_calls if c[:2] == ["git", "add"]]
    assert add_calls == [["git", "add", "--", "app/partial.py"]], (
        "salvage must stage only the files the model wrote"
    )

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
    direct._tool_write_file(
        {"path": "example.py", "old_text": "VALUE = 1", "content": "VALUE = 2"}
    )
    assert target.read_text() == "before\nVALUE = 2\nafter\n"


@pytest.mark.parametrize("old_text", ["", "missing", "x", None])
def test_invalid_small_edit_never_changes_the_file(tmp_path, monkeypatch, old_text):
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    target = tmp_path / "example.py"
    target.write_text("x\nx\n")
    with pytest.raises(ValueError):
        direct._tool_write_file(
            {"path": "example.py", "old_text": old_text, "content": "replacement"}
        )
    assert target.read_text() == "x\nx\n"


def test_small_edit_preserves_protected_path_boundary():
    assert direct._tool_write_file(
        {
            "path": "scripts/swarm_anthropic_direct.py",
            "old_text": "anything",
            "content": "anything",
        }
    ).startswith("ERROR: protected")


def test_durable_execution_summary_excludes_model_text_and_retains_usage(
    tmp_path, capsys
):
    payload = {
        "type": "result",
        "subtype": "error",
        "num_turns": 2,
        "modelUsage": {"model": {"inputTokens": 100, "outputTokens": 30}},
        "error": "max_turns",
        "result": "private model output",
    }
    direct._write_result(tmp_path / "receipt.json", payload)
    output = capsys.readouterr().out
    assert "private model output" not in output
    receipt = json.loads(output.split("[OC-DIRECT-RECEIPT] ")[1])
    assert receipt["modelUsage"] == payload["modelUsage"]
    assert receipt["error"] == "max_turns" and receipt["num_turns"] == 2


def test_turn_budget_notice_counts_down_and_asks_to_finish_near_the_limit() -> None:
    early = direct._turn_budget_notice(5, 24)
    assert "5 of 24 turns used; 19 remaining" in early
    assert "Finish now" not in early
    for turn in (21, 22, 23, 24):
        notice = direct._turn_budget_notice(turn, 24)
        assert f"{24 - turn} remaining" in notice
        assert "Finish now" in notice
    assert "0 remaining" in direct._turn_budget_notice(30, 24)


def test_every_tool_result_carries_the_turn_budget_and_the_prompt_states_it(
    tmp_path, monkeypatch
) -> None:
    """The model sees its ceiling and the stop condition, then finishing opens a PR.

    Regression for the first live cheap-tier run: the change and tests were done
    by turn 15, the model kept re-verifying without knowing the limit, and
    max_turns discarded the draft PR.
    """
    packet = tmp_path / "packet.md"
    packet.write_text("Small two-file change.\n")
    execution_file = tmp_path / "execution.json"
    seen: list[list[dict]] = []

    def provider(**kwargs):
        seen.append(kwargs["messages"])
        last = kwargs["messages"][-1]["content"]
        if isinstance(last, list) and "Finish now" in last[-1].get("text", ""):
            return {
                "content": [{"type": "text", "text": "Done; tests pass."}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": f"tool-{len(seen)}",
                    "name": "list_files",
                    "input": {"pattern": "*.py"},
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "1002")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "_prepare_branch", lambda *a, **k: "dryrun/1002")
    monkeypatch.setattr(direct, "_anthropic_message", provider)
    monkeypatch.setattr(
        direct, "_open_draft_pr", lambda *a, **k: "https://example.invalid/pr/1"
    )
    monkeypatch.setattr(
        direct.sys,
        "argv",
        [
            "swarm_anthropic_direct.py",
            "--issue-number",
            "1843",
            "--title",
            "Budget-aware finish",
            "--packet-file",
            str(packet),
            "--model",
            "claude-haiku-4-5",
            "--max-turns",
            "24",
            "--execution-file",
            str(execution_file),
        ],
    )

    assert direct.main() == 0
    result = json.loads(execution_file.read_text())
    assert result["pr_url"] == "https://example.invalid/pr/1"
    # Turn 21 is the first notice with three or fewer turns left, so the model
    # finishes on turn 22 instead of exhausting the budget.
    assert result["num_turns"] == 22

    prompt = seen[0][0]["content"]
    assert "at most 24 model turns" in prompt
    assert "do not re-run passing checks" in prompt
    final_messages = seen[-1]
    tool_turns = [
        m["content"]
        for m in final_messages
        if m["role"] == "user" and isinstance(m["content"], list)
    ]
    assert len(tool_turns) == 21
    for index, content in enumerate(tool_turns, start=1):
        assert content[0]["type"] == "tool_result"
        assert content[-1] == {
            "type": "text",
            "text": direct._turn_budget_notice(index, 24),
        }


@pytest.mark.parametrize(
    ("packet", "expected"),
    [
        (
            "Allowed paths: `runtime/a.py` and a new `tests/test_a.py`. Do not...",
            {"runtime/a.py", "tests/test_a.py"},
        ),
        (
            "Scope\nAllowed paths:\n- `runtime/a.py`\n- `tests/test_a.py`\nDo not change x",
            {"runtime/a.py", "tests/test_a.py"},
        ),
        ("No declaration here.", None),
        ("Allowed paths: `a.py`\nAllowed paths: `b.py`", set()),
        (
            "Allowed paths: runtime/a.py, tests/test_a.py.",
            {"runtime/a.py", "tests/test_a.py"},
        ),
        (
            "Allowed paths:\n- `runtime/a.py` (new)\n- tests/test_a.py\nDone",
            {"runtime/a.py", "tests/test_a.py"},
        ),
        (
            "Allowed paths: runtime/a.py only; do not change runtime/health.py.",
            {"runtime/a.py"},
        ),
        ("Allowed paths: runtime/a.py; see README.md", {"runtime/a.py"}),
        (
            "Allowed paths:\n- runtime/a.py\n- runtime/health.py must stay unchanged",
            {"runtime/a.py"},
        ),
    ],
)
def test_allowed_paths_are_read_inline_or_as_a_list(packet, expected):
    assert direct._parse_allowed_paths(packet) == expected


def test_writes_outside_the_allowed_paths_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "ALLOWED_PATHS", {"runtime/a.py"})
    monkeypatch.setattr(direct, "WRITTEN", set())
    ok = direct._tool_write_file({"path": "runtime/a.py", "content": "a = 1\n"})
    assert ok.startswith("WROTE runtime/a.py")
    refused = direct._tool_write_file(
        {"path": "test_verify_changes.py", "content": "x"}
    )
    assert refused.startswith("ERROR: test_verify_changes.py is outside")
    assert not (tmp_path / "test_verify_changes.py").exists()
    assert direct.WRITTEN == {"runtime/a.py"}


def test_only_written_files_are_staged_never_test_side_effects(tmp_path, monkeypatch):
    """PR #1855 carried calyx_runtime_journal.jsonl and runtime/discovery_registry.json,
    which the test suite rewrites; git add -A committed them."""
    calls = []

    def fake_run(cmd, *, timeout=120, check=False):
        calls.append(cmd)

        class Result:
            returncode = 0
            stdout = "runtime/a.py\n" if cmd[:3] == ["git", "diff", "--cached"] else ""
            stderr = ""

        return Result()

    monkeypatch.setattr(direct, "_run", fake_run)
    monkeypatch.setattr(direct, "WRITTEN", {"runtime/a.py"})
    assert direct._stage_written_files() is True
    adds = [c for c in calls if c[:2] == ["git", "add"]]
    assert adds == [["git", "add", "--", "runtime/a.py"]]
    assert ["git", "add", "-A"] not in calls
    monkeypatch.setattr(direct, "WRITTEN", set())
    calls.clear()

    def nothing_staged(cmd, *, timeout=120, check=False):
        calls.append(cmd)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(direct, "_run", nothing_staged)
    assert direct._stage_written_files() is False
    assert not [c for c in calls if c[:2] == ["git", "add"]]


def test_no_git_add_all_remains_in_the_executor():
    assert '"add", "-A"' not in SCRIPT.read_text()


def _run_executor(tmp_path, monkeypatch, replies, check_results, max_turns="6"):
    packet = tmp_path / "packet.md"
    packet.write_text("Allowed paths:\n- `app/a.py`\n")
    execution_file = tmp_path / "execution.json"
    sent: list[list[dict]] = []
    checks = iter(check_results)

    def fake_run(cmd, *, timeout=120, check=False):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = Result()
        if cmd == ["git", "diff", "--cached", "--name-only"]:
            result.stdout = "app/a.py\n"
        elif cmd == ["git", "diff", "--cached", "--check"]:
            result.returncode, result.stdout = next(checks)
        return result

    def model(**kwargs):
        sent.append(copy.deepcopy(kwargs["messages"]))
        return replies.pop(0)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "3000")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "_prepare_branch", lambda *a, **k: "dryrun/3000")
    monkeypatch.setattr(direct, "_anthropic_message", model)
    monkeypatch.setattr(direct, "_open_draft_pr", lambda *a, **k: "https://pr/1")
    monkeypatch.setattr(direct, "_run", fake_run)
    monkeypatch.setattr(
        direct.sys,
        "argv",
        [
            "swarm_anthropic_direct.py",
            "--issue-number",
            "1861",
            "--title",
            "Whitespace feedback",
            "--packet-file",
            str(packet),
            "--model",
            "claude-haiku-4-5",
            "--max-turns",
            max_turns,
            "--execution-file",
            str(execution_file),
        ],
    )
    code = direct.main()
    return code, json.loads(execution_file.read_text()), sent


def _write(n, content):
    return {
        "content": [
            {
                "type": "tool_use",
                "id": f"w{n}",
                "name": "write_file",
                "input": {"path": "app/a.py", "content": content},
            }
        ],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }


DONE = {
    "content": [{"type": "text", "text": "Done."}],
    "usage": {"input_tokens": 3, "output_tokens": 2},
}


def test_whitespace_errors_go_back_to_the_model_instead_of_failing_the_run(
    tmp_path, monkeypatch
):
    """#1861: finished work died on `git diff --cached --check` at commit time."""
    report = "app/a.py:1: trailing whitespace.\n+x = 1"
    code, result, sent = _run_executor(
        tmp_path,
        monkeypatch,
        [_write(1, "x = 1  \n"), dict(DONE), _write(2, "x = 1\n"), dict(DONE)],
        [(2, report), (0, "")],
    )
    assert code == 0
    assert result["subtype"] == "success"
    feedback = sent[2][-1]
    assert feedback["role"] == "user"
    assert "git diff --check" in feedback["content"]
    assert report in feedback["content"]
    assert len(sent) == 4


def test_clean_changes_finish_without_an_extra_turn(tmp_path, monkeypatch):
    code, _, sent = _run_executor(
        tmp_path, monkeypatch, [_write(1, "x = 1\n"), dict(DONE)], [(0, "")]
    )
    assert code == 0
    assert len(sent) == 2


def test_no_whitespace_turn_is_taken_on_the_last_allowed_turn(tmp_path, monkeypatch):
    code, _, sent = _run_executor(
        tmp_path,
        monkeypatch,
        [_write(1, "x = 1  \n"), dict(DONE)],
        [],
        max_turns="3",
    )
    assert len(sent) == 2
    assert code == 0


def test_whitespace_problems_reads_a_real_index(tmp_path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(direct, "ALLOWED_PATHS", None)
    monkeypatch.setattr(direct, "WRITTEN", set())
    direct._tool_write_file({"path": "app/new.py", "content": "x = 1  \n"})
    assert "trailing whitespace" in direct._whitespace_problems()
    direct._tool_write_file({"path": "app/new.py", "content": "x = 1\n"})
    assert direct._whitespace_problems() == ""
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert staged.stdout == "", "the probe must leave the index as it found it"


def test_a_model_that_never_fixes_stays_within_the_turn_limit(tmp_path, monkeypatch):
    report = (2, "app/a.py:1: trailing whitespace.")
    replies = [_write(1, "x = 1  \n")] + [dict(DONE) for _ in range(5)]
    code, _, sent = _run_executor(
        tmp_path, monkeypatch, replies, [report] * 5, max_turns="4"
    )
    assert len(sent) == 3, "feedback only while a write and a finish still fit"
    assert "[turn budget] 2 of 4 turns used; 2 remaining." in sent[2][-1]["content"]
    assert "no tool call" not in sent[2][-1]["content"]
    assert code == 0  # the mocked commit; the real commit check stays authoritative


def test_lint_findings_go_back_to_the_model(tmp_path, monkeypatch):
    """#1860/#1862: tests passed, but `ruff check` in PR validation did not."""
    lint = "app/a.py:1:8: F401 `os` imported but unused\nFound 1 error."
    findings = iter([lint, ""])
    monkeypatch.setattr(direct, "_whitespace_problems", lambda: "")
    monkeypatch.setattr(direct, "_lint_problems", lambda: next(findings))
    monkeypatch.setattr(direct, "RETAINED", set())
    replies = [_write(1, "import os\n"), dict(DONE), _write(2, "x = 1\n"), dict(DONE)]
    code, _, sent = _run_executor(tmp_path, monkeypatch, replies, [(0, "")])
    assert code == 0
    feedback = sent[2][-1]["content"]
    assert "ruff check" in feedback
    assert lint in feedback
    assert len(sent) == 4


def _lint_run(returncode, stdout, seen):
    def fake_run(cmd, *, timeout=120, check=False):
        seen.append(cmd)

        class Result:
            pass

        result = Result()
        result.returncode, result.stdout, result.stderr = returncode, stdout, ""
        return result

    return fake_run


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (1, "app/a.py:1:8: F401 unused", "app/a.py:1:8: F401 unused"),
        (0, "All checks passed!", ""),
        (2, "error: ruff crashed", ""),  # not actionable by the model
        (1, "", ""),  # ruff missing: exit 1, message only on stderr
    ],
)
def test_lint_problems_runs_ruff_on_written_python_files_only(
    tmp_path, monkeypatch, returncode, stdout, expected
):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("import os\n")
    (tmp_path / "notes.md").write_text("x\n")
    seen: list[list[str]] = []
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "WRITTEN", {"app/a.py", "notes.md", "gone.py"})
    monkeypatch.setattr(direct, "RETAINED", set())
    monkeypatch.setattr(direct, "_run", _lint_run(returncode, stdout, seen))
    assert direct._lint_problems() == expected
    assert seen == [
        [
            direct.sys.executable,
            "-m",
            "ruff",
            "check",
            "--output-format=concise",
            "--",
            "app/a.py",
        ]
    ]


def test_lint_problems_is_silent_without_written_python(tmp_path, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "WRITTEN", {"notes.md"})
    monkeypatch.setattr(direct, "RETAINED", set())
    monkeypatch.setattr(direct, "_run", _lint_run(1, "x", seen))
    assert direct._lint_problems() == ""
    assert seen == []


def test_lint_problems_includes_retained_partial_branch_files(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "retained.py").write_text("import os\n")
    seen: list[list[str]] = []
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "WRITTEN", set())
    monkeypatch.setattr(direct, "RETAINED", {"app/retained.py"})
    monkeypatch.setattr(
        direct,
        "_run",
        _lint_run(1, "app/retained.py:1:8: F401 unused", seen),
    )
    assert "F401" in direct._lint_problems()
    assert seen[0][-1] == "app/retained.py"


def test_lint_problems_with_the_real_ruff(tmp_path, monkeypatch):
    pytest.importorskip("ruff")
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "ALLOWED_PATHS", None)
    monkeypatch.setattr(direct, "WRITTEN", set())
    monkeypatch.setattr(direct, "RETAINED", set())
    direct._tool_write_file({"path": "app/a.py", "content": "import os\n"})
    assert "F401" in direct._lint_problems()
    direct._tool_write_file({"path": "app/a.py", "content": "x = 1\n"})
    assert direct._lint_problems() == ""


def test_finish_problems_labels_each_report(monkeypatch):
    monkeypatch.setattr(direct, "_whitespace_problems", lambda: "a.py:1: trailing")
    monkeypatch.setattr(direct, "_lint_problems", lambda: "a.py:1:8: F401")
    assert direct._finish_problems() == (
        "[git diff --check]\na.py:1: trailing\n[ruff check]\na.py:1:8: F401"
    )
    monkeypatch.setattr(direct, "_whitespace_problems", lambda: "")
    assert direct._finish_problems() == "[ruff check]\na.py:1:8: F401"
    monkeypatch.setattr(direct, "_lint_problems", lambda: "")
    assert direct._finish_problems() == ""


def test_old_text_errors_say_whether_it_was_missing_or_ambiguous(tmp_path, monkeypatch):
    """#1863: eleven failed writes; the model was only told to read again."""
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(direct, "ALLOWED_PATHS", None)
    monkeypatch.setattr(direct, "WRITTEN", set())
    (tmp_path / "a.py").write_text("x = '\u2014'\ny = 1\ny = 1\n")
    with pytest.raises(ValueError, match="not found.*em dash"):
        direct._tool_write_file(
            {"path": "a.py", "old_text": "x = '-'", "content": "x = 2"}
        )
    with pytest.raises(ValueError, match="matches 2 times"):
        direct._tool_write_file({"path": "a.py", "old_text": "y = 1", "content": "y"})
    assert direct.WRITTEN == set()


def test_tool_errors_are_logged_with_their_reason(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(direct, "_whitespace_problems", lambda: "")
    monkeypatch.setattr(direct, "_lint_problems", lambda: "")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("x = 1\n")
    bad = {
        "content": [
            {
                "type": "tool_use",
                "id": "bad",
                "name": "write_file",
                "input": {"path": "app/a.py", "old_text": "nope", "content": "y"},
            }
        ],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    _run_executor(tmp_path, monkeypatch, [bad, _write(2, "x = 2\n"), dict(DONE)], [])
    lines = [
        json.loads(line.split(" ", 1)[1])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("[OC-DIRECT-TOOL]")
    ]
    assert lines[0]["input_error"] is True
    assert lines[0]["error"].startswith("ERROR: ValueError: old_text was not found")
    assert "error" not in lines[1]
