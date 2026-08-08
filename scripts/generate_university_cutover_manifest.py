#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.preflight_university_activation import preflight
from scripts.validate_university_release_evidence import (
    EvidenceError,
    evidence_digest_bytes,
    release_commits,
    validate_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "ocu_sci_008_durable_sessions.sql"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _https_origin(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.query
        and not parsed.fragment
    )


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_release_evidence(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"release evidence JSON is invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise EvidenceError("evidence root must be a JSON object")
    validate_evidence(data)
    return data


def _release_binding_bytes(payload: bytes) -> dict[str, Any]:
    try:
        data = _parse_release_evidence(payload)
        frontend_sha, backend_sha = release_commits(data)
        return {
            "valid": True,
            "frontend_commit": frontend_sha,
            "backend_commit": backend_sha,
            "frontend_origin": str(data["frontend_origin"]).rstrip("/"),
            "api_origin": str(data["api_origin"]).rstrip("/"),
        }
    except (EvidenceError, KeyError, TypeError, ValueError) as exc:
        return {"valid": False, "error": str(exc)}


def _preflight_from_snapshot(
    payload: bytes | None,
    *,
    database_url: str | None,
) -> dict[str, Any]:
    if payload is None:
        return preflight(release_evidence=None, database_url=database_url)
    with tempfile.TemporaryDirectory(prefix="ocu-release-evidence-") as directory:
        snapshot = Path(directory) / "university-production-evidence.json"
        snapshot.write_bytes(payload)
        return preflight(release_evidence=snapshot, database_url=database_url)


def generate_manifest(
    *,
    frontend_commit: str,
    backend_commit: str,
    frontend_origin: str,
    api_origin: str,
    release_evidence: Path,
    database_url: str | None = None,
) -> dict[str, Any]:
    try:
        evidence_snapshot = release_evidence.read_bytes()
        evidence_read_error: str | None = None
    except OSError as exc:
        evidence_snapshot = None
        evidence_read_error = str(exc)

    readiness = _preflight_from_snapshot(
        evidence_snapshot,
        database_url=database_url,
    )
    blockers = list(readiness["blockers"])
    frontend_commit = frontend_commit.strip().lower()
    backend_commit = backend_commit.strip().lower()
    normalized_frontend_origin = frontend_origin.rstrip("/")
    normalized_api_origin = api_origin.rstrip("/")

    if not SHA_RE.fullmatch(frontend_commit):
        blockers.append("frontend commit must be a full lowercase 40-character Git SHA")
    if not SHA_RE.fullmatch(backend_commit):
        blockers.append("backend commit must be a full lowercase 40-character Git SHA")
    if not _https_origin(frontend_origin):
        blockers.append("frontend origin must be an HTTPS origin")
    if not _https_origin(api_origin):
        blockers.append("API origin must be an HTTPS origin")

    if evidence_snapshot is None:
        binding: dict[str, Any] = {
            "valid": False,
            "error": evidence_read_error or "release evidence unavailable",
        }
    else:
        binding = _release_binding_bytes(evidence_snapshot)
    if not binding.get("valid"):
        blockers.append("release evidence does not contain valid deployed release identities")
    else:
        if frontend_commit != binding["frontend_commit"]:
            blockers.append(
                "frontend commit does not match the release attested by OCU-SCI-007 evidence"
            )
        if backend_commit != binding["backend_commit"]:
            blockers.append(
                "backend commit does not match the release attested by OCU-SCI-007 evidence"
            )
        if normalized_frontend_origin != binding["frontend_origin"]:
            blockers.append(
                "frontend origin does not match the OCU-SCI-007 evidence origin"
            )
        if normalized_api_origin != binding["api_origin"]:
            blockers.append("API origin does not match the OCU-SCI-007 evidence origin")

    migration_digest = _sha256(MIGRATION)
    evidence_digest = (
        evidence_digest_bytes(evidence_snapshot)
        if evidence_snapshot is not None
        else None
    )

    phases = [
        {
            "phase": 0,
            "name": "read_only_cutover",
            "requires": [
                "canonical frontend deployed",
                "OCU-SCI-007 pass with release identities",
            ],
            "mutations": ["hosting/DNS only"],
            "university_write_flags": False,
        },
        {
            "phase": 1,
            "name": "database_migration",
            "requires": ["backup/rollback reviewed", "preflight ready"],
            "mutations": ["apply ocu_sci_008_durable_sessions.sql"],
            "university_write_flags": False,
        },
        {
            "phase": 2,
            "name": "post_migration_read_only_verification",
            "requires": ["schema validation pass"],
            "mutations": [],
            "university_write_flags": False,
        },
        {
            "phase": 3,
            "name": "durable_activation",
            "requires": [
                "qualified science reviewer present",
                "evidence SHA configured",
            ],
            "mutations": ["enable learner auth/session writes/durable flags"],
            "university_write_flags": True,
        },
        {
            "phase": 4,
            "name": "authenticated_e2e",
            "requires": ["durable capability verified"],
            "mutations": ["test learner session/review records only"],
            "university_write_flags": True,
        },
    ]
    rollback = {
        "before_phase_3": [
            "keep session writes disabled",
            "keep durable flag disabled",
            "restore prior frontend/domain if cutover fails",
        ],
        "after_phase_3": [
            "disable session writes",
            "disable durable flag",
            "preserve database records for audit; do not delete automatically",
        ],
        "always": [
            "publication remains disabled",
            "Candidate Knowledge promotion remains external",
            "Calyx model calls remain disabled",
        ],
    }

    return {
        "contract": "OCU-SCI-009I-CUTOVER-MANIFEST-002",
        "release_identity_contract": "OCU-RELEASE-IDENTITY-001",
        "frontend": {
            "commit": frontend_commit,
            "origin": normalized_frontend_origin,
        },
        "backend": {"commit": backend_commit, "api_origin": normalized_api_origin},
        "attested_release": binding,
        "migration": {
            "path": str(MIGRATION.relative_to(ROOT)),
            "sha256": migration_digest,
        },
        "release_evidence": {
            "path": release_evidence.name,
            "sha256": evidence_digest,
            "single_snapshot_bound": evidence_snapshot is not None,
        },
        "preflight": readiness,
        "reviewer_grants": {
            "science": readiness["reviewer_registry"].get("science_grant_count", 0),
            "expert": readiness["reviewer_registry"].get("expert_grant_count", 0),
            "publication": readiness["reviewer_registry"].get(
                "publication_grant_count", 0
            ),
            "subjects_exposed": False,
        },
        "phases": phases,
        "rollback": rollback,
        "blockers": blockers,
        "ready_for_operator_cutover": not blockers,
        "mutations_performed": False,
        "secrets_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a non-mutating Orchid University production cutover manifest"
    )
    parser.add_argument("--frontend-commit", required=True)
    parser.add_argument("--backend-commit", required=True)
    parser.add_argument("--frontend-origin", required=True)
    parser.add_argument("--api-origin", required=True)
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = generate_manifest(
        frontend_commit=args.frontend_commit,
        backend_commit=args.backend_commit,
        frontend_origin=args.frontend_origin,
        api_origin=args.api_origin,
        release_evidence=args.release_evidence,
    )
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"WROTE: {args.output}")
    print("READY" if manifest["ready_for_operator_cutover"] else "BLOCKED")
    return 0 if manifest["ready_for_operator_cutover"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
