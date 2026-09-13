"""Portfolio Steward Reconciliation CLI — workflow entry point.

Reads oc-prepared issues from the frontend repository, builds a deduplication
snapshot from existing queue state, runs the Portfolio Steward reconciler, and
emits structured output for GitHub Actions label-mutation steps.

Usage (from workflow):
    python3 scripts/oc_portfolio_steward_reconcile.py \
        --prepared-issues "$RUNNER_TEMP/prepared-issues.json" \
        --all-issues "$RUNNER_TEMP/all-issues.json" \
        --github-output "$GITHUB_OUTPUT"

Outputs to stdout: JSON reconciliation report.
Sets GITHUB_OUTPUT:
    admitted_count  — number of issues admitted this cycle
    admitted_numbers — JSON array of admitted issue numbers
    suppressed_count — number suppressed by dedup
    rejected_count  — number rejected (missing lineage etc.)
    no_api_mode      — always "true"

NO-API: never invokes a paid model API.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from runtime.deep_orchestrate_queue_bridge import _fingerprint as _leaf_fingerprint
from runtime.portfolio_steward_reconciler import (
    _issue_to_leaf,
    reconcile,
)

_QUEUED_LABELS = frozenset({"oc-queued", "oc-running", "oc-validating", "oc-done"})
_SCHEMA = "oc.portfolio-steward-workflow-bridge.v1"


@dataclass(frozen=True, slots=True)
class LabelDispatchReceipt:
    issue_number: int
    operation: str  # "add_oc_queued"
    status: str     # "dispatched" | "dry_run" | "failed"
    error: str | None = None


class LabelDispatcher:
    """Emit oc-queued label transitions. Injected for testing; default is dry-run."""

    def __init__(self, execute: bool = False, gh_repo: str = "") -> None:
        self._execute = execute
        self._repo = gh_repo
        self._receipts: list[LabelDispatchReceipt] = []

    def add_oc_queued(self, issue_number: int) -> LabelDispatchReceipt:
        """Transition issue from oc-prepared → oc-queued."""
        if not self._execute:
            receipt = LabelDispatchReceipt(
                issue_number=issue_number,
                operation="add_oc_queued",
                status="dry_run",
            )
        else:
            import subprocess
            result = subprocess.run(
                [
                    "gh", "issue", "edit", str(issue_number),
                    "--repo", self._repo,
                    "--add-label", "oc-queued",
                    "--remove-label", "oc-prepared",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                receipt = LabelDispatchReceipt(
                    issue_number=issue_number,
                    operation="add_oc_queued",
                    status="dispatched",
                )
            else:
                receipt = LabelDispatchReceipt(
                    issue_number=issue_number,
                    operation="add_oc_queued",
                    status="failed",
                    error=result.stderr.strip()[:256],
                )
        self._receipts.append(receipt)
        return receipt

    def receipts(self) -> list[LabelDispatchReceipt]:
        return list(self._receipts)


def _label_names(issue: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for label in issue.get("labels") or []:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, dict) and label.get("name"):
            names.append(str(label["name"]))
    return names


def build_frontend_snapshot(all_issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a deduplication snapshot from current frontend issue state.

    Issues already in oc-queued/oc-running/oc-validating contribute their
    material_fingerprint and semantic_key so the bridge does not re-admit them.
    Issues in oc-done contribute to the completed set.
    """
    snapshot_issues: list[dict[str, Any]] = []
    for issue in all_issues:
        labels = set(_label_names(issue))
        if not (labels & _QUEUED_LABELS):
            continue
        leaf = _issue_to_leaf(issue)
        if leaf is None:
            continue
        fp = _leaf_fingerprint(leaf)
        sk = f"deep-orchestrate:{leaf.key}"
        snapshot_issues.append({
            "number": issue.get("number"),
            "labels": list(labels),
            "material_fingerprint": fp,
            "semantic_key": sk,
        })
    return {
        "issues": snapshot_issues,
        "leases": [],
        "dispatch_fingerprints": [],
    }


def run_reconciliation(
    prepared_issues: list[dict[str, Any]],
    all_issues: list[dict[str, Any]],
    *,
    dispatcher: LabelDispatcher | None = None,
    reserve_depth: int = 3,
) -> dict[str, Any]:
    """Execute one full reconciliation cycle. Injectable dispatcher for testing."""
    snapshot = build_frontend_snapshot(all_issues)
    report = reconcile(prepared_issues, snapshot, reserve_depth=reserve_depth)

    dispatch_receipts: list[dict[str, Any]] = []
    if dispatcher is not None:
        for proposal in report.bridge_result.get("proposals", []):
            source_ref = proposal.get("source_ref", "")
            if source_ref.startswith("#"):
                try:
                    issue_number = int(source_ref[1:])
                except ValueError:
                    continue
                receipt = dispatcher.add_oc_queued(issue_number)
                dispatch_receipts.append({
                    "issue_number": receipt.issue_number,
                    "operation": receipt.operation,
                    "status": receipt.status,
                    "error": receipt.error,
                })

    return {
        "schema": _SCHEMA,
        "admitted_count": report.admitted_count,
        "admitted_numbers": [
            int(p["source_ref"][1:])
            for p in report.bridge_result.get("proposals", [])
            if p.get("source_ref", "").startswith("#")
        ],
        "suppressed_count": report.dedup_suppressed,
        "rejected_count": report.rejected_count,
        "source_count": report.source_count,
        "no_api_mode": True,
        "provider_launch_authorized": False,
        "dispatch_receipts": dispatch_receipts,
        "bridge_status": report.bridge_result.get("status"),
        "evidence_count": len(report.evidence),
        "executed_count": report.executed_count,
        "report": report.as_dict(),
    }


def _write_github_output(path: str, result: dict[str, Any]) -> None:
    lines = [
        f"admitted_count={result['admitted_count']}",
        f"admitted_numbers={json.dumps(result['admitted_numbers'])}",
        f"suppressed_count={result['suppressed_count']}",
        f"rejected_count={result['rejected_count']}",
        "no_api_mode=true",
    ]
    with open(path, "a") as fh:
        fh.writelines(line + "\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Portfolio Steward reconciliation")
    parser.add_argument("--prepared-issues", required=True, help="JSON file of oc-prepared issues")
    parser.add_argument("--all-issues", required=True, help="JSON file of all frontend issues for snapshot")
    parser.add_argument("--frontend-repo", default="", help="GitHub repo for label dispatch")
    parser.add_argument("--github-output", default="", help="Path to GITHUB_OUTPUT file")
    parser.add_argument("--execute", action="store_true", help="Apply label transitions (default: dry-run)")
    parser.add_argument("--reserve-depth", type=int, default=3)
    args = parser.parse_args(argv)

    with open(args.prepared_issues) as fh:
        prepared_issues: list[dict[str, Any]] = json.load(fh)
    with open(args.all_issues) as fh:
        all_issues: list[dict[str, Any]] = json.load(fh)

    dispatcher = LabelDispatcher(execute=args.execute, gh_repo=args.frontend_repo)

    try:
        result = run_reconciliation(
            prepared_issues,
            all_issues,
            dispatcher=dispatcher,
            reserve_depth=args.reserve_depth,
        )
    except Exception as exc:  # noqa: BLE001
        error_result = {
            "schema": _SCHEMA,
            "status": "failed_closed",
            "error": str(exc)[:512],
            "admitted_count": 0,
            "admitted_numbers": [],
            "suppressed_count": 0,
            "rejected_count": 0,
            "no_api_mode": True,
            "provider_launch_authorized": False,
            "dispatch_receipts": [],
        }
        json.dump(error_result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        if args.github_output:
            _write_github_output(args.github_output, error_result)
        return 1

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    if args.github_output:
        _write_github_output(args.github_output, result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
