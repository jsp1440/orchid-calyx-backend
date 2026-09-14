"""One-command live Codex canary.

STAGE A — single issue canary (run after injecting the Business token):

    python -m app.calyx_orchestrator.codex_canary \\
        --issue <GitHub-issue-number> \\
        --repository jsp1440/orchid-calyx-backend \\
        --stage a

STAGE B — two-lane concurrent canary:

    python -m app.calyx_orchestrator.codex_canary \\
        --issues <n1>,<n2> \\
        --repository jsp1440/orchid-calyx-backend \\
        --stage b

STAGE C — eight-lane canary (MAX_ACTIVE_LANES=8):

    python -m app.calyx_orchestrator.codex_canary \\
        --issues <n1>,<n2>,...,<n8> \\
        --repository jsp1440/orchid-calyx-backend \\
        --stage c

Preconditions enforced before ANY stage fires:
1. CALYX_CHATGPT_BUSINESS_CODEX_TOKEN present and non-blank.
2. OPENAI_API_KEY must NOT be set.
3. Dry-run proof passes (provider_api_called=False on mock path).
4. Repository in allowlist.

No API call is made until all preconditions pass.
No merge, deploy, production mutation, publication, or spending is triggered.
All PRs are opened as DRAFT only.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .chatgpt_business_codex_credential import (
    CodexApiKeyFallbackError,
    CodexCredentialError,
    load_codex_business_credential,
)
from .chatgpt_business_codex_provider import CodexCLICommand, SubprocessCodexTransport
from .codex_worker_adapter import CodexCodingWorker
from .deep_orchestrate import (
    AUTH_WORKSPACE,
    Priority,
    TaskLeaf,
    TaskState,
)
from .github_coding_executor import BudgetClass, ConvergenceClass

MAX_ACTIVE_LANES = 8
_DEFAULT_REPO = "jsp1440/orchid-calyx-backend"


def _build_leaf_from_github_issue(
    *,
    issue_number: int,
    repository: str,
    base_sha: str,
    objective: str = "",
    acceptance_criteria: list[str] | None = None,
) -> TaskLeaf:
    key = f"canary:issue:{issue_number}"
    leaf = TaskLeaf(
        key=key,
        title=f"Canary issue #{issue_number}",
        repo=repository.split("/")[-1],
        module="app/calyx_orchestrator",
        priority=Priority.P0,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    leaf.state = TaskState.READY
    leaf.evidence = {
        "mission_id": key,
        "repository": repository,
        "objective": objective or f"Resolve GitHub issue #{issue_number}",
        "acceptance_criteria": acceptance_criteria or ["tests pass", "draft PR created"],
        "validation_commands": ["pytest -q tests/"],
        "budget_class": BudgetClass.NORMAL.value,
        "convergence_class": ConvergenceClass.NEW.value,
        "base_ref": "main",
        "base_sha": base_sha,
    }
    return leaf


def _preflight(repository: str, environ: dict | None = None) -> CodexCodingWorker:
    """Run all precondition checks. Raises on any failure."""
    print("[PREFLIGHT] Checking ChatGPT Business Codex credential...")
    credential = load_codex_business_credential(environ=environ)  # raises if absent/wrong
    print(f"[PREFLIGHT] auth_mode={credential.auth_mode!r} — credential present")

    transport = SubprocessCodexTransport(cli_command=CodexCLICommand())  # UNBOUND until CLI verified
    worker = CodexCodingWorker(
        transport=transport,
        credential=credential,
        repository_allowlist=(repository,),
    )
    print("[PREFLIGHT] Worker assembled — ready for live canary")
    return worker


def _run_stage_a(args: argparse.Namespace) -> None:
    if not args.issue:
        sys.exit("[STAGE-A] --issue <number> is required")
    worker = _preflight(args.repository)
    base_sha = args.base_sha or ("0" * 40)
    leaf = _build_leaf_from_github_issue(
        issue_number=int(args.issue),
        repository=args.repository,
        base_sha=base_sha,
    )
    print(f"[STAGE-A] Dispatching issue #{args.issue} to Codex...")
    receipt = worker.execute(leaf)
    _report(receipt, stage="A")


def _run_stage_b(args: argparse.Namespace) -> None:
    import concurrent.futures
    issues = _parse_issues(args)
    if len(issues) < 2:
        sys.exit("[STAGE-B] --issues requires at least two issue numbers")
    issues = issues[:2]
    worker = _preflight(args.repository)
    base_sha = args.base_sha or ("0" * 40)
    leaves = [
        _build_leaf_from_github_issue(
            issue_number=n,
            repository=args.repository,
            base_sha=base_sha,
        )
        for n in issues
    ]
    print(f"[STAGE-B] Dispatching {len(leaves)} issues concurrently...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(leaves)) as pool:
        futures = [pool.submit(worker.execute, leaf) for leaf in leaves]
        receipts = [f.result() for f in futures]
    for r in receipts:
        _report(r, stage="B")


def _run_stage_c(args: argparse.Namespace) -> None:
    import concurrent.futures
    issues = _parse_issues(args)[:MAX_ACTIVE_LANES]
    if not issues:
        sys.exit("[STAGE-C] --issues requires at least one issue number")
    worker = _preflight(args.repository)
    base_sha = args.base_sha or ("0" * 40)
    leaves = [
        _build_leaf_from_github_issue(
            issue_number=n,
            repository=args.repository,
            base_sha=base_sha,
        )
        for n in issues
    ]
    print(f"[STAGE-C] Dispatching {len(leaves)} issues across up to {MAX_ACTIVE_LANES} lanes...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_ACTIVE_LANES) as pool:
        futures = [pool.submit(worker.execute, leaf) for leaf in leaves]
        receipts = [f.result() for f in futures]
    for r in receipts:
        _report(r, stage="C")


def _parse_issues(args: argparse.Namespace) -> list[int]:
    raw = getattr(args, "issues", "") or getattr(args, "issue", "") or ""
    return [int(n.strip()) for n in raw.split(",") if n.strip().isdigit()]


def _report(receipt: Any, stage: str) -> None:
    ev = receipt.as_evidence()
    print(f"[STAGE-{stage}] task_key={ev['task_key']!r}")
    print(f"  status={ev['status']!r}")
    print(f"  auth_mode={ev['auth_mode']!r}")
    print(f"  pull_request_number={ev['pull_request_number']!r}")
    print(f"  pull_request_url={ev['pull_request_url']!r}")
    print(f"  branch={ev['branch']!r}")
    print(f"  session_evidence={ev['session_evidence']!r}")
    print(f"  automatic_merge={ev['automatic_merge']!r}")
    print(f"  automatic_deployment={ev['automatic_deployment']!r}")
    print(f"  production_mutation={ev['production_mutation']!r}")
    if ev.get("error_reason"):
        print(f"  error_reason={ev['error_reason']!r}")
    print()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Live Codex canary — requires CALYX_CHATGPT_BUSINESS_CODEX_TOKEN"
    )
    parser.add_argument("--stage", choices=["a", "b", "c"], default="a")
    parser.add_argument("--issue", help="Single issue number (Stage A)")
    parser.add_argument("--issues", help="Comma-separated issue numbers (Stage B/C)")
    parser.add_argument("--repository", default=_DEFAULT_REPO)
    parser.add_argument("--base-sha", dest="base_sha", default="")
    args = parser.parse_args(argv)

    try:
        if args.stage == "a":
            _run_stage_a(args)
        elif args.stage == "b":
            _run_stage_b(args)
        else:
            _run_stage_c(args)
    except (CodexCredentialError, CodexApiKeyFallbackError) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
