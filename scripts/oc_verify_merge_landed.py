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
    1  it does not (`tree_mismatch`), or the comparison was inconclusive
       (`evidence_incomplete`) -- either way, stop the merge lane
    2  an argument or ref was refused before anything was compared

so a lane that pipes this into `&&` stops on missing evidence rather than
sailing past it. The three exit codes are distinct on purpose: a corrupted merge
and a mistyped invocation are different problems and a lane must not confuse
them.

Every declared path must carry positive evidence on the verified side, because
absence is not evidence and comparing "not there" with "not there" is how a
vacuous pass is manufactured. So:

* `--path P` must resolve at the verified head.
* `--deleted-path P` must resolve at `--deleted-at` -- the head the change was
  made from, `<verified-head>^` unless given -- which is what makes it a
  deletion rather than a name nobody ever used. A path that resolves at neither
  is a mistyped or stale argument and is refused.

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
derive the set mechanically with `git diff --name-status <base>..<verified-head>`
rather than by hand. It is built for the dropped-commit failure class of #706,
not for injection.

Collecting the evidence is a handful of `git rev-parse` calls. That is the whole
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
        help="a path the change removed; it must exist at --deleted-at and be absent after the merge",
    )
    parser.add_argument(
        "--deleted-at",
        default=None,
        help="the ref a --deleted-path existed at before the change (default: <verified-head>^)",
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
        print("Correct the spelling. A path the change removed is proven, not assumed:")
        print("  derive the set with `git diff --name-status <base>..<verified-head>`,")
        print("  and pass a removed path as --deleted-path, which must exist at --deleted-at.")
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
    if args.deleted_paths:
        before = args.deleted_at or f"{args.verified_head}^"
        before_ids = _resolve_ref("--deleted-at", before)
        if before_ids is None:
            if args.deleted_at is None:
                print("The default is <verified-head>^; pass --deleted-at explicitly for a root commit.")
            return 2
        never_there = [path for path in args.deleted_paths if _entry(before, path) in (ABSENT, UNKNOWN)]
        if never_there:
            print(f"REFUSED: these --deleted-path arguments do not exist at {before!r} either,")
            print("so there is no deletion to verify and their absence proves nothing:")
            for path in never_there:
                print(f"  {path}")
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
