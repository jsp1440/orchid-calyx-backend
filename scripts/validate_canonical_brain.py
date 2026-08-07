from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / "artifacts" / "validation" / "canonical-brain-validation.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "canonical-brain-validation.yml"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(name: str, args: list[str], receipt: dict[str, object]) -> None:
    command = [sys.executable, *args]
    step = {
        "name": name,
        "command": command,
        "started_at": _utc_now(),
        "status": "running",
    }
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


def _validated_files(tests: list[str]) -> list[Path]:
    sources = sorted(path for path in (ROOT / "app" / "canonical_brain").rglob("*.py") if path.is_file())
    paths = [*sources, *(ROOT / test for test in tests), Path(__file__).resolve(), WORKFLOW_PATH]
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"CANONICAL_BRAIN_VALIDATION_INPUT_MISSING:{','.join(sorted(missing))}")
    return sorted(set(paths), key=lambda path: str(path.relative_to(ROOT)))


def _fingerprint_files(paths: list[Path]) -> tuple[list[dict[str, object]], str]:
    records: list[dict[str, object]] = []
    aggregate = hashlib.sha256()
    for path in paths:
        relative = str(path.relative_to(ROOT)).replace("\\", "/")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        records.append({"path": relative, "sha256": digest, "bytes": len(content)})
        aggregate.update(f"{digest}  {relative}\n".encode("utf-8"))
    return records, aggregate.hexdigest()


def _receipt_path() -> Path:
    override = os.environ.get("CANONICAL_BRAIN_VALIDATION_RECEIPT", "").strip()
    return Path(override).expanduser().resolve() if override else DEFAULT_RECEIPT


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    receipt_path = _receipt_path()
    receipt: dict[str, object] = {
        "schema_version": "1.1",
        "validator": "canonical-brain",
        "started_at": _utc_now(),
        "completed_at": None,
        "status": "running",
        "failed_step": None,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "repository_root": str(ROOT),
        "tests": [],
        "validated_files": [],
        "validated_tree_sha256": None,
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
        files = _validated_files(tests)
        fingerprints, tree_digest = _fingerprint_files(files)
        receipt["validated_files"] = fingerprints
        receipt["validated_tree_sha256"] = tree_digest
        _run("compile", ["-m", "compileall", "-q", "app/canonical_brain"], receipt)
        _run("ruff", ["-m", "ruff", "check", "app/canonical_brain", *tests], receipt)
        _run("pytest", ["-m", "pytest", "-q", *tests], receipt)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        if receipt["status"] != "failed":
            receipt["status"] = "failed"
            receipt["failed_step"] = "validation_input"
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
