#!/usr/bin/env python3
"""Operator for verified cross-domain Knowledge Graph relationship materialization."""

from __future__ import annotations

import argparse
import json
import os

from runtime.knowledge_graph.production_materializer import (
    CONFIRMATION_TOKEN,
    DEFAULT_DRY_RUN_MAX_ROWS_PER_DOMAIN,
    materialize_verified_relationships,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--domains",
        nargs="*",
        default=None,
        help=(
            "Verified domains to validate/materialize. Read-only validation defaults "
            "to audit-priority domains; --execute requires an explicit list."
        ),
    )
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument(
        "--max-dry-run-rows-per-domain",
        type=int,
        default=DEFAULT_DRY_RUN_MAX_ROWS_PER_DOMAIN,
        help="Read-only two-pass validation ceiling per domain.",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Publish selected verified domains to oc_graph transactionally. "
            "Without this flag the command is read-only."
        ),
    )
    p.add_argument(
        "--confirm",
        default=None,
        help=f"Required with --execute: {CONFIRMATION_TOKEN}",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    dsn = os.getenv("DATABASE_URL", "").strip()
    report = materialize_verified_relationships(
        dsn,
        domains=args.domains,
        execute=args.execute,
        confirmation=args.confirm,
        batch_size=args.batch_size,
        max_dry_run_rows_per_domain=args.max_dry_run_rows_per_domain,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
