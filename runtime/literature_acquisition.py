"""Filesystem-backed Literature Acquisition Service for the Research Station.

Provides a read-only view of completed or in-progress literature runs stored
under CALYX_LITERATURE_ACQUISITION_PATH (default /tmp/calyx/literature-acquisition).

Each run is a directory at:
    <root>/runs/<run_id>/

Required files written by the literature pipeline:
    manifest.json    — run identity, source, and status
    readiness.json   — source_sha256, extraction_sha256, evidence_span_count,
                       ready_for_review

Optional files (read by the research station when present):
    candidate_handoffs.json — list of candidate-knowledge handoff records

This module does NOT write run data; it reads runs that were created by an
upstream literature-pipeline step.  If no run directory exists, the service
returns a "not_ready" readiness record rather than raising, so downstream
callers can distinguish UNAVAILABLE from ERROR.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "calyx-literature-acquisition/1"


class LiteratureAcquisitionService:
    """Read-only accessor for literature run outputs.

    Args:
        root: Root directory produced by the literature pipeline.
              Defaults to the CALYX_LITERATURE_ACQUISITION_PATH env var,
              then /tmp/calyx/literature-acquisition.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(
            os.getenv(
                "CALYX_LITERATURE_ACQUISITION_PATH",
                "/tmp/calyx/literature-acquisition",
            )
        )

    def _run_dir(self, run_id: str) -> Path:
        """Return the directory for a literature run.

        Does not verify that the directory or its contents exist.
        Callers that need verified data should use ``readiness()``.
        """
        clean = run_id.strip()
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("LITERATURE_RUN_ID_INVALID")
        return self._root / "runs" / clean

    def readiness(self, run_id: str) -> dict[str, Any]:
        """Return the readiness record for a literature run.

        Returns a structured dict regardless of whether the run directory
        or readiness file exists so callers can distinguish UNAVAILABLE from
        ERROR without an exception path.

        Schema of the returned dict:
            source_sha256        (str | None)
            extraction_sha256    (str | None)
            evidence_span_count  (int)
            ready_for_review     (bool)
            run_id               (str)
            status               (str)
        """
        run_dir = self._run_dir(run_id)
        readiness_path = run_dir / "readiness.json"

        if not readiness_path.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "status": "UNAVAILABLE",
                "source_sha256": None,
                "extraction_sha256": None,
                "evidence_span_count": 0,
                "ready_for_review": False,
                "note": "run directory or readiness.json not found",
            }

        try:
            payload = json.loads(readiness_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "status": "READ_ERROR",
                "source_sha256": None,
                "extraction_sha256": None,
                "evidence_span_count": 0,
                "ready_for_review": False,
                "error": str(exc),
            }

        if not isinstance(payload, dict):
            return {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "status": "SCHEMA_ERROR",
                "source_sha256": None,
                "extraction_sha256": None,
                "evidence_span_count": 0,
                "ready_for_review": False,
                "error": "readiness.json is not a JSON object",
            }

        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "status": str(payload.get("status", "UNKNOWN")),
            "source_sha256": payload.get("source_sha256"),
            "extraction_sha256": payload.get("extraction_sha256"),
            "evidence_span_count": int(payload.get("evidence_span_count", 0)),
            "ready_for_review": bool(payload.get("ready_for_review", False)),
        }

    def list_runs(self) -> list[str]:
        """Return sorted run IDs found under the root."""
        runs_dir = self._root / "runs"
        if not runs_dir.is_dir():
            return []
        return sorted(
            entry.name
            for entry in runs_dir.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        )

    def status(self) -> dict[str, Any]:
        """Return diagnostic status for the literature acquisition store."""
        runs_dir = self._root / "runs"
        run_count = len(self.list_runs()) if runs_dir.is_dir() else 0
        return {
            "schema_version": SCHEMA_VERSION,
            "root": str(self._root),
            "runs_dir_exists": runs_dir.is_dir(),
            "run_count": run_count,
        }
