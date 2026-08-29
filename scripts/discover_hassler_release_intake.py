"""Read-only discovery of the deployed Hassler taxonomy intake state.

This script authenticates with the owner session and performs GET requests only.
It never uploads a release, stages rows, activates taxonomy, or mutates the graph.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("CALYX_BACKEND_URL", "").strip().rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "").strip()
REPORT_PATH = Path(
    os.environ.get(
        "CALYX_HASSLER_DISCOVERY_REPORT", "calyx-hassler-intake-discovery.json"
    )
)
EXPECTED_FILENAME = "WorldOrchids 26-08 (Aug 2 2026).csv"
EXPECTED_SHA256 = "e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f"


def _request(
    path: str, *, method: str = "GET", payload: dict | None = None, token: str = ""
) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "******"
    request = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    with urlopen(request, timeout=60) as response:
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw) if raw else {}


def _artifact_hash(report: dict) -> str:
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _optional_request(path: str, *, token: str) -> tuple[int | None, dict | None]:
    """GET a path that may legitimately 404, without aborting discovery."""
    try:
        return _request(path, token=token)
    except HTTPError as exc:
        return exc.code, None
    except (URLError, OSError, ValueError):
        return None, None


def _lifecycle_module():
    """Import the shared lifecycle contract from the repository root."""
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    import runtime.hassler_release_lifecycle as lifecycle_module

    return lifecycle_module


def main() -> int:
    lifecycle_api = _lifecycle_module()
    Evidence = lifecycle_api.Evidence
    build_owner_exception_receipt = lifecycle_api.build_owner_exception_receipt
    build_release_status_block = lifecycle_api.build_release_status_block
    classify_release_lifecycle = lifecycle_api.classify_release_lifecycle
    enumerate_downstream_relink_impact = (
        lifecycle_api.enumerate_downstream_relink_impact
    )

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
    detail_status, detail_payload = _optional_request(
        f"/api/mission-control/taxonomy/releases/{EXPECTED_SHA256}", token=token
    )
    staging_status, staging_payload = _optional_request(
        f"/api/mission-control/taxonomy/releases/{EXPECTED_SHA256}/staging",
        token=token,
    )

    matches = []
    for item in releases_payload.get("releases", []):
        snapshot = item.get("snapshot", {}) if isinstance(item, dict) else {}
        if (
            snapshot.get("filename") == EXPECTED_FILENAME
            or item.get("release_id") == EXPECTED_SHA256
        ):
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

    gates = readiness.get("gates", [])
    blocked_gates = [
        {
            "name": gate.get("name"),
            "blocking_reason": gate.get("blocking_reason"),
            "evidence": gate.get("evidence"),
        }
        for gate in gates
        if gate.get("status") != "passed"
        and gate.get("name") != "owner_promotion_approval"
    ]
    exact_match = any(
        item.get("release_id") == EXPECTED_SHA256
        or item.get("sha256") == EXPECTED_SHA256
        for item in matches
    )
    report = {
        "schema_version": "1.2",
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
        "ready_for_upload": readiness.get("ready_for_upload"),
        "blocked_gates": blocked_gates,
        "release_count": len(releases_payload.get("releases", [])),
        "matching_releases": matches,
        "real_release_present": exact_match,
        "bounded_smoke_ready": bool(
            exact_match and migration.get("schema_complete") and not blocked_gates
        ),
    }

    lifecycle = classify_release_lifecycle(
        releases=(
            Evidence.of(releases_payload, f"HTTP {releases_status} release list")
            if releases_status == 200
            else Evidence.unavailable(f"release list HTTP {releases_status}")
        ),
        release_detail=(
            Evidence.of(detail_payload, f"HTTP {detail_status} release readback")
            if detail_status == 200
            else Evidence.of(None, "release readback HTTP 404")
            if detail_status == 404
            else Evidence.unavailable(f"release readback HTTP {detail_status}")
        ),
        readiness=(
            Evidence.of(readiness, f"HTTP {readiness_status} readiness gates")
            if readiness_status == 200
            else Evidence.unavailable(f"readiness HTTP {readiness_status}")
        ),
        staging=(
            Evidence.of(staging_payload, f"HTTP {staging_status} durable staging state")
            if staging_status == 200
            else Evidence.unavailable(f"durable staging state HTTP {staging_status}")
        ),
        active_taxonomy=Evidence.unavailable(
            "no canonical taxonomy activation probe exists; activation remains a "
            "separate owner gate and is never inferred from intake or staging"
        ),
    )
    change_report = (staging_payload or {}).get("change_report")
    downstream = enumerate_downstream_relink_impact(
        change_report=(
            Evidence.of(change_report, "durable change report")
            if isinstance(change_report, dict)
            else Evidence.unavailable(
                "no durable change report exists for the exact release"
            )
        )
    )
    report["lifecycle"] = lifecycle
    report["downstream_relink_impact"] = downstream
    report["status_block"] = build_release_status_block(
        lifecycle=lifecycle, downstream=downstream
    )
    report["http"]["release_readback"] = detail_status
    report["http"]["staging_state"] = staging_status

    if lifecycle["lifecycle_state"] in {"ABSENT", "UNAVAILABLE"}:
        report["owner_exception_receipt"] = build_owner_exception_receipt(
            lifecycle=lifecycle,
            blocking_reason=(
                "The exact Hassler release is not durably present and a production "
                "intake write requires explicit owner authorization."
                if lifecycle["lifecycle_state"] == "ABSENT"
                else "Production release state could not be read; absence must not "
                "be assumed and no write may be prepared against unknown state."
            ),
            next_executable_action=(
                "Run scripts/upload_hassler_release_guarded.py against the exact "
                f"source '{EXPECTED_FILENAME}' with --execute and "
                "CALYX_HASSLER_UPLOAD_CONFIRMATION=UPLOAD_WORLD_ORCHIDS_26_08."
                if lifecycle["lifecycle_state"] == "ABSENT"
                else "Restore read access to the deployed Mission Control taxonomy "
                "endpoints and re-run this read-only discovery probe."
            ),
            responsible_party="repository owner",
            prepared_action=(
                {
                    "script": "scripts/upload_hassler_release_guarded.py",
                    "mode": "--execute",
                    "confirmation_token_env": "CALYX_HASSLER_UPLOAD_CONFIRMATION",
                    "guards": [
                        "exact filename, byte size and SHA-256 validated before any request",
                        "existing durable release short-circuits to NO_OP_ALREADY_PRESENT",
                        "ready_for_upload and next_job asserted before upload",
                        "durable readback asserted after upload",
                        "staging, activation and Knowledge Graph writes never invoked",
                    ],
                }
                if lifecycle["lifecycle_state"] == "ABSENT"
                else None
            ),
        )

    report["artifact_hash"] = _artifact_hash(report)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
