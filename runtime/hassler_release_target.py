"""Validated, data-driven identity for the current Hassler WorldOrchids release.

The active intake target is configuration, not application code.  Operators may
point ``CALYX_HASSLER_RELEASE_MANIFEST`` at a newly verified manifest to inspect
or upload the next release without editing Python.  The repository manifest is
the conservative default and retains the currently verified August 2026 target.

Loading a target grants no upload, staging, activation, relink, publication, or
Knowledge Graph authority.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1] / "config" / "hassler-release-target.json"
)


@dataclass(frozen=True)
class HasslerReleaseTarget:
    filename: str
    size_bytes: int
    sha256: str
    version_label: str
    acquired_at: str
    execution_confirmation: str
    manifest_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "version_label": self.version_label,
            "acquired_at": self.acquired_at,
            "execution_confirmation": self.execution_confirmation,
            "manifest_path": self.manifest_path,
            "automatic_promotion": False,
            "execution_authorized": False,
            "taxonomy_activation_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Hassler release manifest requires non-empty {key}")
    return value.strip()


def load_hassler_release_target(path: str | Path | None = None) -> HasslerReleaseTarget:
    """Load and strictly validate one exact release identity.

    ``path`` wins over the environment; otherwise
    ``CALYX_HASSLER_RELEASE_MANIFEST`` may select a new verified manifest without
    a code change.  If neither is supplied the repository's reviewed manifest is
    used.
    """
    selected = Path(
        path
        or os.environ.get("CALYX_HASSLER_RELEASE_MANIFEST", "").strip()
        or _DEFAULT_MANIFEST
    ).expanduser()
    if not selected.is_file():
        raise ValueError(f"Hassler release manifest does not exist: {selected}")
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Hassler release manifest is unreadable: {selected}") from exc
    if not isinstance(payload, dict):
        raise TypeError("Hassler release manifest must be a JSON object")

    filename = _required_text(payload, "filename")
    if Path(filename).name != filename:
        raise ValueError("Hassler release filename must be a basename, not a path")

    size_bytes = payload.get("size_bytes")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes <= 0
    ):
        raise ValueError(
            "Hassler release manifest requires positive integer size_bytes"
        )

    sha256 = _required_text(payload, "sha256").lower()
    if _SHA256.fullmatch(sha256) is None:
        raise ValueError(
            "Hassler release manifest sha256 must be 64 lowercase hex characters"
        )

    version_label = _required_text(payload, "version_label")
    acquired_at = _required_text(payload, "acquired_at")
    try:
        date.fromisoformat(acquired_at)
    except ValueError as exc:
        raise ValueError(
            "Hassler release manifest acquired_at must be YYYY-MM-DD"
        ) from exc

    execution_confirmation = _required_text(payload, "execution_confirmation")
    if not execution_confirmation.startswith("UPLOAD_WORLD_ORCHIDS_"):
        raise ValueError(
            "Hassler release execution_confirmation must use the guarded UPLOAD_WORLD_ORCHIDS_ prefix"
        )

    return HasslerReleaseTarget(
        filename=filename,
        size_bytes=size_bytes,
        sha256=sha256,
        version_label=version_label,
        acquired_at=acquired_at,
        execution_confirmation=execution_confirmation,
        manifest_path=str(selected.resolve()),
    )
