"""The trusted publisher admits only plain text edits inside the admitted scope.

Patches here are produced by real ``git diff`` in a scratch repository, the
same command the executor runs, so the verifier is tested against the format it
will actually receive rather than a hand-written approximation of it.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pytest

from scripts import oc_patch_publish as publisher
from scripts import swarm_anthropic_direct as direct

ALLOWED = {"app/example.py", "tests/test_example.py", "app/new_module.py"}
DIFF = [
    "diff",
    "--cached",
    "--binary",
    "--full-index",
    "--no-renames",
    "--no-ext-diff",
    "--no-textconv",
]


def _git(cwd, *args):
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(cwd),
    }
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "oc-autonomous-integration")
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app/example.py").write_text("VALUE = 1\n")
    (root / "tests/test_example.py").write_text("def test_x():\n    assert True\n")
    (root / "app/linked.py").write_text("X = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _patch(root):
    _git(root, "add", "-A")
    return _git(root, *DIFF, "HEAD")


def test_a_plain_edit_and_a_new_file_are_admitted(repo):
    (repo / "app/example.py").write_text("VALUE = 2\n")
    (repo / "app/new_module.py").write_text("NEW = True\n")
    assert sorted(publisher.verify_patch(_patch(repo), ALLOWED)) == [
        "app/example.py",
        "app/new_module.py",
    ]


def _refused(text, allowed=ALLOWED):
    with pytest.raises(publisher.PatchRefused) as exc:
        publisher.verify_patch(text, allowed)
    return str(exc.value)


def test_a_path_outside_the_admitted_scope_is_refused(repo):
    (repo / "app/linked.py").write_text("X = 2\n")
    assert _refused(_patch(repo)) == "patch_outside_scope"


@pytest.mark.parametrize(
    "path",
    [
        "conftest.py",
        "tests/conftest.py",
        "app/sitecustomize.py",
        "pytest.ini",
        "app/evil.pth",
        ".gitattributes",
        "scripts/oc_hosted_completion.py",
        "scripts/swarm_anthropic_direct.py",
        "scripts/oc_patch_publish_helper.py",
    ],
)
def test_a_protected_path_is_refused_even_when_in_scope(repo, path):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n")
    detail = _refused(_patch(repo), ALLOWED | {path})
    assert detail in {"patch_protected_or_unsafe_path"}, detail


def test_a_workflow_path_is_refused(repo):
    target = repo / ".github/workflows/x.yml"
    target.parent.mkdir(parents=True)
    target.write_text("on: push\n")
    assert _refused(_patch(repo), ALLOWED | {".github/workflows/x.yml"}) == (
        "patch_protected_or_unsafe_path"
    )


def test_a_symlink_is_refused(repo):
    os.symlink("/etc/passwd", repo / "app/new_module.py")
    assert _refused(_patch(repo)) == "patch_mode"


def test_replacing_a_file_with_a_symlink_is_refused(repo):
    (repo / "app/example.py").unlink()
    os.symlink("../tests/test_example.py", repo / "app/example.py")
    assert _refused(_patch(repo)) in {"patch_mode", "patch_extended_header"}


def test_a_mode_change_is_refused(repo):
    (repo / "app/example.py").chmod(0o755)
    assert _refused(_patch(repo)) == "patch_extended_header"


def test_an_executable_new_file_is_refused(repo):
    (repo / "app/new_module.py").write_text("#!/bin/sh\n")
    (repo / "app/new_module.py").chmod(0o755)
    assert _refused(_patch(repo)) == "patch_mode"


def test_a_binary_file_is_refused(repo):
    (repo / "app/new_module.py").write_bytes(b"\x00\x01\x02binary")
    assert _refused(_patch(repo)) in {
        "patch_control_bytes",
        "patch_binary_or_empty",
        "patch_binary_or_mismatch",
    }


def test_a_deletion_is_refused(repo):
    (repo / "app/example.py").unlink()
    assert _refused(_patch(repo)) == "patch_extended_header"


def test_a_rename_into_a_protected_path_is_refused(repo):
    (repo / "scripts").mkdir()
    _git(repo, "mv", "app/example.py", "scripts/oc_hosted_completion.py")
    _git(repo, "add", "-A")
    renamed = _git(repo, "diff", "--cached", "--full-index", "-M", "HEAD")
    assert "rename from" in renamed
    assert _refused(renamed, ALLOWED | {"scripts/oc_hosted_completion.py"}) in {
        "patch_rename_or_copy",
        "patch_protected_or_unsafe_path",
        "patch_outside_scope",
    }


def test_a_rename_header_is_refused_even_between_allowed_paths(repo):
    _git(repo, "mv", "app/example.py", "app/new_module.py")
    _git(repo, "add", "-A")
    renamed = _git(repo, "diff", "--cached", "--full-index", "-M", "HEAD")
    assert _refused(renamed) == "patch_rename_or_copy"


@pytest.mark.parametrize(
    "header",
    [
        "diff --git a/../etc/passwd b/../etc/passwd",
        "diff --git a//etc/passwd b//etc/passwd",
        'diff --git "a/app/x y.py" "b/app/x y.py"',
        "diff --git a/app/./example.py b/app/./example.py",
        "diff --git a/.git/config b/.git/config",
    ],
)
def test_traversing_absolute_quoted_or_git_paths_are_refused(header):
    text = (
        header
        + "\nindex "
        + "1" * 40
        + ".."
        + "2" * 40
        + " 100644\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    )
    assert _refused(text, ALLOWED | {"../etc/passwd", ".git/config"}) in {
        "patch_unparseable",
        "patch_protected_or_unsafe_path",
    }


def test_a_gitlink_is_refused():
    text = (
        "diff --git a/app/example.py b/app/example.py\n"
        "index " + "1" * 40 + ".." + "2" * 40 + " 160000\n"
        "--- a/app/example.py\n+++ b/app/example.py\n@@ -1 +1 @@\n-Subproject\n+Subproject\n"
    )
    assert _refused(text) == "patch_mode"


def test_smuggled_content_after_a_hunk_is_refused(repo):
    (repo / "app/example.py").write_text("VALUE = 2\n")
    text = _patch(repo) + "rename to scripts/oc_hosted_completion.py\n"
    assert _refused(text) == "patch_unparseable"


def test_the_same_path_twice_is_refused(repo):
    (repo / "app/example.py").write_text("VALUE = 2\n")
    text = _patch(repo)
    assert _refused(text + text) == "patch_duplicate_path"


def test_an_empty_or_oversized_patch_is_refused():
    assert _refused("") == "patch_size"
    assert _refused("x" * (publisher.MAX_PATCH_BYTES + 1)) == "patch_size"


def test_the_worker_and_grant_protections_are_both_enforced():
    for path in (
        "runtime/swarm/x.py",
        "scripts/oc_paid_issue_admission.py",
        "app/.env",
    ):
        assert publisher.path_admissible(path) is False
    assert publisher.path_admissible("app/example.py") is True


# -- end to end: the worker's emitted patch through the trusted publisher -----


@pytest.fixture
def origin(tmp_path, repo):
    bare = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    workspace = tmp_path / "workspace"
    _git(tmp_path, "clone", "-q", str(bare), str(workspace))
    return bare, workspace


def _emit(monkeypatch, tmp_path, repo, out):
    """Run the executor's own patch emission against a model-edited clone."""
    model_tree = tmp_path / "model-tree"
    _git(tmp_path, "clone", "-q", str(repo), str(model_tree))
    monkeypatch.setattr(direct, "REPO_ROOT", model_tree)
    direct.WRITTEN.clear()
    direct.RETAINED.clear()
    direct.ARTIFACT_DIGESTS.clear()
    direct.BASE_SHA.clear()
    direct.BASE_SHA.append(_git(model_tree, "rev-parse", "HEAD").strip())
    (model_tree / "app/example.py").write_text("VALUE = 2\n")
    (model_tree / "tests/test_example.py").write_text(
        "def test_x():\n    assert 2 == 2\n"
    )
    direct.WRITTEN.update({"app/example.py", "tests/test_example.py"})
    monkeypatch.setattr(direct, "_autofix_written", lambda: None)
    return direct._emit_patch(out, "1968", partial=False)


def test_an_emitted_patch_publishes_in_a_side_worktree(
    monkeypatch, tmp_path, repo, origin
):
    _, workspace = origin
    out = tmp_path / "out"
    assert _emit(monkeypatch, tmp_path, repo, out)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema"] == publisher.MANIFEST_SCHEMA
    assert set(direct.ARTIFACT_DIGESTS) == {"patch.diff", "manifest.json"}
    before = {p: p.read_bytes() for p in workspace.rglob("*.py")}
    worktree = tmp_path / "publish-worktree"
    result = publisher.publish(
        workspace=workspace,
        artifact=out,
        worktree=worktree,
        repository="jsp1440/orchid-calyx-backend",
        issue_number=1968,
        run_id="38990149027",
        title="t",
        base="oc-autonomous-integration",
        allowed=ALLOWED,
        dry_run=True,
    )
    assert result["branch"] == "claude-direct/issue-1968-38990149027"
    assert sorted(result["files"]) == ["app/example.py", "tests/test_example.py"]
    assert (worktree / "app/example.py").read_text() == "VALUE = 2\n"
    # The trusted workspace, where later steps run code, never received it.
    assert {p: p.read_bytes() for p in workspace.rglob("*.py")} == before
    log = _git(worktree, "log", "-1", "--format=%an %s")
    assert log.startswith(publisher.BOT_NAME)


def test_a_patch_based_on_a_commit_outside_integration_is_refused(
    monkeypatch, tmp_path, repo, origin
):
    _, workspace = origin
    out = tmp_path / "out"
    _emit(monkeypatch, tmp_path, repo, out)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["base_sha"] = "f" * 40
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises((publisher.PatchRefused, subprocess.CalledProcessError)):
        publisher.publish(
            workspace=workspace,
            artifact=out,
            worktree=tmp_path / "wt",
            repository="r/r",
            issue_number=1968,
            run_id="1",
            title="t",
            base="oc-autonomous-integration",
            allowed=ALLOWED,
            dry_run=True,
        )


def test_a_manifest_for_another_issue_is_refused(monkeypatch, tmp_path, repo, origin):
    _, workspace = origin
    out = tmp_path / "out"
    _emit(monkeypatch, tmp_path, repo, out)
    with pytest.raises(publisher.PatchRefused, match="manifest_invalid"):
        publisher.publish(
            workspace=workspace,
            artifact=out,
            worktree=tmp_path / "wt",
            repository="r/r",
            issue_number=1969,
            run_id="1",
            title="t",
            base="oc-autonomous-integration",
            allowed=ALLOWED,
            dry_run=True,
        )


def test_a_symlinked_artifact_file_is_refused(monkeypatch, tmp_path, repo, origin):
    _, workspace = origin
    out = tmp_path / "out"
    _emit(monkeypatch, tmp_path, repo, out)
    real = tmp_path / "elsewhere.diff"
    (out / "patch.diff").rename(real)
    os.symlink(real, out / "patch.diff")
    with pytest.raises(publisher.PatchRefused, match="artifact_missing"):
        publisher.publish(
            workspace=workspace,
            artifact=out,
            worktree=tmp_path / "wt",
            repository="r/r",
            issue_number=1968,
            run_id="1",
            title="t",
            base="oc-autonomous-integration",
            allowed=ALLOWED,
            dry_run=True,
        )


# -- collection: only bytes the executor itself wrote leave the model job ----


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_collect_copies_only_files_matching_the_executor_digests(tmp_path):
    source = tmp_path / "out"
    source.mkdir()
    files = {
        "execution.json": b'{"type": "result"}',
        "patch.diff": b"diff --git a/x b/x\n",
        "manifest.json": b"{}",
    }
    for name, data in files.items():
        (source / name).write_bytes(data)
    digests = {name: _digest(data) for name, data in files.items()}
    # A later model process rewrote the patch after the executor hashed it.
    (source / "patch.diff").write_bytes(b"diff --git a/evil b/evil\n")
    (source / "extra.sh").write_bytes(b"#!/bin/sh\n")
    log = tmp_path / "stdout.log"
    log.write_text(
        "noise\n" + direct.ARTIFACT_MARKER + " " + json.dumps(digests) + "\n"
    )
    destination = tmp_path / "dest"
    copied = publisher.collect(log, source, destination, read=lambda p: p.read_bytes())
    assert sorted(copied) == ["execution.json", "manifest.json"]
    assert sorted(p.name for p in destination.iterdir()) == copied


def test_collect_without_a_digest_line_copies_nothing(tmp_path):
    source = tmp_path / "out"
    source.mkdir()
    (source / "execution.json").write_bytes(b"{}")
    log = tmp_path / "stdout.log"
    log.write_text("[OC-DIRECT-ARTIFACT] not json\n")
    assert (
        publisher.collect(log, source, tmp_path / "d", read=lambda p: p.read_bytes())
        == []
    )


def test_the_executor_reports_digests_of_exactly_the_bytes_it_wrote(tmp_path, capsys):
    direct.ARTIFACT_DIGESTS.clear()
    path = tmp_path / "execution.json"
    direct._write_result(path, {"type": "result", "subtype": "success"})
    line = [
        x
        for x in capsys.readouterr().out.splitlines()
        if x.startswith(direct.ARTIFACT_MARKER)
    ][-1]
    digests = json.loads(line[len(direct.ARTIFACT_MARKER) + 1 :])
    assert digests["execution.json"] == _digest(path.read_bytes())
