from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

OUTPUT_PATH = Path("calyx-eligible-ledger-discovery.json")
BASE_URL = os.environ.get("CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com").rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "").strip()


def call(path: str, method: str = "GET", payload: dict | None = None, token: str = ""):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(req, timeout=45) as response:
        body = response.read().decode()
        return response.status, json.loads(body) if body else {}


def discover() -> dict:
    if not ACCESS_CODE:
        raise RuntimeError("missing owner access code")
    session_status, session = call(
        "/api/mission-control/owner/session-token",
        method="POST",
        payload={"access_code": ACCESS_CODE},
    )
    token = session.get("token") or session.get("access_token") or ""
    if session_status != 200 or not token:
        raise RuntimeError("owner session unavailable")
    discovery_status, report = call(
        "/api/reasoning-ledgers/eligible-for-publication", token=token
    )
    if discovery_status != 200:
        raise RuntimeError(f"discovery failed: HTTP {discovery_status}")
    result = dict(report)
    result.update(
        {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "backend_url": BASE_URL,
            "owner_session_status": session_status,
            "discovery_status": discovery_status,
            "read_only": True,
            "production_mutation": False,
            "publication_endpoint_invoked": False,
        }
    )
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
    result["artifact_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    return result


def main() -> int:
    result = discover()
    rendered = json.dumps(result, indent=2, sort_keys=True, default=str)
    OUTPUT_PATH.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if result.get("eligible_count"):
        first = result["eligible_ledgers"][0]
        print("SELECTED_ELIGIBLE_LEDGER")
        print(f"ledger_id={first['ledger_id']}")
        print(f"version={first['version']}")
        print(f"review_content_hash={first['review_content_hash']}")
    else:
        print("NO_ELIGIBLE_REVIEWED_LEDGER_FOUND")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
