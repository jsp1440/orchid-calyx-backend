"""Guarded operator client for the real Hassler WorldOrchids release.

Dry-run is the default. Production upload requires both ``--execute`` and the
exact confirmation token in ``CALYX_HASSLER_UPLOAD_CONFIRMATION``. The client
uploads/inspects the immutable release and verifies readback only. It never
invokes staging, taxonomy activation, publication, or Knowledge Graph writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx

EXPECTED_FILENAME = "WorldOrchids 26-08 (Aug 2 2026).csv"
EXPECTED_SIZE_BYTES = 11_529_836
EXPECTED_SHA256 = "e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f"
VERSION_LABEL = "26-08"
ACQUIRED_AT = "2026-08-02"
EXECUTION_CONFIRMATION = "UPLOAD_WORLD_ORCHIDS_26_08"
DEFAULT_REPORT = "calyx-hassler-upload-receipt.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"source file does not exist: {path}")
    if path.name != EXPECTED_FILENAME:
        raise ValueError(f"unexpected source filename: {path.name}")
    size = path.stat().st_size
    if size != EXPECTED_SIZE_BYTES:
        raise ValueError(f"unexpected source size: {size}")
    checksum = sha256_file(path)
    if checksum != EXPECTED_SHA256:
        raise ValueError(f"unexpected source sha256: {checksum}")
    return {"filename": path.name, "size_bytes": size, "sha256": checksum}


def _assert_release_report(report: dict[str, Any]) -> None:
    snapshot = report.get("snapshot")
    if not isinstance(snapshot, dict):
        raise TypeError("upload response is missing snapshot")
    expected = {
        "release_id": EXPECTED_SHA256,
        "sha256": EXPECTED_SHA256,
        "filename": EXPECTED_FILENAME,
        "version_label": VERSION_LABEL,
        "acquired_at": ACQUIRED_AT,
    }
    actual = {
        "release_id": report.get("release_id"),
        "sha256": snapshot.get("sha256"),
        "filename": snapshot.get("filename"),
        "version_label": snapshot.get("version_label"),
        "acquired_at": snapshot.get("acquired_at"),
    }
    if actual != expected:
        raise RuntimeError(f"release identity mismatch: {actual!r}")
    if report.get("automatic_promotion") is not False:
        raise RuntimeError("automatic promotion must remain false")
    if report.get("durable_storage") != "postgresql":
        raise RuntimeError("durable PostgreSQL storage was not confirmed")


def _owner_token(client: httpx.Client, access_code: str) -> str:
    response = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": access_code, "owner": "owner"},
    )
    response.raise_for_status()
    payload = response.json()
    token = str(payload.get("token") or payload.get("access_token") or "")
    if not token or token == "cookie":
        raise RuntimeError("owner session authentication failed")
    return token


def execute_upload(
    *,
    source_path: Path,
    base_url: str,
    access_code: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    source = validate_source(source_path)
    owns_client = client is None
    if client is None:
        client = httpx.Client(base_url=base_url.rstrip("/"), timeout=120.0)
    try:
        token = _owner_token(client, access_code)
        headers = {"Authorization": f"Bearer {token}"}

        readiness = client.get(
            "/api/mission-control/taxonomy/readiness", headers=headers
        )
        readiness.raise_for_status()
        ready = readiness.json()
        if ready.get("ready_for_upload") is not True:
            raise RuntimeError("Mission Control does not report ready_for_upload=true")
        if ready.get("next_job", {}).get("job") != "upload_world_orchids_release":
            raise RuntimeError(
                "Mission Control next job is not upload_world_orchids_release"
            )

        with source_path.open("rb") as handle:
            uploaded = client.post(
                "/api/mission-control/taxonomy/releases/inspect",
                headers=headers,
                data={
                    "version_label": VERSION_LABEL,
                    "acquired_at": ACQUIRED_AT,
                    "notes": "Guarded real Hassler release intake; no staging or activation authorized.",
                },
                files={"file": (EXPECTED_FILENAME, handle, "text/csv")},
            )
        uploaded.raise_for_status()
        upload_report = uploaded.json()
        _assert_release_report(upload_report)

        readback = client.get(
            f"/api/mission-control/taxonomy/releases/{EXPECTED_SHA256}",
            headers=headers,
        )
        readback.raise_for_status()
        readback_report = readback.json()
        _assert_release_report(readback_report)

        post_readiness = client.get(
            "/api/mission-control/taxonomy/readiness", headers=headers
        )
        post_readiness.raise_for_status()
        post = post_readiness.json()
        if post.get("pipeline_state") != "release_inspected_staging_smoke_required":
            raise RuntimeError("post-upload readiness did not stop at staging smoke")
        if post.get("next_job", {}).get("job") != "verify_taxonomy_staging_smoke":
            raise RuntimeError("post-upload next job is not staging smoke verification")

        receipt = {
            "schema_version": "1.0",
            "status": "passed",
            "source": source,
            "release_id": EXPECTED_SHA256,
            "upload_invoked": True,
            "production_mutation": True,
            "readback_verified": True,
            "post_upload_pipeline_state": post.get("pipeline_state"),
            "next_job": post.get("next_job"),
            "staging_invoked": False,
            "taxonomy_activation_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "automatic_promotion": False,
        }
        canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        receipt["artifact_hash"] = hashlib.sha256(canonical).hexdigest()
        return receipt
    finally:
        if owns_client:
            client.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(os.getenv("CALYX_HASSLER_UPLOAD_REPORT", DEFAULT_REPORT)),
    )
    args = parser.parse_args()

    source = validate_source(args.source)
    if not args.execute:
        report = {
            "schema_version": "1.0",
            "status": "dry_run_passed",
            "source": source,
            "upload_invoked": False,
            "production_mutation": False,
            "staging_invoked": False,
            "taxonomy_activation_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "required_confirmation": EXECUTION_CONFIRMATION,
        }
    else:
        confirmation = os.getenv("CALYX_HASSLER_UPLOAD_CONFIRMATION", "").strip()
        if confirmation != EXECUTION_CONFIRMATION:
            raise SystemExit("explicit Hassler upload confirmation token is required")
        base_url = os.getenv("CALYX_BACKEND_URL", "").strip()
        access_code = os.getenv("CALYX_OWNER_ACCESS_CODE", "").strip()
        if not base_url or not access_code:
            raise SystemExit(
                "CALYX_BACKEND_URL and CALYX_OWNER_ACCESS_CODE are required"
            )
        report = execute_upload(
            source_path=args.source,
            base_url=base_url,
            access_code=access_code,
        )

    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
