#!/usr/bin/env python3
"""Fail-closed NO-API mode guard for Orchid Continuum provider steps.

Reads NO_API_MODE from the environment.  Anything other than an explicit
disable value is treated as blocked (fail-closed).  Writes
`blocked=true|false` to $GITHUB_OUTPUT and always exits 0 so downstream
`if:` conditions can gate provider steps without failing the job.

Disable values (case-insensitive): disabled, false, 0, no, off
Absent variable → blocked (fail-closed).
"""
from __future__ import annotations

import os
import sys

_DISABLE_VALUES = frozenset({"disabled", "false", "0", "no", "off"})


def evaluate(no_api_mode_raw: str | None) -> bool:
    """Return True when providers are blocked, False when allowed."""
    if no_api_mode_raw is None:
        return True
    return no_api_mode_raw.strip().lower() not in _DISABLE_VALUES


def write_output(blocked: bool) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    line = f"blocked={'true' if blocked else 'false'}\n"
    if github_output:
        try:
            with open(github_output, "a") as fh:
                fh.write(line)
            return
        except OSError:
            pass
    sys.stdout.write(line)


def main() -> None:
    raw = os.environ.get("NO_API_MODE")
    blocked = evaluate(raw)
    write_output(blocked)
    if blocked:
        print(
            f"[OC-NO-API-GUARD] NO_API_MODE={raw!r}: providers BLOCKED "
            "(set NO_API_MODE=false to enable)."
        )
    else:
        print(f"[OC-NO-API-GUARD] NO_API_MODE={raw!r}: providers ALLOWED.")


if __name__ == "__main__":
    main()
