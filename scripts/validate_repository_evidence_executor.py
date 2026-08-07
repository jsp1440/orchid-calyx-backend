from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = ROOT / "artifacts" / "validation" / "repository-evidence-executor.json"
VALIDATOR_PATH = "scripts/validate_repository_evidence_executor.py"

COMPILE_TARGETS = (
    "app/calyx_orchestrator/repository_evidence_executor.py",
    "app/calyx_orchestrator/executor_registry.py",
    "tests/test_calyx_repository_evidence_executor.py",
    VALIDATOR_PATH,
)

RUFF_TARGETS = COMPILE_TARGETS

PYTEST_TARGETS = (
    "tests/test_calyx_repository_evidence_executor.py",
    "tests/test_calyx_autonomous_program_cycle.py",
    "tests/test_calyx_dry_run_execution_loop.py",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(name: str, command: list[str]) -> dict[str, object]:
    started_at = utcnow()
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    except OSError as exc:
        return {
            "name": name,
            "command": command,
            "started_at": started_at,
            "finished_at": utcnow(),
            "return_code": 127,
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}: {exc}",
        }
    return {
        "name": name,
        "command": command,
        "started_at": started_at,
        "finished_at": utcnow(),
        "return_code": result.returncode,
        "stdout_tail": result.stdout[-8000:],
        "stderr_tail": result.stderr[-8000:],
    }


def write_receipt(receipt: dict[str, object]) -> None:
    RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_PATH.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    required_paths = (*COMPILE_TARGETS, *PYTEST_TARGETS)
    missing = [path for path in required_paths if not (ROOT / path).is_file()]
    receipt: dict[str, object] = {
        "validator": "BUILD-BRAIN-114B",
        "started_at": utcnow(),
        "python": sys.version,
        "platform": platform.platform(),
        "repository_root": str(ROOT),
        "authority": {
            "merge": False,
            "deploy": False,
            "publish": False,
            "production_write": False,
        },
        "missing_required_files": sorted(set(missing)),
        "commands": [],
    }
    if missing:
        receipt["status"] = "failed"
        receipt["failure_stage"] = "required_file_inventory"
        receipt["finished_at"] = utcnow()
        write_receipt(receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 2

    commands = [
        ("compile", [sys.executable, "-m", "py_compile", *COMPILE_TARGETS]),
        ("ruff", [sys.executable, "-m", "ruff", "check", *RUFF_TARGETS]),
        ("pytest", [sys.executable, "-m", "pytest", "-q", *PYTEST_TARGETS]),
    ]

    for name, command in commands:
        result = run_command(name, command)
        receipt["commands"].append(result)
        if result["return_code"] != 0:
            receipt["status"] = "failed"
            receipt["failure_stage"] = name
            receipt["finished_at"] = utcnow()
            write_receipt(receipt)
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return int(result["return_code"]) or 1

    receipt["status"] = "passed"
    receipt["failure_stage"] = None
    receipt["finished_at"] = utcnow()
    write_receipt(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
