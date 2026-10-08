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
_ENABLE_VALUES = frozenset({"enabled", "true", "1", "yes", "on"})


def evaluate(no_api_mode_raw: str | None) -> bool:
    """Return True when providers are blocked, False when allowed."""
    if no_api_mode_raw is None:
        return True
    return no_api_mode_raw.strip().lower() not in _DISABLE_VALUES


def configuration_status(no_api_mode_raw: str | None) -> str:
    """Diagnose configuration without returning or logging arbitrary input.

    This does not authorize provider execution: the governor must separately
    admit paid work. Unknown values retain evaluate()'s fail-closed behavior.
    """
    value = (no_api_mode_raw or "").strip().lower()
    if not value:
        return "missing"
    if value in _DISABLE_VALUES:
        return "disabled"
    if value in _ENABLE_VALUES:
        return "enabled"
    return "invalid"


def write_output(blocked: bool, *, status: str | None = None) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    line = f"blocked={'true' if blocked else 'false'}\n"
    if status is not None:
        line += f"configuration_status={status}\n"
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
    status = configuration_status(raw)
    write_output(blocked, status=status)
    if blocked:
        print(
            f"[OC-NO-API-GUARD] configuration_status={status}: providers BLOCKED. "
            "Provider-free work remains eligible."
        )
    else:
        print(
            "[OC-NO-API-GUARD] configuration_status=disabled: providers ALLOWED "
            "by NO-API guard only; paid execution still requires governor admission."
        )


if __name__ == "__main__":
    main()
