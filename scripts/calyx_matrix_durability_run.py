#!/usr/bin/env python3
"""Canonical launcher for governed Matrix durability deployment.

This launcher is the supported direct-command entrypoint. It bootstraps the
repository import path and, when a custom registry source root is supplied,
scopes CALYX_MATRIX_REGISTRY_DIR to that same root for the complete deployment
call so post-copy readiness verifies the exact source that was copied.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.calyx_matrix_durability_deploy import execute_deployment  # noqa: E402


@contextmanager
def _registry_source_scope(source_root: Path | None) -> Iterator[None]:
    key = "CALYX_MATRIX_REGISTRY_DIR"
    previous = os.environ.get(key)
    if source_root is not None:
        os.environ[key] = str(source_root)
    try:
        yield
    finally:
        if source_root is None:
            return
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def run(*, apply: bool = False, source_root: Path | None = None) -> dict:
    """Execute the guarded deployment with one consistent registry source root."""
    with _registry_source_scope(source_root):
        return execute_deployment(apply=apply, source_root=source_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Canonical Matrix durability deployment launcher; dry-run by default."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the guarded database/data-copy phase. Persistent activation flags are not changed.",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Optional immutable-registry source root used consistently for copy and verification.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    source_root = Path(args.source_root) if args.source_root else None
    result = run(apply=bool(args.apply), source_root=source_root)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 3 if result.get("blockers") else 0


if __name__ == "__main__":
    raise SystemExit(main())
