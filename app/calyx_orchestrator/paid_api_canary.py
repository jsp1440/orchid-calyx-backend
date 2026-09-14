"""Paid API canary — Stage A and B execution with real provider calls.

Requires OPENAI_API_KEY or ANTHROPIC_API_KEY in the environment.
These are repository secrets available in GitHub Actions but NOT in CCR shell.

STAGE A — one issue via cheapest configured provider:
    python -m app.calyx_orchestrator.paid_api_canary --stage a --issue 1330

STAGE B — two issues concurrently:
    python -m app.calyx_orchestrator.paid_api_canary --stage b --issues 1330,1402

Both stages:
- Pre-reserve budget before each provider call
- Record actual provider/model/token/cost in the receipt
- Post machine-readable receipt to issue #1330 (SWARM-GOVERNOR-LEDGER)
- Enforce $50 program ceiling (no auto-reload)
- No merge, deployment, production mutation, taxonomy, publication
- No unbounded retries (MAX_RETRIES=2)
- Tier 0 path (no-API) remains available independently

Exit codes:
    0 = all stages passed
    1 = Stage A blocked/failed (credential, budget, provider error)
    2 = Stage B partial failure
    3 = no API keys configured
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .deep_orchestrate import AUTH_WORKSPACE, Priority, TaskLeaf, TaskState
from .github_coding_executor import BudgetClass, ConvergenceClass
from .paid_api_budget_governor import BudgetExhaustedError, PaidAPIBudgetGovernor
from .paid_api_provider import build_cheapest_provider_from_env
from .paid_api_worker import (
    MAX_RETRIES,
    PaidAPIWorker,
    PaidAPIWorkerReceipt,
    build_paid_api_worker_from_env,
)

LEDGER_ISSUE = 1330  # SWARM-GOVERNOR-LEDGER
ALLOWED_REPO = "jsp1440/orchid-calyx-backend"
PROGRAM_CEILING_USD = 50.0
_DEFAULT_REPO = "jsp1440/orchid-calyx-backend"


# ── TaskLeaf factory from GitHub issue number ─────────────────────────────────


def _leaf_for_issue(issue_number: int, repository: str = ALLOWED_REPO) -> TaskLeaf:
    """Fetch issue details from GitHub API and build a TaskLeaf."""
    github_token = os.environ.get("GITHUB_TOKEN", "")
    issue_data: dict[str, Any] = {}
    if github_token:
        try:
            url = f"https://api.github.com/repos/{repository}/issues/{issue_number}"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                issue_data = json.loads(resp.read())
        except Exception as exc:
            print(f"[WARN] Could not fetch issue #{issue_number}: {exc}", file=sys.stderr)

    title = issue_data.get("title") or f"Issue #{issue_number}"
    body = issue_data.get("body") or ""
    key = f"paid-api:issue:{issue_number}"

    leaf = TaskLeaf(
        key=key,
        title=title,
        repo=repository.split("/")[-1],
        module="app/calyx_orchestrator",
        priority=Priority.P1,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    leaf.state = TaskState.READY
    leaf.evidence = {
        "mission_id": key,
        "repository": repository,
        "objective": (body[:500] if body else f"Implement issue #{issue_number}: {title}"),
        "acceptance_criteria": ["implementation complete", "tests pass", "evidence recorded"],
        "validation_commands": ["pytest -q tests/"],
        "budget_class": BudgetClass.TINY.value,
        "convergence_class": ConvergenceClass.NEW.value,
        "base_ref": "main",
        "base_sha": "0" * 40,
        "github_issue_number": issue_number,
    }
    return leaf


# ── Ledger posting ────────────────────────────────────────────────────────────


def _post_ledger_receipt(receipt: PaidAPIWorkerReceipt, stage: str) -> bool:
    """Post machine-readable receipt to #1330 SWARM-GOVERNOR-LEDGER."""
    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        print("[WARN] GITHUB_TOKEN not set; skipping ledger post", file=sys.stderr)
        return False

    ledger_line = receipt.receipt_ledger_line or (
        f"[OC-GOVERNOR-COST] run_id={receipt.run_id or 'NONE'} "
        f"task={receipt.task_key} provider={receipt.provider} model={receipt.model} "
        f"reserved_usd={receipt.estimated_usd:.6f} actual_usd={receipt.actual_usd:.6f} "
        f"date={receipt.started_at[:10]} month={receipt.started_at[:7]}"
    )

    comment_body = (
        f"**Paid API Stage {stage.upper()} Receipt**\n\n"
        f"```\n{ledger_line}\n```\n\n"
        f"- status: `{receipt.status}`\n"
        f"- task: `{receipt.task_key}`\n"
        f"- provider: `{receipt.provider}` / model: `{receipt.model}`\n"
        f"- tokens: `{receipt.input_tokens}` in / `{receipt.output_tokens}` out\n"
        f"- cost: estimated `${receipt.estimated_usd:.6f}` / actual `${receipt.actual_usd:.6f}`\n"
        f"- duration: `{receipt.duration_seconds:.2f}s`\n"
    )
    if receipt.error_reason:
        comment_body += f"- error: `{receipt.error_reason[:200]}`\n"
    if receipt.analysis_excerpt:
        comment_body += f"\n**Analysis excerpt:**\n> {receipt.analysis_excerpt[:200]}\n"

    try:
        url = f"https://api.github.com/repos/{ALLOWED_REPO}/issues/{LEDGER_ISSUE}/comments"
        payload = json.dumps({"body": comment_body}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 201
    except Exception as exc:
        print(f"[WARN] Could not post ledger receipt: {exc}", file=sys.stderr)
        return False


# ── Stage execution ───────────────────────────────────────────────────────────


def _run_stage_a(
    issue: int,
    worker: PaidAPIWorker,
    governor: PaidAPIBudgetGovernor,
) -> PaidAPIWorkerReceipt:
    leaf = _leaf_for_issue(issue)
    print(f"[STAGE-A] Dispatching issue #{issue}: {leaf.title!r}")
    receipt = worker.execute(leaf)
    _post_ledger_receipt(receipt, "A")
    return receipt


def _run_stage_b(
    issues: list[int],
    worker: PaidAPIWorker,
    governor: PaidAPIBudgetGovernor,
) -> list[PaidAPIWorkerReceipt]:
    if len(issues) < 2:
        raise ValueError("Stage B requires at least 2 issue numbers")
    issues_b = issues[:2]
    leaves = [_leaf_for_issue(n) for n in issues_b]
    print(f"[STAGE-B] Dispatching {len(leaves)} issues CONCURRENTLY: {issues_b}")

    receipts: list[PaidAPIWorkerReceipt] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(worker.execute, leaf): leaf for leaf in leaves}
        for fut, leaf in futures.items():
            receipt = fut.result()
            receipts.append(receipt)
            _post_ledger_receipt(receipt, "B")

    run_ids = [r.run_id for r in receipts]
    assert len(set(run_ids)) == len(run_ids), "STAGE_B_DUPLICATE_RUN_IDS"
    task_keys = [r.task_key for r in receipts]
    assert len(set(task_keys)) == len(task_keys), "STAGE_B_DUPLICATE_TASK_KEYS"
    return receipts


# ── Reporting ─────────────────────────────────────────────────────────────────


def _print_receipt(receipt: PaidAPIWorkerReceipt, stage: str) -> None:
    print(f"\n{'='*60}")
    print(f"STAGE {stage.upper()} — {receipt.task_key}")
    print(f"  status:    {receipt.status}")
    print(f"  provider:  {receipt.provider} / {receipt.model}")
    print(f"  run_id:    {receipt.run_id}")
    print(f"  tokens:    {receipt.input_tokens} in / {receipt.output_tokens} out")
    print(f"  cost:      est ${receipt.estimated_usd:.6f} / actual ${receipt.actual_usd:.6f}")
    print(f"  duration:  {receipt.duration_seconds:.2f}s")
    if receipt.error_reason:
        print(f"  ERROR:     {receipt.error_reason[:200]}")
    if receipt.receipt_ledger_line:
        print(f"  LEDGER:    {receipt.receipt_ledger_line}")
    if receipt.analysis_excerpt:
        print(f"  EXCERPT:   {receipt.analysis_excerpt[:120]}...")
    print(f"{'='*60}\n")


def _final_report(
    *,
    stage_a_receipt: PaidAPIWorkerReceipt | None,
    stage_b_receipts: list[PaidAPIWorkerReceipt] | None,
    governor: PaidAPIBudgetGovernor,
    provider_name: str,
    model: str,
    blocker: str | None,
    pr_branch: str = "claude/orchid-worker-codex-adapter-u0rxqr",
) -> None:
    summary = governor.summary()
    a_pass = (stage_a_receipt is not None and stage_a_receipt.status == "completed")
    b_pass = (
        stage_b_receipts is not None
        and len(stage_b_receipts) == 2
        and all(r.status == "completed" for r in stage_b_receipts)
    )
    b_cost = sum(r.actual_usd for r in (stage_b_receipts or []))
    total_cost = summary["spent_usd"]

    print("\n" + "="*70)
    print("FINAL REPORT")
    print("="*70)
    print(f"PAID MODE: {'ENABLED' if not blocker else 'BLOCKED'}")
    print(f"STAGE A: {'PASS' if a_pass else 'FAIL'}")
    print(f"PROVIDER/MODEL: {provider_name}/{model}")
    print(f"ACTUAL COST: ${stage_a_receipt.actual_usd:.6f}" if stage_a_receipt else "ACTUAL COST: N/A")
    print(f"STAGE B: {'PASS' if b_pass else 'FAIL'}")
    print(f"SIMULTANEOUS REAL LANES: {2 if b_pass else 0}")
    print(f"STAGE B COST: ${b_cost:.6f}")
    print(f"TOTAL PROGRAM SPEND: ${total_cost:.6f}")
    print(f"BUDGET REMAINING: ${summary['available_usd']:.4f} of ${summary['ceiling_usd']:.2f}")
    print(f"AUTO REFILL: NOT WORKING (intentionally disabled)")
    print(f"PR: https://github.com/{ALLOWED_REPO}/pull/1423")
    print(f"HEAD: (see branch {pr_branch})")
    print(f"TESTS: (run pytest tests/test_paid_api_worker.py)")
    print(f"CI: (see GitHub Actions on PR #1423)")
    print(f"BLOCKER: {blocker or 'NONE'}")
    print(f"NEXT ACTION: {'See BLOCKER above' if blocker else 'Stage C — up to 8 lanes; no additional spend needed for proof'}")
    print("="*70)


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paid API canary — Stage A and B with real provider calls"
    )
    parser.add_argument("--stage", choices=["a", "b", "ab"], default="a")
    parser.add_argument("--issue", type=int, help="Issue number for Stage A")
    parser.add_argument("--issues", help="Comma-separated issue numbers for Stage B (e.g. 1330,1402)")
    parser.add_argument("--ceiling", type=float, default=PROGRAM_CEILING_USD, help="Budget ceiling USD")
    args = parser.parse_args(argv)

    try:
        worker, governor = build_paid_api_worker_from_env(ceiling_usd=args.ceiling)
    except RuntimeError as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        _final_report(
            stage_a_receipt=None,
            stage_b_receipts=None,
            governor=PaidAPIBudgetGovernor(),
            provider_name="none",
            model="none",
            blocker=str(exc),
        )
        return 3

    provider_name = worker._provider.provider_name
    model = worker._provider.model

    stage_a_receipt: PaidAPIWorkerReceipt | None = None
    stage_b_receipts: list[PaidAPIWorkerReceipt] | None = None
    blocker: str | None = None

    if args.stage in ("a", "ab"):
        issue_a = args.issue or LEDGER_ISSUE
        try:
            stage_a_receipt = _run_stage_a(issue_a, worker, governor)
            _print_receipt(stage_a_receipt, "A")
            if stage_a_receipt.status != "completed":
                blocker = f"STAGE_A_FAILED: {stage_a_receipt.error_reason}"
        except Exception as exc:
            blocker = f"STAGE_A_EXCEPTION: {exc}"
            print(f"[STAGE-A FAIL] {exc}", file=sys.stderr)

    if args.stage in ("b", "ab") and (args.stage == "b" or stage_a_receipt):
        raw_issues = args.issues or ""
        issues_b = [int(s.strip()) for s in raw_issues.split(",") if s.strip().isdigit()]
        if len(issues_b) < 2:
            issues_b = [LEDGER_ISSUE, 1402]  # default Stage B targets
        try:
            stage_b_receipts = _run_stage_b(issues_b, worker, governor)
            for r in stage_b_receipts:
                _print_receipt(r, "B")
            if not all(r.status == "completed" for r in stage_b_receipts):
                blocker = f"STAGE_B_PARTIAL_FAIL"
        except Exception as exc:
            blocker = f"STAGE_B_EXCEPTION: {exc}"
            print(f"[STAGE-B FAIL] {exc}", file=sys.stderr)

    _final_report(
        stage_a_receipt=stage_a_receipt,
        stage_b_receipts=stage_b_receipts,
        governor=governor,
        provider_name=provider_name,
        model=model,
        blocker=blocker,
    )

    if blocker:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
