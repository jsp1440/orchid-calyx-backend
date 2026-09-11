"""Governed direct Anthropic executor for bounded repository engineering.

This bypasses anthropics/claude-code-action while preserving Orchid governor,
concurrency, budget, retry, and durable settlement controls.

The model never receives arbitrary shell access. It can read/search files, write
repository files outside protected paths, and run a fixed allowlist of local
validation commands. Git branch creation, commit, push, and draft PR creation
are performed deterministically by this script after model execution.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

REPO_ROOT = Path(__file__).resolve().parent.parent
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class DirectExecutorError(RuntimeError):
    """Base error for bounded direct-executor failures."""


class AnthropicHTTPError(DirectExecutorError):
    """Safe structured Anthropic HTTP failure."""

    def __init__(self, status_code: int, detail: dict[str, Any]) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"anthropic_http_{status_code}: {json.dumps(detail)[:2000]}")


class ToolExecutionError(DirectExecutorError):
    """Safe model-tool execution failure."""


PROTECTED_PREFIXES = (
    ".git/",
    ".github/workflows/",
    "runtime/swarm/",
)
PROTECTED_FILES = {
    "scripts/oc_no_api_guard.py",
    "scripts/swarm_anthropic_direct.py",
    "scripts/swarm_governor_precheck.py",
    "scripts/swarm_governor_postrun.py",
    "scripts/swarm_governor_github_ledger.py",
}
PROTECTED_BASENAMES = {
    ".env",
    ".env.local",
    "secrets.json",
}

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List repository files matching a glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    {
        "name": "search_text",
        "description": "Search repository text files for a literal string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "pattern": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "write_file",
        "description": "Replace a repository text file with supplied UTF-8 content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_check",
        "description": (
            "Run one fixed local validation command. Names: git_status, git_diff, "
            "git_diff_check, pytest, ruff_check, ruff_format_check, compile_python."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["name"],
        },
    },
]


def _safe_path(raw: str) -> Path:
    rel = raw.strip().replace("\\", "/")
    if not rel or rel.startswith("/"):
        raise ValueError("invalid repository path")
    path = (REPO_ROOT / rel).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("path escapes repository") from exc
    return path


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _writable(path: Path) -> bool:
    rel = _relative(path)
    if path.name in PROTECTED_BASENAMES or rel in PROTECTED_FILES:
        return False
    return not any(
        rel == prefix.rstrip("/") or rel.startswith(prefix)
        for prefix in PROTECTED_PREFIXES
    )


def _run(
    cmd: list[str], *, timeout: int = 120, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def _truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _tool_read_file(args: dict[str, Any]) -> str:
    path = _safe_path(str(args["path"]))
    if not path.is_file():
        return f"ERROR: file not found: {_relative(path)}"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(int(args.get("start_line", 1)), 1)
    end = int(args.get("end_line", min(len(lines), start + 399)))
    end = min(max(end, start), len(lines))
    body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
    return _truncate(body)


def _tool_list_files(args: dict[str, Any]) -> str:
    pattern = str(args["pattern"]).strip() or "*"
    matches: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = _relative(path)
        if fnmatch.fnmatch(rel, pattern):
            matches.append(rel)
        if len(matches) >= 300:
            break
    return "\n".join(sorted(matches)) or "(no matches)"


def _tool_search_text(args: dict[str, Any]) -> str:
    query = str(args["query"])
    pattern = str(args.get("pattern") or "*")
    if not query:
        return "ERROR: empty query"
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = _relative(path)
        if not fnmatch.fnmatch(rel, pattern):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if query in line:
                hits.append(f"{rel}:{line_no}:{line[:300]}")
                if len(hits) >= 200:
                    return "\n".join(hits)
    return "\n".join(hits) or "(no matches)"


def _tool_write_file(args: dict[str, Any]) -> str:
    path = _safe_path(str(args["path"]))
    if not _writable(path):
        return f"ERROR: protected path is not writable: {_relative(path)}"
    content = str(args["content"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"WROTE {_relative(path)} bytes={len(content.encode('utf-8'))}"


def _safe_target(raw: str | None) -> str:
    if not raw:
        return ""
    target = raw.strip()
    if not re.fullmatch(r"[A-Za-z0-9_./*?\-\[\]]+", target):
        raise ValueError("unsafe validation target")
    return target


def _tool_run_check(args: dict[str, Any]) -> str:
    name = str(args["name"])
    target = _safe_target(args.get("target"))
    if name == "git_status":
        cmd = ["git", "status", "--short"]
    elif name == "git_diff":
        cmd = ["git", "diff", "--"]
        if target:
            cmd.append(target)
    elif name == "git_diff_check":
        cmd = ["git", "diff", "--check"]
    elif name == "pytest":
        cmd = [sys.executable, "-m", "pytest", "-q"]
        if target:
            cmd.append(target)
    elif name == "ruff_check":
        cmd = [sys.executable, "-m", "ruff", "check", target or "."]
    elif name == "ruff_format_check":
        cmd = [sys.executable, "-m", "ruff", "format", "--check", target or "."]
    elif name == "compile_python":
        cmd = [sys.executable, "-m", "compileall", "-q", target or "."]
    else:
        return f"ERROR: unsupported check: {name}"

    result = _run(cmd, timeout=180)
    combined = (result.stdout or "") + (result.stderr or "")
    return _truncate(f"exit_code={result.returncode}\n{combined}", 16000)


TOOL_HANDLERS = {
    "read_file": _tool_read_file,
    "list_files": _tool_list_files,
    "search_text": _tool_search_text,
    "write_file": _tool_write_file,
    "run_check": _tool_run_check,
}


def _anthropic_message(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: int,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": TOOLS,
        }
    ).encode("utf-8")
    req = urlrequest.Request(
        ANTHROPIC_URL,
        data=payload,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except ValueError:
            detail = {"error": {"message": raw[:1000]}}
        raise AnthropicHTTPError(exc.code, detail) from exc


def _content_text(content: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if block.get("type") == "text" and block.get("text")
    )


def _prepare_branch(issue_number: str, run_id: str, base: str) -> str:
    branch = f"claude-direct/issue-{issue_number}-{run_id}"
    _run(["git", "fetch", "origin", base], timeout=120, check=True)
    _run(["git", "checkout", "-B", branch, f"origin/{base}"], timeout=60, check=True)
    return branch


def _open_draft_pr(issue_number: str, branch: str, base: str, title: str) -> str:
    status = _run(
        ["git", "status", "--porcelain"], timeout=30, check=True
    ).stdout.strip()
    if not status:
        return ""

    _run(["git", "diff", "--check"], timeout=60, check=True)
    _run(["git", "add", "-A"], timeout=30, check=True)
    _run(
        [
            "git",
            "commit",
            "-m",
            f"feat(oc): implement issue #{issue_number} via direct Claude",
        ],
        timeout=60,
        check=True,
    )
    _run(["git", "push", "-u", "origin", branch], timeout=120, check=True)
    body = (
        f"OC-AUTO-ISSUE: #{issue_number}\n"
        "OC-AUTO-REQUEUE: false\n"
        "OC-AUTO-BLOCKED: false\n\n"
        "Implemented by the governed direct Anthropic executor after Swarm governor authorization.\n"
        "No merge, deployment, production mutation, credential change, scientific publication, "
        "or taxonomy activation is performed by this executor."
    )
    result = _run(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title[:240],
            "--body",
            body,
        ],
        timeout=120,
        check=True,
    )
    return result.stdout.strip()


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _github_output(values: dict[str, Any]) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
            handle.write(f"{key}={rendered}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--packet-file", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-tokens", type=int, default=3072)
    parser.add_argument("--base", default="oc-autonomous-integration")
    parser.add_argument("--execution-file", required=True)
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY_REQUIRED")
    run_id = os.getenv("GITHUB_RUN_ID", str(int(time.time())))
    packet = Path(args.packet_file).read_text(encoding="utf-8")
    execution_path = Path(args.execution_file)

    input_tokens = 0
    output_tokens = 0
    calls = 0
    branch = ""
    pr_url = ""
    error_kind = ""
    error_status = ""
    error_message = ""
    final_text = ""

    try:
        branch = _prepare_branch(args.issue_number, run_id, args.base)
        system = (
            "You are the Orchid Continuum bounded engineering executor. Work only on the supplied "
            "task. Use repository tools to inspect and edit. Do not modify .github/workflows, "
            "credentials, secrets, production state, scientific data, taxonomy activation, or "
            "publication controls. Run focused tests. When implementation is complete, stop; the "
            "wrapper will commit, push, and open the draft PR."
        )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"{system}\n\n{packet}"}
        ]

        # The economy router's cheap tier is budgeted for up to 24 turns.
        # Honor that route ceiling instead of silently truncating it to 12,
        # while still keeping a hard repository-local cap.
        bounded_turns = min(max(args.max_turns, 1), 24)
        bounded_tokens = min(max(args.max_tokens, 256), 3072)
        for turn in range(1, bounded_turns + 1):
            response = _anthropic_message(
                api_key=api_key,
                model=args.model,
                messages=messages,
                max_tokens=bounded_tokens,
                timeout=120,
            )
            calls += 1
            usage = response.get("usage") or {}
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
            content = response.get("content") or []
            final_text = _content_text(content) or final_text
            tool_uses = [b for b in content if b.get("type") == "tool_use"]

            messages.append({"role": "assistant", "content": content})
            if not tool_uses:
                break

            results: list[dict[str, Any]] = []
            for block in tool_uses:
                name = str(block.get("name", ""))
                handler = TOOL_HANDLERS.get(name)
                if handler is None:
                    tool_result = f"ERROR: unsupported tool: {name}"
                else:
                    try:
                        tool_result = handler(dict(block.get("input") or {}))
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        tool_result = f"ERROR: {type(exc).__name__}: {exc}"
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.get("id"),
                        "content": tool_result,
                    }
                )
            messages.append({"role": "user", "content": results})
        else:
            error_kind = "max_turns"
            raise DirectExecutorError("direct executor reached max turns")

        pr_url = _open_draft_pr(
            args.issue_number,
            branch,
            args.base,
            f"OC-AUTO #{args.issue_number}: {args.title}",
        )
        if not pr_url:
            error_kind = "no_durable_change"
            raise DirectExecutorError("model completed without repository changes")

        result = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": calls,
            "total_cost_usd": None,
            "modelUsage": {
                args.model: {
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                }
            },
            "result": final_text,
            "pr_url": pr_url,
            "branch": branch,
        }
        _write_result(execution_path, result)
        _github_output(
            {
                "execution_file": execution_path,
                "conclusion": "success",
                "session_id": run_id,
                "pr_url": pr_url,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
        return 0
    except (
        DirectExecutorError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        if not error_kind:
            status = exc.status_code if isinstance(exc, AnthropicHTTPError) else ""
            error_status = str(status or "")
            detail = exc.detail if isinstance(exc, AnthropicHTTPError) else {}
            message = ""
            if isinstance(detail, dict):
                error = detail.get("error") or {}
                if isinstance(error, dict):
                    message = str(error.get("message") or "")
                    error_kind = str(error.get("type") or "")
            error_message = message or str(exc)
            if not error_kind:
                if error_status in {"401", "403"}:
                    error_kind = "authentication_error"
                elif (
                    "credit" in error_message.lower()
                    or "billing" in error_message.lower()
                ):
                    error_kind = "billing_error"
                else:
                    error_kind = "provider_or_executor_error"

        # Attempt best-effort salvage of partial file changes written to disk.
        # When the model reached max_turns or hit a transient 5xx mid-turn, files
        # it wrote via write_file are on disk but never committed.  Committing and
        # pushing them makes the work visible for human-assisted repair without
        # blocking settlement. Authentication failures and billing errors produce
        # no partial work worth salvaging; no_durable_change never writes files.
        partial_branch: str | None = None
        if branch and error_kind in {"max_turns", "provider_or_executor_error"}:
            try:
                dirty = _run(["git", "status", "--porcelain"], timeout=30)
                if dirty.stdout.strip():
                    _run(["git", "add", "-A"], timeout=30)
                    msg = (
                        f"partial(oc): salvage partial changes for "
                        f"#{args.issue_number} [{error_kind}]\n\n"
                        f"Partial work committed by direct executor after {error_kind}; "
                        f"turns={calls}."
                    )
                    commit = _run(["git", "commit", "-m", msg], timeout=60)
                    if commit.returncode == 0:
                        push = _run(
                            ["git", "push", "-u", "origin", branch], timeout=120
                        )
                        if push.returncode == 0:
                            partial_branch = branch
                            print(
                                f"[OC-ANTHROPIC-DIRECT] salvage: committed partial "
                                f"changes to {branch}",
                                file=sys.stderr,
                            )
            except Exception as _salvage_exc:  # noqa: BLE001
                print(
                    f"[OC-ANTHROPIC-DIRECT] salvage skipped: {_salvage_exc}",
                    file=sys.stderr,
                )

        result = {
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "num_turns": calls,
            "total_cost_usd": None,
            "modelUsage": (
                {
                    args.model: {
                        "inputTokens": input_tokens,
                        "outputTokens": output_tokens,
                    }
                }
                if calls
                else {}
            ),
            "error": error_kind,
            "api_error_status": error_status or None,
            "result": error_message or str(exc),
            "branch": branch,
            "partial_branch": partial_branch,
        }
        _write_result(execution_path, result)
        _github_output(
            {
                "execution_file": execution_path,
                "conclusion": "failure",
                "session_id": run_id,
                "pr_url": "",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
        print(
            f"[OC-ANTHROPIC-DIRECT] {error_kind}: {error_message or exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
