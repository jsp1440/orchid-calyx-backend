from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / "artifacts" / "validation" / "canonical-brain-validation.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(name: str, args: list[str], receipt: dict[str, object]) -> None:
    command = [sys.executable, *args]
    step = {"name": name, "command": command, "started_at": _utc_now(), "status": "running"}
    receipt["steps"].append(step)
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        step["status"] = "failed"
        step["returncode"] = exc.returncode
        step["completed_at"] = _utc_now()
        receipt["status"] = "failed"
        receipt["failed_step"] = name
        raise
    step["status"] = "passed"
    step["returncode"] = 0
    step["completed_at"] = _utc_now()


def _test_files() -> list[str]:
    tests = sorted(ROOT.glob("tests/test_canonical_brain_*.py"))
    if not tests:
        raise RuntimeError("CANONICAL_BRAIN_TESTS_MISSING")
    return [str(path.relative_to(ROOT)) for path in tests]


def _receipt_path() -> Path:
    override = os.environ.get("CANONICAL_BRAIN_VALIDATION_RECEIPT", "").strip()
    return Path(override).expanduser().resolve() if override else DEFAULT_RECEIPT


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    receipt_path = _receipt_path()
    receipt: dict[str, object] = {
        "schema_version": "1.0",
        "validator": "canonical-brain",
        "started_at": _utc_now(),
        "completed_at": None,
        "status": "running",
        "failed_step": None,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "repository_root": str(ROOT),
        "tests": [],
        "steps": [],
        "authority": {
            "merge": False,
            "deploy": False,
            "publish": False,
            "credential_access": False,
            "production_database_mutation": False,
            "production_knowledge_graph_mutation": False,
        },
    }

    try:
        tests = _test_files()
        receipt["tests"] = tests
        _run("compile", ["-m", "compileall", "-q", "app/canonical_brain"], receipt)
        _run("ruff", ["-m", "ruff", "check", "app/canonical_brain", *tests], receipt)
        _run("pytest", ["-m", "pytest", "-q", *tests], receipt)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        if receipt["status"] != "failed":
            receipt["status"] = "failed"
            receipt["failed_step"] = "test_discovery"
            receipt["error"] = str(exc)
        receipt["completed_at"] = _utc_now()
        _write_receipt(receipt_path, receipt)
        return 1

    receipt["status"] = "passed"
    receipt["completed_at"] = _utc_now()
    _write_receipt(receipt_path, receipt)
    print(f"Canonical Brain validation passed; receipt={receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
