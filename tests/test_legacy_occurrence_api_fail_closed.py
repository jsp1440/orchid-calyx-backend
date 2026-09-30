"""Standalone FastAPI apps must not serve raw occurrence coordinates unauthenticated.

``orchid_api.py`` was a runnable standalone app whose ``GET /api/occurrences``
returned raw database latitude/longitude with no authentication and a
wildcard CORS policy. Nothing imported or launched it, so it was removed.

This test keeps the class of defect from returning: any tracked Python file
outside ``app/`` (which ``app.main`` mounts under its own auth dependencies)
that builds its own ``FastAPI()`` and reads occurrence coordinates must gate
them behind ``verify_owner_or_api_key``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_STANDALONE_APP = re.compile(r"\bFastAPI\s*\(")
_READS_COORDINATES = re.compile(r"decimal_(?:latitude|longitude)", re.IGNORECASE)
_EXCLUDED_PREFIXES = ("app/", "tests/", "alembic/", "migrations/")


def _tracked_python_files() -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "*.py"],
        check=True,
        capture_output=True,
    ).stdout
    return [
        entry.decode("utf-8", "surrogateescape")
        for entry in output.split(b"\0")
        if entry
    ]


def standalone_coordinate_apps_without_auth(root: Path, paths: list[str]) -> list[str]:
    offenders = []
    for relative in paths:
        if relative.startswith(_EXCLUDED_PREFIXES):
            continue
        source = (root / relative).read_text(encoding="utf-8", errors="replace")
        if not _STANDALONE_APP.search(source) or not _READS_COORDINATES.search(source):
            continue
        if "verify_owner_or_api_key" not in source:
            offenders.append(relative)
    return offenders


def test_legacy_orchid_api_is_removed():
    assert "orchid_api.py" not in _tracked_python_files()
    assert not (REPO_ROOT / "orchid_api.py").exists()


def test_no_standalone_app_serves_coordinates_without_owner_check():
    offenders = standalone_coordinate_apps_without_auth(
        REPO_ROOT, _tracked_python_files()
    )
    assert offenders == []


def test_detector_flags_an_unauthenticated_coordinate_app(tmp_path):
    (tmp_path / "leaky_api.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/api/occurrences')\n"
        "def points():\n"
        "    return 'SELECT decimal_latitude, decimal_longitude FROM oc_occurrences'\n"
    )
    (tmp_path / "guarded_api.py").write_text(
        "from fastapi import FastAPI\n"
        "from app.security import verify_owner_or_api_key\n"
        "app = FastAPI()\n"
        "SQL = 'SELECT decimal_latitude, decimal_longitude FROM oc_occurrences'\n"
    )
    assert standalone_coordinate_apps_without_auth(
        tmp_path, ["leaky_api.py", "guarded_api.py"]
    ) == ["leaky_api.py"]
