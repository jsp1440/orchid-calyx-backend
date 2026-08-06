#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python}"
RECEIPT_PATH="${CANONICAL_BRAIN_VALIDATION_RECEIPT:-artifacts/canonical-brain-validation.json}"
STARTED_AT="$($PYTHON_BIN - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).isoformat())
PY
)"

mkdir -p "$(dirname "$RECEIPT_PATH")"

status="passed"
failed_step=""

run_step() {
  local step_name="$1"
  shift
  printf '==> %s\n' "$step_name"
  if ! "$@"; then
    status="failed"
    failed_step="$step_name"
    write_receipt
    exit 1
  fi
}

write_receipt() {
  STATUS="$status" FAILED_STEP="$failed_step" STARTED_AT="$STARTED_AT" RECEIPT_PATH="$RECEIPT_PATH" "$PYTHON_BIN" - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

payload = {
    "schema_version": "1.0",
    "suite": "canonical-brain",
    "status": os.environ["STATUS"],
    "failed_step": os.environ["FAILED_STEP"] or None,
    "started_at": os.environ["STARTED_AT"],
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "commands": [
        "python -m compileall -q app/canonical_brain",
        "ruff check app/canonical_brain tests/test_canonical_brain_*.py",
        "pytest -q tests/test_canonical_brain_*.py",
    ],
    "publication_enabled": False,
    "deployment_enabled": False,
}
path = Path(os.environ["RECEIPT_PATH"])
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"validation receipt: {path}")
PY
}

run_step "compile" "$PYTHON_BIN" -m compileall -q app/canonical_brain
run_step "lint" ruff check app/canonical_brain tests/test_canonical_brain_*.py
run_step "test" pytest -q tests/test_canonical_brain_*.py
write_receipt
