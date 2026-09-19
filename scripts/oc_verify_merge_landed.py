#!/usr/bin/env python3
"""Prove a merge landed the verified result, from a real checkout.

Usage, run immediately after an integration merge:

    python3 scripts/oc_verify_merge_landed.py \\
        --verified-head 4efa379 \\
        --integration-ref origin/oc-autonomous-integration \\
        --path src/lib/cognitiveIntegration.ts \\
        --path src/components/calyx/ReasoningMapPanel.tsx

Exit status is the point: 0 only when the integration branch holds what was
verified. Any other outcome is non-zero, including the inconclusive ones, so a
lane that pipes this into `&&` stops on missing evidence rather than sailing
past it.

Collecting the evidence is three `git rev-parse` calls. That is the whole cost
of the check that would have caught #706 in seconds. No provider, no network
beyond whatever fetch the caller already did.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calyx_orchestrator.merge_integrity import (
    IntegrationResult,
    MergeVerdict,
    VerifiedResult,
    inspect_merge,
    may_report_integrated,
    restoration_paths,
)


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def _blob(ref: str, path: str) -> str | None:
    """The blob id at `ref:path`, or None when the path is absent there.

    Absence is a real answer -- a change that deletes a file must be checked as
    strictly as one that edits it -- so it is distinguished from an unresolved
    lookup, which `inspect_merge` refuses to treat as agreement.
    """
    out = _git("rev-parse", f"{ref}:{path}")
    return out or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified-head", required=True)
    parser.add_argument("--integration-ref", required=True)
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        dest="paths",
        help="a path the change touched; repeat per path",
    )
    parser.add_argument(
        "--merge-reported-success",
        action="store_true",
        default=True,
        help="set when the merge API returned success (the default)",
    )
    args = parser.parse_args(argv)

    if not args.paths:
        # Refusing here rather than passing vacuously: "no paths given" is the
        # shape of evidence that let #706 through.
        print("REFUSED: no --path given, so there is nothing to verify")
        return 2

    verified = VerifiedResult(
        head_sha=_git("rev-parse", args.verified_head) or args.verified_head,
        tree_sha=_git("rev-parse", f"{args.verified_head}^{{tree}}") or "",
        blobs={p: _blob(args.verified_head, p) for p in args.paths},
    )
    integration = IntegrationResult(
        head_sha=_git("rev-parse", args.integration_ref) or args.integration_ref,
        tree_sha=_git("rev-parse", f"{args.integration_ref}^{{tree}}") or "",
        blobs={p: _blob(args.integration_ref, p) for p in args.paths},
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
        print(f"  git checkout {args.verified_head} -- " + " ".join(restoration_paths(result)))

    return 0 if may_report_integrated(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
