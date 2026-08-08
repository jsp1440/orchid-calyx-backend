#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.validate_university_release_evidence import (
    EvidenceError,
    release_commits,
    validate_evidence,
)

FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
FRONTEND_META = re.compile(
    r'<meta\s+name=["\']ocu-release-sha["\']\s+content=["\']([^"\']+)["\']\s*/?>',
    re.IGNORECASE,
)
MANIFEST_CONTRACT = "OCU-SCI-009I-CUTOVER-MANIFEST-003"


class LiveCutoverError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LiveCutoverError(message)


def _fetch_bytes(url: str, accept: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": accept})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = getattr(response, "status", response.getcode())
            _require(status == 200, f"{url} returned HTTP {status}")
            return response.read()
    except urllib.error.HTTPError as exc:
        raise LiveCutoverError(f"{url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise LiveCutoverError(f"{url} is unreachable: {exc.reason}") from exc


def _fetch_text(url: str) -> str:
    return _fetch_bytes(url, "text/html").decode("utf-8", errors="replace")


def _fetch_json(url: str) -> dict[str, Any]:
    try:
        payload = json.loads(_fetch_bytes(url, "application/json").decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise LiveCutoverError(f"{url} did not return valid JSON") from exc
    _require(isinstance(payload, dict), f"{url} JSON root must be an object")
    return payload


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveCutoverError(f"{label} could not be read: {exc}") from exc
    _require(isinstance(payload, dict), f"{label} root must be an object")
    return payload


def _frontend_sha(html: str) -> str:
    match = FRONTEND_META.search(html)
    sha = (match.group(1) if match else "").strip().lower()
    _require(bool(FULL_GIT_SHA.fullmatch(sha)), "live frontend does not expose an attested full Git SHA")
    _require('id="root"' in html or "id='root'" in html, "live frontend is not the canonical React app shell")
    _require("Built on Famous.ai" not in html, "live frontend is still the Famous.ai deployment")
    return sha


def _backend_sha(identity: dict[str, Any]) -> str:
    _require(identity.get("contract") == "OCU-RELEASE-IDENTITY-001", "backend release identity contract mismatch")
    _require(identity.get("service") == "orchid-calyx-backend", "backend release identity service mismatch")
    _require(identity.get("attested") is True, "backend release identity is not attested")
    sha = str(identity.get("commit_sha", "")).strip().lower()
    _require(bool(FULL_GIT_SHA.fullmatch(sha)), "backend release identity does not contain a full Git SHA")
    return sha


def verify_live_cutover(*, evidence_path: Path, manifest_path: Path) -> dict[str, Any]:
    evidence = _load_json_object(evidence_path, "release evidence")
    try:
        validate_evidence(evidence)
        evidence_frontend_sha, evidence_backend_sha = release_commits(evidence)
    except EvidenceError as exc:
        raise LiveCutoverError(f"release evidence is invalid: {exc}") from exc

    manifest = _load_json_object(manifest_path, "cutover manifest")
    _require(manifest.get("contract") == MANIFEST_CONTRACT, f"cutover manifest must use {MANIFEST_CONTRACT}")
    _require(manifest.get("ready_for_operator_cutover") is True, "cutover manifest is not ready for operator cutover")
    _require(manifest.get("mutations_performed") is False, "cutover manifest unexpectedly reports mutations")
    _require(manifest.get("secrets_included") is False, "cutover manifest unexpectedly reports secrets")

    frontend = manifest.get("frontend") or {}
    backend = manifest.get("backend") or {}
    frontend_origin = str(frontend.get("origin", "")).rstrip("/")
    api_origin = str(backend.get("api_origin", "")).rstrip("/")
    manifest_frontend_sha = str(frontend.get("commit", "")).strip().lower()
    manifest_backend_sha = str(backend.get("commit", "")).strip().lower()

    _require(frontend_origin == str(evidence.get("frontend_origin", "")).rstrip("/"), "manifest frontend origin differs from evidence")
    _require(api_origin == str(evidence.get("api_origin", "")).rstrip("/"), "manifest API origin differs from evidence")
    _require(manifest_frontend_sha == evidence_frontend_sha, "manifest frontend commit differs from evidence")
    _require(manifest_backend_sha == evidence_backend_sha, "manifest backend commit differs from evidence")

    html = _fetch_text(f"{frontend_origin}/university/lab")
    live_frontend_sha = _frontend_sha(html)
    live_identity = _fetch_json(f"{api_origin}/release-identity")
    live_backend_sha = _backend_sha(live_identity)
    readiness = _fetch_json(f"{api_origin}/learning/release-readiness")
    capability = _fetch_json(f"{api_origin}/learning/capabilities")

    _require(live_frontend_sha == evidence_frontend_sha, "live frontend release drifted from retained OCU-SCI-007 evidence")
    _require(live_backend_sha == evidence_backend_sha, "live backend release drifted from retained OCU-SCI-007 evidence")

    safe_read_only = {
        "university_enabled": True,
        "session_writes_enabled": False,
        "publication_enabled": False,
        "candidate_knowledge_writes_enabled": False,
        "calyx_model_calls_enabled": False,
        "human_review_required": True,
        "durable_sessions_enabled": False,
    }
    for key, expected in safe_read_only.items():
        _require(readiness.get(key) is expected, f"live release-readiness.{key} must be {expected}")
    _require(capability.get("enabled") is True, "live capabilities.enabled must be true")
    _require(capability.get("session_writes_enabled") is False, "live capabilities.session_writes_enabled must be false")
    _require(capability.get("durable_sessions_enabled") is False, "live capabilities.durable_sessions_enabled must be false")
    _require(capability.get("publication_enabled") is False, "live capabilities.publication_enabled must be false")
    _require(capability.get("candidate_knowledge_writes_enabled") is False, "live capabilities.candidate_knowledge_writes_enabled must be false")
    _require(capability.get("calyx_model_calls_enabled") is False, "live capabilities.calyx_model_calls_enabled must be false")

    return {
        "contract": "OCU-SCI-009L-LIVE-DRIFT-001",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "result": "pass",
        "frontend_origin": frontend_origin,
        "api_origin": api_origin,
        "frontend_commit": live_frontend_sha,
        "backend_commit": live_backend_sha,
        "release_identity_contract": "OCU-RELEASE-IDENTITY-001",
        "release_evidence_schema": evidence.get("schema_version"),
        "cutover_manifest_contract": manifest.get("contract"),
        "safe_pre_activation_state": True,
        "mutations_performed": False,
        "secrets_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live Orchid University releases have not drifted before activation")
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--cutover-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_live_cutover(evidence_path=args.release_evidence, manifest_path=args.cutover_manifest)
    except (LiveCutoverError, OSError, TypeError, ValueError) as exc:
        result = {
            "contract": "OCU-SCI-009L-LIVE-DRIFT-001",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "result": "fail",
            "error": str(exc),
            "mutations_performed": False,
            "secrets_included": False,
        }
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"BLOCKED: {exc}")
        return 1
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PASS: live University releases match retained evidence and remain safely read-only")
    print(f"WROTE: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
