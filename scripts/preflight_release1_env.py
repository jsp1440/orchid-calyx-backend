#!/usr/bin/env python3
"""Release 1 environment preflight: which variables are present, never values.

Env-only: no network, no database, no file reads beyond this repository's
catalogue (``app/release_env.py``). Prints one line per variable
(``present`` / ``absent``) and never prints a value, a length or a hash.

Exit 0 when every required variable (or its documented fallback) is present,
1 otherwise. ``--json`` prints the same report as JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.release_env import config_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)

    report = config_readiness()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for entry in report["variables"]:
            kind = "required" if entry["required"] else "optional"
            state = "present" if entry["present"] else "absent"
            note = ""
            if entry["required"] and not entry["present"] and entry["satisfied"]:
                note = " (satisfied by fallback)"
            print(f"{entry['name']}: {state} [{kind}]{note}")
        if report["missing_required"]:
            missing = ", ".join(report["missing_required"])
            print(f"NOT READY: missing required: {missing}")
        else:
            print("READY: every required variable is present")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
