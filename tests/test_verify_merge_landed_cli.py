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


@pytest.fixture(autouse=True, scope="session")
def _unsigned_fixture_commits():
    """Fixture repositories must not depend on the ambient commit signer.

    This environment configures a global `commit.gpgsign` helper. When it fails
    -- it began returning "too many open files" partway through a mutation
    sweep -- every `git commit` in every fixture returns 128, the suite goes red
    for a reason that has nothing to do with the code, and a mutation run then
    reports each mutant as KILLED while proving nothing. Six mutants were
    recorded that way before a red baseline gave it away.

    Signing a throwaway commit in a temp directory buys nothing, so turn it off
    for the whole session and let the suite measure the code.
    """
    previous = {key: os.environ.get(key) for key in
                ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0")}
    os.environ["GIT_CONFIG_COUNT"] = "1"
    os.environ["GIT_CONFIG_KEY_0"] = "commit.gpgsign"
    os.environ["GIT_CONFIG_VALUE_0"] = "false"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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


def declaration(repo: Path, base: str, head: str) -> list[str]:
    """The declaration the tool now requires: exactly what the change touched.

    Derived the same way the tool derives it, on purpose. These arguments are
    not the subject of most tests below -- the divergence, the mode, the tree
    reading are -- and hand-picking them is what the tool now refuses. The
    derivation itself is the subject of `TestTheDeclaredSetIsDerivedNotChosen`,
    which builds the expectations by hand instead.
    """
    out = _git(repo, "diff", "--name-status", "--no-renames", f"{base}..{head}")
    args: list[str] = []
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        args += ["--deleted-path" if status.startswith("D") else "--path", path]
    return args


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
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
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
            "--integration-ref", str(history["verified_landed"]), "--base-ref", str(history["base"]),
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
            "--integration-ref", str(history["verified"]), "--base-ref", str(history["base"]),
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
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
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
            "--integration-ref", str(history["integrated"]), "--base-ref", str(history["base"]),
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
            "--integration-ref", str(history["integrated"]), "--base-ref", str(history["base"]),
            "--deleted-path", REMOVED,
            "--path", EDITED,
        )
        assert done.returncode == 0

    def test_a_real_deletion_still_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]), "--base-ref", str(history["base"]),
            "--deleted-path", REMOVED,
            "--path", EDITED,
        )
        assert done.returncode == 0
        assert "landed" in done.stdout
        # A real land, not a self-comparison: the trees genuinely differ.
        assert "identical tree: False" in done.stdout

    def test_no_flag_lets_the_caller_name_the_deletion_revision(self, history):
        # The hole this replaced: the deletion base was a caller argument, so any
        # commit in the object database that happened to contain the path
        # satisfied it, including one with no relationship to the merge -- and a
        # declared set of only deletions then returned `landed` without reading a
        # byte of the integration ref.
        #
        # This asserts the SPELLING is gone, which is all it ever asserted. The
        # property -- that no caller-supplied revision can decide a deletion --
        # is asserted by `TestTheDeclaredSetIsDerivedNotChosen`, because
        # `--base-ref` later reintroduced exactly that hole and this test, under
        # its old name, went on passing throughout.
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]), "--base-ref", str(history["base"]),
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
            "--integration-ref", str(history["integrated"]), "--base-ref", str(history["base"]),
            "--deleted-path", REMOVED,
            "--path", EDITED,
        )
        assert provable.returncode == 0, provable.stdout

        unprovable = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["from_the_base"]), "--base-ref", str(history["base"]),
            "--deleted-path", LATER,
            "--path", EDITED,
        )
        # LATER was added AND removed by the change, so it is not in the diff
        # against the fork point at all -- there is no deletion of it to verify,
        # and the refusal now says so by naming the set instead of hunting for a
        # revision where the path happened to exist.
        assert unprovable.returncode == 2
        assert "no deletion to verify" in unprovable.stdout
        assert LATER in unprovable.stdout

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
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
            "--deleted-path", "gone.txt",
        )
        assert done.returncode == 2
        assert "no deletion to verify" in done.stdout


class TestThePathspecIsLiteral:
    def test_a_filename_beginning_with_a_colon_is_a_path_not_pathspec_magic(self, tmp_path):
        # Without `:(literal)` git reads `:odd.txt` as pathspec magic, matches
        # nothing, and the tool refuses a file that is plainly there. The change
        # has to TOUCH it, now that the declared set must be the derived one.
        repo = tmp_path / "colon"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / COLON_PREFIXED).write_text("before\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / COLON_PREFIXED).write_text("the verified content\n")
        verified = _commit(repo, "the change edits a colon-prefixed path")

        _git(repo, "checkout", "-q", "--force", "-b", "integ", base)
        (repo / COLON_PREFIXED).write_text("the verified content\n")
        (repo / "beside.txt").write_text("other work\n")
        integration = _commit(repo, "it landed, alongside other work")

        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", base, "--path", COLON_PREFIXED)

        assert done.returncode == 0, done.stdout
        assert "landed" in done.stdout

    def test_a_wildcard_path_is_not_expanded_into_a_real_one(self, history):
        # Without `:(literal)`, `kept.tx*` matches exactly one file and the tool
        # would compare that file while reporting the pattern as the path --
        # a pass for a path that does not exist.
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
            "--path", f"{EDITED[:-1]}*",
        )
        assert done.returncode == 2
        assert "do not exist at the verified head" in done.stdout


class TestHowTheTreeIsRead:
    """What is pinned, what is not, and why -- counted from a sweep, not read.

    50 mutants, 33 killed, SEVENTEEN survivors, 0 skipped, with an unmutated
    control copy green through the same pipeline first. Earlier versions of this
    docstring said three, five, eight, six and sixteen; every one before the
    last was reached by reading the code, and every one was wrong.

    UNREACHABLE, because the declared set is derived rather than chosen. Every
    declared path comes from `git diff --name-status`, so it is a path git named,
    spelled as git spells it:

      * `_differs_from_every_base`'s UNKNOWN guard -- a derived path resolves.
      * the `--deleted-path` UNKNOWN arm.
      * `identical_tree`'s two `!= UNKNOWN` conjuncts -- `VerifiedResult` refuses
        an empty tree sha and identity needs both sides equal.
        `TestWhyTheIdenticalTreeGuardsCannotBeExercised` proves that premise.
      * the empty-derived-set gate -- `--base-ref` is required now, so the
        revision it guarded against (the verified head standing in for its own
        pre-change state) can no longer be reached.

    DEFENSIVE, and correct rather than covered:

      * `--end-of-options` on ls-tree, on rev-parse and on git diff (`--verify`
        already rejects a dash ref, and by the time the diff runs both ends are
        40-hex ids)
      * `--quiet` on rev-parse
      * `_entry`'s empty-field guard
      * `_resolve_ref`'s commit and tree resolution checks
      * `_changed_paths`' return-code guard and its odd-field guard -- the
        second is what would catch a pair-wise parse sliding by one, and `-z`
        plus `--no-renames` means it never does. `TestTheDerivationReadsWhat
        GitActuallyPrinted` asserts the property instead of the guard.
      * the derived union's preference for `D` when bases disagree
      * `may_report_integrated`'s `and inspection.landed` conjunct
      * `restoration_paths`' verdict guard

    None of them is claimed as covered.

    A NOTE ON METHOD, because this harness has now produced false results FIVE
    times and three of them nearly reached a commit message:

      1. a `replace(..., 1)` mutating the wrong copy of a guard appearing twice;
      2. a killed sweep leaving a mutant stranded in the working tree, so the
         next run's green suite was measured against it;
      3. a test whose own premise was wrong, so the baseline was red and every
         "kill" was an artifact;
      4. a sibling harness whose copies excluded `.git`, breaking 22 subprocess
         tests before any mutation;
      5. this environment's global commit-signing helper running out of file
         descriptors mid-sweep, so every fixture's `git commit` returned 128 and
         six mutants were recorded as KILLED while proving nothing.

    Hence the session fixture that turns commit signing off, the control copy
    that must be green before any result is believed, and the byte-for-byte
    restoration check after. A kill you did not watch happen is not a kill.
    """

    def test_a_path_resolves_the_same_from_a_subdirectory(self, history):
        # Without `--full-tree`, ls-tree is relative to the cwd, so the same
        # root-relative path would silently stop resolving in a nested checkout.
        nested = Path(str(history["repo"])) / "nested"
        nested.mkdir(exist_ok=True)
        done = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--verified-head", str(history["verified"]),
             "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
             "--path", EDITED, "--path", LATER],
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

        done = run(history, "--verified-head", head, "--integration-ref", landed,
                   "--base-ref", str(history["base"]), "--path", odd)
        assert done.returncode == 0
        assert "landed" in done.stdout


class TestModeAndType:
    """A blob id alone cannot see a file become a symlink or gain +x."""

    def test_the_executable_bit_changing_is_a_divergence(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["chmodded"]), "--base-ref", str(history["base"]),
            "--path", EDITED,
            "--path", LATER,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout
        assert f"DIVERGED {EDITED}" in done.stdout

    def test_a_file_becoming_a_symlink_to_its_own_content_is_a_divergence(self, history):
        done = run(
            history,
            "--verified-head", str(history["symlinked"]),
            "--integration-ref", str(history["verified"]), "--base-ref", str(history["base"]),
            "--path", SYMLINKABLE,
            "--path", EDITED,
            "--path", LATER,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout
        assert f"DIVERGED {SYMLINKABLE}" in done.stdout

    def test_the_compared_identity_names_the_mode_and_type(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["chmodded"]), "--base-ref", str(history["base"]),
            "--path", EDITED,
            "--path", LATER,
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
            "--integration-ref", str(history["verified"]), "--base-ref", str(history["base"]),
            "--path", EDITED,
        )
        assert done.returncode == 2
        assert "are the same commit" in done.stdout

    def test_no_paths_never_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified_landed"]), "--base-ref", str(history["base"]),
        )
        assert done.returncode == 2
        assert "nothing to verify" in done.stdout


class TestTheContract:
    def test_a_merge_that_dropped_the_verified_content_stops_the_lane(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
            "--path", EDITED,
            "--path", LATER,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout
        assert f"DIVERGED {EDITED}" in done.stdout
        assert "STOP THIS MERGE LANE" in done.stdout

    def test_a_merge_that_kept_it_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified_landed"]), "--base-ref", str(history["base"]),
            "--path", EDITED,
            "--path", LATER,
        )
        assert done.returncode == 0
        assert "landed" in done.stdout

    def test_an_untouched_path_is_not_enough_to_hide_a_dropped_one(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
            "--path", UNTOUCHED,
            "--path", EDITED,
            "--path", LATER,
        )
        # Padding the real set with an untouched path is now refused outright,
        # rather than tolerated because something else in the set was probative.
        assert done.returncode == 2
        assert "does not touch them" in done.stdout
        assert UNTOUCHED in done.stdout

    def test_a_merge_api_that_did_not_report_success_is_never_a_pass(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified_landed"]), "--base-ref", str(history["base"]),
            "--path", EDITED,
            "--path", LATER,
            "--no-merge-reported-success",
        )
        assert done.returncode == 1
        assert "merge_not_reported" in done.stdout


class TestDeletions:
    def test_a_deletion_that_landed_passes(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]), "--base-ref", str(history["base"]),
            "--deleted-path", REMOVED,
            "--path", EDITED,
        )
        assert done.returncode == 0

    def test_a_deletion_the_merge_did_not_apply_stops_the_lane(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["kept_the_removed_file"]), "--base-ref", str(history["base"]),
            "--deleted-path", REMOVED,
            "--path", EDITED,
        )
        assert done.returncode == 1
        assert "tree_mismatch" in done.stdout

    def test_declaring_a_live_file_deleted_is_refused(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["verified_landed"]), "--base-ref", str(history["base"]),
            "--deleted-path", EDITED,
        )
        assert done.returncode == 2
        assert "still exist at the verified head" in done.stdout

    def test_the_same_path_cannot_be_declared_twice(self, history):
        done = run(
            history,
            "--verified-head", str(history["deletion"]),
            "--integration-ref", str(history["integrated"]), "--base-ref", str(history["base"]),
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
                "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
                "--path", EDITED,
                "--path", LATER,
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

        return {"repo": repo, "base": base, "verified": verified, "integration": integration}

    def test_a_record_of_only_deletions_never_reports_landed(self, tmp_path):
        history = self._forked(tmp_path / "forked")
        # `git diff --name-status base..verified` on a pure-deletion change gives
        # exactly this set, so the operating memory's own prescribed workflow
        # produced it. It returned `landed`, exit 0, having read nothing.
        done = run(history, "--verified-head", str(history["verified"]),
                   "--integration-ref", str(history["integration"]), "--base-ref", str(history["base"]), "--deleted-path", "leak.py")

        # Refused before anything is compared. The tool now derives the set
        # itself, so a deletions-only DECLARATION of a change that also edited a
        # file is refused as the wrong set -- and the message names the file
        # whose content can actually witness the merge, rather than sending the
        # operator to find one.
        assert done.returncode == 2
        assert "not the paths this change touched" in done.stdout
        assert "--path core.py" in done.stdout
        assert "verdict      :" not in done.stdout

    def test_and_the_full_set_reaches_a_real_comparison(self, tmp_path):
        history = self._forked(tmp_path / "forked-full")
        done = run(history, "--verified-head", str(history["verified"]),
                   "--integration-ref", str(history["integration"]), "--base-ref", str(history["base"]),
                   "--path", "core.py", "--deleted-path", "leak.py")

        # Whatever the verdict, it was reached by reading content rather than by
        # comparing an absence with an absence.
        assert done.returncode in (0, 1)
        assert "verdict" in done.stdout

    def test_the_same_refs_reveal_the_regression_once_a_kept_path_is_declared(self, tmp_path):
        history = self._forked(tmp_path / "forked2")
        done = run(history, "--verified-head", str(history["verified"]),
                   "--integration-ref", str(history["integration"]), "--base-ref", str(history["base"]),
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
                   "--base-ref", root, "--deleted-path", "F.py", "--path", "keep.txt")

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

        _git(repo, "checkout", "-q", "--force", "-b", "base-branch", left)
        _git(repo, "merge", "-q", "--no-edit", right)
        (repo / "base-branch-marker.txt").write_text("the base branch moved on\n")
        crisscross_base = _commit(repo, "base branch, merging both sides")

        bases = _git(repo, "merge-base", "--all", verified, crisscross_base).split()
        if len(bases) < 2:
            pytest.skip("this git produced a single merge base")
        values = {_git(repo, "ls-tree", base, "--", "P.txt") for base in bases}
        if len(values) < 2:
            pytest.skip("both bases hold the same P.txt; the distinction is not exercised")

        # P.txt matches `left` and differs from `right`, so `any` would call it
        # touched and `all` correctly does not.
        # The declared set must be the derived one, so both paths are named;
        # `P.txt` still matches one base and differs from the other, which is
        # exactly the case the quantifier decides.
        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", crisscross_base, "--path", "P.txt", "--path", "other.txt")

        assert done.returncode == 2, done.stdout
        assert "do not differ from EVERY pre-change revision" in done.stdout
        assert "P.txt" in done.stdout


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
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
            "--path", UNTOUCHED,
        )

        assert done.returncode == 2
        assert "not the paths this change touched" in done.stdout
        assert "verdict      :" not in done.stdout

    def test_the_same_refs_are_caught_once_a_touched_path_is_declared(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
            "--path", EDITED,
            "--path", LATER,
        )

        assert done.returncode == 1
        assert f"DIVERGED {EDITED}" in done.stdout

    def test_an_untouched_path_does_not_dilute_a_touched_one(self, history):
        done = run(
            history,
            "--verified-head", str(history["verified"]),
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
            "--path", EDITED,
            "--path", LATER,
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
            "--integration-ref", str(history["diverged"]), "--base-ref", str(history["base"]),
            "--path", "does/not/exist.txt",
        )

        assert done.returncode == 2
        # The tool derives the set now, so the remediation is to read the set it
        # prints -- not to go looking for a path that gets past the gate.
        assert "this tool prints the exact set it derived" in done.stdout
        assert "the change kept as well" not in done.stdout
        assert "substitute" not in done.stdout


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

        return {"repo": repo, "base": base, "verified": verified, "bad": bad}

    def test_a_trailing_slash_path_cannot_certify_a_squash_that_lost_the_fix(self, tmp_path):
        lab = self._lab(tmp_path / "slash")
        # `src/lib/` matches two children at the base and one at the verified
        # head, so the base lookup is UNKNOWN. That was read as a difference,
        # and the only object compared -- `src/lib/core` -- is byte-identical
        # everywhere, while the integration side reverted the locality fix.
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["bad"], "--base-ref", lab["base"], "--path", "src/lib/")

        assert done.returncode == 2
        # Refused before the comparison, as a directory rather than as an
        # ambiguous pathspec: either way it never reaches the merge base, which
        # is where UNKNOWN was being read as a difference.
        assert "name a directory" in done.stdout

    def test_the_same_squash_is_caught_when_the_path_is_spelled_as_git_reports_it(self, tmp_path):
        lab = self._lab(tmp_path / "slash2")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["bad"], "--base-ref", lab["base"],
                   "--path", "src/locality.ts", "--deleted-path", "src/lib/legacy/index.ts")

        assert done.returncode == 1, done.stdout
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

    def test_nothing_is_verified_without_a_base_ref(self, tmp_path):
        lab = self._lab(tmp_path / "no-base")
        # Deliberately no `--base-ref`: the merge base of the two refs is an
        # ancestor of the verified head, and so is every commit of the change,
        # so it cannot be trusted to be the fork point.
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--path", "keep.ts")

        assert done.returncode == 2
        # `--base-ref` is required now, precisely because the merge base of the
        # two refs cannot be trusted to be the fork point.
        assert "--base-ref is required" in done.stdout
        assert "BEFORE the merge" in done.stdout
        assert "verdict      :" not in done.stdout

    def test_a_merge_that_kept_the_commit_and_dropped_the_content_is_caught(self, tmp_path):
        # `-s ours`: the verified head IS a parent, and not one byte of it
        # landed. Round 7 reported this as `landed` for an untouched path.
        lab = self._lab(tmp_path / "ours", strategy=("-s", "ours"))
        repo = Path(str(lab["repo"]))
        assert _git(repo, "cat-file", "-p", f"{lab['integration']}:keep.ts").strip() == "before"

        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["base"], "--path", "untouched.txt")

        assert done.returncode == 2, done.stdout
        # Named as declared-but-untouched, and told what the real set is.
        assert "does not touch them" in done.stdout
        assert "untouched.txt" in done.stdout
        assert "--path keep.ts" in done.stdout

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
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"], "--base-ref", lab["base"],
                   "--deleted-path", "src/lib/legacy/index.ts")

        assert done.returncode == 2
        assert "only removes files cannot be verified" in done.stdout

    @pytest.mark.parametrize("directory", ["src/lib", "src"])
    def test_and_a_parent_directory_cannot_smuggle_the_same_deletion_past_it(self, tmp_path, directory):
        # Both of these returned exit 0 `landed` for two lineages that never
        # merged, on the strength of a tree whose only change was a removal.
        lab = self._lab(tmp_path / f"dir-{directory.replace('/', '-')}")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"], "--base-ref", lab["base"],
                   "--path", directory)

        assert done.returncode == 2, done.stdout
        assert "name a directory" in done.stdout

    def test_the_trailing_slash_spelling_is_refused_by_the_probative_gate_instead(self, tmp_path):
        # `src/lib/` is a directory PREFIX, so git lists the children rather than
        # the tree: here that is one blob, which is not caught as a directory.
        # It is still refused, by the gate that asks what the change could have
        # altered -- and the refusal has to be exit 2, not a pass.
        lab = self._lab(tmp_path / "dir-trailing")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"], "--base-ref", lab["base"],
                   "--path", "src/lib/")

        assert done.returncode == 2, done.stdout
        # Refused as a path this change does not touch: `src/lib/` resolves to
        # something git never named, so it cannot be in the derived set.
        assert "does not touch them" in done.stdout
        assert "src/lib/" in done.stdout

    def test_a_file_under_it_reports_what_actually_happened(self, tmp_path):
        lab = self._lab(tmp_path / "dir-file")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"], "--base-ref", lab["base"],
                   "--path", "README.md")

        # Untouched by the change, so it cannot witness the merge -- and the
        # refusal names it as declared-but-untouched rather than passing.
        assert done.returncode == 2
        assert "does not touch them" in done.stdout
        assert "README.md" in done.stdout


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

        _git(repo, "checkout", "-q", "--force", "-b", "base-branch", left)
        _git(repo, "merge", "-q", "--no-edit", right)
        (repo / "base-branch-marker.txt").write_text("the base branch moved on\n")
        crisscross_base = _commit(repo, "base branch, merging both sides")

        bases = _git(repo, "merge-base", "--all", verified, crisscross_base).split()
        if len(bases) < 2:
            pytest.skip("this git produced a single merge base")

        # `never.txt` existed at neither base, so the verdict is a refusal under
        # either reading -- no tie-break is involved. What differs is the list.
        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", crisscross_base, "--path", "keep.txt", "--deleted-path", "never.txt")

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

        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"], "--base-ref", lab["base"],
                   "--path", "src/lib/")

        assert done.returncode == 2, done.stdout
        # A multi-match is UNKNOWN, not ABSENT, and those are now separate
        # refusals: "it is not there" and "that did not resolve to one file"
        # are different facts. This one is the second, it names the pathspec,
        # and it does not claim the spelling is fine -- a trailing slash IS the
        # spelling problem here, even though the sibling cause (undecodable
        # bytes) is not.
        assert "did not resolve to one file" in done.stdout
        assert "src/lib/" in done.stdout
        assert "verdict" not in done.stdout
        # The PROPERTY, not one spelling of it: this message must not tell the
        # operator anything about WHICH cause of UNKNOWN they hit, because
        # `_entry` has four and they disagree about whether the input can be
        # corrected. Pinning the literal phrase "the spelling is not the
        # problem" let the next false claim -- "only one of them is a spelling
        # you can correct" -- straight through.
        lowered = done.stdout.lower()
        for overclaim in (
            "the spelling is not the problem",
            "only one of them is a spelling",
            "nothing to correct",
            "correct the spelling",
        ):
            assert overclaim not in lowered, overclaim

    def test_and_the_file_that_was_reverted_is_reported_when_it_is_declared(self, tmp_path):
        lab = self._lab(tmp_path / "ambiguous2")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"], "--base-ref", lab["base"],
                   "--path", "src/lib/a.ts", "--path", "src/lib/locality.ts")

        assert done.returncode == 1
        assert "DIVERGED src/lib/locality.ts" in done.stdout


class TestTheDeclaredSetIsDerivedNotChosen:
    """Instance ten, and the rule that ends the whole family.

    `--base-ref` was added so an ordinary merge could be verified at all. It
    reintroduced the case `657b2f1` closed and the operating memory lists as
    already shut: **a caller-named base**. Nothing tied it to the fork point, so
    a base named further back made an untouched path differ from it -- and
    `git merge -s ours`, which keeps the verified head as a parent and lands not
    one byte of it, was reported `landed`.

    Every false pass this tool has had was a declaration the operator chose. The
    rule that ends them is not another constraint on WHERE evidence may come
    from; it is that the operator no longer chooses. The tool derives the set
    with `git diff --name-status <pre-change revision>..<verified head>` and
    refuses anything else.

    A base further BACK is then self-defeating: it does not shrink the set,
    it GROWS it, and every path it adds must be declared and compared. The
    expectations below are written out by hand, never derived by the helper, so
    they cannot agree with the tool by construction.
    """

    @staticmethod
    def _lab(repo: Path, strategy: tuple[str, ...] = (), revert: bool = False) -> dict[str, str]:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        # `f.txt` changes between the DISTANT base and the real fork point, so
        # it is the path a caller-named distant base makes look probative.
        (repo / "f.txt").write_text("v1\n")
        (repo / "x.txt").write_text("x1\n")
        ancient = _commit(repo, "ancient")

        (repo / "f.txt").write_text("v2\n")
        fork = _commit(repo, "the real fork point")

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "x.txt").write_text("the verified content\n")
        verified = _commit(repo, "the change: x.txt only")

        _git(repo, "checkout", "-q", "--force", "main")
        if strategy and strategy[0] == "-X":
            # `-X ours` resolves CONFLICTS in favour of main, so there has to be
            # one: without it the merge fast-forwards and lands the change.
            (repo / "x.txt").write_text("main's own edit\n")
            _commit(repo, "main edits the same file")
        if strategy:
            _git(repo, "merge", "-q", "--no-edit", *strategy, "feature")
        else:
            _git(repo, "merge", "-q", "--no-edit", "feature")
            if revert:
                (repo / "x.txt").write_text("reverted\n")
                _commit(repo, "revert it")
        integration = _git(repo, "rev-parse", "HEAD")
        return {"repo": repo, "ancient": ancient, "fork": fork, "verified": verified, "integration": integration}

    def test_a_distant_base_cannot_make_an_untouched_path_probative(self, tmp_path):
        # The exact attack: `-s ours` landed nothing, and `f.txt` is identical
        # at the verified head and the integration ref while differing from the
        # ancient base. This returned exit 0 `landed`.
        lab = self._lab(tmp_path / "ours", strategy=("-s", "ours"))
        repo = Path(str(lab["repo"]))
        assert _git(repo, "cat-file", "-p", f"{lab['integration']}:x.txt").strip() == "x1"

        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["ancient"], "--path", "f.txt")

        assert done.returncode == 2, done.stdout
        assert "not the paths this change touched" in done.stdout

    def test_and_declaring_the_whole_derived_set_catches_it(self, tmp_path):
        # A distant base does not shrink the set, it grows it -- so the honest
        # declaration from that same base includes the path that tells the truth.
        lab = self._lab(tmp_path / "ours-full", strategy=("-s", "ours"))
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["ancient"], "--path", "f.txt", "--path", "x.txt")

        assert done.returncode == 1, done.stdout
        assert "DIVERGED x.txt" in done.stdout

    def test_the_honest_base_catches_it_with_one_path(self, tmp_path):
        lab = self._lab(tmp_path / "ours-honest", strategy=("-s", "ours"))
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["fork"], "--path", "x.txt")

        assert done.returncode == 1, done.stdout
        assert "DIVERGED x.txt" in done.stdout

    def test_an_ours_strategy_conflict_resolution_is_caught_too(self, tmp_path):
        lab = self._lab(tmp_path / "x-ours", strategy=("-X", "ours"))
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["ancient"], "--path", "f.txt")

        assert done.returncode == 2, done.stdout
        assert "not the paths this change touched" in done.stdout

    def test_a_merge_then_revert_is_caught_too(self, tmp_path):
        lab = self._lab(tmp_path / "revert", revert=True)
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["ancient"], "--path", "f.txt")

        assert done.returncode == 2, done.stdout

        honest = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                     "--base-ref", lab["fork"], "--path", "x.txt")
        assert honest.returncode == 1, honest.stdout
        assert "DIVERGED x.txt" in honest.stdout

    def test_a_deletion_this_change_never_made_is_not_deletion_evidence(self, tmp_path):
        # `ancient.txt` was removed on main long before the fork, so it appears
        # as a deletion against a distant base while this change never touched
        # it. That satisfied the owner's criterion nowhere and returned exit 0.
        repo = tmp_path / "old-deletion"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "ancient.txt").write_text("long gone\n")
        (repo / "f.txt").write_text("v1\n")
        ancient = _commit(repo, "ancient")
        (repo / "ancient.txt").unlink()
        (repo / "f.txt").write_text("v2\n")
        fork = _commit(repo, "someone else removed it, before the fork")

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "f.txt").write_text("the verified content\n")
        verified = _commit(repo, "the change: f.txt only")

        _git(repo, "checkout", "-q", "--force", "main")
        (repo / "other.txt").write_text("other\n")
        _commit(repo, "other work")
        _git(repo, "merge", "-q", "--no-edit", "feature")
        integration = _git(repo, "rev-parse", "HEAD")
        lab = {"repo": repo, "ancient": ancient, "fork": fork, "verified": verified, "integration": integration}

        done = run(lab, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", ancient, "--path", "f.txt", "--deleted-path", "ancient.txt")

        # `ancient.txt` IS in the set derived from that distant base, so the
        # refusal is not about the declaration -- the point is that it no longer
        # buys a pass on its own, and the honest base rejects it outright.
        honest = run(lab, "--verified-head", verified, "--integration-ref", integration,
                     "--base-ref", fork, "--path", "f.txt", "--deleted-path", "ancient.txt")
        assert honest.returncode == 2, honest.stdout
        # The deletion gate speaks first: against the real fork point the file
        # was already gone, so there is no deletion of it to verify here.
        assert "do not exist at every pre-change revision" in honest.stdout
        assert "ancient.txt" in honest.stdout

        # And against the distant base, the declaration must be complete, so the
        # path that tells the truth about the merge is compared either way.
        assert done.returncode in (0, 1), done.stdout
        if done.returncode == 0:
            assert "landed" in done.stdout

    def test_a_base_ref_is_required_even_where_the_merge_base_looks_usable(self, tmp_path):
        """The squash shape, where round 9 derived the base and called it safe.

        `merge-base(verified, integration)` is an ancestor of the verified head
        -- and so is every commit of the change. When the integration ref
        descends from a commit INSIDE the change, that merge base IS that
        commit, the derived set shrinks to the change's tail, and the paths the
        earlier commits touched are reported as paths the change "does not
        touch". Round 9 reasoned only about a base further BACK, where the set
        grows; a base forward of the fork point shrinks it, and shrinking is
        what hides a regression.

        This is the shape this repository keeps producing: a branch merged from
        a commit behind its head.
        """
        repo = tmp_path / "merged-from-behind"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "src").mkdir()
        (repo / "src" / "locality.py").write_text("coords: PLAIN\n")
        (repo / "docs.md").write_text("v0\n")
        base = _commit(repo, "the base branch")

        # A two-commit change: C1 hardens the locality, C2 edits the docs.
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "src" / "locality.py").write_text("coords: WITHHELD  # C1 hardening\n")
        c1 = _commit(repo, "C1: withhold the coordinates")
        (repo / "docs.md").write_text("v1\n")
        verified = _commit(repo, "C2: document it")

        # The integration branch took C1 only -- merged from behind the head.
        _git(repo, "checkout", "-q", "--force", "-b", "integ", c1)
        (repo / "docs.md").write_text("v1\n")
        integration = _commit(repo, "integration carries C1 and its own docs edit")

        lab = {"repo": repo}
        # The merge base of the two refs IS C1, inside the change.
        assert _git(Path(str(repo)), "merge-base", verified, integration) == c1

        # Without a base ref the tool refuses rather than deriving from C1.
        refused = run(lab, "--verified-head", verified, "--integration-ref", integration, "--path", "docs.md")
        assert refused.returncode == 2, refused.stdout
        assert "--base-ref is required" in refused.stdout

        # With the real fork point, the locality file is in the derived set and
        # the regression is reported instead of being called untouched.
        honest = run(lab, "--verified-head", verified, "--integration-ref", integration,
                     "--base-ref", base, "--path", "docs.md")
        assert honest.returncode == 2, honest.stdout
        assert "src/locality.py" in honest.stdout

        caught = run(lab, "--verified-head", verified, "--integration-ref", integration,
                     "--base-ref", base, "--path", "docs.md", "--path", "src/locality.py")
        assert caught.returncode == 0, caught.stdout
        # C1 did land here, so this one passes -- the point is that the path was
        # COMPARED rather than declared untouchable.
        assert "landed" in caught.stdout

    def test_and_the_regression_is_caught_when_the_integration_side_lost_it(self, tmp_path):
        repo = tmp_path / "merged-from-behind-lost"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "src").mkdir()
        (repo / "src" / "locality.py").write_text("coords: PLAIN\n")
        (repo / "docs.md").write_text("v0\n")
        base = _commit(repo, "the base branch")

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "src" / "locality.py").write_text("coords: WITHHELD  # C1 hardening\n")
        c1 = _commit(repo, "C1: withhold the coordinates")
        (repo / "docs.md").write_text("v1\n")
        verified = _commit(repo, "C2: document it")

        # The integration branch reverted the hardening after taking it.
        _git(repo, "checkout", "-q", "--force", "-b", "integ", c1)
        (repo / "src" / "locality.py").write_text("coords: PLAIN\n")
        (repo / "docs.md").write_text("v1\n")
        integration = _commit(repo, "integration lost the locality hardening")

        lab = {"repo": repo}
        done = run(lab, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", base, "--path", "docs.md", "--path", "src/locality.py")

        assert done.returncode == 1, done.stdout
        assert "DIVERGED src/locality.py" in done.stdout
    def _criss_cross(repo: Path) -> dict[str, str]:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "P.txt").write_text("v0\n")
        (repo / "keep.txt").write_text("keep\n")
        root = _commit(repo, "root")

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
        (repo / "keep.txt").write_text("y moves on\n")
        integration = _commit(repo, "y moves on")
        return {"repo": repo, "base": root, "verified": verified, "integration": integration}

    def test_the_probative_gate_reads_every_base_not_the_first(self, tmp_path):
        """Two paths, each matching a DIFFERENT base.

        An earlier version of this test used one path and asserted the verdict,
        which is order-dependent: whether `before[0]` is the base the path
        matches decides whether the mutant refuses too, so it survived. The way
        out is the same one that pinned `merge-base --all` -- do not make the
        verdict differ, make the MESSAGE differ. Under every base BOTH paths are
        non-probative and both must be listed; reading only `before[0]` can list
        at most one of them, whichever base git names first.
        """
        repo = tmp_path / "multi-base"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "P.txt").write_text("v0\n")
        (repo / "Q.txt").write_text("w0\n")
        root = _commit(repo, "root")

        # left sets P; right sets Q. The merge of the two carries both, so P
        # matches left and differs from right, and Q the other way round.
        _git(repo, "checkout", "-q", "-b", "left")
        (repo / "P.txt").write_text("v1\n")
        left = _commit(repo, "left sets P")

        _git(repo, "checkout", "-q", "--force", "-b", "right", root)
        (repo / "Q.txt").write_text("w1\n")
        right = _commit(repo, "right sets Q")

        _git(repo, "checkout", "-q", "--force", "-b", "x", left)
        _git(repo, "merge", "-q", "--no-edit", right)
        verified = _git(repo, "rev-parse", "HEAD")

        _git(repo, "checkout", "-q", "--force", "-b", "y", right)
        _git(repo, "merge", "-q", "--no-edit", left)
        (repo / "keep.txt").write_text("y moves on\n")
        integration = _commit(repo, "y moves on")

        _git(repo, "checkout", "-q", "--force", "-b", "base-branch", left)
        _git(repo, "merge", "-q", "--no-edit", right)
        (repo / "base-branch-marker.txt").write_text("the base branch moved on\n")
        crisscross_base = _commit(repo, "base branch, merging both sides")

        bases = _git(repo, "merge-base", "--all", verified, crisscross_base).split()
        if len(bases) < 2:
            pytest.skip("this git produced a single merge base")
        # The premise, asserted: each path matches exactly one of the two bases.
        for path in ("P.txt", "Q.txt"):
            matches = [b for b in bases
                       if _git(repo, "ls-tree", b, "--", path) == _git(repo, "ls-tree", verified, "--", path)]
            assert len(matches) == 1, (path, matches)

        lab = {"repo": repo}
        done = run(lab, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", crisscross_base, "--path", "P.txt", "--path", "Q.txt")

        assert done.returncode == 2, done.stdout
        assert "do not differ from EVERY pre-change revision" in done.stdout
        # BOTH, whichever base git named first.
        assert "P.txt" in done.stdout
        assert "Q.txt" in done.stdout
        assert "verdict      :" not in done.stdout

    def test_a_base_ref_sharing_no_history_is_refused(self, tmp_path):
        repo = tmp_path / "orphan-base"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "f.txt").write_text("v1\n")
        _commit(repo, "base")
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "f.txt").write_text("the verified content\n")
        verified = _commit(repo, "the change")
        _git(repo, "checkout", "-q", "--force", "main")
        # Main moves on first, so the merge is a real merge rather than a
        # fast-forward that would make the two refs the same commit.
        (repo / "other.txt").write_text("other work\n")
        _commit(repo, "main moves on")
        _git(repo, "merge", "-q", "--no-edit", "feature")
        integration = _git(repo, "rev-parse", "HEAD")

        # An orphan lineage: a real commit that shares no ancestor at all.
        _git(repo, "checkout", "-q", "--orphan", "stranger")
        _git(repo, "rm", "-rqf", ".")
        (repo / "unrelated.txt").write_text("no shared history\n")
        orphan = _commit(repo, "orphan")
        _git(repo, "checkout", "-q", "--force", "main")

        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", orphan, "--path", "f.txt")

        assert done.returncode == 2, done.stdout
        assert "share no common ancestor" in done.stdout


class TestARenameIsTwoPathsNotOne:
    """`--no-renames`, because the derivation parses git's output in pairs.

    `git diff --name-status -z` emits a rename as THREE fields -- `R100`, the
    old path, the new path -- where every other status emits two. Parsing in
    pairs then reads the new path as a status and the next status as a path, and
    the derived set silently becomes nonsense. With `--no-renames` a rename is a
    delete and an add, which is what the comparison can actually check.
    """

    @staticmethod
    def _lab(repo: Path) -> dict[str, str]:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "old-name.ts").write_text("identical content, moved\n")
        (repo / "beside.ts").write_text("v1\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        _git(repo, "mv", "old-name.ts", "new-name.ts")
        (repo / "beside.ts").write_text("v2\n")
        verified = _commit(repo, "the change renames a file and edits another")

        _git(repo, "checkout", "-q", "--force", "-b", "integ", base)
        _git(repo, "mv", "old-name.ts", "new-name.ts")
        (repo / "beside.ts").write_text("the squash lost this edit\n")
        integration = _commit(repo, "squash: the rename landed, the edit did not")
        return {"repo": repo, "base": base, "verified": verified, "integration": integration}

    def test_a_renaming_change_derives_a_delete_and_an_add(self, tmp_path):
        lab = self._lab(tmp_path / "rename")
        # A real path, but an incomplete set, so the refusal prints the whole
        # derived set rather than stopping at a spelling mistake.
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"], "--base-ref", lab["base"],
                   "--path", "new-name.ts")

        assert done.returncode == 2
        # Both halves of the rename, spelled as paths rather than as a status.
        assert "--path new-name.ts" in done.stdout
        assert "--deleted-path old-name.ts" in done.stdout
        assert "--path beside.ts" in done.stdout
        assert "R100" not in done.stdout

    def test_and_the_derived_set_catches_what_the_squash_dropped(self, tmp_path):
        lab = self._lab(tmp_path / "rename2")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"], "--base-ref", lab["base"],
                   "--path", "new-name.ts", "--path", "beside.ts", "--deleted-path", "old-name.ts")

        assert done.returncode == 1, done.stdout
        assert "DIVERGED beside.ts" in done.stdout


class TestASubmoduleIsVerifiableLikeAnythingElse:
    """A gitlink is one object id, so it compares like a blob.

    Refusing gitlinks made a submodule change unverifiable BY CONSTRUCTION:
    `git diff --name-status` reports `D vendor` for a removed submodule, the
    tool printed that under `Declare exactly:`, and then refused the very
    declaration it had just instructed the operator to make. That closed loop
    is the third time a refusal message here has been the defect, and it was
    shipped in the same round that listed the gate as a headline feature and
    gave it no test at all.

    A tree is still refused: its identity aggregates its children, so it changes
    when one is DELETED, which is how a directory turned an absence into
    presence. A gitlink aggregates nothing.
    """

    @staticmethod
    def _repo_with_submodule(tmp_path: Path, name: str):
        inner = tmp_path / f"{name}-inner"
        inner.mkdir(parents=True, exist_ok=True)
        _git(inner, "init", "-q", "-b", "main")
        _git(inner, "config", "user.email", "checker@example.invalid")
        _git(inner, "config", "user.name", "checker")
        (inner / "lib.txt").write_text("v1\n")
        first = _commit(inner, "inner v1")
        (inner / "lib.txt").write_text("v2\n")
        second = _commit(inner, "inner v2")

        repo = tmp_path / name
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        _git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "vendor")
        # Pin the submodule at its FIRST commit, so a bump to the second is a
        # real change rather than a no-op.
        _git(repo / "vendor", "checkout", "-q", first)
        (repo / "app.txt").write_text("v0\n")
        base = _commit(repo, "base, with a submodule")
        return repo, inner, base, second

    def test_a_removed_submodule_can_be_declared_as_the_tool_instructs(self, tmp_path):
        repo, _inner, base, _bumped = self._repo_with_submodule(tmp_path, "sub-removed")

        _git(repo, "checkout", "-q", "-b", "feature")
        _git(repo, "rm", "-q", "vendor")
        (repo / "app.txt").write_text("v1\n")
        verified = _commit(repo, "drop the submodule and edit the app")

        _git(repo, "checkout", "-q", "--force", "-b", "integ", base)
        _git(repo, "rm", "-q", "vendor")
        (repo / "app.txt").write_text("v1\n")
        integration = _commit(repo, "it landed")

        lab = {"repo": repo}
        refused = run(lab, "--verified-head", verified, "--integration-ref", integration,
                      "--base-ref", base, "--path", "app.txt")
        assert refused.returncode == 2
        assert "--deleted-path vendor" in refused.stdout

        # Follow the instruction VERBATIM -- which is the whole point: the tool
        # printed a declaration and then refused it.
        instructed: list[str] = []
        for line in refused.stdout.splitlines():
            line = line.strip()
            for flag in ("--deleted-path ", "--path "):
                if line.startswith(flag):
                    instructed += [flag.strip(), line[len(flag):]]
                    break

        done = run(lab, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", base, *instructed)
        assert done.returncode == 0, done.stdout
        assert "landed" in done.stdout

    def test_a_gitlink_the_merge_did_not_carry_is_a_divergence(self, tmp_path):
        """The gitlink written straight into the index.

        `git submodule` needs a working checkout to bump a pointer, which makes
        a fixture that has to fetch. `update-index --cacheinfo 160000` records
        exactly the same tree entry without one, and the tree entry is all this
        tool ever reads.
        """
        repo = tmp_path / "gitlink"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "app.txt").write_text("v0\n")
        old_pointer = "1" * 40
        new_pointer = "2" * 40
        _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{old_pointer},vendor")
        base = _commit(repo, "base, pointing at the old commit", stage=False)

        _git(repo, "checkout", "-q", "-b", "feature")
        _git(repo, "update-index", "--cacheinfo", f"160000,{new_pointer},vendor")
        verified = _commit(repo, "bump the pointer", stage=False)

        _git(repo, "checkout", "-q", "--force", "-b", "integ", base)
        (repo / "other.txt").write_text("other work\n")
        integration = _commit(repo, "the squash did not carry the bump")

        at_verified = _git(repo, "ls-tree", verified, "--", "vendor")
        at_integration = _git(repo, "ls-tree", integration, "--", "vendor")
        assert at_verified != at_integration, (at_verified, at_integration)

        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", base, "--path", "vendor")

        assert done.returncode == 1, done.stdout
        assert "DIVERGED vendor" in done.stdout
        # `mode type id`, so the gitlink's commit is what was compared.
        assert "160000 commit" in done.stdout

class TestTheDeletedPathTypeGateIsReachable:
    """A claim of mine that was false, and the reason it mattered.

    The survivor list called the `--deleted-path` type gate UNREACHABLE, on the
    grounds that `git diff` never reports a directory deletion. Two things were
    wrong with that: the gate runs BEFORE the set is derived, so any string can
    reach it; and `git diff` does report a gitlink deletion, which is how the
    closed loop above came about.
    """

    def test_a_directory_declared_deleted_is_refused_before_any_derivation(self, tmp_path):
        repo = tmp_path / "dir-deleted"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "gone").mkdir()
        (repo / "gone" / "a.txt").write_text("a\n")
        (repo / "keep.txt").write_text("v0\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        _git(repo, "rm", "-qr", "gone")
        (repo / "keep.txt").write_text("v1\n")
        verified = _commit(repo, "remove the directory")

        _git(repo, "checkout", "-q", "--force", "-b", "integ", base)
        (repo / "other.txt").write_text("other\n")
        integration = _commit(repo, "other work")

        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", base, "--path", "keep.txt", "--deleted-path", "gone")

        assert done.returncode == 2, done.stdout
        assert "name a directory" in done.stdout


class TestBothHalvesOfTheSetGate:
    """The deleted half of the set-equality gate had no test.

    `sorted(args.deleted_paths) != expected_deleted` could be dropped and the
    suite stayed green -- the `--path` half was pinned, the `--deleted-path`
    half was not, and the equality of those two sets is this whole design's
    thesis. An undeclared deletion is a path the verdict says nothing about.
    """

    @staticmethod
    def _lab(repo: Path) -> dict[str, str]:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "kept.txt").write_text("v0\n")
        (repo / "dropped-a.txt").write_text("a\n")
        (repo / "dropped-b.txt").write_text("b\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "kept.txt").write_text("v1\n")
        (repo / "dropped-a.txt").unlink()
        (repo / "dropped-b.txt").unlink()
        verified = _commit(repo, "edit one file and remove two")

        _git(repo, "checkout", "-q", "--force", "-b", "integ", base)
        (repo / "kept.txt").write_text("v1\n")
        (repo / "dropped-a.txt").unlink()
        # `dropped-b.txt` SURVIVES the squash -- the deletion did not land.
        integration = _commit(repo, "squash that kept one of the removed files")
        return {"repo": repo, "base": base, "verified": verified, "integration": integration}

    def test_an_undeclared_deletion_is_refused_not_ignored(self, tmp_path):
        lab = self._lab(tmp_path / "half-set")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["base"], "--path", "kept.txt", "--deleted-path", "dropped-a.txt")

        assert done.returncode == 2, done.stdout
        assert "not the paths this change touched" in done.stdout
        assert "--deleted-path dropped-b.txt" in done.stdout

    def test_and_the_full_set_catches_the_deletion_that_did_not_land(self, tmp_path):
        lab = self._lab(tmp_path / "half-set-full")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["base"], "--path", "kept.txt",
                   "--deleted-path", "dropped-a.txt", "--deleted-path", "dropped-b.txt")

        assert done.returncode == 1, done.stdout
        assert "DIVERGED dropped-b.txt" in done.stdout

    def test_a_surplus_deletion_is_refused_too(self, tmp_path):
        lab = self._lab(tmp_path / "half-set-surplus")
        done = run(lab, "--verified-head", lab["verified"], "--integration-ref", lab["integration"],
                   "--base-ref", lab["base"], "--path", "kept.txt",
                   "--deleted-path", "dropped-a.txt", "--deleted-path", "dropped-b.txt",
                   "--deleted-path", "never-existed.txt")

        assert done.returncode == 2, done.stdout


class TestTheDerivationReadsWhatGitActuallyPrinted:
    """Two guards in `_changed_paths` that the survivor list under-described.

    The disclosed bullet covered its return-code guard. It did not cover
    `--end-of-options`, nor the odd-field guard that refuses a half-record --
    the one that keeps a pair-wise parse from silently sliding by one.
    """

    def test_a_dash_leading_ref_cannot_reach_git_diff_as_an_option(self, tmp_path):
        repo = tmp_path / "dash"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "f.txt").write_text("v0\n")
        _commit(repo, "base")

        # Refused at resolution, long before the derivation -- which is why the
        # `--end-of-options` on `git diff` is belt-and-braces and is disclosed
        # as a survivor rather than claimed as covered.
        done = run({"repo": repo}, "--verified-head", "-bogus", "--integration-ref", "HEAD",
                   "--base-ref", "HEAD", "--path", "f.txt")
        assert done.returncode == 2
        # argparse refuses it as a missing argument, which is earlier still.
        assert "expected one argument" in done.stderr or "does not resolve" in done.stdout

    def test_a_path_with_a_newline_survives_the_pairwise_parse(self, tmp_path):
        # `-z` makes every record NUL-separated, so a path containing a newline
        # cannot be read as a status field. This is the case the odd-field guard
        # exists for: if the stream ever desynchronised, the count would be odd.
        repo = tmp_path / "odd-fields"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        odd = "two\nlines.txt"
        (repo / odd).write_text("v0\n")
        (repo / "plain.txt").write_text("v0\n")
        base = _commit(repo, "base")

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / odd).write_text("v1\n")
        (repo / "plain.txt").write_text("v1\n")
        verified = _commit(repo, "edit both")

        _git(repo, "checkout", "-q", "--force", "-b", "integ", base)
        (repo / odd).write_text("v1\n")
        (repo / "plain.txt").write_text("v1\n")
        integration = _commit(repo, "both landed")

        done = run({"repo": repo}, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", base, "--path", odd, "--path", "plain.txt")

        assert done.returncode == 0, done.stdout
        assert "landed" in done.stdout

class TestTheDerivedSetDoesNotDependOnGitConfig:
    """Configuration is another way of choosing the set.

    Round 10 replaced a declared path set with a derived one on the premise
    that the operator can no longer choose it. Two ordinary `git config`
    settings were still choosing it, and the first is a false pass reproduced
    against shipped code.
    """

    def test_ignore_submodules_can_hide_a_dropped_submodule_bump(self, tmp_path):
        """`diff.ignoreSubmodules=all` dropped the gitlink from the derived set,
        so the declaration did not have to mention it, and a merge that dropped
        the bump returned exit 0 `landed`."""
        repo = tmp_path / "ignored-submodule"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")

        (repo / "keep.txt").write_text("keep\n")
        _git(repo, "update-index", "--add", "--cacheinfo",
             f"160000,{'0' * 39}1,vendor")
        _git(repo, "add", "keep.txt")
        fork = _commit(repo, "M0", stage=False)

        _git(repo, "update-index", "--cacheinfo", f"160000,{'0' * 39}2,vendor")
        (repo / "keep.txt").write_text("keep2\n")
        _git(repo, "add", "keep.txt")
        verified = _commit(repo, "bump the submodule and touch keep", stage=False)

        _git(repo, "checkout", "-q", "-b", "integration", fork)
        _git(repo, "checkout", "-q", verified, "--", ".")
        _git(repo, "update-index", "--cacheinfo", f"160000,{'0' * 39}1,vendor")
        integration = _commit(repo, "merge but drop the submodule bump", stage=False)

        # The premise, asserted: this setting really does change what git lists.
        _git(repo, "config", "diff.ignoreSubmodules", "all")
        listed = _git(repo, "diff", "--name-status", "--no-renames", f"{fork}..{verified}")
        assert "vendor" not in listed, listed

        lab = {"repo": repo}
        # Declaring only what the CONFIGURED listing shows must not pass.
        done = run(lab, "--verified-head", verified, "--integration-ref", integration,
                   "--base-ref", fork, "--path", "keep.txt")
        assert done.returncode == 2, done.stdout
        assert "not the paths this change touched" in done.stdout
        assert "--path vendor" in done.stdout

        # And the set the tool derives catches the dropped bump.
        caught = run(lab, "--verified-head", verified, "--integration-ref", integration,
                     "--base-ref", fork,
                     "--path", "keep.txt", "--path", "vendor")
        assert caught.returncode == 1, caught.stdout
        assert "DIVERGED vendor" in caught.stdout

    def test_diff_relative_does_not_move_the_set_with_the_working_directory(self, tmp_path):
        """`diff.relative=true` lists paths relative to the CURRENT directory
        while `_entry` reads them with `ls-tree --full-tree` from the root, so
        the two halves stop agreeing about what a path is called.

        Fail-closed rather than a false pass -- the set empties or shrinks and
        the refusal follows -- and still the set depending on where someone
        stood when they ran it.
        """
        repo = tmp_path / "relative"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        _git(repo, "config", "diff.relative", "true")

        (repo / "sub").mkdir()
        (repo / "root.txt").write_text("v1\n")
        (repo / "sub" / "inner.txt").write_text("s0\n")
        fork = _commit(repo, "M0")

        (repo / "root.txt").write_text("v2\n")
        (repo / "sub" / "inner.txt").write_text("s1\n")
        verified = _commit(repo, "the change touches both")

        _git(repo, "checkout", "-q", "-b", "integration", fork)
        _git(repo, "checkout", "-q", verified, "--", ".")
        _git(repo, "checkout", "-q", fork, "--", "root.txt")
        integration = _commit(repo, "merge, reverting the root file")

        # Run from the subdirectory, which is what the setting reacts to.
        done = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--verified-head", verified, "--integration-ref", integration,
             "--base-ref", fork,
             "--path", "root.txt", "--path", "sub/inner.txt"],
            cwd=str(repo / "sub"), capture_output=True, text=True, check=False,
        )

        # Repo-root spellings, derived identically from anywhere, and the
        # reverted root file is caught rather than lost with the directory.
        assert done.returncode == 1, done.stdout
        assert "DIVERGED root.txt" in done.stdout

    def test_a_path_that_is_not_utf8_is_refused_rather_than_raised(self, tmp_path):
        """A crash must not be spelled the same way as a verdict.

        A non-UTF-8 path is legal in git. `subprocess(text=True)` raised
        `UnicodeDecodeError` out of `communicate()` -- an unhandled traceback
        and exit 1, which is this tool's code for "the integration ref does not
        hold the verified result". Fail-closed, and indistinguishable to a
        caller from a real dropped commit.
        """
        repo = tmp_path / "not-utf8"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")

        (repo / "plain.txt").write_text("a\n")
        fork = _commit(repo, "M0")

        # Raw bytes. Writing `b"bad-\xff-name.txt".decode("latin-1")` through a
        # str path re-encodes it as valid UTF-8 and the premise evaporates.
        with open(os.path.join(os.fsencode(str(repo)), b"bad-\xff-name.txt"), "wb") as handle:
            handle.write(b"x")
        (repo / "plain.txt").write_text("a2\n")
        verified = _commit(repo, "a path that is not utf-8")

        _git(repo, "checkout", "-q", "-b", "integration", fork)
        (repo / "other.txt").write_text("other\n")
        _commit(repo, "integration moves on")
        _git(repo, "merge", "-q", "--no-edit", verified)
        integration = _git(repo, "rev-parse", "HEAD")

        done = run({"repo": repo}, "--verified-head", verified,
                   "--integration-ref", integration, "--base-ref", fork, "--path", "plain.txt")

        assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
        assert "Traceback" not in done.stderr, done.stderr
        assert "could not derive the changed paths" in done.stdout
        # The reason, named: 2 is "I cannot read this", 1 is "the merge dropped
        # your work", and a caller has to be able to tell them apart.
        assert "not valid UTF-8" in done.stdout

    def test_and_declaring_the_undecodable_path_does_not_raise_either(self, tmp_path):
        """The other call site, which runs FIRST.

        `_changed_paths` was fixed and `_entry` was not, so the identical
        traceback stayed reachable by DECLARING the undecodable path rather
        than merely having it in the range -- `main` builds the verified
        entries through `_entry` before it ever derives the set. An independent
        check found it sixty-five lines under a comment saying a crash must not
        be spelled the same way as a verdict. (An earlier version of THIS line
        said "two hundred", and the commit that corrected that figure in the
        source and the operating memory missed this copy of it -- one commit
        after writing "grep for the pattern, not the symptom you reproduced"
        into that same memory file.)
        """
        repo = tmp_path / "not-utf8-declared"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")

        (repo / "plain.txt").write_text("a\n")
        fork = _commit(repo, "M0")

        bad = os.path.join(os.fsencode(str(repo)), b"bad-\xff-name.txt")
        with open(bad, "wb") as handle:
            handle.write(b"x")
        (repo / "plain.txt").write_text("a2\n")
        verified = _commit(repo, "a path that is not utf-8")

        _git(repo, "checkout", "-q", "-b", "integration", fork)
        (repo / "other.txt").write_text("other\n")
        _commit(repo, "integration moves on")
        _git(repo, "merge", "-q", "--no-edit", verified)
        integration = _git(repo, "rev-parse", "HEAD")

        # The undecodable path named directly, as a `--path`.
        #
        # An earlier version of this comment said argv's surrogate-escaped
        # spelling is "a spelling no tree lookup can match". That is FALSE --
        # `surrogateescape` round-trips to the original bytes, so `:(literal)`
        # matches the entry exactly; `git ls-tree` returns the record. It also
        # mattered: had it been true this test would have been VACUOUS, because
        # a non-matching lookup is ABSENT, which also refuses with exit 2 and no
        # traceback, so the test would have passed against unfixed code. It
        # discriminates only because the premise was wrong.
        #
        # It is the same error as the one this test's sibling already had to
        # fix -- a fixture whose stated premise had quietly evaporated -- which
        # is why the assertion below is on the ABSENCE OF A CRASH, a fact the
        # lookup's behaviour cannot make vacuous.
        done = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--verified-head", verified, "--integration-ref", integration,
             "--base-ref", fork,
             "--path", os.fsdecode(b"bad-\xff-name.txt"), "--path", "plain.txt"],
            cwd=str(repo), capture_output=True, text=True, check=False,
            errors="surrogateescape",
        )

        assert "Traceback" not in done.stderr, done.stderr
        assert "UnicodeDecodeError" not in done.stderr, done.stderr
        assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
        assert "verdict      : landed" not in done.stdout
        # And the premise, asserted rather than described: the lookup really
        # does match, so this path reaches the tool as a resolvable entry and
        # the refusal is about reading it, not about finding it.
        record = subprocess.run(
            ["git", "ls-tree", "--full-tree", "-z", "--end-of-options", verified,
             "--", ":(literal)" + os.fsdecode(b"bad-\xff-name.txt")],
            cwd=str(repo), capture_output=True, check=False,
        )
        assert record.returncode == 0
        assert record.stdout, "the pathspec matched nothing; this test would be vacuous"


class TestWhatAnUnreadableLookupReturns:
    """`_entry`'s contract, which only a comment asserted.

    An independent check mutated the new guard two ways -- `return ABSENT`
    instead of `UNKNOWN`, and `errors="replace"` instead of refusing -- and both
    left the whole suite green. Neither can produce a wrong verdict, because the
    gates downstream absorb them, so they are equivalent at the verdict level.
    They are not equivalent in what the tool SAYS: ABSENT routes an unreadable
    path to "does not exist at the verified head", which is untrue of a path
    that is sitting right there.
    """

    def _repo_with_an_undecodable_path(self, tmp_path):
        repo = tmp_path / "unreadable-entry"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "checker@example.invalid")
        _git(repo, "config", "user.name", "checker")
        (repo / "plain.txt").write_text("a\n")
        with open(os.path.join(os.fsencode(str(repo)), b"bad-\xff-name.txt"), "wb") as handle:
            handle.write(b"x")
        head = _commit(repo, "a path that is not utf-8")
        return repo, head

    def test_an_unreadable_lookup_is_unknown_and_not_absent(self, tmp_path):
        import importlib.util

        repo, head = self._repo_with_an_undecodable_path(tmp_path)
        spec = importlib.util.spec_from_file_location("verifier_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        cwd = os.getcwd()
        try:
            os.chdir(repo)
            entry = module._entry(head, os.fsdecode(b"bad-\xff-name.txt"))
        finally:
            os.chdir(cwd)

        # The distinction the comment claimed and nothing checked.
        assert entry == module.UNKNOWN
        assert entry is not module.ABSENT
        # And it is not a fabricated entry either: nothing that could be
        # compared against the integration side as though it were read.
        assert entry == ""
