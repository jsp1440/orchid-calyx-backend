"""Read-only discovery of the deployed Hassler taxonomy intake state.

This script authenticates with the owner session and performs GET requests only.
It never uploads a release, stages rows, activates taxonomy, or mutates the graph.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("CALYX_BACKEND_URL", "").strip().rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "").strip()
REPORT_PATH = Path(os.environ.get("CALYX_HASSLER_DISCOVERY_REPORT", "calyx-hassler-intake-discovery.json"))
EXPECTED_FILENAME = "WorldOrchids 26-08 (Aug 2 2026).csv"
EXPECTED_SHA256 = "e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f"


def _request(path: str, *, method: str = "GET", payload: dict | None = None, token: str = "") -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    with urlopen(request, timeout=60) as response:
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw) if raw else {}


def _artifact_hash(report: dict) -> str:
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def main() -> int:
    if not BASE_URL or not ACCESS_CODE:
        raise SystemExit("CALYX_BACKEND_URL and CALYX_OWNER_ACCESS_CODE are required")

    session_status, session = _request(
        "/api/mission-control/owner/session-token",
        method="POST",
        payload={"access_code": ACCESS_CODE, "owner": "owner"},
    )
    token = str(session.get("token") or session.get("access_token") or "")
    if session_status != 200 or not token or token == "cookie":
        raise SystemExit("owner session authentication failed")

    migration_status, migration = _request(
        "/api/mission-control/taxonomy/migration-preflight", token=token
    )
    readiness_status, readiness = _request(
        "/api/mission-control/taxonomy/readiness", token=token
    )
    releases_status, releases_payload = _request(
        "/api/mission-control/taxonomy/releases", token=token
    )

    matches = []
    for item in releases_payload.get("releases", []):
        snapshot = item.get("snapshot", {}) if isinstance(item, dict) else {}
        if snapshot.get("filename") == EXPECTED_FILENAME or item.get("release_id") == EXPECTED_SHA256:
            matches.append(
                {
                    "release_id": item.get("release_id"),
                    "filename": snapshot.get("filename"),
                    "sha256": snapshot.get("sha256"),
                    "version_label": snapshot.get("version_label"),
                    "acquired_at": snapshot.get("acquired_at"),
                    "state": item.get("state"),
                    "automatic_promotion": item.get("automatic_promotion"),
                }
            )

    exact_match = any(
        item.get("release_id") == EXPECTED_SHA256
        or item.get("sha256") == EXPECTED_SHA256
        for item in matches
    )
    report = {
        "schema_version": "1.0",
        "read_only": True,
        "production_mutation": False,
        "upload_invoked": False,
        "staging_invoked": False,
        "taxonomy_activation_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "expected_filename": EXPECTED_FILENAME,
        "expected_sha256": EXPECTED_SHA256,
        "http": {
            "migration_preflight": migration_status,
            "readiness": readiness_status,
            "releases": releases_status,
        },
        "migration_state": migration.get("state"),
        "migration_schema_complete": migration.get("schema_complete"),
        "pipeline_state": readiness.get("pipeline_state"),
        "next_job": readiness.get("next_job"),
        "release_count": len(releases_payload.get("releases", [])),
        "matching_releases": matches,
        "real_release_present": exact_match,
        "bounded_smoke_ready": bool(exact_match and migration.get("schema_complete")),
    }
    report["artifact_hash"] = _artifact_hash(report)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
