from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_test_files(repo_root: Path) -> list[str]:
    files = sorted(repo_root.glob("tests/test_canonical_brain_*.py"))
    if not files:
        raise RuntimeError("no canonical Brain test files were found")
    return [str(path.relative_to(repo_root)) for path in files]


def build_commands(repo_root: Path) -> list[tuple[str, list[str]]]:
    tests = canonical_test_files(repo_root)
    return [
        ("compile", [sys.executable, "-m", "compileall", "-q", "app/canonical_brain"]),
        ("lint", [sys.executable, "-m", "ruff", "check", "app/canonical_brain", *tests]),
        ("test", [sys.executable, "-m", "pytest", "-q", *tests]),
    ]


def write_receipt(
    receipt_path: Path,
    *,
    started_at: str,
    status: str,
    failed_step: str | None,
    commands: Sequence[tuple[str, Sequence[str]]],
) -> None:
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.1",
        "suite": "canonical-brain",
        "status": status,
        "failed_step": failed_step,
        "started_at": started_at,
        "completed_at": utc_now(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "commands": [
            {"step": step, "argv": list(argv)} for step, argv in commands
        ],
        "publication_enabled": False,
        "deployment_enabled": False,
    }
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"validation receipt: {receipt_path}")


def run_validation(repo_root: Path, receipt_path: Path) -> int:
    started_at = utc_now()
    try:
        commands = build_commands(repo_root)
    except Exception as exc:
        commands: list[tuple[str, list[str]]] = []
        print(f"validation setup failed: {exc}", file=sys.stderr)
        write_receipt(
            receipt_path,
            started_at=started_at,
            status="failed",
            failed_step="setup",
            commands=commands,
        )
        return 1

    for step, argv in commands:
        print(f"==> {step}")
        completed = subprocess.run(argv, cwd=repo_root, check=False)
        if completed.returncode != 0:
            write_receipt(
                receipt_path,
                started_at=started_at,
                status="failed",
                failed_step=step,
                commands=commands,
            )
            return completed.returncode or 1

    write_receipt(
        receipt_path,
        started_at=started_at,
        status="passed",
        failed_step=None,
        commands=commands,
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile, lint, and test the canonical Brain package.",
    )
    parser.add_argument(
        "--receipt",
        default=os.environ.get(
            "CANONICAL_BRAIN_VALIDATION_RECEIPT",
            "artifacts/canonical-brain-validation.json",
        ),
        help="Path for the machine-readable validation receipt.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    receipt_path = Path(args.receipt)
    if not receipt_path.is_absolute():
        receipt_path = repo_root / receipt_path
    return run_validation(repo_root, receipt_path)


if __name__ == "__main__":
    raise SystemExit(main())
