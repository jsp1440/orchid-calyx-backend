"""Price or verify the cost block of a direct-executor execution file.

Offline and deterministic: reads the execution JSON written by
``scripts/swarm_anthropic_direct.py`` and the versioned price table
``config/provider-pricing-v1.json``. No network, no provider calls, no writes
unless ``--output`` is given.

    python scripts/oc_execution_cost.py --execution-file run.json
    python scripts/oc_execution_cost.py --execution-file run.json --verify

``--verify`` recomputes the estimate from the receipt's own per-request usage
under the pricing version the receipt names and exits 1 on any mismatch.
Receipts without per-request usage (written before pricing existed) are
reported as unpriceable: run totals cannot be priced correctly, because some
rates depend on each request's prompt length.

The output is a list-price estimate. It must not be passed to the governor as
``OC_GOVERNOR_ACTUAL_COST_USD``: that variable means billed spend.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_MODULE = REPO_ROOT / "runtime" / "swarm" / "pricing.py"


def _pricing():
    spec = importlib.util.spec_from_file_location("oc_provider_pricing", PRICING_MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("oc_provider_pricing", module)
    spec.loader.exec_module(module)
    return module


def _model(result: dict[str, Any]) -> str | None:
    usage = result.get("modelUsage") or {}
    return next(iter(usage), None) if len(usage) == 1 else None


def price_execution(
    result: dict[str, Any], pricing_path: Path | None = None
) -> dict[str, Any]:
    pricing = _pricing()
    table = pricing.load_table(pricing_path or pricing.PRICING_PATH)
    model = _model(result)
    usages = result.get("requestUsage")
    if model is None:
        return pricing.unavailable_cost("execution names no single model")
    if not isinstance(usages, list):
        return pricing.unavailable_cost(
            "per-request usage not recorded; run totals cannot be priced"
        )
    return pricing.estimate(model, usages, table).to_jsonable()


def verify_execution(
    result: dict[str, Any], pricing_path: Path | None = None
) -> list[str]:
    """Return mismatches between the stored cost block and a recomputation."""
    stored = result.get("cost")
    if not isinstance(stored, dict):
        return ["execution has no cost block"]
    recomputed = price_execution(result, pricing_path)
    if stored.get("basis") == "unavailable":
        return (
            []
            if stored.get("estimated_usd") is None
            else ["unavailable cost carries an estimate"]
        )
    if stored.get("pricing_version") != recomputed.get("pricing_version"):
        return [
            (
                f"receipt priced with {stored.get('pricing_version')}, current table is "
                f"{recomputed.get('pricing_version')}; verify against that version's table"
            )
        ]
    problems = [
        f"{key}: stored={stored.get(key)!r} recomputed={recomputed.get(key)!r}"
        for key in (
            "estimated_usd",
            "priced_subtotal_usd",
            "complete",
            "components_usd",
            "requests",
        )
        if stored.get(key) != recomputed.get(key)
    ]
    if (
        stored.get("billed_usd") is not None
        and stored.get("basis") == "list_price_estimate"
    ):
        problems.append("estimate carries a billed amount")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--execution-file", required=True, type=Path)
    parser.add_argument("--pricing", type=Path, default=None)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = json.loads(args.execution_file.read_text(encoding="utf-8"))
    if args.verify:
        problems = verify_execution(result, args.pricing)
        print(json.dumps({"verified": not problems, "problems": problems}, indent=2))
        return 0 if not problems else 1
    cost = price_execution(result, args.pricing)
    rendered = json.dumps(cost, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
