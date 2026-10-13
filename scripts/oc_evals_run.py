"""Run the OC-EVALS-001 deterministic evaluator suite on a frozen fixture set.

Offline and provider-free. Evaluates a baseline and one or more candidate
strategies on the same frozen cases, prints the runs and the promotion
decision, and optionally records no-benefit/rejected candidates in a JSON
suppression ledger so an unchanged candidate is not re-evaluated.

    PYTHONPATH=. python scripts/oc_evals_run.py \\
        --fixture-dir tests/fixtures/evals/coding_repair_v1 \\
        --baseline baseline --candidate candidate_better

NO_API_MODE is read from the environment with the repository's fail-closed
rule; provider-requiring evaluators are parked, never called. A decision
authorizes nothing: no merge, deploy, publication or provider activation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from runtime.evals.decision import SuppressionLedger, decide, memory_summary
from runtime.evals.fixtures import (
    load_cases,
    load_outputs,
    load_strategies,
    load_task_class,
)
from runtime.evals.runner import run_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--fixture-dir", required=True, type=Path)
    parser.add_argument("--baseline", required=True)
    parser.add_argument(
        "--candidate", required=True, action="append", help="repeat for replicate runs"
    )
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--code-sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    task_class = load_task_class(args.fixture_dir)
    cases = load_cases(args.fixture_dir)
    strategies = load_strategies(args.fixture_dir)

    def run(name: str):
        return run_evaluation(
            task_class=task_class,
            strategy=strategies[name.split(":")[0]],
            cases=cases,
            outputs=load_outputs(args.fixture_dir, name.split(":")[-1]),
            code_sha=args.code_sha,
        )

    baseline = run(args.baseline)
    candidates = [run(name) for name in args.candidate]
    ledger = SuppressionLedger.load(args.ledger) if args.ledger else None
    decision = decide(
        task_class=task_class, baseline=baseline, candidates=candidates, ledger=ledger
    )
    if ledger is not None:
        ledger.save(args.ledger)
    report = {
        "baseline": baseline.to_jsonable(),
        "candidates": [c.to_jsonable() for c in candidates],
        "decision": decision.to_jsonable(),
        "memory_summary": memory_summary(decision, candidates[0]),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"decision": decision.decision.value, "rationale": decision.rationale},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
