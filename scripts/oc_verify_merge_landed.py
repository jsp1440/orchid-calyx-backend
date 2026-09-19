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
    1  it does not, or the comparison was inconclusive -- stop the merge lane
    2  the tool could not obtain the evidence it was asked about

so a lane that pipes this into `&&` stops on missing evidence rather than
sailing past it. The three exit codes are distinct on purpose: a corrupted merge
and a mistyped invocation are different problems and a lane must not confuse
them.

Every declared `--path` must exist at the verified head. A path that is absent
there is a mistyped or stale argument, and this refuses rather than comparing
absence with absence and calling that agreement -- which is exactly how a
vacuous pass is manufactured. A change that genuinely removes a file declares
that with `--deleted-path`, and the deletion is then checked as strictly as an
edit.

Both refs are resolved with `--verify --end-of-options` before anything is
compared, so an unresolvable ref -- including one beginning with `-`, which bare
`rev-parse` echoes back verbatim with status 0 -- is an evidence failure rather
than a pair of matching nonsense strings.

Scope, stated plainly: this proves the integration side holds what was verified
at the declared paths. It says nothing about content the merge *added* at paths
that were never verified. It is built for the dropped-commit failure class of
#706, not for injection.

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


def _blob(ref: str, path: str) -> str | None:
    """The blob id at `ref:path`; ABSENT when the path is not there.

    The ref is already proven to resolve, so status 1 means the path is absent,
    which is a real answer. Any other failure is genuinely unresolved and becomes
    UNKNOWN, which `inspect_merge` refuses to treat as agreement.
    """
    code, out = _rev_parse(f"{ref}:{path}")
    if code == 0 and out:
        return out
    return ABSENT if code == 1 else UNKNOWN


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
        help="a path the change removed, and that must therefore be absent after the merge",
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

    verified_blobs = {path: _blob(args.verified_head, path) for path in declared}

    # A --path the verified head does not contain is a mistyped or stale
    # argument. Comparing its absence with the integration side's absence would
    # report agreement on evidence that was never gathered.
    missing = [path for path in args.paths if verified_blobs[path] in (ABSENT, UNKNOWN)]
    if missing:
        print("REFUSED: these --path arguments do not exist at the verified head:")
        for path in missing:
            print(f"  {path}")
        print("Correct the path, or declare it with --deleted-path if the change removed it.")
        return 2
    present_but_declared_deleted = [path for path in args.deleted_paths if verified_blobs[path] is not ABSENT]
    if present_but_declared_deleted:
        print("REFUSED: these --deleted-path arguments still exist at the verified head:")
        for path in present_but_declared_deleted:
            print(f"  {path}")
        return 2

    verified = VerifiedResult(
        head_sha=verified_ids[0], tree_sha=verified_ids[1], blobs=verified_blobs
    )
    integration = IntegrationResult(
        head_sha=integration_ids[0],
        tree_sha=integration_ids[1],
        blobs={path: _blob(args.integration_ref, path) for path in declared},
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
