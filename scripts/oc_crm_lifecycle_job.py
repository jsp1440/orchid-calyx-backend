#!/usr/bin/env python3
"""Daily society CRM membership lifecycle job (active -> grace -> lapsed).

Idempotent and safe to re-run. Intended as a Render cron job, e.g. daily:

    python scripts/oc_crm_lifecycle_job.py

Reads DATABASE_URL. Prints a JSON summary (counts only, no member data) and exits 0
on success, 1 if any society failed (the others are still processed), 2 if the job
could not start.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.constituent_platform.crm_diagnostics import run_lifecycle_job  # noqa: E402
from app.constituent_platform.postgres_repository import PostgresSocietyCRMRepository  # noqa: E402


def main() -> int:
    try:
        repo = PostgresSocietyCRMRepository()
        result = run_lifecycle_job(repo)
    except Exception as exc:  # noqa: BLE001 - report the class only; never a DSN
        print(json.dumps({"succeeded": False, "error": type(exc).__name__}))
        return 2
    print(json.dumps(result, default=str))
    return 0 if result["succeeded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
