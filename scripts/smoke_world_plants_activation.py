"""Certify deployed World Plants intake with a harmless fixture.

The script authenticates as the owner, uploads only the committed smoke fixture,
verifies release readback, and records the live readiness report. It never uploads
the production Hassler file and never promotes a release.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.getenv(
    "CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com"
).rstrip("/")
ACCESS_CODE = os.getenv("CALYX_OWNER_ACCESS_CODE", "").strip()
FIXTURE = Path("tests/fixtures/world_plants_activation_smoke.csv")
REPORT_PATH = Path(os.getenv("CALYX_TAXONOMY_READINESS_REPORT", "taxonomy-readiness.json"))


def _json_request(
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str = "",
) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body) if body else {}


def _multipart_upload(token: str) -> tuple[int, dict]:
    boundary = f"----calyx-{uuid.uuid4().hex}"
    acquired_at = datetime.now(UTC).date().isoformat()
    fields = {
        "version_label": "activation-smoke",
        "acquired_at": acquired_at,
        "notes": "Harmless CALYX-TAXONOMY-ACTIVATION-001 smoke fixture; never canonical.",
    }
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="world_plants_activation_smoke.csv"\r\n',
            b"Content-Type: text/csv\r\n\r\n",
            FIXTURE.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = Request(
        f"{BASE_URL}/api/mission-control/taxonomy/releases/inspect",
        data=b"".join(chunks),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body) if body else {}


def main() -> int:
    if not ACCESS_CODE:
        print("FAIL owner_authentication: CALYX_OWNER_ACCESS_CODE is not configured")
        return 1
    if not FIXTURE.is_file():
        print(f"FAIL smoke_fixture_missing: {FIXTURE}")
        return 1

    try:
        status, session = _json_request(
            "/api/mission-control/owner/session",
            method="POST",
            payload={"access_code": ACCESS_CODE},
        )
        token = session.get("token") or session.get("access_token") or ""
        if status != 200 or not token:
            raise RuntimeError("OWNER_SESSION_FAILED")

        status, uploaded = _multipart_upload(token)
        if status != 200:
            raise RuntimeError(f"SMOKE_UPLOAD_HTTP_{status}")
        release_id = str(uploaded.get("release_id") or uploaded.get("snapshot_id") or "")
        if not release_id:
            raise RuntimeError("SMOKE_RELEASE_ID_MISSING")

        status, detail = _json_request(
            f"/api/mission-control/taxonomy/releases/{release_id}", token=token
        )
        if status != 200:
            raise RuntimeError(f"SMOKE_READBACK_HTTP_{status}")
        if str(detail.get("release_id") or detail.get("snapshot_id") or "") != release_id:
            raise RuntimeError("SMOKE_READBACK_ID_MISMATCH")

        status, listing = _json_request(
            "/api/mission-control/taxonomy/releases", token=token
        )
        if status != 200:
            raise RuntimeError(f"SMOKE_LIST_HTTP_{status}")
        release_ids = {
            str(item.get("release_id") or item.get("snapshot_id") or "")
            for item in listing.get("releases", [])
        }
        if release_id not in release_ids:
            raise RuntimeError("SMOKE_RELEASE_NOT_LISTED")

        status, readiness = _json_request(
            "/api/mission-control/taxonomy/readiness", token=token
        )
        if status != 200:
            raise RuntimeError(f"READINESS_HTTP_{status}")
        REPORT_PATH.write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")

        if readiness.get("ready_for_promotion") is not False:
            raise RuntimeError("PROMOTION_MUST_REMAIN_BLOCKED")
        if readiness.get("ready_for_upload") is not True:
            blocked = [
                gate.get("name")
                for gate in readiness.get("gates", [])
                if gate.get("status") != "passed"
                and gate.get("name") != "owner_promotion_approval"
            ]
            raise RuntimeError(f"UPLOAD_READINESS_BLOCKED:{','.join(blocked)}")
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        print(f"FAIL taxonomy_activation: {type(exc).__name__}: {exc}")
        return 1

    print(f"PASS smoke_release_uploaded_and_read_back: {release_id}")
    print(f"PASS ready_for_upload=true; readiness_report={REPORT_PATH}")
    print("PASS ready_for_promotion=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
