"""The first provider-free lane that changes code: a one-line pinned requirement.

Eighty recent autonomous runs across three repositories produced no code
change. Every receipt was validate-only, ``changed_file_count: 0``. The engine
could prove a defect and could prove a fix, and could not produce one.

This lane produces one, for exactly the two discovery sources whose remedy the
evidence fully determines:

* ``dependency-gap``: a pytest marker's distribution is undeclared, so the line
  ``<distribution>==<version>`` goes into ``requirements-dev.txt``;
* ``undeclared-import``: production code imports a module an installed
  distribution provides and nothing declares, so the same line goes into
  ``requirements.txt``.

The version is the one *installed* in the lane's environment, read from
``importlib.metadata`` and never from an index: a pin this lane did not observe
is a pin it made up. When the distribution is not installed, the lane may
provision it once -- constrained by every requirements file, so the resolver
cannot move an existing pin -- and then reads what arrived. Everything else is
a refusal: an unparseable version, a file that already declares it, a
candidate from any other source, a condition the evidence no longer shows.

What the lane does with a derivable edit, in order, on a branch named from the
condition's fingerprint and never on the checked-out revision:

1. runs the candidate's own validation command and records the node ids that
   fail *before*;
2. applies the one line;
3. runs the same command again and requires exit 0 **and** every previously
   failing node id absent from the result -- otherwise the branch is removed
   and the issue settles blocked with both runs' evidence;
4. commits, pushes, and opens a draft pull request against the integration
   branch whose body carries the fingerprint, the diff, and both runs;
5. emits a receipt that names the changed file count, the PR number, the exact
   commit and the sha256 of the diff, and raises rather than emit one that
   does not.

It is idempotent by the same identity the intake uses: a fingerprint. A pull
request already open for it means this lane files nothing and edits nothing,
and reports the PR it found. No provider is called; nothing is merged; nothing
is deployed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from scripts import oc_work_discovery as discovery
from scripts import oc_work_materialize as materialize
from scripts.oc_swarm_provider_free_worker import declared_validation_commands
from scripts.oc_validation_commands import VALIDATION_COMMANDS

RECEIPT_SCHEMA = "oc.provider-free-edit-result.v1"
BRANCH_PREFIX = "oc/discovered-"
DEFAULT_INTEGRATION_BRANCH = "oc-autonomous-integration"
DEFAULT_TIMEOUT_SECONDS = 600

#: A version this lane is willing to write. PEP 440's public shape, no local
#: segment: a pin with a ``+local`` suffix names a build no index serves.
PINNABLE_VERSION = re.compile(
    r"^(?:\d+!)?\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?$"
)
DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
PR_URL = re.compile(r"/pull/(?P<number>\d+)\s*$")

Transport = Callable[[list[str], dict | None], Any]
Git = Callable[[list[str], str | None], str]
Runner = Callable[
    [tuple[str, ...], str | None, int], "subprocess.CompletedProcess[str]"
]


class LaneRefusal(RuntimeError):
    """The lane declined to write. Carries the reason a receipt records."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Edit:
    """One derived line, and where it goes."""

    fingerprint: str
    path: str
    distribution: str
    version: str
    validation_command: str
    provisioned: bool = False

    @property
    def line(self) -> str:
        return f"{self.distribution}=={self.version}"

    def to_record(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "distribution": self.distribution,
            "version": self.version,
            "provisioned": self.provisioned,
        }


# -- Derivation ---------------------------------------------------------------


def canonical_distribution(name: str) -> str:
    """PEP 503 normalised name: ``Foo.Bar_baz`` and ``foo-bar-baz`` are one.

    pip treats every run of ``-``, ``_`` and ``.`` as the same separator, so a
    file that declares ``pytest.asyncio`` already declares ``pytest-asyncio``;
    writing it a second time is a duplicate requirement, not a remedy.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def derive_edit(
    candidate: Mapping[str, Any],
    root: Path,
    *,
    version_of: Callable[[str], str | None] = discovery.installed_version,
) -> Edit:
    """The exact line the evidence determines, or a refusal.

    Every branch that refuses names what was missing. None of them guesses: a
    distribution that is not installed yields no version, and no version is
    not a reason to write ``>=`` or nothing at all.
    """
    source = str(candidate.get("source") or "")
    if source not in discovery.MECHANICAL_SOURCES:
        raise LaneRefusal("unsupported_source", source or "unnamed")
    if not materialize.is_mechanically_remediable(candidate):
        raise LaneRefusal(
            "no_structured_remedy", "candidate carries no declare-distribution remedy"
        )
    remedy = candidate["remedy"]
    distribution = str(remedy.get("distribution") or "")
    if not DISTRIBUTION_NAME.fullmatch(distribution):
        raise LaneRefusal("invalid_distribution_name", distribution)
    path = str(remedy.get("requirements_file") or "")
    if path != discovery.MECHANICAL_SOURCES[source]:
        raise LaneRefusal(
            "remedy_file_mismatch", f"{path!r} is not the file for {source}"
        )
    fingerprint = str(candidate.get("fingerprint") or "")
    if not re.fullmatch(r"[a-f0-9]{16}", fingerprint):
        raise LaneRefusal("unusable_fingerprint", fingerprint)
    command = str(candidate.get("validation_command") or "")
    if command not in VALIDATION_COMMANDS:
        raise LaneRefusal("no_validation_command", command or "none bound")
    normalised = canonical_distribution(distribution)
    if normalised in {
        canonical_distribution(name) for name in discovery.declared_distributions(root)
    }:
        raise LaneRefusal("already_declared", distribution)
    version = version_of(distribution)
    if version is None:
        raise LaneRefusal("distribution_not_installed", distribution)
    if not PINNABLE_VERSION.fullmatch(str(version)):
        raise LaneRefusal("version_unparseable", str(version))
    return Edit(
        fingerprint=fingerprint,
        path=path,
        distribution=distribution,
        version=str(version),
        validation_command=command,
    )


def apply_edit(edit: Edit, root: Path) -> bool:
    """Append the pinned line to the requirements file. True when it wrote.

    Idempotent: a file that already carries the exact line is left alone. The
    comment names the fingerprint so a reader can find the issue that filed
    the condition without a search.
    """
    target = root / edit.path
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if any(line.strip() == edit.line for line in existing.splitlines()):
        return False
    block = (
        f"# Declared by the provider-free edit lane from discovery fingerprint "
        f"{edit.fingerprint}: the installed version, pinned.\n{edit.line}\n"
    )
    if existing and not existing.endswith("\n"):
        existing += "\n"
    target.write_text(existing + block, encoding="utf-8")
    return True


# -- Environment ---------------------------------------------------------------


def github(args: list[str], payload: dict | None = None) -> Any:
    result = subprocess.run(
        ["gh", *args],
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    text = result.stdout.strip()
    return json.loads(text) if text.startswith(("{", "[")) else text


def git(args: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300, check=True
    )
    return result.stdout.strip()


def provision_with_pip(distribution: str, root: Path) -> None:
    """Install ``distribution`` once, constrained by every requirements file.

    The constraint files keep the resolver from moving any pin the repository
    already holds; only the missing distribution and what it needs arrive.
    This is the one network action the lane performs, and it spends nothing.
    """
    args = [sys.executable, "-m", "pip", "install", "--quiet"]
    for requirements in sorted(root.glob("requirements*.txt")):
        args += ["-c", str(requirements)]
    args.append(distribution)
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=600)


def default_runner(
    argv: tuple[str, ...], cwd: str | None, timeout: int
) -> subprocess.CompletedProcess[str]:
    from scripts.oc_provider_free_validate import sanitized_environment

    return subprocess.run(
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=sanitized_environment(),
    )


# -- Validation with node ids --------------------------------------------------


def run_validation(
    command_id: str,
    *,
    cwd: str,
    runner: Runner = default_runner,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run one registered command and keep the node ids, not only a digest.

    ``oc_provider_free_validate`` records a digest and a tail, which is enough
    to settle a validate task and not enough to say *which* tests moved. This
    lane's whole claim is that specific node ids stopped failing, so it reads
    the full output with the same regex discovery uses on pytest reports.
    """
    command = VALIDATION_COMMANDS[command_id]
    timed_out = False
    exit_code: int | None = None
    output = ""
    try:
        completed = runner(command.argv, cwd, timeout)
        exit_code = int(completed.returncode)
        output = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = _decode(exc.stdout) + _decode(exc.stderr)
    failing = sorted(
        {match.group("nodeid") for match in discovery.PYTEST_OUTCOME.finditer(output)}
    )
    has_summary = bool(discovery.PYTEST_SUMMARY.search(output))
    return {
        "command_id": command_id,
        "argv": list(command.argv),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "passed": exit_code == 0 and not timed_out,
        "has_summary": has_summary,
        "failing_node_ids": failing,
        "output_digest": "sha256:" + hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output_tail": output[-1200:],
    }


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def judge(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[bool, str]:
    """Did the edit do what the candidate said it would?

    Two conditions, both required: the command now exits zero, and no node id
    that failed before still fails. A run without a pytest summary line is not
    read as a result at all -- an empty failure set from a run that collected
    nothing is the same shape as green, and it is not green.
    """
    if not before.get("has_summary") or not after.get("has_summary"):
        return False, "a validation run carried no pytest summary line"
    if not after.get("passed"):
        return False, f"validation exited {after.get('exit_code')} after the edit"
    still = sorted(
        set(before.get("failing_node_ids") or [])
        & set(after.get("failing_node_ids") or [])
    )
    if still:
        return False, f"{len(still)} previously failing node id(s) still fail"
    return True, "validation passed and every previously failing node id now passes"


# -- The lane ------------------------------------------------------------------


def branch_name(fingerprint: str) -> str:
    return f"{BRANCH_PREFIX}{fingerprint}"


def open_pull_requests(
    repository: str, fingerprint: str, *, call: Transport = github
) -> list[dict[str, Any]]:
    """Open pull requests whose body carries this exact fingerprint marker."""
    if not materialize.REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")
    if not re.fullmatch(r"[a-f0-9]{16}", fingerprint):
        raise ValueError("invalid fingerprint")
    rows = call(
        [
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
            "--search",
            f'"{fingerprint}" in:body',
            "--limit",
            "50",
            "--json",
            "number,url,headRefName,body",
        ],
        None,
    )
    if not isinstance(rows, list):
        raise materialize.IncompleteHistory("pull_request_search_unreadable")
    found = []
    for row in rows:
        if not isinstance(row, dict):
            raise materialize.IncompleteHistory("unresolvable_pull_request_row")
        match = materialize.FINGERPRINT.search(str(row.get("body") or ""))
        if (
            match
            and match.group("value") == fingerprint
            and isinstance(row.get("number"), int)
        ):
            found.append(row)
    return sorted(found, key=lambda row: row["number"])


def pull_request_body(
    edit: Edit,
    candidate: Mapping[str, Any],
    *,
    issue_number: int,
    diff: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    base_sha: str,
    commit_sha: str,
) -> str:
    lines = [
        (
            f"Filed by the provider-free edit lane for #{issue_number} from a "
            "`scripts/oc_work_discovery.py` candidate. No person selected it and no "
            "model wrote it: the line below is the evidence's own remedy, pinned to the "
            "version installed where the lane ran."
        ),
        "",
        "## Condition",
        "",
        str(candidate.get("summary") or ""),
        "",
        "## Change",
        "",
        f"- `{edit.path}`: add `{edit.line}`",
        f"- base: `{base_sha}`; commit: `{commit_sha}`",
        f"- provisioned into the lane environment before pinning: {'yes' if edit.provisioned else 'no'}",
        "",
        "```diff",
        diff.rstrip("\n"),
        "```",
        "",
        "## Validation",
        "",
        f"Command `{edit.validation_command}` (`{' '.join(after.get('argv') or [])}`).",
        "",
        (
            f"- before: exit {before.get('exit_code')}, {len(before.get('failing_node_ids') or [])} "
            f"failing node id(s), digest `{before.get('output_digest')}`"
        ),
        (
            f"- after: exit {after.get('exit_code')}, {len(after.get('failing_node_ids') or [])} "
            f"failing node id(s), digest `{after.get('output_digest')}`"
        ),
        "",
    ]
    for nodeid in before.get("failing_node_ids") or []:
        lines.append(f"- `{nodeid}` — failed before, passes after")
    lines += [
        "",
        "```",
        str(after.get("output_tail") or "").rstrip("\n")[-800:],
        "```",
        "",
        (
            "No provider call, merge, deploy, credential change or production mutation. "
            "An independent checker verifies this exact head before integration."
        ),
        "",
        f"{materialize.FINGERPRINT_MARKER}: {edit.fingerprint}",
    ]
    return "\n".join(lines)


def _receipt(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "outcome": "",
        "disposition": "blocked",
        "reason": "",
        "fingerprint": None,
        "issue_number": None,
        "validation_commands": [],
        "validation_passed": False,
        "changed_file_count": 0,
        "changed_files": [],
        "pr_number": None,
        "pr_url": None,
        "branch": None,
        "commit_sha": None,
        "diff_sha256": None,
        "edit": None,
        "before": None,
        "after": None,
        "safety": {
            "provider_calls": False,
            "merge_to_main": False,
            "push_to_main": False,
            "production_deploy": False,
            "scientific_mutation": False,
            "checkout_writes": False,
        },
    }
    base.update(fields)
    return finalize_receipt(base)


def finalize_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Refuse to emit a receipt that claims more than it can show.

    A ``pr_opened`` receipt without a PR number, a full commit id, a diff
    digest and exactly one changed file is the false pass this lane exists to
    make impossible, so it raises here rather than being written anywhere.
    """
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("receipt schema is not the edit lane's")
    outcome = receipt.get("outcome")
    if outcome == "pr_opened":
        number = receipt.get("pr_number")
        if not isinstance(number, int) or number <= 0:
            raise ValueError("pr_opened receipt carries no pull request number")
        if not isinstance(receipt.get("commit_sha"), str) or not FULL_SHA.fullmatch(
            receipt["commit_sha"]
        ):
            raise ValueError("pr_opened receipt carries no full commit id")
        if not isinstance(receipt.get("diff_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", receipt["diff_sha256"]
        ):
            raise ValueError("pr_opened receipt carries no diff digest")
        if (
            receipt.get("changed_file_count") != 1
            or len(receipt.get("changed_files") or []) != 1
        ):
            raise ValueError("pr_opened receipt must change exactly one file")
        if not isinstance(receipt.get("branch"), str) or not receipt[
            "branch"
        ].startswith(BRANCH_PREFIX):
            raise ValueError("pr_opened receipt names no lane branch")
        if receipt.get("disposition") != "blocked":
            raise ValueError("a pull request parks the issue; it does not complete it")
        url = receipt.get("pr_url")
        found = PR_URL.search(url) if isinstance(url, str) else None
        if not found or int(found.group("number")) != number:
            raise ValueError("pr_opened receipt carries no URL for its pull request")
        if receipt.get("validation_passed") is not True:
            raise ValueError("pr_opened receipt does not record a passing validation")
        if not isinstance(receipt.get("fingerprint"), str) or not re.fullmatch(
            r"[a-f0-9]{16}", receipt["fingerprint"]
        ):
            raise ValueError("pr_opened receipt carries no discovery fingerprint")
        issue_number = receipt.get("issue_number")
        if not isinstance(issue_number, int) or issue_number <= 0:
            raise ValueError("pr_opened receipt names no issue")
        commands = receipt.get("validation_commands")
        if not isinstance(commands, list) or len(commands) != 1:
            raise ValueError("pr_opened receipt names no single validation command")
        edit = receipt.get("edit")
        if (
            not isinstance(edit, Mapping)
            or edit.get("path") != (receipt.get("changed_files") or [None])[0]
        ):
            raise ValueError("pr_opened receipt's edit does not name the changed file")
        for side in ("before", "after"):
            run = receipt.get(side)
            if not isinstance(run, Mapping) or run.get("command_id") != commands[0]:
                raise ValueError(f"pr_opened receipt carries no {side} validation run")
        if not isinstance(receipt.get("reason"), str) or not receipt["reason"]:
            raise ValueError("pr_opened receipt carries no reason")
        safety = receipt.get("safety")
        if (
            not isinstance(safety, Mapping)
            or not safety
            or any(value is not False for value in safety.values())
        ):
            raise ValueError("pr_opened receipt carries no all-false safety record")
    elif outcome == "already_open":
        if (
            not isinstance(receipt.get("pr_number"), int)
            or receipt.get("changed_file_count") != 0
        ):
            raise ValueError("already_open receipt is malformed")
    elif outcome == "condition_absent_validated":
        if (
            receipt.get("validation_passed") is not True
            or receipt.get("changed_file_count") != 0
        ):
            raise ValueError("condition_absent_validated receipt is malformed")
    elif outcome in {"refused", "validation_failed", "unconfirmed"}:
        if (
            receipt.get("disposition") != "blocked"
            or receipt.get("changed_file_count") != 0
        ):
            raise ValueError(f"{outcome} receipt must settle blocked with no change")
    else:
        raise ValueError(f"unknown edit lane outcome {outcome!r}")
    return receipt


def run_lane(
    issue: Mapping[str, Any],
    *,
    repository: str,
    root: Path,
    base_sha: str,
    integration_branch: str = DEFAULT_INTEGRATION_BRANCH,
    call: Transport = github,
    git_call: Git = git,
    runner: Runner = default_runner,
    version_of: Callable[[str], str | None] = discovery.installed_version,
    provision: Callable[[str, Path], None] | None = provision_with_pip,
    discover: Callable[[Path], dict[str, Any]] = lambda root: discovery.discover(root),
    worktree_root: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """One bounded pass over one leased issue. Returns the receipt.

    Idempotency comes first and costs no lease: an open pull request for the
    fingerprint ends the pass before anything is read from the tree.
    """
    if not materialize.REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")
    if not FULL_SHA.fullmatch(str(base_sha or "")):
        raise ValueError("base sha must be a full commit id")
    number = int(issue.get("number") or 0)
    if number <= 0:
        raise ValueError("issue number is required")
    body = str(issue.get("body") or "")
    commands = declared_validation_commands(body)
    match = materialize.FINGERPRINT.search(body)
    if not match:
        return _receipt(
            outcome="refused",
            reason="no_fingerprint",
            issue_number=number,
            validation_commands=commands,
        )
    fingerprint = match.group("value")

    existing = open_pull_requests(repository, fingerprint, call=call)
    if existing:
        first = existing[0]
        return _receipt(
            outcome="already_open",
            reason="pull_request_already_open",
            fingerprint=fingerprint,
            issue_number=number,
            validation_commands=commands,
            pr_number=int(first["number"]),
            pr_url=first.get("url"),
            branch=first.get("headRefName"),
        )

    report = discover(root)
    candidate = next(
        (
            row
            for row in report.get("candidates") or []
            if row.get("fingerprint") == fingerprint
        ),
        None,
    )
    if candidate is None:
        # The condition is gone. Prove it with the command the issue names and
        # settle from that, not from the absence alone.
        if len(commands) != 1:
            return _receipt(
                outcome="refused",
                reason="condition_absent_but_no_single_command",
                fingerprint=fingerprint,
                issue_number=number,
                validation_commands=commands,
            )
        if commands[0] not in VALIDATION_COMMANDS:
            return _receipt(
                outcome="refused",
                reason="unknown_validation_command",
                fingerprint=fingerprint,
                issue_number=number,
                validation_commands=commands,
            )
        result = run_validation(
            commands[0], cwd=str(root), runner=runner, timeout=timeout
        )
        passed = bool(result["passed"] and result["has_summary"])
        return _receipt(
            outcome="condition_absent_validated" if passed else "validation_failed",
            reason="condition_absent"
            if passed
            else "condition_absent_but_validation_failed",
            disposition="done" if passed else "blocked",
            fingerprint=fingerprint,
            issue_number=number,
            validation_commands=commands,
            validation_passed=passed,
            after=result,
        )

    try:
        edit = derive_edit(candidate, root, version_of=version_of)
    except LaneRefusal as refusal:
        if refusal.reason != "distribution_not_installed" or provision is None:
            return _receipt(
                outcome="refused",
                reason=refusal.reason,
                fingerprint=fingerprint,
                issue_number=number,
                validation_commands=commands,
                edit={"detail": refusal.detail},
            )
        edit = None
    if commands != [str(candidate.get("validation_command") or "")]:
        return _receipt(
            outcome="refused",
            reason="issue_and_candidate_disagree_on_command",
            fingerprint=fingerprint,
            issue_number=number,
            validation_commands=commands,
        )

    branch = branch_name(fingerprint)
    if git_call(["ls-remote", "--heads", "origin", branch], str(root)).strip():
        return _receipt(
            outcome="unconfirmed",
            reason="branch_exists_without_pull_request",
            fingerprint=fingerprint,
            issue_number=number,
            validation_commands=commands,
            branch=branch,
        )

    workdir = Path(
        tempfile.mkdtemp(
            prefix="oc-edit-", dir=str(worktree_root) if worktree_root else None
        )
    )
    worktree = workdir / "tree"
    git_call(["worktree", "add", "--detach", str(worktree), base_sha], str(root))
    try:
        git_call(["checkout", "-B", branch], str(worktree))
        command_id = commands[0]
        before = run_validation(
            command_id, cwd=str(worktree), runner=runner, timeout=timeout
        )
        if edit is None:
            # Provision, then derive again: the version written is the one
            # that actually arrived, read from the environment.
            provision(candidate["remedy"]["distribution"], worktree)  # type: ignore[misc]
            try:
                edit = derive_edit(candidate, worktree, version_of=version_of)
            except LaneRefusal as refusal:
                return _receipt(
                    outcome="refused",
                    reason=refusal.reason,
                    fingerprint=fingerprint,
                    issue_number=number,
                    validation_commands=commands,
                    edit={"detail": refusal.detail, "provisioned": True},
                    before=before,
                )
            edit = replace(edit, provisioned=True)
        if not apply_edit(edit, worktree):
            return _receipt(
                outcome="refused",
                reason="already_declared",
                fingerprint=fingerprint,
                issue_number=number,
                validation_commands=commands,
                edit=edit.to_record(),
            )
        after = run_validation(
            command_id, cwd=str(worktree), runner=runner, timeout=timeout
        )
        ok, why = judge(before, after)
        if not ok:
            return _receipt(
                outcome="validation_failed",
                reason=why,
                fingerprint=fingerprint,
                issue_number=number,
                validation_commands=commands,
                edit=edit.to_record(),
                before=before,
                after=after,
            )

        git_call(["add", "--", edit.path], str(worktree))
        git_call(
            [
                "-c",
                "user.name=oc-edit-lane",
                "-c",
                "user.email=oc-edit-lane@users.noreply.github.com",
                "commit",
                "-q",
                "-m",
                (
                    f"fix(deps): declare {edit.line} in {edit.path}\n\n"
                    f"Applied by the provider-free edit lane for #{number}. The version is the one "
                    f"installed where the lane ran; `{command_id}` failed {len(before['failing_node_ids'])} "
                    f"node id(s) before and passes after.\n\n{materialize.FINGERPRINT_MARKER}: {fingerprint}"
                ),
            ],
            str(worktree),
        )
        commit_sha = git_call(["rev-parse", "HEAD"], str(worktree)).strip()
        changed = [
            line
            for line in git_call(
                ["diff", "--name-only", base_sha, commit_sha], str(worktree)
            ).splitlines()
            if line
        ]
        diff = git_call(["diff", base_sha, commit_sha], str(worktree))
        diff_sha = hashlib.sha256(diff.encode("utf-8")).hexdigest()
        if changed != [edit.path] or not FULL_SHA.fullmatch(commit_sha):
            return _receipt(
                outcome="unconfirmed",
                reason="commit_did_not_match_the_edit",
                fingerprint=fingerprint,
                issue_number=number,
                validation_commands=commands,
                edit=edit.to_record(),
                before=before,
                after=after,
            )
        git_call(["push", "-u", "origin", f"{branch}:{branch}"], str(worktree))
        pr_body = pull_request_body(
            edit,
            candidate,
            issue_number=number,
            diff=diff,
            before=before,
            after=after,
            base_sha=base_sha,
            commit_sha=commit_sha,
        )
        url = str(
            call(
                [
                    "pr",
                    "create",
                    "--repo",
                    repository,
                    "--base",
                    integration_branch,
                    "--head",
                    branch,
                    "--draft",
                    "--title",
                    f"fix(deps): declare {edit.line} in {edit.path}",
                    "--body",
                    pr_body,
                ],
                None,
            )
            or ""
        ).strip()
        found = PR_URL.search(url)
        if not found:
            return _receipt(
                outcome="unconfirmed",
                reason="pull_request_creation_returned_no_url",
                fingerprint=fingerprint,
                issue_number=number,
                validation_commands=commands,
                edit=edit.to_record(),
                before=before,
                after=after,
                branch=branch,
                commit_sha=commit_sha,
            )
        return _receipt(
            outcome="pr_opened",
            reason=why,
            disposition="blocked",
            fingerprint=fingerprint,
            issue_number=number,
            validation_commands=commands,
            validation_passed=True,
            changed_file_count=len(changed),
            changed_files=changed,
            pr_number=int(found.group("number")),
            pr_url=url,
            branch=branch,
            commit_sha=commit_sha,
            diff_sha256=diff_sha,
            edit=edit.to_record(),
            before=before,
            after=after,
        )
    finally:
        with contextlib.suppress(Exception):  # cleanup must not mask the receipt
            git_call(["worktree", "remove", "--force", str(worktree)], str(root))
        with contextlib.suppress(Exception):
            git_call(["branch", "-D", branch], str(root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-json", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--integration-branch", default=DEFAULT_INTEGRATION_BRANCH)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--github-output")
    args = parser.parse_args(argv)
    try:
        issue = json.loads(args.issue_json)
        if not isinstance(issue, dict):
            raise TypeError("issue-json must be an object")
        receipt = run_lane(
            issue,
            repository=args.repository,
            root=Path(args.root).resolve(),
            base_sha=args.base_sha,
            integration_branch=args.integration_branch,
            timeout=args.timeout,
        )
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        OSError,
        materialize.IncompleteHistory,
    ) as exc:
        json.dump(
            {
                "schema": RECEIPT_SCHEMA,
                "outcome": "unconfirmed",
                "disposition": "blocked",
                "error_type": type(exc).__name__,
                "changed_file_count": 0,
            },
            sys.stdout,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 2
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"outcome={receipt['outcome']}\n")
            handle.write(f"disposition={receipt['disposition']}\n")
            handle.write(f"pr_number={receipt.get('pr_number') or ''}\n")
            handle.write(f"changed_file_count={receipt['changed_file_count']}\n")
    json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
