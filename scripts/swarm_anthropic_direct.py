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
import ctypes
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from decimal import ROUND_CEILING, Decimal
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
    "scripts/oc_hosted_completion.py",
    "scripts/oc_paid_issue_admission.py",
    "scripts/oc_work_materialize.py",
    "scripts/oc_patch_publish.py",
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
        "description": (
            "Write UTF-8 content. For a small edit to an existing file, provide "
            "old_text to replace exactly one matching literal with content. "
            "Prefer small edits to avoid truncating large whole-file tool calls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "old_text": {"type": "string", "minLength": 1},
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


#: Every subprocess this executor starts runs model-written code or reads
#: model-written files: pytest imports the tests the model wrote, ruff and git
#: read its files. None of it may inherit a credential. GH_TOKEN (issues:
#: write) in a test's environment could open an issue shaped like engine
#: discovery, which the owner's discovery grant would then pay for, or delete
#: admission receipts. So the default environment is scrubbed, and only the
#: deterministic network steps this script itself issues -- ``gh`` and the git
#: remote commands -- receive the inherited one.
SECRET_ENV_NAMES = frozenset(
    {
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "DATABASE_URL",
        "TEST_DATABASE_URL",
    }
)
SECRET_ENV_PATTERN = re.compile(
    r"TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|_DSN$|DATABASE_URL$",
    re.IGNORECASE,
)
#: Runner and OIDC plumbing (ACTIONS_ID_TOKEN_REQUEST_URL/TOKEN,
#: ACTIONS_RUNTIME_TOKEN, ACTIONS_CACHE_URL, ...) is dropped wholesale.
SECRET_ENV_PREFIXES = ("ACTIONS_",)
CREDENTIAL_GIT_COMMANDS = frozenset({"push", "fetch", "pull", "ls-remote", "clone"})
#: A model-written test can write .git/hooks or core.fsmonitor; neither may then
#: run inside a trusted git call. Set through the environment so the command
#: lines stay exactly as they were.
GIT_SAFETY = {
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "core.hooksPath",
    "GIT_CONFIG_VALUE_0": "/dev/null",
    "GIT_CONFIG_KEY_1": "core.fsmonitor",
    "GIT_CONFIG_VALUE_1": "false",
}


def _secret_env_name(name: str) -> bool:
    upper = name.upper()
    return (
        upper in SECRET_ENV_NAMES
        or upper.startswith(SECRET_ENV_PREFIXES)
        or bool(SECRET_ENV_PATTERN.search(upper))
    )


def tool_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    """The inherited environment with every credential-shaped name removed."""
    source = os.environ if environ is None else environ
    clean = {k: v for k, v in source.items() if not _secret_env_name(k)}
    clean.update(GIT_SAFETY)
    return clean


def _needs_credentials(cmd: list[str]) -> bool:
    """Only this script's own remote steps; never a model-chosen check."""
    if not cmd:
        return False
    program = Path(cmd[0]).name
    if program == "gh":
        return True
    return program == "git" and len(cmd) > 1 and cmd[1] in CREDENTIAL_GIT_COMMANDS


def _run(
    cmd: list[str], *, timeout: int = 120, check: bool = False
) -> subprocess.CompletedProcess[str]:
    env = (
        {**os.environ, **GIT_SAFETY} if _needs_credentials(cmd) else tool_environment()
    )
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
        env=env,
    )


def harden_process() -> bool:
    """Make this process non-dumpable, so a child cannot read its environment.

    A model-written test runs as the same user; without this it could read
    ``/proc/<this pid>/environ`` and recover the credentials the scrub above
    withheld. Linux only; reports whether it took effect.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        pr_set_dumpable = 4
        return libc.prctl(pr_set_dumpable, 0, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


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


# Files the model wrote through write_file in this run, and the issue's declared
# "Allowed paths" (None when the task declares none). Only written files are
# committed: running the test suite rewrites tracked artifacts such as
# calyx_runtime_journal.jsonl and runtime/discovery_registry.json, and
# "git add -A" swept those into PR #1855, failing the hosted scope check.
WRITTEN: set[str] = set()
RETAINED: set[str] = set()
ALLOWED_PATHS: set[str] | None = None
_ALLOWED_HEADER = re.compile(r"^\s*Allowed paths:(?P<rest>.*)$", re.IGNORECASE)
_LIST_PATH = re.compile(
    r"^\s*[-*]\s+(?:`(?P<quoted>[^`]+)`(?:\s.*)?|(?P<bare>[\w./-]+))\s*$"
)
_BARE_PATH = re.compile(r"^[\w.-]*(?:/[\w.-]+)+$|^[\w-]+\.\w+$")


def _inline_paths(rest: str) -> set[str]:
    quoted = set(re.findall(r"`([^`]+)`", rest))
    if quoted:
        return quoted
    # Bare paths: read only the leading run of paths, so trailing prose such as
    # "only; do not change runtime/health.py" never widens the scope.
    found: set[str] = set()
    for token in re.split(r"[\s,]+", rest.strip()):
        if token.lower() == "and":
            continue
        path = token.rstrip(".;:")
        if not _BARE_PATH.match(path):
            break
        found.add(path)
        if path != token:
            break
    return found


def _parse_allowed_paths(packet: str) -> set[str] | None:
    """Read the task's "Allowed paths:" declaration, inline or as a bullet list."""
    lines = packet.splitlines()
    found: set[str] | None = None
    for index, line in enumerate(lines):
        header = _ALLOWED_HEADER.match(line)
        if not header:
            continue
        if found is not None:
            return set()  # ambiguous declaration: allow nothing
        found = _inline_paths(header.group("rest"))
        if not found:
            for item in lines[index + 1 :]:
                listed = _LIST_PATH.match(item)
                if not listed:
                    break
                found.add(listed.group("quoted") or listed.group("bare"))
    return found


def _tool_write_file(args: dict[str, Any]) -> str:
    # #1862 lost five turns to a bare "KeyError: 'content'".
    missing = [key for key in ("path", "content") if key not in args]
    if missing:
        raise ValueError(
            "write_file is missing "
            + " and ".join(repr(k) for k in missing)
            + f" (received arguments: {sorted(str(k)[:40] for k in args)[:8]}). "
            "Always pass path and content. For an edit, content is the replacement "
            "text for old_text; to delete old_text, pass content as an empty string."
        )
    if not isinstance(args["path"], str) or not isinstance(args["content"], str):
        raise TypeError("write_file requires string path and content")
    path = _safe_path(str(args["path"]))
    if not _writable(path):
        return f"ERROR: protected path is not writable: {_relative(path)}"
    if ALLOWED_PATHS is not None and _relative(path) not in ALLOWED_PATHS:
        return (
            f"ERROR: {_relative(path)} is outside this task's allowed paths: "
            + ", ".join(sorted(ALLOWED_PATHS))
        )
    content = args["content"]
    if "old_text" in args:
        old_text = args["old_text"]
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("old_text must be a nonempty string")
        current = path.read_text(encoding="utf-8")
        matches = current.count(old_text)
        if matches == 0:
            raise ValueError(
                "old_text was not found. Copy it character for character from "
                "read_file output, including indentation and non-ASCII characters "
                "such as the em dash \u2014; prefer a short, distinctive old_text."
            )
        if matches > 1:
            raise ValueError(
                f"old_text matches {matches} times; extend it with surrounding "
                "lines until it matches exactly once."
            )
        content = current.replace(old_text, content, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    WRITTEN.add(_relative(path))
    return f"WROTE {_relative(path)} bytes={len(content.encode('utf-8'))}"


def _stage_written_files() -> bool:
    """Stage only files the model wrote; report whether anything is staged."""
    paths = sorted(WRITTEN)
    if paths:
        _run(["git", "add", "--", *paths], timeout=30, check=True)
    staged = _run(["git", "diff", "--cached", "--name-only"], timeout=30, check=True)
    return bool(staged.stdout.strip())


def _whitespace_problems() -> str:
    """Report `git diff --check` problems in the written files ('' when clean).

    #1861 (run 38805836543) finished its work, then died committing because a
    written file had a whitespace error; the model is asked to fix it instead.
    """
    # Best effort: the commit-time check in _open_draft_pr stays authoritative.
    try:
        if not WRITTEN or not _stage_written_files():
            return ""
        result = _run(["git", "diff", "--cached", "--check"], timeout=60)
        # Unstage again so the model's own diff checks still compare its
        # working tree against HEAD.
        _run(["git", "reset", "-q", "--", *sorted(WRITTEN)], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode == 0:
        return ""
    return (result.stdout or result.stderr or "whitespace errors").strip()[:2000]


def _autofix_written() -> None:
    """Apply ruff's safe fixes to the Python files the model wrote.

    #1866 twice opened PRs that failed validation on one mechanical finding
    (an unused import, then unsorted imports) that `ruff check --fix` fixes
    deterministically. Only safe fixes, only files in WRITTEN; best effort.
    """
    files = sorted(
        p for p in WRITTEN if p.endswith(".py") and (REPO_ROOT / p).is_file()
    )
    if not files:
        return
    try:
        before = {p: (REPO_ROOT / p).read_bytes() for p in files}
        _run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--fix",
                "--extend-select",
                "I001",
                "--quiet",
                "--",
                *files,
            ],
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return
    # Record what the auto-fix changed (e.g. a removed import) for reviewers.
    try:
        changed = [p for p in files if (REPO_ROOT / p).read_bytes() != before[p]]
    except OSError:
        return
    if changed:
        print("[OC-DIRECT-AUTOFIX] " + json.dumps({"files": changed}), flush=True)


def _lint_problems() -> str:
    """Report `ruff check` problems in changed Python files ('' when clean).

    PR validation runs `ruff check` on every changed Python file, so its
    pre-existing findings count too. #1860 and #1862 opened PRs whose tests
    passed but whose lint failed, and stopped at hosted prepare.
    """
    _autofix_written()
    files = sorted(
        p for p in WRITTEN | RETAINED if p.endswith(".py") and (REPO_ROOT / p).is_file()
    )
    if not files:
        return ""
    try:
        result = _run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--output-format=concise",
                "--",
                *files,
            ],
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    # ruff exits 1 with findings on stdout. Anything else is not actionable by
    # the model and is left to validation: a crash, or a missing ruff, which
    # also exits 1 but writes only "No module named ruff" to stderr.
    findings = (result.stdout or "").strip()
    if result.returncode != 1 or not findings:
        return ""
    return findings[:3000]


def _finish_problems() -> str:
    # Auto-fix first: a fix can itself leave a whitespace problem (removing a
    # trailing import leaves a blank line at EOF) that the probe must report.
    _autofix_written()
    sections = (
        ("git diff --check", _whitespace_problems()),
        ("ruff check", _lint_problems()),
    )
    return "\n".join(f"[{name}]\n{found}" for name, found in sections if found)


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
    print(
        "[OC-DIRECT-CHECK] "
        + json.dumps({"check": name, "target": target, "exit_code": result.returncode}),
        flush=True,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    return _truncate(f"exit_code={result.returncode}\n{combined}", 16000)


TOOL_HANDLERS = {
    "read_file": _tool_read_file,
    "list_files": _tool_list_files,
    "search_text": _tool_search_text,
    "write_file": _tool_write_file,
    "run_check": _tool_run_check,
}


# USD per million tokens. Only models listed here get an actual cost; any other
# model reports none, and the governor ledger keeps its reservation instead.
PRICE_PER_MTOK: dict[str, dict[str, Decimal]] = {
    "claude-haiku-4-5": {
        "input": Decimal("1.00"),
        "output": Decimal("5.00"),
        "cache_write": Decimal("1.25"),  # 5-minute TTL write, 1.25x input
        "cache_read": Decimal("0.10"),
    },
}
USAGE_FIELDS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_write": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
}


def _validated_usage(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    counts = {}
    for kind, field in USAGE_FIELDS.items():
        value = usage.get(field, 0)
        if kind in {"input", "output"} and field not in usage:
            return None
        if type(value) is not int or value < 0:
            return None
        counts[field] = value
    return counts


def _actual_cost_usd(model: str, usage: dict[str, int]) -> str | None:
    """Provider cost of this run from its token usage, or None if unpriced."""
    prices = PRICE_PER_MTOK.get(model)
    if prices is None:
        return None
    counts = _validated_usage(usage)
    if counts is None:
        return None
    total = sum(
        Decimal(counts[field]) * prices[kind] for kind, field in USAGE_FIELDS.items()
    ) / Decimal(1_000_000)
    # Round up: the budget may overcount by a fraction of a cent, never under.
    return str(total.quantize(Decimal("0.0001"), rounding=ROUND_CEILING))


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
            # Automatic prompt caching: each turn resends the whole conversation,
            # so the growing prefix is read from cache at ~0.1x input price.
            "cache_control": {"type": "ephemeral"},
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


def _resume_from_packet(packet: str, issue_number: str) -> tuple[str, str] | None:
    declarations = re.findall(r"^OC-SWARM-RESUME:[ \t]*(.*)$", packet, re.MULTILINE)
    if not declarations:
        return None
    if len(declarations) != 1:
        raise DirectExecutorError("resume declaration must be unique")
    match = re.fullmatch(
        rf"(claude-direct/issue-{re.escape(issue_number)}-[0-9]+)@([a-f0-9]{{40}})",
        declarations[0].strip(),
    )
    if not match:
        raise DirectExecutorError(
            "resume must bind this issue to an exact partial head"
        )
    return match.group(1), match.group(2)


#: The integration commit the model's work starts from, recorded when the
#: branch is prepared. A patch is always the difference from this commit.
BASE_SHA: list[str] = []
#: sha256 of each file handed to the trusted publisher, computed from the bytes
#: this process wrote (never re-read) and printed on this process's stdout,
#: which no model-driven child can write to. The collector refuses any file
#: whose bytes no longer match, so nothing the model ran can swap them later.
ARTIFACT_DIGESTS: dict[str, str] = {}
ARTIFACT_MARKER = "[OC-DIRECT-ARTIFACT]"


def _record_artifact(path: Path, text: str) -> None:
    data = text.encode("utf-8")
    path.write_bytes(data)
    ARTIFACT_DIGESTS[path.name] = hashlib.sha256(data).hexdigest()


def _prepare_branch(
    issue_number: str,
    run_id: str,
    base: str,
    *,
    resume: tuple[str, str] | None = None,
) -> str:
    RETAINED.clear()
    BASE_SHA.clear()
    branch = f"claude-direct/issue-{issue_number}-{run_id}"
    _run(["git", "fetch", "origin", base], timeout=120, check=True)
    BASE_SHA.append(
        _run(["git", "rev-parse", f"origin/{base}"], check=True).stdout.strip()
    )
    if resume:
        if base != "oc-autonomous-integration":
            raise DirectExecutorError("resume requires the integration boundary")
        branch, expected_sha = resume
        _run(["git", "fetch", "origin", branch], timeout=120, check=True)
        actual_sha = _run(
            ["git", "rev-parse", f"origin/{branch}"], check=True
        ).stdout.strip()
        if actual_sha != expected_sha:
            raise DirectExecutorError("partial branch moved; refresh the repair packet")
        # A normal merge must retain both the partial work and current control
        # plane. Fail before a provider call if ancestry or protected scope is
        # unavailable; never force-push or silently reset the remote branch.
        _run(["git", "merge-base", expected_sha, f"origin/{base}"], check=True)
        files = _run(
            ["git", "diff", "--name-only", f"origin/{base}...{expected_sha}"],
            check=True,
        ).stdout.splitlines()
        if not files or any(not _writable(_safe_path(path)) for path in files):
            raise DirectExecutorError("partial branch has no admissible work set")
        RETAINED.update(files)
        start = expected_sha
    else:
        start = f"origin/{base}"
    _run(["git", "checkout", "-B", branch, start], timeout=60, check=True)
    _run(
        ["git", "config", "user.name", "orchid-continuum-orchestrator[bot]"],
        timeout=30,
        check=True,
    )
    _run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ],
        timeout=30,
        check=True,
    )
    if resume:
        _run(["git", "merge", "--no-edit", f"origin/{base}"], timeout=120, check=True)
        print(
            "[OC-DIRECT-RESUME] "
            + json.dumps({"branch": branch, "source_sha": resume[1]}),
            flush=True,
        )
    return branch


def _open_draft_pr(issue_number: str, branch: str, base: str, title: str) -> str:
    # Also covers a model that finished on its last turn, when no finish
    # feedback round (and so no earlier auto-fix) was possible.
    _autofix_written()
    if not _stage_written_files():
        return ""

    _run(["git", "diff", "--cached", "--check"], timeout=60, check=True)
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


def _emit_patch(directory: Path, issue_number: str, *, partial: bool) -> str:
    """Hand the work to the trusted publisher instead of pushing it.

    In the split lane this process holds no write credential. It writes the
    difference from the recorded integration commit as a patch, with a small
    manifest; the privileged job verifies the patch against the admitted scope
    and is the only party that commits, pushes or opens a pull request.
    Returns the patch path, or "" when there is no change.
    """
    if not partial:
        _autofix_written()
    if not BASE_SHA or not re.fullmatch(r"[0-9a-f]{40}", BASE_SHA[0]):
        raise DirectExecutorError("integration base commit unknown")
    _stage_written_files()
    diff = _run(
        [
            "git",
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            BASE_SHA[0],
        ],
        timeout=60,
        check=True,
    ).stdout
    if not diff.strip():
        return ""
    if not partial:
        _run(
            ["git", "diff", "--cached", "--check", BASE_SHA[0]], timeout=60, check=True
        )
    directory.mkdir(parents=True, exist_ok=True)
    patch = directory / "patch.diff"
    _record_artifact(patch, diff)
    _record_artifact(
        directory / "manifest.json",
        json.dumps(
            {
                "schema": "oc.direct-patch.v1",
                "issue": int(issue_number),
                "base_sha": BASE_SHA[0],
                "partial": partial,
            },
            sort_keys=True,
        ),
    )
    return str(patch)


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    _record_artifact(path, json.dumps(payload, indent=2, sort_keys=True))
    print(
        ARTIFACT_MARKER + " " + json.dumps(ARTIFACT_DIGESTS, sort_keys=True), flush=True
    )
    # Keep execution/usage evidence in the durable job log as well as the
    # runner-local classifier input. Never log model text or raw API errors.
    receipt = {
        key: payload[key]
        for key in (
            "type",
            "subtype",
            "is_error",
            "num_turns",
            "modelUsage",
            "total_cost_usd",
            "pr_url",
            "branch",
            "partial_branch",
            "error",
            "api_error_status",
        )
        if key in payload
    }
    print("[OC-DIRECT-RECEIPT] " + json.dumps(receipt, sort_keys=True), flush=True)


def _github_output(values: dict[str, Any]) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
            handle.write(f"{key}={rendered}\n")


def _turn_budget_notice(turn: int, limit: int) -> str:
    """Tell the model how many turns remain after this tool result.

    Without this the model cannot see the ceiling: a first live cheap-tier run
    had its change written and its tests passing by turn 15, kept re-verifying,
    and hit max_turns, so no draft PR was opened.
    """
    remaining = max(limit - turn, 0)
    notice = f"[turn budget] {turn} of {limit} turns used; {remaining} remaining."
    if remaining <= 3:
        notice += (
            " Finish now: if the change is written and its focused tests pass, reply "
            "with a short summary and no tool call."
        )
    return notice


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
    # Split lane: write a patch for the trusted publisher; never push.
    parser.add_argument("--emit-patch-dir", default="")
    args = parser.parse_args()
    emit_dir = Path(args.emit_patch_dir) if args.emit_patch_dir else None

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY_REQUIRED")
    if not harden_process():
        print("[OC-ANTHROPIC-DIRECT] warning: process not hardened", file=sys.stderr)
    run_id = os.getenv("GITHUB_RUN_ID", str(int(time.time())))
    packet = Path(args.packet_file).read_text(encoding="utf-8")
    execution_path = Path(args.execution_file)
    global ALLOWED_PATHS
    ALLOWED_PATHS = _parse_allowed_paths(packet)
    WRITTEN.clear()
    RETAINED.clear()
    ARTIFACT_DIGESTS.clear()

    input_tokens = 0
    output_tokens = 0
    usage_totals = dict.fromkeys(USAGE_FIELDS.values(), 0)
    usage_complete = True
    # A call that dies in transport (timeout, cut-off response) may still be
    # billed without its usage reaching us; the run then reports no actual
    # cost so the ledger keeps the reservation.
    call_in_flight = False
    calls = 0
    branch = ""
    pr_url = ""
    error_kind = ""
    error_status = ""
    error_message = ""
    final_text = ""

    try:
        branch = _prepare_branch(
            args.issue_number,
            run_id,
            args.base,
            resume=_resume_from_packet(packet, args.issue_number),
        )
        system = (
            "You are the Orchid Continuum bounded engineering executor. Work only on the supplied "
            "task. Use repository tools to inspect and edit. Do not modify .github/workflows, "
            "credentials, secrets, production state, scientific data, taxonomy activation, or "
            "publication controls. Run focused tests. When implementation is complete, stop; the "
            "wrapper will commit, push, and open the draft PR."
        )
        bounded_turns = min(max(args.max_turns, 1), 24)
        system += (
            f" You have at most {bounded_turns} model turns, and every tool call uses one. "
            "Finishing means replying with a short summary and no tool call. Finish as soon "
            "as the required change is written and its focused tests and lint pass; do not "
            "re-run passing checks or re-read files you just verified. Reaching the turn limit "
            "discards the draft PR, even if the work is complete."
        )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"{system}\n\n{packet}"}
        ]

        # The economy router's cheap tier is budgeted for up to 24 turns.
        # Honor that route ceiling instead of silently truncating it to 12,
        # while still keeping a hard repository-local cap (bounded_turns above).
        bounded_tokens = min(max(args.max_tokens, 256), 3072)
        for turn in range(1, bounded_turns + 1):
            call_in_flight = True
            response = _anthropic_message(
                api_key=api_key,
                model=args.model,
                messages=messages,
                max_tokens=bounded_tokens,
                timeout=120,
            )
            call_in_flight = False
            calls += 1
            usage = _validated_usage(response.get("usage"))
            if usage is None:
                usage_complete = False
                usage = dict.fromkeys(USAGE_FIELDS.values(), 0)
            input_tokens += usage["input_tokens"]
            output_tokens += usage["output_tokens"]
            for field in usage_totals:
                usage_totals[field] += usage[field]
            content = response.get("content") or []
            final_text = _content_text(content) or final_text
            tool_uses = [b for b in content if b.get("type") == "tool_use"]

            messages.append({"role": "assistant", "content": content})
            if not tool_uses:
                # A fix needs a write turn and a finishing turn.
                problems = _finish_problems() if turn < bounded_turns - 1 else ""
                if not problems:
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "PR validation would reject your changes: it runs "
                            "`git diff --check` and `ruff check` on every changed "
                            "Python file, including findings already in the file. "
                            "Fix what is reported below using write_file, then finish. "
                            # The bare count: _turn_budget_notice's "finish now"
                            # wording would contradict the fix request.
                            f"[turn budget] {turn} of {bounded_turns} turns used; "
                            f"{bounded_turns - turn} remaining.\n" + problems
                        ),
                    }
                )
                continue

            # A reply cut off at max_tokens ends in a tool call whose arguments
            # are incomplete (#1863: eight write_file calls failed with
            # KeyError 'content' while rewriting a 676-line file). That call is
            # not run; the model is told to make a smaller edit instead.
            cut_off = (
                tool_uses[-1] if response.get("stop_reason") == "max_tokens" else None
            )
            results: list[dict[str, Any]] = []
            for block in tool_uses:
                name = str(block.get("name", ""))
                handler = TOOL_HANDLERS.get(name)
                if block is cut_off:
                    tool_result = (
                        f"ERROR: your reply reached the {bounded_tokens}-token output "
                        "limit before this call's arguments were complete, so it was "
                        "not run. Make a smaller change: write_file with a short, "
                        "exact old_text and only its replacement, never a whole file."
                    )
                elif handler is None:
                    tool_result = f"ERROR: unsupported tool: {name}"
                else:
                    try:
                        tool_result = handler(dict(block.get("input") or {}))
                    except (
                        OSError,
                        ValueError,
                        KeyError,
                        TypeError,
                        subprocess.SubprocessError,
                    ) as exc:
                        tool_result = f"ERROR: {type(exc).__name__}: {exc}"
                print(
                    "[OC-DIRECT-TOOL] "
                    + json.dumps(
                        {
                            "turn": turn,
                            "tool": name if handler else "unsupported",
                            "input_error": tool_result.startswith("ERROR:"),
                            # #1863 failed eleven writes with no recorded reason.
                            **(
                                {"error": tool_result[:160]}
                                if tool_result.startswith("ERROR:")
                                else {}
                            ),
                        }
                    ),
                    flush=True,
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.get("id"),
                        "content": tool_result,
                    }
                )
            results.append(
                {"type": "text", "text": _turn_budget_notice(turn, bounded_turns)}
            )
            messages.append({"role": "user", "content": results})
        else:
            error_kind = "max_turns"
            raise DirectExecutorError("direct executor reached max turns")

        if emit_dir is not None:
            pr_url = _emit_patch(emit_dir, args.issue_number, partial=False)
        else:
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
            "total_cost_usd": (
                _actual_cost_usd(args.model, usage_totals) if usage_complete else None
            ),
            "modelUsage": {
                args.model: {
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                    "cacheCreationInputTokens": usage_totals[
                        "cache_creation_input_tokens"
                    ],
                    "cacheReadInputTokens": usage_totals["cache_read_input_tokens"],
                }
            },
            "result": final_text,
            "pr_url": "" if emit_dir is not None else pr_url,
            "patch_file": pr_url if emit_dir is not None else None,
            "branch": branch,
        }
        _write_result(execution_path, result)
        _github_output(
            {
                "execution_file": execution_path,
                "conclusion": "success",
                "session_id": run_id,
                "pr_url": "" if emit_dir is not None else pr_url,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
        return 0
    except (
        DirectExecutorError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
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
        if (
            emit_dir is not None
            and branch
            and error_kind in {"max_turns", "provider_or_executor_error"}
        ):
            try:
                if _emit_patch(emit_dir, args.issue_number, partial=True):
                    partial_branch = "pending-trusted-publish"
            except Exception as _salvage_exc:  # noqa: BLE001
                print(
                    f"[OC-ANTHROPIC-DIRECT] salvage skipped: {_salvage_exc}",
                    file=sys.stderr,
                )
        elif branch and error_kind in {"max_turns", "provider_or_executor_error"}:
            try:
                if _stage_written_files():
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
            "total_cost_usd": (
                _actual_cost_usd(args.model, usage_totals)
                if calls
                and usage_complete
                and not (call_in_flight and not isinstance(exc, AnthropicHTTPError))
                else None
            ),
            "modelUsage": (
                {
                    args.model: {
                        "inputTokens": input_tokens,
                        "outputTokens": output_tokens,
                        "cacheCreationInputTokens": usage_totals[
                            "cache_creation_input_tokens"
                        ],
                        "cacheReadInputTokens": usage_totals["cache_read_input_tokens"],
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
