#!/usr/bin/env python3
"""Verify/dry-run or explicitly publish habitat/elevation graph relationships."""

from __future__ import annotations

import argparse
import json
import os

from runtime.knowledge_graph.verified_dynamic_materializer import (
    CONFIRMATION_TOKEN,
    DYNAMIC_DOMAINS,
    materialize_dynamic_relationship,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("domain", choices=DYNAMIC_DOMAINS)
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--max-dry-run-rows", type=int, default=10_000)
    p.add_argument("--execute", action="store_true")
    p.add_argument(
        "--confirm",
        default=None,
        help=f"Required with --execute: {CONFIRMATION_TOKEN}",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    report = materialize_dynamic_relationship(
        os.getenv("DATABASE_URL", "").strip(),
        domain=args.domain,
        execute=args.execute,
        confirmation=args.confirm,
        batch_size=args.batch_size,
        max_dry_run_rows=args.max_dry_run_rows,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
