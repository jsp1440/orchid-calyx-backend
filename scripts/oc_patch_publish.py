"""Verify a model-produced patch and publish it from trusted code only.

The completion lane runs the model in a job that holds no write credential.
That job hands over a patch, a manifest and the executor's execution record as
an artifact. Everything in that artifact was produced next to model-written
code and is untrusted data. This module runs in the privileged publish job,
from a fresh checkout of the trusted revision, and never executes, imports or
checks out anything the model wrote:

* ``verify_patch`` parses the patch text itself and admits only plain
  modifications or additions of regular, non-executable text files
  (mode 100644) at exact paths inside the admitted scope. Renames, copies,
  deletions, mode changes, symlinks, gitlinks, binary hunks, quoted or
  traversing paths, and protected paths are refused.
* ``publish`` applies the patch in a detached worktree outside the workspace
  (git hooks disabled), re-derives the changed set from git's own view and
  requires it to equal the verified set, commits, pushes a branch name it
  chooses itself, and opens the draft pull request.

Trusted scripts in later steps keep running from the pristine workspace; the
worktree holding model content is never on any import path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.oc_hosted_completion import PROTECTED, PROTECTED_SEGMENTS
from scripts.swarm_anthropic_direct import (
    ARTIFACT_MARKER,
    PROTECTED_BASENAMES,
    PROTECTED_FILES,
    PROTECTED_PREFIXES,
)

MAX_PATCH_BYTES = 1_000_000
MAX_FILES = 12
MANIFEST_SCHEMA = "oc.direct-patch.v1"
SAFE_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
HEADER = re.compile(r"diff --git a/(?P<a>\S+) b/(?P<b>\S+)")
INDEX = re.compile(
    r"index (?P<old>[0-9a-f]{7,64})\.\.(?P<new>[0-9a-f]{7,64})(?: (?P<mode>[0-7]{6}))?"
)
NULL_OID = re.compile(r"0+")
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
BOT_NAME = "orchid-continuum-orchestrator[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


_PROTECTED_BASENAMES_FOLDED = frozenset(name.casefold() for name in PROTECTED_BASENAMES)


class PatchRefused(ValueError):
    """The artifact is not something trusted code may publish."""


def _refuse(condition: bool, reason: str) -> None:
    if not condition:
        raise PatchRefused(reason)


def path_admissible(path: str) -> bool:
    """A plain repository-relative path no grant or executor may write."""
    if not SAFE_PATH.fullmatch(path) or str(PurePosixPath(path)) != path:
        return False
    # Every name comparison is case-insensitive: ``app/x.PTH`` or ``app/.ENV``
    # must not slip past a check spelled in lower case.
    folded = [part.casefold() for part in PurePosixPath(path).parts]
    if any(part in {".", ".."} or part.startswith(".git") for part in folded):
        return False
    if any(part in PROTECTED_SEGMENTS or part.endswith(".pth") for part in folded):
        return False
    if path.startswith(PROTECTED) or path in PROTECTED_FILES:
        return False
    if folded[-1] in _PROTECTED_BASENAMES_FOLDED:
        return False
    return not any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in PROTECTED_PREFIXES
    )


def verify_patch(text: str, allowed: set[str]) -> list[str]:
    """Return the changed paths, or refuse anything but plain text edits."""
    _refuse(
        isinstance(text, str) and 0 < len(text.encode("utf-8")) <= MAX_PATCH_BYTES,
        "patch_size",
    )
    _refuse("\x00" not in text and "\r" not in text, "patch_control_bytes")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    files: list[str] = []
    index = 0
    while index < len(lines):
        header = HEADER.fullmatch(lines[index])
        _refuse(header is not None, "patch_unparseable")
        path = header["a"]
        _refuse(header["b"] == path, "patch_rename_or_copy")
        _refuse(path_admissible(path), "patch_protected_or_unsafe_path")
        _refuse(path in allowed, "patch_outside_scope")
        _refuse(path not in files, "patch_duplicate_path")
        files.append(path)
        index += 1
        new_file = False
        if index < len(lines) and lines[index].startswith("new file mode "):
            _refuse(lines[index] == "new file mode 100644", "patch_mode")
            new_file = True
            index += 1
        _refuse(index < len(lines), "patch_truncated")
        meta = INDEX.fullmatch(lines[index])
        _refuse(meta is not None, "patch_extended_header")
        if new_file:
            _refuse(
                NULL_OID.fullmatch(meta["old"]) is not None and meta["mode"] is None,
                "patch_mode",
            )
        else:
            _refuse(meta["mode"] == "100644", "patch_mode")
        index += 1
        _refuse(index + 1 < len(lines), "patch_binary_or_empty")
        old_side = "/dev/null" if new_file else f"a/{path}"
        _refuse(lines[index] == f"--- {old_side}", "patch_binary_or_mismatch")
        _refuse(lines[index + 1] == f"+++ b/{path}", "patch_binary_or_mismatch")
        index += 2
        hunks = 0
        while index < len(lines) and not lines[index].startswith("diff --git "):
            line = lines[index]
            if line.startswith("@@ "):
                hunks += 1
            else:
                _refuse(
                    hunks > 0 and line[:1] in {" ", "+", "-", "\\"}, "patch_unparseable"
                )
            index += 1
        _refuse(hunks > 0, "patch_binary_or_empty")
    _refuse(0 < len(files) <= MAX_FILES, "patch_file_count")
    return files


COLLECTED = ("execution.json", "manifest.json", "patch.diff")
MAX_COLLECTED_BYTES = 4_000_000


MODEL_USER = "oc-model"

#: Runs as the model account, not root, so a symlink or hard link the model
#: planted cannot reach anything that account could not already read; and it
#: refuses anything but a regular file itself. ``O_NOFOLLOW`` fails on a final
#: symlink, ``O_NONBLOCK`` keeps a FIFO from hanging the open, and ``fstat`` on
#: the opened descriptor (not the path) decides what was actually opened.
READER = """
import os, stat, sys
path, limit = sys.argv[1], int(sys.argv[2])
flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY
fd = os.open(path, flags)
if not stat.S_ISREG(os.fstat(fd).st_mode):
    sys.exit("not a regular file")
chunks, size = [], 0
while size <= limit:
    chunk = os.read(fd, min(65536, limit + 1 - size))
    if not chunk:
        break
    chunks.append(chunk)
    size += len(chunk)
sys.stdout.buffer.write(b"".join(chunks))
"""


def _reader_command(path: Path) -> list[str]:
    """The in-account reader, isolated from site, environment and cwd imports."""
    return [sys.executable, "-I", "-S", "-c", READER, str(path)]


def _sudo_read(path: Path, user: str = MODEL_USER) -> bytes:
    """Read a regular file the model account owns, as that account, bounded."""
    _refuse(
        user != "root" and re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) is not None,
        "user_invalid",
    )
    result = subprocess.run(
        [
            "sudo",
            "-n",
            "-u",
            user,
            "--",
            *_reader_command(path),
            str(MAX_COLLECTED_BYTES),
        ],
        capture_output=True,
        check=True,
        timeout=60,
        cwd="/",
    )
    return result.stdout


def collect(
    stdout_log: Path, source: Path, destination: Path, read=_sudo_read
) -> list[str]:
    """Copy only the files whose bytes still match the executor's own digests.

    The executor prints the sha256 of every file it hands over on its stdout,
    which no model-driven process can write to. Anything else in the model's
    output directory, or a listed file changed after the executor wrote it, is
    left behind. Returns the names copied.
    """
    digests: dict[str, str] = {}
    for line in stdout_log.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(ARTIFACT_MARKER + " "):
            try:
                parsed = json.loads(line[len(ARTIFACT_MARKER) + 1 :])
            except ValueError:
                continue
            if isinstance(parsed, dict):
                digests = parsed
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in COLLECTED:
        expected = digests.get(name)
        if not (isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected)):
            continue
        try:
            data = read(source / name)
        except (OSError, subprocess.SubprocessError, PatchRefused):
            continue
        if (
            len(data) > MAX_COLLECTED_BYTES
            or hashlib.sha256(data).hexdigest() != expected
        ):
            continue
        (destination / name).write_bytes(data)
        copied.append(name)
    return copied


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", *GIT_SAFE, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        timeout=180,
        env=env,
    )


def _git_view(worktree: Path, patch: Path) -> set[str]:
    """The paths git itself would touch, and nothing but plain edits."""
    numstat = _git(worktree, "apply", "--numstat", "-z", str(patch)).stdout
    paths = set()
    for record in filter(None, numstat.split("\0")):
        added, deleted, name = record.split("\t", 2)
        _refuse(added.isdigit() and deleted.isdigit(), "patch_binary")
        paths.add(name)
    summary = _git(worktree, "apply", "--summary", str(patch)).stdout
    for line in summary.splitlines():
        stripped = line.strip()
        _refuse(stripped.startswith("create mode 100644 "), "patch_mode_or_rename")
    return paths


def _staged(worktree: Path) -> dict[str, tuple[str, str]]:
    raw = _git(worktree, "diff", "--cached", "--raw", "--no-renames", "-z").stdout
    fields = raw.split("\0")
    staged = {}
    for meta, name in zip(fields[0::2], fields[1::2], strict=False):
        if not meta:
            continue
        parts = meta.lstrip(":").split()
        staged[name] = (parts[1], parts[4])
    return staged


def read_manifest(directory: Path, issue_number: int) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    _refuse(isinstance(manifest, dict), "manifest_invalid")
    _refuse(
        manifest.get("schema") == MANIFEST_SCHEMA
        and manifest.get("issue") == issue_number
        and isinstance(manifest.get("partial"), bool)
        and isinstance(manifest.get("base_sha"), str)
        and re.fullmatch(r"[0-9a-f]{40}", manifest["base_sha"]) is not None,
        "manifest_invalid",
    )
    return manifest


def publish(
    *,
    workspace: Path,
    artifact: Path,
    worktree: Path,
    repository: str,
    issue_number: int,
    run_id: str,
    title: str,
    base: str,
    allowed: set[str],
    dry_run: bool = False,
) -> dict:
    """Verify, apply in a side worktree, commit, push and open the draft PR."""
    for name in ("manifest.json", "patch.diff"):
        candidate = artifact / name
        _refuse(candidate.is_file() and not candidate.is_symlink(), "artifact_missing")
    manifest = read_manifest(artifact, issue_number)
    patch_path = artifact / "patch.diff"
    files = verify_patch(patch_path.read_text(encoding="utf-8"), allowed)
    base_sha = manifest["base_sha"]
    _git(workspace, "fetch", "--no-tags", "origin", base)
    _refuse(
        _git(
            workspace,
            "merge-base",
            "--is-ancestor",
            base_sha,
            "FETCH_HEAD",
            check=False,
        ).returncode
        == 0,
        "patch_base_not_on_integration",
    )
    _git(workspace, "worktree", "add", "--detach", str(worktree), base_sha)
    _refuse(_git_view(worktree, patch_path) == set(files), "patch_git_view_mismatch")
    _git(worktree, "apply", "--index", "--whitespace=error-all", str(patch_path))
    staged = _staged(worktree)
    _refuse(set(staged) == set(files), "patch_git_view_mismatch")
    _refuse(
        all(
            mode == "100644" and status in {"A", "M"}
            for mode, status in staged.values()
        ),
        "patch_mode",
    )
    branch = f"claude-direct/issue-{issue_number}-{run_id}"
    partial = manifest["partial"]
    message = (
        f"partial(oc): salvage partial changes for #{issue_number}"
        if partial
        else f"feat(oc): implement issue #{issue_number} via direct Claude"
    )
    _git(
        worktree,
        "-c",
        f"user.name={BOT_NAME}",
        "-c",
        f"user.email={BOT_EMAIL}",
        "commit",
        "--no-verify",
        "-m",
        message,
    )
    result = {"branch": branch, "files": files, "partial": partial, "pr_url": ""}
    if dry_run:
        return result
    _git(worktree, "push", "origin", f"HEAD:refs/heads/{branch}")
    if partial:
        result["partial_branch"] = branch
        return result
    body = (
        f"OC-AUTO-ISSUE: #{issue_number}\n"
        "OC-AUTO-REQUEUE: false\n"
        "OC-AUTO-BLOCKED: false\n\n"
        "Implemented by the governed direct Anthropic executor after Swarm governor "
        "authorization. The model ran in a job without write credentials; this pull "
        "request was opened by trusted code after the patch was verified against the "
        "admitted path scope.\n"
        "No merge, deployment, production mutation, credential change, scientific "
        "publication, or taxonomy activation is performed by this executor."
    )
    created = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--repo",
            repository,
            "--base",
            base,
            "--head",
            branch,
            "--title",
            f"OC-AUTO #{issue_number}: {title}"[:240],
            "--body",
            body,
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    result["pr_url"] = created.stdout.strip()
    return result


def main() -> int:
    if sys.argv[1:2] == ["collect"]:
        collector = argparse.ArgumentParser(description="collect model output")
        collector.add_argument("command")
        collector.add_argument("--stdout-log", required=True)
        collector.add_argument("--source", required=True)
        collector.add_argument("--destination", required=True)
        collector.add_argument("--model-user", default=MODEL_USER)
        options = collector.parse_args()
        copied = collect(
            Path(options.stdout_log),
            Path(options.source),
            Path(options.destination),
            read=lambda path: _sudo_read(path, options.model_user),
        )
        print("[OC-PATCH-COLLECT] " + json.dumps({"copied": copied}))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--base", default="oc-autonomous-integration")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--allowed-paths-json", required=True)
    args = parser.parse_args()
    _refuse(re.fullmatch(r"[0-9]+", args.run_id) is not None, "run_id_invalid")
    allowed = json.loads(args.allowed_paths_json)
    _refuse(
        isinstance(allowed, list) and all(isinstance(p, str) for p in allowed),
        "scope_invalid",
    )
    outputs = {"published": "false", "pr_url": "", "partial_branch": "", "reason": ""}
    try:
        result = publish(
            workspace=Path.cwd(),
            artifact=Path(args.artifact_dir),
            worktree=Path(args.worktree),
            repository=args.repository,
            issue_number=args.issue_number,
            run_id=args.run_id,
            title=args.title,
            base=args.base,
            allowed=set(allowed),
        )
        outputs.update(
            published="true",
            pr_url=result["pr_url"],
            partial_branch=result.get("partial_branch", ""),
        )
    except (PatchRefused, OSError, ValueError, subprocess.SubprocessError) as exc:
        outputs["reason"] = (
            re.sub(r"[^a-z0-9_]", "_", str(exc).lower())[:80] or "publish_failed"
        )
    print("[OC-PATCH-PUBLISH] " + json.dumps(outputs, sort_keys=True))
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in outputs.items())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
