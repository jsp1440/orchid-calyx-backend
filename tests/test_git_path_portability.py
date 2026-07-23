from __future__ import annotations

import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
WINDOWS_RESERVED_CHARACTERS = set('<>:"\\|?*')


def _tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path
    ]


def _windows_portability_errors(path: str) -> list[str]:
    errors: list[str] = []
    for component in path.split("/"):
        stem = component.split(".", 1)[0].upper()
        if component.endswith((" ", ".")):
            errors.append("component ends with a space or period")
        if WINDOWS_RESERVED_CHARACTERS.intersection(component):
            errors.append("component contains a Windows-reserved character")
        if stem in WINDOWS_RESERVED_NAMES:
            errors.append("component uses a Windows-reserved device name")
        if len(component.encode("utf-8")) > 255:
            errors.append("component exceeds 255 UTF-8 bytes")
    return errors


def test_tracked_paths_are_windows_portable() -> None:
    failures = {
        path: errors
        for path in _tracked_paths()
        if (errors := _windows_portability_errors(path))
    }

    assert failures == {}, f"Windows-incompatible tracked paths: {failures}"
