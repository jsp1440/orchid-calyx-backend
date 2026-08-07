#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.preflight_university_activation import preflight

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "ocu_sci_008_durable_sessions.sql"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _https_origin(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.query and not parsed.fragment


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def generate_manifest(*, frontend_commit: str, backend_commit: str, frontend_origin: str, api_origin: str,
                      release_evidence: Path, database_url: str | None = None) -> dict[str, Any]:
    readiness = preflight(release_evidence=release_evidence, database_url=database_url)
    blockers = list(readiness["blockers"])
    if not SHA_RE.fullmatch(frontend_commit):
        blockers.append("frontend commit must be a full lowercase 40-character Git SHA")
    if not SHA_RE.fullmatch(backend_commit):
        blockers.append("backend commit must be a full lowercase 40-character Git SHA")
    if not _https_origin(frontend_origin):
        blockers.append("frontend origin must be an HTTPS origin")
    if not _https_origin(api_origin):
        blockers.append("API origin must be an HTTPS origin")

    migration_digest = _sha256(MIGRATION)
    evidence_digest = _sha256(release_evidence) if release_evidence.exists() else None

    phases = [
        {"phase": 0, "name": "read_only_cutover", "requires": ["canonical frontend deployed", "OCU-SCI-007 pass"],
         "mutations": ["hosting/DNS only"], "university_write_flags": False},
        {"phase": 1, "name": "database_migration", "requires": ["backup/rollback reviewed", "preflight ready"],
         "mutations": ["apply ocu_sci_008_durable_sessions.sql"], "university_write_flags": False},
        {"phase": 2, "name": "post_migration_read_only_verification", "requires": ["schema validation pass"],
         "mutations": [], "university_write_flags": False},
        {"phase": 3, "name": "durable_activation", "requires": ["qualified science reviewer present", "evidence SHA configured"],
         "mutations": ["enable learner auth/session writes/durable flags"], "university_write_flags": True},
        {"phase": 4, "name": "authenticated_e2e", "requires": ["durable capability verified"],
         "mutations": ["test learner session/review records only"], "university_write_flags": True},
    ]
    rollback = {
        "before_phase_3": ["keep session writes disabled", "keep durable flag disabled", "restore prior frontend/domain if cutover fails"],
        "after_phase_3": ["disable session writes", "disable durable flag", "preserve database records for audit; do not delete automatically"],
        "always": ["publication remains disabled", "Candidate Knowledge promotion remains external", "Calyx model calls remain disabled"],
    }

    return {
        "contract": "OCU-SCI-009I-CUTOVER-MANIFEST-001",
        "frontend": {"commit": frontend_commit, "origin": frontend_origin.rstrip("/")},
        "backend": {"commit": backend_commit, "api_origin": api_origin.rstrip("/")},
        "migration": {"path": str(MIGRATION.relative_to(ROOT)), "sha256": migration_digest},
        "release_evidence": {"path": release_evidence.name, "sha256": evidence_digest},
        "preflight": readiness,
        "reviewer_grants": {
            "science": readiness["reviewer_registry"].get("science_grant_count", 0),
            "expert": readiness["reviewer_registry"].get("expert_grant_count", 0),
            "publication": readiness["reviewer_registry"].get("publication_grant_count", 0),
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
    parser = argparse.ArgumentParser(description="Generate a non-mutating Orchid University production cutover manifest")
    parser.add_argument("--frontend-commit", required=True)
    parser.add_argument("--backend-commit", required=True)
    parser.add_argument("--frontend-origin", required=True)
    parser.add_argument("--api-origin", required=True)
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = generate_manifest(frontend_commit=args.frontend_commit, backend_commit=args.backend_commit,
                                 frontend_origin=args.frontend_origin, api_origin=args.api_origin,
                                 release_evidence=args.release_evidence)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"WROTE: {args.output}")
    print("READY" if manifest["ready_for_operator_cutover"] else "BLOCKED")
    return 0 if manifest["ready_for_operator_cutover"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
