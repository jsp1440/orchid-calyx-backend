#!/usr/bin/env python3
"""Prove a merge landed the verified result, from a real checkout.

Usage, run immediately after an integration merge:

    python3 scripts/oc_verify_merge_landed.py \\
        --verified-head 4efa379 \\
        --integration-ref origin/oc-autonomous-integration \\
        --path src/lib/cognitiveIntegration.ts \\
        --path src/components/calyx/ReasoningMapPanel.tsx

Exit status is the point:

    0  the integration ref holds the verified content at every declared path
    1  it does not (`tree_mismatch`), the comparison was inconclusive
       (`evidence_incomplete`), or the merge was never reported
       (`merge_not_reported`) -- in every case, stop the merge lane
    2  an argument or ref was refused before anything was compared

so a lane that pipes this into `&&` stops on missing evidence rather than
sailing past it. The three exit codes are distinct on purpose: a corrupted merge
and a mistyped invocation are different problems and a lane must not confuse
them.

Every declared path must carry positive evidence on the verified side, because
absence is not evidence and comparing "not there" with "not there" is how a
vacuous pass is manufactured. So:

* `--path P` must resolve at the verified head.
* `--deleted-path P` must resolve at every pre-change revision (see below),
  which is what makes it a deletion rather than a name nobody ever used.
  `--all`, because a criss-cross history has more than one base and a gate whose
  answer turns on which one git's tie-break prints is not a gate.

**Only a path this change could have altered is evidence.** Three ways to fail
that, and all three have been live in this tool:

* Absence is symmetric, so a declared set made only of deletions is
  `evidence_incomplete`, never `landed`. Two lineages that both lack a file agree
  about it for reasons that have nothing to do with this merge.
* Identity is equally symmetric when it predates the change. A file untouched by
  the change is identical at the pre-change revision and on both sides, so
  declaring it satisfies any "declare a surviving path" rule while witnessing
  nothing.
* A directory is neither. `git ls-tree <ref> -- :(literal)src/lib` returns one
  record, `040000 tree <sha> src/lib`, whose identity changes when a child is
  DELETED -- so a directory turns absence into presence and walks past both of
  the rules above. Only files are accepted.

So at least one `--path` must resolve unambiguously at every pre-change revision
and differ from it there -- an unresolved lookup is not a difference. A change
that only removes files cannot be verified here at all, and this says so rather
than sending you to find a path that makes the check pass.

The pre-change revision is normally `git merge-base --all <verified-head>
<integration-ref>`. When the verified head is already an ancestor of the
integration ref -- an ordinary merge or a fast-forward -- that base IS the
verified head, and a revision cannot be the pre-change state of a change it
already contains. Pass `--base-ref <the branch the change forked off>` and it is
derived from there instead.

`--base-ref` alone is not enough, and an earlier version of this paragraph said
it was. A merge base is the fork point only while the base branch carries NO
commit of this change. Once it carries one -- an earlier partial merge of the
same lineage, a cherry-pick, a branch merged from behind its head -- the merge
base is a commit INSIDE the change, the derived set is that change's tail, and
every path the change touched earlier is dropped while the tool states as fact
that the change "does not touch" them. So `--fork-point` is required: the commit
this change forked FROM, read from a record made BEFORE the base branch moved --
the pull request's own recorded base sha is the usual source. When it and the
merge base disagree, the tool says so and derives from the fork point.

Containment is NOT an answer to this, and an earlier version of this tool
treating it as one is how the class reopened. It proves the COMMIT is in the
history; it says nothing about the resulting tree. `git merge -s ours` makes the
verified head a parent and lands not one byte of it. So does `-X ours` on a real
conflict, and so does a merge followed by a commit reverting it. All three were
reported as `landed` for an untouched declared path.

`--base-ref` is a ref used to DERIVE which paths are probative, validated before
it is used: it must resolve, it must share an ancestor with the verified head,
and it must not already contain the verified head. It is not a verdict and not
an assertion that anything landed. What it cannot do is stop you naming a
needlessly distant base; like `--integration-ref`, it is only as honest as the
person running this, which is why the paths are derived mechanically.

Paths are compared as `mode type id`, not blob id alone, so a file that becomes
a symlink or gains the executable bit without changing a byte is a divergence
rather than a match.

Both refs are resolved with `--verify --quiet --end-of-options` before anything
is compared, so an unresolvable ref -- including one beginning with `-`, which bare
`rev-parse` echoes back verbatim with status 0 -- is an evidence failure rather
than a pair of matching nonsense strings.

Scope, stated plainly: this proves the integration side holds what was verified
at the declared paths, and only those. It says nothing about content the merge
*added* at paths nobody declared, and nothing about paths the caller forgot --
derive the set mechanically with
`git diff --name-status <fork-point>..<verified-head>` rather than by hand, and
note `<fork-point>` rather than `<merge-base>`: see above for why they are not
the same commit once the base branch has absorbed part of the change. It is built for the dropped-commit failure class of #706,
not for injection.

Collecting the evidence is a handful of read-only `git rev-parse`, `merge-base`
and `ls-tree` calls. That is the whole
cost of the check that would have caught #706 in seconds. No provider, no
network beyond whatever fetch the caller already did.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calyx_orchestrator.merge_integrity import (
    UNKNOWN,
    IntegrationResult,
    MergeVerdict,
    VerifiedResult,
    inspect_merge,
    may_report_integrated,
    restoration_paths,
)

ABSENT = None


def _rev_parse(rev: str) -> tuple[int, str]:
    """Resolve one revision. `--verify` rejects what `--end-of-options` protects.

    Bare `git rev-parse -bogus` prints `-bogus` and exits 0, so without these two
    flags any ref beginning with a dash resolves to itself on both sides and
    compares equal.
    """
    done = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "--end-of-options", rev],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout.strip()


def _merge_bases(left: str, right: str) -> tuple[int, list[str]]:
    """Every common ancestor of two commits.

    `--all`, because a criss-cross history has more than one and bare
    `merge-base` prints whichever git's tie-break picks. A deletion gate whose
    answer depends on that is not a gate.

    Both arguments are 40-hex ids `_resolve_ref` has already produced, so neither
    can be read as an option and no `--end-of-options` is needed to say so.
    """
    done = subprocess.run(
        ["git", "merge-base", "--all", left, right], capture_output=True, text=True, check=False
    )
    return done.returncode, [line.strip() for line in done.stdout.splitlines() if line.strip()]


def _changed_paths(base: str, head: str) -> tuple[int, dict[str, str]]:
    """Every path that differs between `base` and `head`, with its status.

    This is the set the operator was being asked to declare by hand, and the
    reason a hand-declared set was never safe: the tool can derive it, so a
    declaration that disagrees with it is a declaration the tool can refuse.

    `-z` because a status record and its path are NUL-separated here; a rename
    carries two paths, so the fields are consumed as a stream rather than split
    per line. It also turns off `core.quotePath`, so a non-ASCII path arrives as
    its bytes rather than as an escaped spelling nothing else here would match.

    EVERY option that decides WHICH paths are listed is passed explicitly, and
    none is left to `git config`. Round 10 replaced a declared set with a derived
    one on the premise that the operator can no longer choose it. Configuration
    is another way of choosing, and two settings a person may perfectly
    reasonably have set were changing the answer:

    * `diff.ignoreSubmodules=all` drops gitlinks from the listing. The derived
      set then omits a submodule the change bumped, so the declaration need not
      mention it, and a merge that dropped the bump reported `landed` with exit
      0. Reproduced against shipped code. `--ignore-submodules=none` says so
      outright.
    * `diff.relative=true` makes the listing relative to the CURRENT DIRECTORY,
      while `_entry` reads paths with `ls-tree --full-tree` from the repository
      root. Run from a subdirectory the two halves then disagree about what a
      path is called -- the derived set empties out, or shrinks to the paths
      under that directory. That is fail-closed rather than a false pass, and it
      is still the set depending on where someone stood. `--no-relative`.

    `--no-renames` was already explicit for the same reason, and is the reason to
    look for the rest: one option pinned against config while its neighbours are
    not is a rule that holds by luck.
    """
    # Bytes, decoded here rather than by `subprocess`. A path that is not UTF-8
    # is legal in git, and `text=True` raised `UnicodeDecodeError` out of
    # `communicate()` -- an unhandled traceback and exit 1, which is this tool's
    # code for "the integration ref does not hold the verified result". A crash
    # must not be spelled the same way as a verdict, even a refusing one.
    done = subprocess.run(
        [
            "git", "diff", "--name-status", "--no-renames", "--no-relative",
            "--ignore-submodules=none", "-z", "--end-of-options", f"{base}..{head}",
        ],
        capture_output=True, check=False,
    )
    if done.returncode != 0:
        return done.returncode, {}
    try:
        stdout = done.stdout.decode("utf-8")
    except UnicodeDecodeError:
        # 2, not 1: this is an evidence failure, and the caller must be able to
        # tell "I cannot read this" from "the merge dropped your work".
        return 2, {}
    fields = [field for field in stdout.split("\0") if field]
    changed: dict[str, str] = {}
    index = 0
    while index + 1 < len(fields) + 1 and index < len(fields):
        status = fields[index]
        if index + 1 >= len(fields):
            return 1, {}
        changed[fields[index + 1]] = status[0]
        index += 2
    return 0, changed


def _is_ancestor(maybe_ancestor: str, descendant: str) -> bool:
    """Whether the first commit is reachable from the second.

    Both arguments are 40-hex ids `_resolve_ref` has already produced, so neither
    can be read as an option.
    """
    done = subprocess.run(
        ["git", "merge-base", "--is-ancestor", maybe_ancestor, descendant],
        capture_output=True, text=True, check=False,
    )
    return done.returncode == 0


def _resolve_ref(label: str, ref: str) -> tuple[str, str] | None:
    """The commit and tree ids for `ref`, or None with a message already printed."""
    commit_rc, commit = _rev_parse(f"{ref}^{{commit}}")
    tree_rc, tree = _rev_parse(f"{ref}^{{tree}}")
    if commit_rc != 0 or tree_rc != 0 or not commit or not tree:
        print(f"REFUSED: {label} {ref!r} does not resolve to a commit in this checkout")
        return None
    return commit, tree


def _entry(ref: str, path: str) -> str | None:
    """`mode type id` at `ref:path`; ABSENT when the path is not there.

    Mode and type are part of the identity on purpose. A regular file replaced
    by a symlink to the path it used to contain, or one that gains the
    executable bit, keeps its blob id exactly -- comparing ids alone would call
    that the verified result.

    A pathspec is passed as `:(literal)` so a `*` in a path cannot widen the
    match. An empty output is a real answer: the path is not in that tree.
    Anything else is genuinely unresolved and becomes UNKNOWN, which
    `inspect_merge` refuses to treat as agreement.
    """
    done = subprocess.run(
        ["git", "ls-tree", "--full-tree", "-z", "--end-of-options", ref, "--", f":(literal){path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        return UNKNOWN
    records = [record for record in done.stdout.split("\0") if record]
    if not records:
        return ABSENT
    if len(records) != 1:
        return UNKNOWN
    mode, _, rest = records[0].partition(" ")
    kind, _, rest = rest.partition(" ")
    object_id = rest.split("\t", 1)[0].strip()
    if not mode or not kind or not object_id:
        return UNKNOWN
    return f"{mode} {kind} {object_id}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified-head", required=True)
    parser.add_argument("--integration-ref", required=True)
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        dest="paths",
        help="a path the change touched and that exists at the verified head; repeat per path",
    )
    parser.add_argument(
        "--deleted-path",
        action="append",
        default=[],
        dest="deleted_paths",
        help="a path the change removed; it must exist at the merge base and be absent after the merge",
    )
    parser.add_argument(
        "--base-ref",
        default=None,
        help=(
            "the branch this change forked off, e.g. the pull request's base. Required when "
            "the verified head is already an ancestor of --integration-ref, because their "
            "merge base is then the verified head and cannot say which paths the change touched"
        ),
    )
    parser.add_argument(
        "--fork-point",
        default=None,
        help=(
            "the commit this change forked FROM, taken from a record made before the "
            "base branch moved -- the pull request's own recorded base sha is the usual "
            "source. Required, because the merge base of --verified-head and --base-ref "
            "is NOT the fork point once the base branch has absorbed part of this change"
        ),
    )
    parser.add_argument(
        "--merge-reported-success",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="whether the merge API returned success (default: yes)",
    )
    args = parser.parse_args(argv)

    declared = [*args.paths, *args.deleted_paths]
    if not declared:
        # Refusing here rather than passing vacuously: "no paths given" is the
        # shape of evidence that let #706 through.
        print("REFUSED: no --path or --deleted-path given, so there is nothing to verify")
        return 2
    if len(set(declared)) != len(declared):
        print("REFUSED: a path was declared twice, or declared both present and deleted")
        return 2

    verified_ids = _resolve_ref("--verified-head", args.verified_head)
    integration_ids = _resolve_ref("--integration-ref", args.integration_ref)
    if verified_ids is None or integration_ids is None:
        return 2

    if verified_ids[0] == integration_ids[0]:
        print("REFUSED: --verified-head and --integration-ref are the same commit,")
        print("so the comparison is a tautology rather than evidence that a merge landed.")
        return 2

    verified_entries = {path: _entry(args.verified_head, path) for path in declared}

    # Every declared path must carry positive evidence on the verified side.
    # Absence is not evidence: comparing "not there" with "not there" reports
    # agreement on a comparison that never happened, which is how each of this
    # tool's false passes has been manufactured.
    missing = [path for path in args.paths if verified_entries[path] in (ABSENT, UNKNOWN)]
    if missing:
        print("REFUSED: these --path arguments do not exist at the verified head:")
        for path in missing:
            print(f"  {path}")
        print("Correct the spelling. You do not need to work the set out yourself: declare")
        print("anything real and this tool prints the exact set it derived, which is also")
        print("the only set it accepts.")
        return 2
    # `git ls-tree <ref> -- :(literal)src/lib` returns ONE record,
    # `040000 tree <sha> src/lib`, so a directory looked like present evidence
    # whose identity changed because a child was DELETED. That let a pure
    # deletion -- which this tool refuses outright -- be certified by declaring
    # its parent directory, and let `--path src/lib` pass the very squash that
    # `--path src/lib/` was fixed to catch. Only files can witness content.
    def _is_tree(entry: str | None) -> bool:
        # UNKNOWN is the empty string, which splits to one field, not three.
        fields = entry.split(" ") if isinstance(entry, str) else []
        return len(fields) == 3 and fields[1] == "tree"

    def _kind(entry: str | None) -> str:
        fields = entry.split(" ") if isinstance(entry, str) else []
        return fields[1] if len(fields) == 3 else ""

    # Only a TREE is refused. Its identity aggregates its children, so it
    # changes when one is DELETED -- that is how a directory turned an absence
    # into presence. A gitlink aggregates nothing: `160000 commit <sha>` is a
    # single object id and compares exactly like a blob, so a submodule bump is
    # real, comparable content. Refusing it made a submodule change
    # unverifiable by construction.
    directories = [path for path in args.paths if _kind(verified_entries[path]) == "tree"]
    if directories:
        print("REFUSED: these arguments name a directory, which cannot witness content:")
        for path in directories:
            print(f"  {path}")
        print("A tree's identity changes when any child changes, including when one is")
        print("deleted, so a directory turns an absence into presence. Declare the files.")
        return 2

    still_present = [path for path in args.deleted_paths if verified_entries[path] is not ABSENT]
    if still_present:
        print("REFUSED: these --deleted-path arguments still exist at the verified head:")
        for path in still_present:
            print(f"  {path}")
        return 2

    # A deletion is only a deletion if the file was there to delete. Without
    # this the flag is a way to declare any string, including a typo, and have
    # its absence on both sides read as agreement.
    # Unconditionally, not only when a deletion is declared: without it the tool
    # never establishes any relationship between the two refs and will report
    # `landed` for a pair with no common ancestor, between which no merge can
    # have happened at all.
    code, bases = _merge_bases(verified_ids[0], integration_ids[0])
    if code != 0 or not bases:
        print("REFUSED: --verified-head and --integration-ref share no common ancestor,")
        print("so no merge between them can have happened and there is nothing to verify.")
        return 2

    # Which revision represents the state BEFORE this change. Normally that is
    # the merge base of the two refs. But when the verified head is already an
    # ancestor of the integration ref -- an ordinary merge or a fast-forward --
    # the merge base IS the verified head, and a revision cannot be the
    # pre-change state of a change it already contains.
    #
    # Round 7 handled that by treating containment as sufficient on its own and
    # skipping the probative check, on the stated grounds that "containment is
    # stronger evidence than any comparison". That was false, and it reopened
    # the class. Containment proves the COMMIT is in the history; it proves
    # nothing about the resulting tree. `git merge -s ours` makes the verified
    # head a parent and lands not one byte of it, and the tool reported
    # `landed` for an untouched path. So did `-X ours`, and so did a merge
    # followed by a commit reverting it.
    #
    # There is no way to derive the pre-change revision from these two refs
    # alone in that case, so the caller names the branch the change forked off
    # and the tool refuses until they do. That is a REF used to derive which
    # paths are probative, checked before it is used -- not a verdict, and not
    # an assertion that anything landed.
    # WHERE THE CHANGE FORKED FROM IS NOT DERIVABLE FROM THESE TWO REFS.
    #
    # `merge-base(verified, integration)` is an ancestor of the verified head.
    # So is every commit of the change itself. Nothing distinguishes the fork
    # point from a commit INSIDE the change without knowing the branch the
    # change forked off -- and when the integration ref descends from an
    # intermediate commit of the change, which is exactly what happens when a
    # branch is merged from a commit behind its head, the merge base IS that
    # intermediate commit. The derived set then shrinks to the tail of the
    # change, and the tool refuses the very path that would catch the
    # regression, stating as fact that the change "does not touch" it.
    #
    # Round 9 reasoned only about a base named further BACK than the fork
    # point -- "it does not shrink the derived set, it grows it" -- which is
    # true and answers the wrong direction. A base forward of the fork point
    # shrinks it, and shrinking is what hides a regression.
    #
    # So `--base-ref` is required. Refusing every ancestor of the verified head
    # was tried and is wrong: a base branch that has not moved since the fork IS
    # an ancestor, and that is the ordinary case.
    contained = verified_ids[0] in bases
    if args.base_ref is None:
        print("REFUSED: --base-ref is required. It names the branch this change forked off,")
        print("as it stood BEFORE the merge, and it is the only way to know which paths the")
        print("change touched.")
        print("The merge base of --verified-head and --integration-ref cannot stand in for")
        print("it: every commit of the change is also an ancestor of the verified head, so")
        print("when the integration ref descends from a commit INSIDE the change -- a branch")
        print("merged from behind its head -- that merge base is inside the change too, and")
        print("the set derived from it silently omits everything before it.")
        return 2

    base_ids = _resolve_ref("--base-ref", args.base_ref)
    if base_ids is None:
        return 2
    if _is_ancestor(verified_ids[0], base_ids[0]):
        print("REFUSED: --base-ref already contains --verified-head, so it is not a state")
        print("before this change. Pass the base branch as it stood BEFORE the merge.")
        return 2
    code, before = _merge_bases(verified_ids[0], base_ids[0])
    if code != 0 or not before:
        print("REFUSED: --verified-head and --base-ref share no common ancestor.")
        return 2

    # INSTANCE TWELVE. `merge-base(verified, base-ref)` is the fork point only
    # while the base branch has not acquired any commit OF THIS CHANGE. Once it
    # has -- a branch merged from behind its head, a cherry-pick, an earlier
    # partial merge of the same lineage -- the merge base is a commit INSIDE the
    # change, the derived set shrinks to that change's tail, and every path the
    # change touched before it is dropped with the tool stating as fact that the
    # change "does not touch" them. Reproduced against the code that shipped in
    # #1532: a reverted locality fix reported `landed`, exit 0, with the path set
    # derived exactly as this file's own docstring prescribed.
    #
    # So the fork point is an input, from a record made BEFORE the base branch
    # moved, and it is UNIONED with the merge bases rather than replacing them.
    # Union, specifically, because it makes the choosing monotone: naming an
    # earlier commit can only grow the set, and naming a later one cannot shrink
    # it below what the merge bases already give. The one thing a caller would
    # want from this input -- a smaller set -- is unreachable through it. That is
    # the difference between this input and `--base-ref`, which every previous
    # round got wrong by leaving a way to choose DOWNWARD.
    if args.fork_point is None:
        print("REFUSED: --fork-point is required. It names the commit this change forked")
        print("FROM, read from a record made before the base branch moved -- the pull")
        print("request's own recorded base sha is the usual source.")
        print("The merge base of --verified-head and --base-ref cannot stand in for it:")
        print("once the base branch has absorbed any commit of this change, that merge")
        print("base is inside the change, and the set derived from it silently omits")
        print("every path the change touched before that point.")
        return 2

    fork_ids = _resolve_ref("--fork-point", args.fork_point)
    if fork_ids is None:
        return 2
    if fork_ids[0] == verified_ids[0]:
        print("REFUSED: --fork-point is --verified-head. A commit is not the state before")
        print("itself, and the set derived from it is empty.")
        return 2
    if not _is_ancestor(fork_ids[0], verified_ids[0]):
        print("REFUSED: --fork-point is not an ancestor of --verified-head, so it is not a")
        print("commit this change forked from. Nothing derived from it describes this change.")
        return 2

    # A merge base STRICTLY AFTER the fork point is a commit of this change that
    # the base branch has acquired. It is not a state before the change, so it is
    # not a pre-change revision and it is dropped rather than unioned in.
    #
    # Dropping, not keeping, because the probative gate asks a declared path to
    # differ from EVERY pre-change revision. Keep such a base and the gate reads
    # a path the change altered BEFORE that commit as unchanged -- it is
    # identical there, because that is where the change put it -- and refuses the
    # one path that would catch the regression. Keeping it and unioning was tried
    # here first and did exactly that.
    #
    # Dropping can only move the derived set earlier, which can only make it
    # larger, so this cannot be used to hide a path.
    inside = [base for base in before if base != fork_ids[0] and _is_ancestor(fork_ids[0], base)]
    if inside:
        print(f"NOTE: the base branch already carries part of this change: {', '.join(b[:12] for b in sorted(inside))}")
        print(f"{'is' if len(inside) == 1 else 'are'} descended from --fork-point ({fork_ids[0][:12]}), so the merge base with --base-ref is")
        print("inside the change rather than before it. Deriving from the fork point instead;")
        print("the set below is the wider, correct one.")
    # Only when contamination was actually found. Adding the fork point
    # unconditionally looks harmless -- it is always at or before the merge base
    # -- and is not: the probative gate asks a declared path to differ from EVERY
    # pre-change revision, so a second, later revision in that set turns paths
    # the change genuinely touched into non-probative ones and refuses an honest
    # distant-base check that works today. The fork point replaces what it
    # corrects; it does not accumulate.
    if inside:
        before = sorted({fork_ids[0], *(base for base in before if base not in inside)})

    # WHAT THIS DOES AND DOES NOT ESTABLISH, stated because the alternative is
    # a claim that keeps turning out to be false.
    #
    # Requiring `--base-ref` closes the variant that needed no choice at all:
    # the tool no longer derives the pre-change revision from the integration
    # ref, so an integration branch descending from a commit INSIDE the change
    # can no longer silently shrink the set to that change's tail.
    #
    # It does not, and cannot, establish that the ref you name IS the fork
    # point. A commit inside the change is an ancestor of the verified head,
    # and so is the fork point; nothing in these three refs tells them apart.
    # Name one and the derived set covers only what the change did afterwards.
    # Refusing every ancestor is not the answer either -- a base branch that has
    # not moved since the fork IS an ancestor, and that is the ordinary case.
    #
    # That advice used to end here, with "so: derive `--base-ref` from the pull
    # request's own base branch, mechanically". Following it exactly is how
    # instance twelve was produced: the base branch had absorbed a commit of the
    # change, so the mechanical derivation returned a revision inside it. The
    # mechanical instruction was the delivery vector, for the third time in this
    # lineage.
    #
    # `--fork-point`, read from a record made BEFORE the base branch moved,
    # replaces any merge base that turns out to be inside the change. It is
    # still a fact the caller supplies -- the tool cannot derive it from these
    # refs, which is the honest statement of the limit -- but it is one the
    # caller cannot use to SHRINK the set, because the only thing it can do is
    # move the pre-change revision earlier.
    if args.deleted_paths:
        # A path must have existed at EVERY pre-change revision. Accepting it at
        # one of several would make the verdict depend on which base git named.
        never_there = sorted({path for base in before for path in args.deleted_paths
                              if _entry(base, path) in (ABSENT, UNKNOWN)})
        # Only a TREE. A gitlink is one object id and compares like a blob, and
        # refusing it made a submodule removal unverifiable BY CONSTRUCTION:
        # `git diff` reports `D vendor`, the tool printed it under "Declare
        # exactly", and then refused that exact declaration. A refusal that
        # instructs the operator to do the thing it refuses is the third time a
        # message here has become the defect.
        wrong_kind = sorted({path for base in before for path in args.deleted_paths
                             if _kind(_entry(base, path)) == "tree"})
        if wrong_kind:
            named = ", ".join(base[:12] for base in before)
            print("REFUSED: these --deleted-path arguments name a directory at the pre-change")
            print(f"revision ({named}), so their absence afterwards is not a file's:")
            for path in wrong_kind:
                print(f"  {path}")
            return 2
        if never_there:
            named = ", ".join(base[:12] for base in before)
            print(f"REFUSED: these --deleted-path arguments do not exist at every pre-change revision ({named}),")
            print("so there is no deletion to verify and their absence proves nothing:")
            for path in never_there:
                print(f"  {path}")
            if contained and args.base_ref is None:
                print("--verified-head is an ancestor of --integration-ref, so that revision is the")
                print("verified head itself, where a deleted path is absent by definition. Pass")
                print("--base-ref <the branch this change forked off> to derive it properly.")
            return 2

    # THE DECLARED SET MUST BE THE SET THIS CHANGE ACTUALLY TOUCHED.
    #
    # Every false pass this tool has had was a declaration the operator chose:
    # a mistyped path, an untouched path, a deletion that was never a deletion,
    # a directory, and -- once `--base-ref` existed -- an honest path measured
    # against a dishonest revision. Requiring "at least one probative path" left
    # the choosing to the operator, in a tool that exists because the operator's
    # choosing is what failed.
    #
    # So the tool derives the set itself and refuses anything else. A base named
    # further back than the real fork point no longer helps: it does not shrink
    # the derived set, it GROWS it, and every path it adds must then be declared
    # and compared. That is what catches `-s ours`, `-X ours` and merge-then-
    # revert, all of which passed while an untouched path was allowed to stand
    # in for the change.
    #
    # With several merge bases the union is taken, for the same reason `--all`
    # exists: a path that differs from any of them is a path this merge could
    # have altered, and leaving it undeclared is how a verdict says nothing
    # about it.
    derived: dict[str, str] = {}
    for base in before:
        code, changed = _changed_paths(base, verified_ids[0])
        if code != 0:
            print(f"REFUSED: could not derive the changed paths between {base[:12]} and the verified head.")
            if code == 2:
                print("A path in this range is not valid UTF-8. Every other spelling here --")
                print("`--path`, `ls-tree` output, this message -- is text, so the tool cannot")
                print("compare it honestly and says so rather than reporting on the rest.")
            return 2
        for path, status in changed.items():
            derived[path] = "D" if derived.get(path) == "D" or status == "D" else status

    expected_present = sorted(path for path, status in derived.items() if status != "D")
    expected_deleted = sorted(path for path, status in derived.items() if status == "D")
    named = ", ".join(base[:12] for base in before)

    if not derived:
        print(f"REFUSED: this change touches no path at all against the pre-change revision ({named}),")
        print("so there is nothing whose content can witness the merge.")
        if contained and args.base_ref is None:
            print("--verified-head is an ancestor of --integration-ref, so that revision is the")
            print("verified head itself. Pass --base-ref <the commit this change forked off,")
            print("as it was BEFORE the merge> so the paths can be derived.")
        return 2

    if sorted(args.paths) != expected_present or sorted(args.deleted_paths) != expected_deleted:
        print(f"REFUSED: the declared paths are not the paths this change touched ({named}).")
        print("A subset yields a verdict that says nothing about what you left out, and a")
        print("path from outside the set cannot witness this merge at all. Declare exactly:")
        for path in expected_present:
            print(f"  --path {path}")
        for path in expected_deleted:
            print(f"  --deleted-path {path}")
        surplus = sorted((set(args.paths) | set(args.deleted_paths)) - set(derived))
        if surplus:
            print("These were declared and this change does not touch them:")
            for path in surplus:
                print(f"  {path}")
        return 2

    # A change that only removes files still cannot be verified: absence is
    # symmetric, so there is nothing whose content can witness the merge.
    if not expected_present:
        print("REFUSED: a change that only removes files cannot be verified by this tool.")
        print("Absence is symmetric, so there is nothing whose content can witness the merge.")
        return 2

    # An unresolved lookup is not a difference. `_entry` returns UNKNOWN for one,
    # and `UNKNOWN != <entry>` is true, so an ambiguous pathspec would otherwise
    # be read as evidence that the change touched the path. Every other gate here
    # refuses UNKNOWN; this one was counting it as proof.
    #
    # EVERY base, not the first one: with a criss-cross history the bases
    # disagree, and reading one of them makes the verdict turn on which one git
    # happened to name.
    def _differs_from_every_base(path: str) -> bool:
        entries = [_entry(base, path) for base in before]
        if any(entry == UNKNOWN for entry in entries):
            return False
        return all(entry != verified_entries[path] for entry in entries)

    not_probative = [path for path in args.paths if not _differs_from_every_base(path)]
    if not_probative:
        print("REFUSED: these declared paths do not differ from EVERY pre-change revision")
        print(f"({named}), so they cannot witness what this merge did:")
        for path in not_probative:
            print(f"  {path}")
        print("A path identical to one of them predates the change there, and an unresolvable")
        print("lookup is not a difference either. With several merge bases this is the")
        print("ordinary case: the change is in the union, and some of it matches one base.")
        print("Verify against a single-base pair, or against each base in turn.")
        return 2

    verified = VerifiedResult(
        head_sha=verified_ids[0], tree_sha=verified_ids[1], blobs=verified_entries
    )
    integration = IntegrationResult(
        head_sha=integration_ids[0],
        tree_sha=integration_ids[1],
        blobs={path: _entry(args.integration_ref, path) for path in declared},
        merge_api_reported_success=args.merge_reported_success,
    )

    result = inspect_merge(verified, integration)
    print(f"verdict      : {result.verdict.value}")
    print(f"reason       : {result.reason}")
    print(f"verified head: {verified.head_sha}  tree {verified.tree_sha}")
    print(f"integration  : {integration.head_sha}  tree {integration.tree_sha}")
    print(f"identical tree: {result.identical_tree}")

    for path, expected, found in result.divergent_paths:
        print(f"  DIVERGED {path}\n    verified    {expected}\n    integration {found}")
    for path in result.unresolved_paths:
        print(f"  UNRESOLVED {path}")

    if result.verdict is MergeVerdict.TREE_MISMATCH:
        print("\nSTOP THIS MERGE LANE. Restore from the verified head:")
        restore = " ".join(shlex.quote(path) for path in restoration_paths(result))
        print(f"  git checkout {shlex.quote(verified.head_sha)} -- {restore}")

    return 0 if may_report_integrated(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
