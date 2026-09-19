"""Exit-code coverage for the merge verifier's command line.

The pure invariant in `app.calyx_orchestrator.merge_integrity` was well covered
and the command line was not, so both ways of obtaining a false PASS lived in
the untested half: a mistyped `--path`, which made absence-versus-absence read
as agreement, and a ref beginning with `-`, which bare `git rev-parse` echoes
back verbatim with status 0 so that both sides resolved to the same nonsense.

The contract under test is the exit code, because that is what a lane consumes:
0 landed, 1 stop the lane, 2 the evidence was never gathered.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "oc_verify_merge_landed.py"

EDITED = "kept.txt"
REMOVED = "removed.txt"
UNTOUCHED = "untouched.txt"
SYMLINKABLE = "pointer.txt"
COLON_PREFIXED = ":odd.txt"
LATER = "added-then-removed.txt"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def _commit(repo: Path, message: str, stage: bool = True) -> str:
    # `stage=False` keeps an index prepared with `update-index`: `git add -A`
    # would re-read the worktree and undo a mode set only in the index.
    if stage:
        _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def history(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """A real repository with a verified head, a divergent head and a deletion."""
    repo = tmp_path_factory.mktemp("merge-landed")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "checker@example.invalid")
    _git(repo, "config", "user.name", "checker")

    (repo / EDITED).write_text("verified content\n")
    (repo / REMOVED).write_text("to be removed\n")
    (repo / UNTOUCHED).write_text("unrelated\n")
    # Content that is also a valid path, so the symlink below keeps the blob id.
    (repo / SYMLINKABLE).write_text(UNTOUCHED)
    # A legal filename that git would otherwise read as pathspec magic.
    (repo / COLON_PREFIXED).write_text("colon\n")
    base = _commit(repo, "the base both sides branch from")

    (repo / LATER).write_text("added by the change, removed by it too\n")
    verified = _commit(repo, "verified result")

    (repo / EDITED).write_text("something else entirely\n")
    diverged = _commit(repo, "what the squash actually produced")

    _git(repo, "checkout", "-q", "--force", verified)
    (repo / REMOVED).unlink()
    (repo / LATER).unlink()
    deletion = _commit(repo, "remove a file")

    _git(repo, "checkout", "-q", "--force", verified)
    _git(repo, "update-index", "--chmod=+x", EDITED)
    chmodded = _commit(repo, "executable bit only, not one byte changed", stage=False)

    _git(repo, "checkout", "-q", "--force", verified)
    (repo / SYMLINKABLE).unlink()
    (repo / SYMLINKABLE).symlink_to(UNTOUCHED)
    symlinked = _commit(repo, "regular file becomes a symlink, same blob id")

    # What a good merge actually looks like: a different commit, on a branch
    # carrying somebody else's work, holding the verified content and applying
    # the deletion. Comparing a ref against itself is a tautology, not a land.
    _git(repo, "checkout", "-q", "--force", verified)
    (repo / "someone-elses-work.txt").write_text("landed alongside\n")
    (repo / REMOVED).unlink()
    (repo / LATER).unlink()
    integrated = _commit(repo, "integration branch after the merge")

    # The same, minus the deletions: the merge dropped them.
    _git(repo, "checkout", "-q", "--force", verified)
    (repo / "someone-elses-work.txt").write_text("landed alongside\n")
    kept_the_removed_file = _commit(repo, "integration branch that kept the removed files")

    # A sibling branched from the base, so it never saw LATER at all. Its merge
    # base with `deletion` is `base`, where LATER does not exist.
    _git(repo, "checkout", "-q", "--force", base)
    (repo / "sibling.txt").write_text("unrelated lane\n")
    from_the_base = _commit(repo, "a branch that predates the change")

    return {"repo": repo, "base": base, "verified": verified, "diverged": diverged,
            "deletion": deletion, "chmodded": chmodded, "symlinked": symlinked,
            "integrated": integrated, "kept_the_removed_file": kept_the_removed_file,
            "from_the_base": from_the_base}


def run(history: dict[str, object], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(history["repo"]),
        capture_output=True,
        text=True,
        check=False,
    )


class TestTheFalsePasses:
    """Both of these returned 0 and `INTEGRATION_HOLDS_THE_VERIFIED_RESULT`."""

    def test_a_mistyped_path_never_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--path", "does/not/exist.txt",
        )
        assert done.returncode == 2
        assert "do not exist at the verified head" in done.stdout
        assert "landed" not in done.stdout

    def test_a_mistyped_path_never_passes_even_alongside_a_real_one(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified"]),
            "--path", UNTOUCHED,
            "--path", "does/not/exist.txt",
        )
        assert done.returncode == 2

    # Passed with `=` so argparse hands the dash through to the resolver, which
    # is the form that used to reach `git rev-parse` and be echoed back as a
    # status-0 "revision" on both sides.
    @pytest.mark.parametrize("ref", ["-bogus", "--upload-pack=touch /tmp/pwned", "--exec-path=/tmp"])
    def test_a_ref_beginning_with_a_dash_never_passes(self, history, ref):
        done = run(
            history,
            f"--verified-head={ref}",
            f"--integration-ref={ref}",
            "--path", EDITED,
        )
        assert done.returncode == 2
        assert "does not resolve to a commit" in done.stdout
        assert not (Path(str(history["repo"])) / "pwned").exists()

    def test_an_unknown_ref_never_passes(self, history):
        done = run(
            history,
            "--verified-head", "0" * 40,
            "--integration-ref", str(history["verified"]),
            "--path", EDITED,
        )
        assert done.returncode == 2
        # Asserting the reason, not just the code: the mistyped-path guard also
        # exits 2 on this input, so a bare exit-code assertion stays green with
        # the ref guard deleted and pins nothing.
        assert "does not resolve to a commit" in done.stdout


class TestADeletionMustBeAnActualDeletion:
    """Absence is not evidence.

    `--path` was given a "must exist at the verified head" rule, and the same
    hole immediately reopened through `--deleted-path`, which required only
    absence -- something every typo satisfies. Both sides then read "not there"
    and the tool reported the verified result as landed.
    """

    def test_a_path_that_was_never_a_file_is_not_a_deletion(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["diverged"]),
            "--deleted-path", "never/was/a/file.txt",
        )
        assert done.returncode == 2
        assert "no deletion to verify" in done.stdout
        assert "landed" not in done.stdout

    @pytest.mark.parametrize(
        "near_miss", [f" {REMOVED}", f"{REMOVED} ", f"/{REMOVED}", "..", "/", f"{REMOVED}/"]
    )
    def test_a_near_miss_of_a_real_deletion_is_not_a_deletion(self, history, near_miss):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["deletion"]),
            "--deleted-path", near_miss,
        )
        assert done.returncode == 2

    def test_a_real_deletion_still_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]),
            "--deleted-path", REMOVED,
        )
        assert done.returncode == 0
        assert "landed" in done.stdout
        # A real land, not a self-comparison: the trees genuinely differ.
        assert "identical tree: False" in done.stdout

    def test_the_base_is_derived_from_the_two_refs_not_supplied_by_the_caller(self, history):
        # The hole this replaced: the base was a caller argument, so any commit
        # in the object database that happened to contain the path satisfied it,
        # including one with no relationship to the merge -- and a declared set
        # of only deletions then returned `landed` without reading a byte of the
        # integration ref. The base is now merge-base(verified, integration).
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]),
            "--deleted-path", REMOVED,
            "--deleted-at", str(history["verified"]),
        )
        assert done.returncode == 2
        assert "unrecognized arguments" in done.stderr

    def test_the_same_deletion_is_provable_or_not_depending_on_what_it_is_merged_into(self, history):
        # One declaration, one verified head, two integration refs. LATER was
        # added and removed by the change, so it exists at merge-base(deletion,
        # integrated) = `verified` and is provable there -- and does not exist at
        # merge-base(deletion, from_the_base) = `base`, so against that ref there
        # is no deletion to verify. A base chosen from history at large could
        # always find the first and never notice the second.
        provable = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]),
            "--deleted-path", LATER,
        )
        assert provable.returncode == 0, provable.stdout

        unprovable = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["from_the_base"]),
            "--deleted-path", LATER,
        )
        assert unprovable.returncode == 2
        assert "no deletion to verify" in unprovable.stdout

    def test_refs_with_no_common_ancestor_are_refused(self, history):
        tree = _git(history["repo"], "rev-parse", f'{history["verified"]}^{{tree}}')
        orphan = _git(history["repo"], "commit-tree", tree, "-m", "unrelated history")
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", orphan,
            "--deleted-path", REMOVED,
        )
        assert done.returncode == 2
        assert "share no common ancestor" in done.stdout

    def test_a_root_commit_needs_no_special_handling(self, history):
        # The old base was `<verified-head>^`, which a root commit does not have,
        # and the code carried a special case saying so. A merge base always
        # exists between two related refs, so the special case is gone.
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--deleted-path", "gone.txt",
        )
        assert done.returncode == 2
        assert "no deletion to verify" in done.stdout


class TestThePathspecIsLiteral:
    def test_a_filename_beginning_with_a_colon_is_a_path_not_pathspec_magic(self, history):
        # Without `:(literal)` git reads `:odd.txt` as pathspec magic, matches
        # nothing, and the tool refuses a file that is plainly there.
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified"]),
            "--path", COLON_PREFIXED,
        )
        assert done.returncode == 0
        assert "landed" in done.stdout

    def test_a_wildcard_path_is_not_expanded_into_a_real_one(self, history):
        # Without `:(literal)`, `kept.tx*` matches exactly one file and the tool
        # would compare that file while reporting the pattern as the path --
        # a pass for a path that does not exist.
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--path", f"{EDITED[:-1]}*",
        )
        assert done.returncode == 2
        assert "do not exist at the verified head" in done.stdout


class TestHowTheTreeIsRead:
    """One of `_entry`'s flags is load-bearing; three are defensive.

    `--full-tree` is pinned below. `-z`, `--end-of-options` and the multi-record
    guard are not, and no test here claims otherwise: once `_resolve_ref` has
    validated the ref and `:(literal)` has fixed the pathspec, removing any of
    the three changes no outcome this parser can reach. They stay because they
    are correct, not because they are covered.
    """

    def test_a_path_resolves_the_same_from_a_subdirectory(self, history):
        # Without `--full-tree`, ls-tree is relative to the cwd, so the same
        # root-relative path would silently stop resolving in a nested checkout.
        nested = Path(str(history["repo"])) / "nested"
        nested.mkdir(exist_ok=True)
        done = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--verified-head", str(history["verified"]),
             "--integration-ref", str(history["diverged"]),
             "--path", EDITED],
            cwd=str(nested), capture_output=True, text=True, check=False,
        )
        assert done.returncode == 1
        assert f"DIVERGED {EDITED}" in done.stdout

    def test_a_path_containing_a_newline_still_resolves(self, history):
        # Not a `-z` test: git C-quotes such a path onto one line anyway, so
        # dropping `-z` reddens nothing. This pins that an odd filename is
        # verifiable at all, which the `\t` split could otherwise break.
        odd = "two\nlines.txt"
        (Path(str(history["repo"])) / odd).write_text("newline in the name\n")
        _git(history["repo"], "add", "-A")
        _git(history["repo"], "commit", "-q", "-m", "a path with a newline")
        head = _git(history["repo"], "rev-parse", "HEAD")
        done = run(history, "--verified-head", head, "--integration-ref", head, "--path", odd)
        assert done.returncode == 0
        assert "landed" in done.stdout


class TestModeAndType:
    """A blob id alone cannot see a file become a symlink or gain +x."""

    def test_the_executable_bit_changing_is_a_divergence(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["chmodded"]),
            "--path", EDITED,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout
        assert f"DIVERGED {EDITED}" in done.stdout

    def test_a_file_becoming_a_symlink_to_its_own_content_is_a_divergence(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["symlinked"]),
            "--path", SYMLINKABLE,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout

    def test_the_compared_identity_names_the_mode_and_type(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["chmodded"]),
            "--path", EDITED,
        )
        assert "100644 blob" in done.stdout
        assert "100755 blob" in done.stdout

    def test_no_paths_never_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified"]),
        )
        assert done.returncode == 2
        assert "nothing to verify" in done.stdout


class TestTheContract:
    def test_a_merge_that_dropped_the_verified_content_stops_the_lane(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--path", EDITED,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout
        assert f"DIVERGED {EDITED}" in done.stdout
        assert "STOP THIS MERGE LANE" in done.stdout

    def test_a_merge_that_kept_it_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified"]),
            "--path", EDITED,
            "--path", UNTOUCHED,
        )
        assert done.returncode == 0
        assert "landed" in done.stdout

    def test_an_untouched_path_is_not_enough_to_hide_a_dropped_one(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--path", UNTOUCHED,
            "--path", EDITED,
        )
        assert done.returncode == 1

    def test_a_merge_api_that_did_not_report_success_is_never_a_pass(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified"]),
            "--path", EDITED,
            "--no-merge-reported-success",
        )
        assert done.returncode == 1
        assert "merge_not_reported" in done.stdout


class TestDeletions:
    def test_a_deletion_that_landed_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]),
            "--deleted-path", REMOVED,
            "--path", EDITED,
        )
        assert done.returncode == 0

    def test_a_deletion_the_merge_did_not_apply_stops_the_lane(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["kept_the_removed_file"]),
            "--deleted-path", REMOVED,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout

    def test_declaring_a_live_file_deleted_is_refused(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified"]),
            "--deleted-path", EDITED,
        )
        assert done.returncode == 2
        assert "still exist at the verified head" in done.stdout

    def test_the_same_path_cannot_be_declared_twice(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["deletion"]),
            "--path", EDITED,
            "--deleted-path", EDITED,
        )
        assert done.returncode == 2
        # Asserting the reason, not just the code: the later present-versus-
        # deleted check refuses this too, so a bare exit-code assertion passes
        # with this guard deleted and pins nothing.
        assert "declared twice, or declared both present and deleted" in done.stdout


class TestAnUnresolvedLookup:
    """A lookup that fails for any reason other than absence is not agreement.

    Both sides returning "I could not find out" is the shape of a vacuous pass,
    so it has to be reachable from the command line to be worth having.
    """

    @staticmethod
    def _git_that_cannot_read_one_ref(bin_dir: Path, blind_to: str) -> None:
        bin_dir.mkdir(parents=True, exist_ok=True)
        shim = bin_dir / "git"
        shim.write_text(
            "#!/usr/bin/env python3\n"
            "import os, subprocess, sys\n"
            "argv = sys.argv[1:]\n"
            f"blind = {blind_to!r}\n"
            # `_entry` reads a tree with ls-tree; ref resolution still uses
            # rev-parse, so blinding only ls-tree leaves the refs resolvable and
            # the failure lands exactly where UNKNOWN is meant to be produced.
            "if argv[:1] == ['ls-tree'] and blind in argv:\n"
            "    sys.exit(128)\n"
            "path = [p for p in os.environ['PATH'].split(os.pathsep) if p != os.path.dirname(os.path.abspath(sys.argv[0]))]\n"
            "os.environ['PATH'] = os.pathsep.join(path)\n"
            "sys.exit(subprocess.run(['git', *argv], env=os.environ).returncode)\n"
        )
        shim.chmod(0o755)

    def test_an_unresolved_integration_lookup_is_never_a_pass(self, history, tmp_path):
        bin_dir = tmp_path / "bin"
        self._git_that_cannot_read_one_ref(bin_dir, str(history["verified"]))
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        done = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--verified-head", str(history["deletion"]),
                "--integration-ref", str(history["verified"]),
                "--path", EDITED,
            ],
            cwd=str(history["repo"]), capture_output=True, text=True, check=False, env=env,
        )
        assert done.returncode == 1
        assert "evidence_incomplete" in done.stdout
        assert f"UNRESOLVED {EDITED}" in done.stdout
