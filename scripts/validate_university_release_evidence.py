#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

EXPECTED_CHAPTER = "BITB-CHAPTER-ORCHID-FLOWERING-001"
EXPECTED_LAB = "OCU-LAB-FAILURE-TO-BLOOM-001"
EXPECTED_READINESS = {
    "university_enabled": True,
    "read_only_ready": True,
    "session_writes_enabled": False,
    "publication_enabled": False,
    "candidate_knowledge_writes_enabled": False,
    "calyx_model_calls_enabled": False,
    "human_review_required": True,
}
FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class EvidenceError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def release_commits(data: dict[str, Any]) -> tuple[str, str]:
    frontend = data.get("frontend")
    backend = data.get("backend")
    _require(isinstance(frontend, Mapping), "frontend must be a JSON object")
    _require(isinstance(backend, Mapping), "backend must be a JSON object")
    identity = backend.get("release_identity")
    _require(
        isinstance(identity, Mapping),
        "backend.release_identity must be a JSON object",
    )
    frontend_sha = str(frontend.get("release_commit_sha", "")).strip().lower()
    backend_sha = str(identity.get("commit_sha", "")).strip().lower()
    _require(
        bool(FULL_GIT_SHA.fullmatch(frontend_sha)),
        "frontend release commit must be a full Git SHA",
    )
    _require(
        identity.get("contract") == "OCU-RELEASE-IDENTITY-001",
        "backend release identity contract mismatch",
    )
    _require(
        identity.get("service") == "orchid-calyx-backend",
        "backend release identity service mismatch",
    )
    _require(
        identity.get("attested") is True,
        "backend release identity must be attested",
    )
    _require(
        bool(FULL_GIT_SHA.fullmatch(backend_sha)),
        "backend release commit must be a full Git SHA",
    )
    return frontend_sha, backend_sha


def validate_evidence(data: dict[str, Any]) -> None:
    _require(data.get("schema_version") == "1.1.0", "schema_version must be 1.1.0")
    _require(data.get("verification") == "OCU-SCI-007", "verification must be OCU-SCI-007")
    _require(
        data.get("release_identity_contract") == "OCU-RELEASE-IDENTITY-001",
        "release_identity_contract must be OCU-RELEASE-IDENTITY-001",
    )
    _require(data.get("result") == "pass", "release evidence result must be pass")
    _require(bool(data.get("started_at")), "started_at is required")
    _require(bool(data.get("completed_at")), "completed_at is required")
    _require(
        str(data.get("frontend_origin", "")).startswith("https://"),
        "frontend_origin must use https",
    )
    _require(
        str(data.get("api_origin", "")).startswith("https://"),
        "api_origin must use https",
    )

    frontend = data.get("frontend")
    backend = data.get("backend")
    _require(isinstance(frontend, Mapping), "frontend must be a JSON object")
    _require(isinstance(backend, Mapping), "backend must be a JSON object")
    _require(
        frontend.get("canonical_app_shell") is True,
        "canonical frontend shell must be verified",
    )
    _require(frontend.get("status") == 200, "University frontend route must return HTTP 200")

    readiness = backend.get("readiness")
    _require(isinstance(readiness, Mapping), "backend.readiness must be a JSON object")
    for key, expected in EXPECTED_READINESS.items():
        _require(
            readiness.get(key) is expected,
            f"backend.readiness.{key} must be {expected}",
        )

    capability = backend.get("capability")
    _require(isinstance(capability, Mapping), "backend.capability must be a JSON object")
    _require(capability.get("enabled") is True, "University capability must be enabled")
    _require(
        capability.get("session_writes_enabled") is False,
        "session writes must remain disabled",
    )

    catalog = backend.get("catalog")
    _require(isinstance(catalog, Mapping), "backend.catalog must be a JSON object")
    _require(catalog.get("chapter_id") == EXPECTED_CHAPTER, "unexpected chapter id")
    _require(catalog.get("laboratory_id") == EXPECTED_LAB, "unexpected laboratory id")
    _require(int(backend.get("chapter_sections", 0)) > 0, "chapter must contain sections")
    _require(
        int(backend.get("laboratory_evidence_items", 0)) > 0,
        "laboratory must contain evidence",
    )
    release_commits(data)


def evidence_digest_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def evidence_digest(path: Path) -> str:
    return evidence_digest_bytes(path.read_bytes())


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: validate_university_release_evidence.py <university-production-evidence.json>",
            file=sys.stderr,
        )
        return 2
    path = Path(sys.argv[1])
    try:
        payload = path.read_bytes()
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise EvidenceError("evidence root must be a JSON object")
        validate_evidence(data)
        frontend_sha, backend_sha = release_commits(data)
        digest = evidence_digest_bytes(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, EvidenceError, ValueError, TypeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print("VALID: OCU-SCI-007 production evidence")
    print(f"FRONTEND_RELEASE_SHA={frontend_sha}")
    print(f"BACKEND_RELEASE_SHA={backend_sha}")
    print(f"OCU_UNIVERSITY_RELEASE_EVIDENCE_ID={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
