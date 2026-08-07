"""Fail-closed persistent-storage and restart certification for My Conservatory."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

_BOOT_ID = str(uuid4())
_PROBE_FILE = ".conservatory-restart-probe.json"
_CERTIFICATION_FILE = ".conservatory-restart-certified.json"


@dataclass(frozen=True)
class ConservatoryGate:
    name: str
    passed: bool
    evidence: str
    blocking_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def create_restart_probe(root: Path) -> dict[str, Any]:
    """Persist a nonce that can only certify after a subsequent process boot."""
    root.mkdir(parents=True, exist_ok=True)
    token = str(uuid4())
    payload = {
        "token": token,
        "boot_id": _BOOT_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "root": str(root.resolve()),
    }
    (root / _PROBE_FILE).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "token": token,
        "instruction": "Restart the backend, then verify this token through the Conservatory readiness endpoint.",
        "created_at": payload["created_at"],
    }


def verify_restart_probe(root: Path, token: str) -> dict[str, Any]:
    """Certify only when the probe survived and the process boot changed."""
    probe = _read_json(root / _PROBE_FILE)
    if probe is None or probe.get("token") != token:
        raise ValueError("restart probe token was not found")
    if probe.get("root") != str(root.resolve()):
        raise ValueError("restart probe storage path does not match")
    if probe.get("boot_id") == _BOOT_ID:
        raise ValueError("backend restart has not occurred since this probe was created")

    certification = {
        "verified": True,
        "token": token,
        "probe_created_at": probe.get("created_at"),
        "verified_at": datetime.now(UTC).isoformat(),
        "root": str(root.resolve()),
    }
    (root / _CERTIFICATION_FILE).write_text(
        json.dumps(certification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return certification


def build_conservatory_readiness(root: Path) -> dict[str, Any]:
    root_exists = root.exists() and root.is_dir()
    writable = root_exists and os.access(root, os.W_OK)
    persistent_flag = _flag("CALYX_CONSERVATORY_STORAGE_PERSISTENT")
    non_ephemeral_path = not str(root.resolve()).startswith("/tmp/")
    certification = _read_json(root / _CERTIFICATION_FILE)
    restart_verified = bool(
        certification
        and certification.get("verified") is True
        and certification.get("root") == str(root.resolve())
    )

    gates = (
        ConservatoryGate(
            "owner_authentication",
            True,
            "This readiness request passed the owner/API-key dependency.",
        ),
        ConservatoryGate(
            "storage_directory",
            root_exists and writable,
            f"path={root}; exists={root_exists}; writable={writable}",
            None if root_exists and writable else "Configure a writable CALYX_CONSERVATORY_DIR.",
        ),
        ConservatoryGate(
            "non_ephemeral_path",
            non_ephemeral_path,
            f"resolved_path={root.resolve()}",
            None if non_ephemeral_path else "Move Conservatory storage off the temporary filesystem.",
        ),
        ConservatoryGate(
            "persistent_volume_declared",
            persistent_flag,
            "CALYX_CONSERVATORY_STORAGE_PERSISTENT deployment flag checked.",
            None if persistent_flag else "Mount persistent storage and set CALYX_CONSERVATORY_STORAGE_PERSISTENT=true.",
        ),
        ConservatoryGate(
            "restart_survival",
            restart_verified,
            "A persisted probe was read and certified after a different backend process boot."
            if restart_verified
            else "No valid post-restart certification receipt is present.",
            None if restart_verified else "Create a restart probe, restart the backend, and verify the probe token.",
        ),
    )
    ready = all(gate.passed for gate in gates)
    return {
        "ready_for_collection_entry": ready,
        "gates": [gate.as_dict() for gate in gates],
        "storage_path": str(root),
        "checked_at": datetime.now(UTC).isoformat(),
        "instruction": (
            "Begin with three test plants, print and scan their labels, then confirm the records remain available."
            if ready
            else "Do not enter the production collection yet; resolve every blocked readiness gate."
        ),
        "read_only": True,
    }
