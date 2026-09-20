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
    """A base, a change, and integration refs that FORK from the base.

    Every integration ref used to descend from the verified head, which makes
    `merge-base(verified, integration)` the verified head itself -- so no
    declared path could differ from the base, and the fixture modelled a
    fast-forward rather than the squash this tool exists to check.
    """
    repo = tmp_path_factory.mktemp("merge-landed")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "checker@example.invalid")
    _git(repo, "config", "user.name", "checker")

    (repo / EDITED).write_text("before the change\n")
    (repo / REMOVED).write_text("to be removed\n")
    (repo / UNTOUCHED).write_text("unrelated\n")
    (repo / SYMLINKABLE).write_text(UNTOUCHED)
    (repo / COLON_PREFIXED).write_text("colon\n")
    base = _commit(repo, "the base both sides fork from")

    # THE CHANGE: edits one file, adds one, and (in `deletion`) removes two.
    (repo / EDITED).write_text("verified content\n")
    (repo / LATER).write_text("added by the change, removed by it too\n")
    verified = _commit(repo, "verified result")

    _git(repo, "checkout", "-q", "--force", "-b", "diverged-lane", base)
    (repo / EDITED).write_text("something else entirely\n")
    diverged = _commit(repo, "what the squash actually produced")

    _git(repo, "checkout", "-q", "--force", verified)
    (repo / REMOVED).unlink()
    (repo / LATER).unlink()
    deletion = _commit(repo, "the change, also removing two files")

    def _from_base(name: str, message: str, build) -> str:
        _git(repo, "checkout", "-q", "--force", "-B", name, base)
        (repo / EDITED).write_text("verified content\n")
        (repo / LATER).write_text("added by the change, removed by it too\n")
        build()
        return _commit(repo, message)

    chmodded = _from_base("chmod-lane", "the verified content, executable", lambda: None)
    _git(repo, "checkout", "-q", "--force", chmodded)
    _git(repo, "update-index", "--chmod=+x", EDITED)
    chmodded = _commit(repo, "executable bit only, not one byte changed", stage=False)

    def _symlink() -> None:
        (repo / SYMLINKABLE).unlink()
        (repo / SYMLINKABLE).symlink_to(UNTOUCHED)

    symlinked = _from_base("symlink-lane", "regular file becomes a symlink, same blob id", _symlink)

    def _others() -> None:
        (repo / "someone-elses-work.txt").write_text("landed alongside\n")

    verified_landed = _from_base("landed-lane", "integration branch holding the verified content", _others)

    def _integrated() -> None:
        _others()
        (repo / REMOVED).unlink()
        (repo / LATER).unlink()

    integrated = _from_base("integration-lane", "integration branch after the merge", _integrated)
    kept_the_removed_file = _from_base("kept-lane", "integration branch that kept the removed files", _others)

    _git(repo, "checkout", "-q", "--force", "-B", "predates", base)
    (repo / "sibling.txt").write_text("unrelated lane\n")
    from_the_base = _commit(repo, "a branch that predates the change")

    return {"repo": repo, "base": base, "verified": verified, "diverged": diverged,
            "deletion": deletion, "chmodded": chmodded, "symlinked": symlinked,
            "integrated": integrated, "kept_the_removed_file": kept_the_removed_file,
            "from_the_base": from_the_base, "verified_landed": verified_landed}


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
        # The verdict line, not the word: the refusal text itself now explains
        # that a deletion cannot evidence that a merge landed.
        assert "verdict" not in done.stdout

    def test_a_mistyped_path_never_passes_even_alongside_a_real_one(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified_landed"]),
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
            "--integration-ref", str(history["integrated"]),
            "--deleted-path", near_miss,
            "--path", EDITED,
        )
        assert done.returncode == 2
        # Named in the refusal, and paired with the test below, which proves the
        # genuine path passes this same configuration. This ran against a
        # self-comparison before, where the merge base was the verified head
        # itself, so EVERY deleted path was refused -- including the real one --
        # and the test could not tell a near miss from a blanket rejection.
        assert "REFUSED" in done.stdout
        assert near_miss.strip() in done.stdout

    def test_the_genuine_path_passes_the_same_gate_these_near_misses_fail(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]),
            "--deleted-path", REMOVED,
            "--path", EDITED,
        )
        assert done.returncode == 0

    def test_a_real_deletion_still_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]),
            "--deleted-path", REMOVED,
            "--path", EDITED,
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
            "--deleted-path", REMOVED,
            "--path", EDITED,
        )
        assert provable.returncode == 0, provable.stdout

        unprovable = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["from_the_base"]),
            "--deleted-path", LATER,
            "--path", EDITED,
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
            "--integration-ref", str(history["verified_landed"]),
            "--path", COLON_PREFIXED,
            "--path", EDITED,
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
    """What is pinned here, and what is not.

    SIX mutants survive this suite, each confirmed by running it with the guard
    removed. Successive versions of this docstring said three, then five, then
    eight, then six again -- every one of them reached by reading the code, and
    every one of them wrong. Two of the "eight" were not survivors but missing
    tests, and one of those was a live defect: the multi-record guard, which a
    docstring called unreachable on the false grounds that `:(literal)` makes a
    multi-match impossible.

      * `--end-of-options` on ls-tree
      * `--end-of-options` on rev-parse (`--verify` already rejects a dash ref,
        so it is belt-and-braces while `--verify --quiet` is kept)
      * `_entry`'s empty-field guard
      * `_resolve_ref`'s tree-resolution check (a validated commit has a tree)
      * `may_report_integrated`'s `and inspection.landed` conjunct (redundant)
      * `identical_tree`'s two `!= UNKNOWN` conjuncts, which are unreachable:
        `VerifiedResult` refuses an empty tree sha and identity needs both sides
        equal. `TestWhyTheIdenticalTreeGuardsCannotBeExercised` proves the
        premise instead of asserting coverage that cannot exist.

    They stay because they are correct, not because they are covered.

    Two things that were once on this list are now pinned, by tests written
    after a checker demonstrated that the reasons for leaving them off were
    false:

      * the multi-record guard -- removing it makes `--path src/lib/` compare
        the directory's FIRST child and report `landed` while the rest of the
        directory, including a reverted locality fix, goes unread.
        `TestAnAmbiguousPathspecComparesNothingItClaimsTo`.
      * `merge-base --all`. The claim that no order-independent test could exist
        for it was wrong in its own terms: the two readings need not differ in
        VERDICT to be distinguishable. A deletion absent at both bases is
        refused either way, with no tie-break anywhere, and only the refusal's
        list of bases differs.
        `TestTheMergeBaseAllFlagIsPinnedWithoutATieBreak` asserts that list.

    A note on method, because the harness has now produced two false results of
    its own. Once a `replace(..., 1)` mutated the wrong copy of a guard that
    appears twice, reporting a survivor that was never tested. Once a killed
    sweep left `--end-of-options` stripped from ls-tree in the working tree, and
    the next run's "80 passed" was measured against that mutant. Restore the
    file and re-assert the guard after the sweep, not only inside it.
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
        repo = Path(str(history["repo"]))
        # Both sides fork from the base, so the merge base is the base and the
        # odd path genuinely differs from it.
        _git(repo, "checkout", "-q", "--force", "-B", "newline-lane", str(history["base"]))
        (repo / odd).write_text("newline in the name\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "a path with a newline")
        head = _git(repo, "rev-parse", "HEAD")

        _git(repo, "checkout", "-q", "--force", "-B", "newline-landed", str(history["base"]))
        (repo / odd).write_text("newline in the name\n")
        (repo / "beside.txt").write_text("unrelated\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "a commit that holds it without being it")
        landed = _git(repo, "rev-parse", "HEAD")

        done = run(history, "--verified-head", head, "--integration-ref", landed, "--path", odd)
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
            "--path", EDITED,
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

    def test_comparing_a_ref_with_itself_is_refused(self, history):
        # A "merge" that is the verified head is a tautology: it passes with the
        # content comparison removed entirely. Three positive tests relied on
        # this shape and pinned nothing.
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified"]),
            "--path", EDITED,
        )
        assert done.returncode == 2
        assert "are the same commit" in done.stdout

    def test_no_paths_never_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified_landed"]),
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
            "--integration-ref", str(history["verified_landed"]),
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
            "--integration-ref", str(history["verified_landed"]),
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
            "--path", EDITED,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout

    def test_declaring_a_live_file_deleted_is_refused(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified_landed"]),
            "--deleted-path", EDITED,
        )
        assert done.returncode == 2
        assert "still exist at the verified head" in done.stdout

    def test_the_same_path_cannot_be_declared_twice(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]),
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
        # Blind only the integration ref, so the merge base still resolves and
        # the declared path is genuinely touched. The unresolved lookup is then
        # the one thing standing between this and a verdict.
        bin_dir = tmp_path / "bin"
        self._git_that_cannot_read_one_ref(bin_dir, str(history["diverged"]))
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        done = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--verified-head", str(history["verified"]),
                "--integration-ref", str(history["diverged"]),
                "--path", EDITED,
            ],
            cwd=str(history["repo"]), capture_output=True, text=True, check=False, env=env,
        )
        assert done.returncode == 1
        assert "evidence_incomplete" in done.stdout
        assert f"UNRESOLVED {EDITED}" in done.stdout


class TestADeletionCannotEvidenceAMerge:
    """The fifth instance of one failure class, and the premise behind all five.

    Rounds 1-4 each narrowed where a deletion's evidence could come from. None
    of them asked whether a deletion can evidence a merge at all. It cannot:
    absence is symmetric, so two lineages that both lack a file agree about it
    for reasons that have nothing to do with the merge under test.
    """

    @staticmethod
    def _forked(repo: Path) -> dict[str, str]:
        """Two lineages that both drop a file, where neither contains the other."""
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "leak.py").write_text("locality leak\n")
        (repo / "core.py").write_text("v1\n")
        base = _commit(repo, "base: leak present")

        _git(repo, "checkout", "-q", "-b", "pr")
        (repo / "leak.py").unlink()
        (repo / "core.py").write_text("v2, changed by the PR\n")
        verified = _commit(repo, "the PR removes the leak and edits core")

        _git(repo, "checkout", "-q", "--force", "-b", "integration", base)
        (repo / "leak.py").unlink()
        (repo / "core.py").write_text("REGRESSED\n")
        integration = _commit(repo, "someone else removed it, and regressed core")

        return {"repo": repo, "verified": verified, "integration": integration}

    def test_a_record_of_only_deletions_never_reports_landed(self, tmp_path):
        history = self._forked(tmp_path / "forked")
        # `git diff --name-status base..verified` on a pure-deletion change gives
        # exactly this set, so the operating memory's own prescribed workflow
        # produced it. It returned `landed`, exit 0, having read nothing.
        done = run(history, "--verified-head", str(history["verified"]),
                   "--integration-ref", str(history["integration"]), "--deleted-path", "leak.py")

        # Refused before anything is compared, and told plainly that this change
        # is not verifiable here -- rather than sent to find a path that passes.
        assert done.returncode == 2
        assert "cannot be verified by this tool" in done.stdout
        assert "Absence is symmetric" in done.stdout

    def test_the_same_refs_reveal_the_regression_once_a_kept_path_is_declared(self, tmp_path):
        history = self._forked(tmp_path / "forked2")
        done = run(history, "--verified-head", str(history["verified"]),
                   "--integration-ref", str(history["integration"]),
                   "--deleted-path", "leak.py", "--path", "core.py")

        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout
        assert "DIVERGED core.py" in done.stdout


class TestTheMergeBaseIsNotATieBreak:
    def test_a_criss_cross_history_refuses_rather_than_picking_one_base(self, tmp_path):
        """`git merge-base` without `--all` prints whichever base git picks.

        With two bases, one holding the path and one not, the verdict turned on
        that tie-break. A gate whose answer depends on it is not a gate.
        """
        repo = tmp_path / "criss"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "keep.txt").write_text("keep\n")
        root = _commit(repo, "root")

        _git(repo, "checkout", "-q", "-b", "a")
        (repo / "F.py").write_text("present\n")
        left = _commit(repo, "a: adds F")

        _git(repo, "checkout", "-q", "--force", "-b", "b", root)
        (repo / "other.txt").write_text("other\n")
        right = _commit(repo, "b: no F")

        _git(repo, "checkout", "-q", "--force", "-b", "x", left)
        _git(repo, "merge", "-q", "--no-edit", "-X", "ours", right)
        (repo / "F.py").unlink()
        verified = _commit(repo, "x: removes F")

        _git(repo, "checkout", "-q", "--force", "-b", "y", right)
        _git(repo, "merge", "-q", "--no-edit", "-X", "theirs", left)
        if (repo / "F.py").exists():
            (repo / "F.py").unlink()
        integration = _commit(repo, "y: also without F")

        bases = _git(repo, "merge-base", "--all", verified, integration).split()
        holds = [base for base in bases if _git(repo, "ls-tree", base, "--", "F.py")]
        if len(bases) < 2 or len(holds) == len(bases):
            pytest.skip("this git produced a single merge base; the tie-break is not exercised")

        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--deleted-path", "F.py", "--path", "keep.txt")

        assert done.returncode == 2
        assert "do not exist at every pre-change revision" in done.stdout

    def test_a_path_matching_any_merge_base_is_not_treated_as_touched(self, tmp_path):
        """`touched` must differ from EVERY base, not from one of them.

        The earlier version of this test made the path identical at both bases,
        so it was refused under `all` and under `any` alike and killed neither.
        The distinction needs a path that MATCHES one base and DIFFERS from the
        other -- which is order-independent, so nothing here depends on which
        base git names first.
        """
        repo = tmp_path / "criss-touched"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "P.txt").write_text("v0\n")
        root = _commit(repo, "root")

        # left carries v1; right keeps v0. Both become merge bases.
        _git(repo, "checkout", "-q", "-b", "left")
        (repo / "P.txt").write_text("v1\n")
        left = _commit(repo, "left sets v1")

        _git(repo, "checkout", "-q", "--force", "-b", "right", root)
        (repo / "other.txt").write_text("other\n")
        right = _commit(repo, "right leaves P alone")

        _git(repo, "checkout", "-q", "--force", "-b", "x", left)
        _git(repo, "merge", "-q", "--no-edit", right)
        verified = _git(repo, "rev-parse", "HEAD")

        _git(repo, "checkout", "-q", "--force", "-b", "y", right)
        _git(repo, "merge", "-q", "--no-edit", "-X", "theirs", left)
        integration = _git(repo, "rev-parse", "HEAD")

        bases = _git(repo, "merge-base", "--all", verified, integration).split()
        if len(bases) < 2:
            pytest.skip("this git produced a single merge base")
        values = {_git(repo, "ls-tree", base, "--", "P.txt") for base in bases}
        if len(values) < 2:
            pytest.skip("both bases hold the same P.txt; the distinction is not exercised")

        # P.txt matches `left` and differs from `right`, so `any` would call it
        # touched and `all` correctly does not.
        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration, "--path", "P.txt")

        assert done.returncode == 2
        assert "differs from it there" in done.stdout


class TestOnlyAPathTheChangeTouchedIsEvidence:
    """Instance six: identity compared with identity, where it predates the change.

    Rounds 1-5 closed five ways of reaching `landed` without comparing anything
    probative. This was the sixth, and the tool's own refusal message was the
    delivery vector: it told the operator to "declare at least one path the
    change kept", and any untouched path is identical on both sides.
    """

    def test_an_untouched_path_alone_cannot_evidence_a_merge(self, history):
        # `diverged` is the commit the fixture builds to be the #706 failure --
        # the squash that dropped the verified content. UNTOUCHED is identical
        # at the base, the verified head and there.
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--path", UNTOUCHED,
        )

        assert done.returncode == 2
        assert "differs from it there" in done.stdout
        assert "verdict" not in done.stdout

    def test_the_same_refs_are_caught_once_a_touched_path_is_declared(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--path", EDITED,
        )

        assert done.returncode == 1
        assert f"DIVERGED {EDITED}" in done.stdout

    def test_an_untouched_path_does_not_dilute_a_touched_one(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--path", UNTOUCHED,
            "--path", EDITED,
        )

        assert done.returncode == 1
        assert f"DIVERGED {EDITED}" in done.stdout

    def test_refs_with_no_common_ancestor_are_refused_without_a_deletion(self, history, tmp_path):
        # The ancestry gate ran only when `--deleted-path` was passed, so two
        # commits between which no merge can have happened returned `landed`.
        repo = tmp_path / "orphan"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "f.txt").write_text("same\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "main")
        main = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "--orphan", "other")
        (repo / "f.txt").write_text("same\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "unrelated history")
        orphan = _git(repo, "rev-parse", "HEAD")

        done = run({"repo": repo}, "--verified-head", orphan, "--integration-ref", main, "--path", "f.txt")

        assert done.returncode == 2
        assert "share no common ancestor" in done.stdout

    def test_the_refusal_does_not_tell_the_operator_to_declare_a_path_to_pass(self, history):
        # The old text said "Declare at least one path the change kept as well",
        # which for a pure-deletion change means hand-picking an untouched one --
        # the thing the operating memory calls manufacturing the failure.
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]),
            "--path", "does/not/exist.txt",
        )

        assert done.returncode == 2
        assert "Derive the set mechanically" in done.stdout
        assert "an untouched path is identical on both sides and proves nothing" in done.stdout
        assert "the change kept as well" not in done.stdout


class TestAnUnresolvedBaseLookupIsNotADifference:
    """Instance seven: `UNKNOWN != <entry>` is true, so an unresolved base
    lookup was read as evidence that the change touched the path.

    Every other gate in this tool refuses UNKNOWN. This one counted it as proof,
    and the docstring that listed the multi-record guard as unreachable is why
    it went unguarded: `:(literal)` suppresses glob magic, it does not make a
    pathspec match exactly one entry.
    """

    @staticmethod
    def _lab(repo: Path) -> dict[str, str]:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "src" / "lib" / "core").mkdir(parents=True)
        (repo / "src" / "lib" / "legacy").mkdir(parents=True)
        (repo / "src" / "lib" / "core" / "index.ts").write_text("export const core = 1;\n")
        (repo / "src" / "lib" / "legacy" / "index.ts").write_text("export const legacy = 1;\n")
        (repo / "src" / "locality.ts").write_text("const w3w = null; // no locality\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        _git(repo, "rm", "-qr", "src/lib/legacy")
        (repo / "src" / "locality.ts").write_text("const w3w = REDACTED; // the verified fix\n")
        verified = _commit(repo, "verified: drop legacy and suppress the locality leak")

        _git(repo, "checkout", "-q", "--force", "-b", "integ", base)
        (repo / "other.txt").write_text("another lane\n")
        _commit(repo, "other lane")
        _git(repo, "rm", "-qr", "src/lib/legacy")
        bad = _commit(repo, "bad squash: legacy dropped, locality fix lost")

        return {"repo": repo, "verified": verified, "bad": bad}

    def test_a_trailing_slash_path_cannot_certify_a_squash_that_lost_the_fix(self, tmp_path):
        lab = self._lab(tmp_path / "slash")
        # `src/lib/` matches two children at the base and one at the verified
        # head, so the base lookup is UNKNOWN. That was read as a difference,
        # and the only object compared -- `src/lib/core` -- is byte-identical
        # everywhere, while the integration side reverted the locality fix.
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["bad"], "--path", "src/lib/")

        assert done.returncode == 2
        # Refused before the comparison, as a directory rather than as an
        # ambiguous pathspec: either way it never reaches the merge base, which
        # is where UNKNOWN was being read as a difference.
        assert "name a directory" in done.stdout

    def test_the_same_squash_is_caught_when_the_path_is_spelled_as_git_reports_it(self, tmp_path):
        lab = self._lab(tmp_path / "slash2")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["bad"], "--path", "src/locality.ts")

        assert done.returncode == 1
        assert "DIVERGED src/locality.ts" in done.stdout


class TestAnOrdinaryMergeCanBeVerified:
    """Containment is not evidence, and it is not a dead end either.

    When the integration ref keeps the verified head as an ancestor, their merge
    base IS the verified head, so no path can differ from it. Round 6 refused
    every such merge with a message claiming the change "cannot have altered any
    of them", which is false and pointed the operator at the substitution the
    rule exists to prevent.

    Round 7 made containment a SUFFICIENT arm instead, on the grounds that it is
    "stronger evidence than any comparison". That was worse: `git merge -s ours`
    makes the verified head a parent and lands none of its content, and the tool
    called it `landed`. Containment proves the commit is in the history. It
    proves nothing whatever about the resulting tree.

    So the pre-change revision is derived from `--base-ref` -- the branch the
    change forked off -- and the probative check runs exactly as it does for any
    other shape.
    """

    @staticmethod
    def _lab(repo: Path, revert: bool = False, strategy: tuple[str, ...] = ()) -> dict[str, str]:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "keep.ts").write_text("before\n")
        (repo / "untouched.txt").write_text("the same everywhere\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "keep.ts").write_text("the verified content\n")
        verified = _commit(repo, "the change")

        _git(repo, "checkout", "-q", "--force", "main")
        (repo / "other.ts").write_text("another lane\n")
        _commit(repo, "integration moves on")
        if strategy:
            _git(repo, "merge", "-q", "--no-edit", *strategy, "feature")
        else:
            _git(repo, "merge", "-q", "--no-edit", "feature")
            if revert:
                (repo / "keep.ts").write_text("reverted after the merge\n")
                _commit(repo, "revert it again")
        integration = _git(repo, "rev-parse", "HEAD")
        return {"repo": repo, "base": base, "verified": verified, "integration": integration}

    def test_a_merge_that_kept_the_verified_content_passes(self, tmp_path):
        lab = self._lab(tmp_path / "ff")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["base"], "--path", "keep.ts")

        assert done.returncode == 0, done.stdout
        assert "landed" in done.stdout

    def test_containment_alone_is_refused_without_a_base_ref(self, tmp_path):
        lab = self._lab(tmp_path / "no-base")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--path", "keep.ts")

        assert done.returncode == 2
        assert "--base-ref" in done.stdout
        # And it must not send the operator looking for a different path.
        assert "Do NOT substitute a path" in done.stdout

    def test_a_merge_that_kept_the_commit_and_dropped_the_content_is_caught(self, tmp_path):
        # `-s ours`: the verified head IS a parent, and not one byte of it
        # landed. Round 7 reported this as `landed` for an untouched path.
        lab = self._lab(tmp_path / "ours", strategy=("-s", "ours"))
        repo = Path(str(lab["repo"]))
        assert _git(repo, "cat-file", "-p", f"{lab['integration']}:keep.ts").strip() == "before"

        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["base"], "--path", "untouched.txt")

        assert done.returncode == 2, done.stdout
        assert "differs from it there" in done.stdout

    def test_an_untouched_path_cannot_certify_an_ours_merge_even_when_declared(self, tmp_path):
        lab = self._lab(tmp_path / "ours2", strategy=("-s", "ours"))
        # The probative path tells the truth about the same merge.
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["base"], "--path", "keep.ts")

        assert done.returncode == 1
        assert "DIVERGED keep.ts" in done.stdout

    def test_containment_does_not_excuse_a_later_revert(self, tmp_path):
        # The commit is in the history and the content is gone anyway, which is
        # why the path comparison still has to run.
        lab = self._lab(tmp_path / "ff-reverted", revert=True)
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["base"], "--path", "keep.ts")

        assert done.returncode == 1
        assert "DIVERGED keep.ts" in done.stdout

    def test_a_base_ref_that_already_contains_the_change_is_refused(self, tmp_path):
        lab = self._lab(tmp_path / "bad-base")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["integration"], "--path", "keep.ts")

        assert done.returncode == 2
        assert "already contains --verified-head" in done.stdout


class TestADirectoryCannotWitnessContent:
    """Instance nine: `git ls-tree <ref> -- :(literal)src/lib` returns ONE
    record, `040000 tree <sha> src/lib`.

    So a directory looked like present evidence whose identity changed because a
    child was DELETED -- which turned absence into presence and walked straight
    past both deletions-only gates. A pure deletion, which this tool refuses
    outright, could be certified by declaring its parent directory.
    """

    @staticmethod
    def _lab(repo: Path) -> dict[str, str]:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "src" / "lib" / "legacy").mkdir(parents=True)
        (repo / "src" / "lib" / "core.ts").write_text("core\n")
        (repo / "src" / "lib" / "legacy" / "index.ts").write_text("legacy\n")
        (repo / "README.md").write_text("as written\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        _git(repo, "rm", "-qr", "src/lib/legacy")
        verified = _commit(repo, "verified: remove the legacy tree")

        # A SEPARATE lineage that reached the same absence on its own, and broke
        # something else on the way. No merge from `feature` ever happened.
        _git(repo, "checkout", "-q", "--force", "main")
        _git(repo, "rm", "-qr", "src/lib/legacy")
        (repo / "README.md").write_text("a regression nobody declared\n")
        integration = _commit(repo, "someone else removed it, and broke the readme")
        return {"repo": repo, "base": base, "verified": verified, "integration": integration}

    def test_the_tool_refuses_a_pure_deletion_as_it_says_it_does(self, tmp_path):
        lab = self._lab(tmp_path / "delonly")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--deleted-path", "src/lib/legacy/index.ts")

        assert done.returncode == 2
        assert "only removes files cannot be verified" in done.stdout

    @pytest.mark.parametrize("directory", ["src/lib", "src"])
    def test_and_a_parent_directory_cannot_smuggle_the_same_deletion_past_it(self, tmp_path, directory):
        # Both of these returned exit 0 `landed` for two lineages that never
        # merged, on the strength of a tree whose only change was a removal.
        lab = self._lab(tmp_path / f"dir-{directory.replace('/', '-')}")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--path", directory)

        assert done.returncode == 2, done.stdout
        assert "name a directory" in done.stdout

    def test_the_trailing_slash_spelling_is_refused_by_the_probative_gate_instead(self, tmp_path):
        # `src/lib/` is a directory PREFIX, so git lists the children rather than
        # the tree: here that is one blob, which is not caught as a directory.
        # It is still refused, by the gate that asks what the change could have
        # altered -- and the refusal has to be exit 2, not a pass.
        lab = self._lab(tmp_path / "dir-trailing")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--path", "src/lib/")

        assert done.returncode == 2, done.stdout
        assert "trailing slash" in done.stdout

    def test_a_file_under_it_reports_what_actually_happened(self, tmp_path):
        lab = self._lab(tmp_path / "dir-file")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--path", "README.md")

        # Untouched by the change, so it cannot witness the merge either -- and
        # this is the refusal that says so, not a pass.
        assert done.returncode == 2
        assert "differs from it there" in done.stdout


class TestTheMergeBaseAllFlagIsPinnedWithoutATieBreak:
    """`merge-base --all` IS pinnable order-independently, and an earlier
    docstring asserted at length that it was not.

    The claim was that reading one base and reading all of them can only
    disagree when the bases disagree, and then the answer turns on which one git
    prints. The way out is not to make the VERDICT differ -- it is to make the
    MESSAGE name every base. A deletion absent at both bases is refused either
    way, with no tie-break anywhere, and the refusal has to list both.
    """

    def test_the_refusal_names_every_merge_base_not_just_the_one_git_picked(self, tmp_path):
        repo = tmp_path / "criss-all"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "keep.txt").write_text("keep\n")
        root = _commit(repo, "root")

        _git(repo, "checkout", "-q", "-b", "a")
        (repo / "a.txt").write_text("a\n")
        left = _commit(repo, "a")

        _git(repo, "checkout", "-q", "--force", "-b", "b", root)
        (repo / "b.txt").write_text("b\n")
        right = _commit(repo, "b")

        _git(repo, "checkout", "-q", "--force", "-b", "x", left)
        _git(repo, "merge", "-q", "--no-edit", right)
        (repo / "keep.txt").write_text("edited on x\n")
        verified = _commit(repo, "x edits keep")

        _git(repo, "checkout", "-q", "--force", "-b", "y", right)
        _git(repo, "merge", "-q", "--no-edit", left)
        (repo / "y.txt").write_text("y moves on\n")
        integration = _commit(repo, "y moves on")

        bases = _git(repo, "merge-base", "--all", verified, integration).split()
        if len(bases) < 2:
            pytest.skip("this git produced a single merge base")

        # `never.txt` existed at neither base, so the verdict is a refusal under
        # either reading -- no tie-break is involved. What differs is the list.
        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--path", "keep.txt", "--deleted-path", "never.txt")

        assert done.returncode == 2
        for base in bases:
            assert base[:12] in done.stdout, f"the refusal did not name base {base[:12]}"


class TestAnAmbiguousPathspecComparesNothingItClaimsTo:
    """`_entry`'s `len(records) != 1` guard, and why it is not decoration.

    An earlier docstring called it unreachable because `:(literal)` "makes a
    multi-match impossible". It does not: `:(literal)` suppresses glob magic and
    says nothing about how many entries a pathspec matches. A later round then
    listed it as an acknowledged survivor, which was true of the suite and not
    of the code -- removing it produces a `landed` verdict over a directory in
    which the declared change was reverted.

    Without the guard, `git ls-tree -- :(literal)src/lib/` returns every child
    and `_entry` takes the FIRST. The operator believes they declared the
    directory; one file is compared; everything else in it can be anything.
    """

    @staticmethod
    def _lab(repo: Path) -> dict[str, str]:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "src" / "lib").mkdir(parents=True)
        # `a.ts` sorts first, so it is the record an unguarded `_entry` returns.
        (repo / "src" / "lib" / "a.ts").write_text("before\n")
        (repo / "src" / "lib" / "locality.ts").write_text("const w3w = null;\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "src" / "lib" / "a.ts").write_text("after\n")
        (repo / "src" / "lib" / "locality.ts").write_text("const w3w = REDACTED; // the fix\n")
        verified = _commit(repo, "verified: edit a.ts and suppress the locality leak")

        _git(repo, "checkout", "-q", "--force", "main")
        # The squash kept the first file and lost the one that mattered.
        (repo / "src" / "lib" / "a.ts").write_text("after\n")
        integration = _commit(repo, "bad squash: a.ts landed, the locality fix did not")
        return {"repo": repo, "base": base, "verified": verified, "integration": integration}

    def test_a_directory_spelling_cannot_pass_by_comparing_its_first_child(self, tmp_path):
        lab = self._lab(tmp_path / "ambiguous")
        repo = Path(str(lab["repo"]))
        # The premise, asserted rather than assumed: the pathspec really does
        # match more than one entry, and the first of them really is identical
        # on both sides while the change was reverted.
        records = _git(repo, "ls-tree", str(lab["verified"]), "--", ":(literal)src/lib/")
        assert len(records.splitlines()) > 1
        assert "REDACTED" not in _git(repo, "cat-file", "-p", f"{lab['integration']}:src/lib/locality.ts")

        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--path", "src/lib/")

        assert done.returncode == 2, done.stdout
        assert "do not exist at the verified head" in done.stdout

    def test_and_the_file_that_was_reverted_is_reported_when_it_is_declared(self, tmp_path):
        lab = self._lab(tmp_path / "ambiguous2")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--path", "src/lib/a.ts", "--path", "src/lib/locality.ts")

        assert done.returncode == 1
        assert "DIVERGED src/lib/locality.ts" in done.stdout
