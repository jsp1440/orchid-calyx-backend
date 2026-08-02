"""Smoke-test the deployed owner-session and Mission Control backend."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get(
    "CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com"
).rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")


def request(path: str, *, method: str = "GET", payload: dict | None = None, token: str = ""):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(req, timeout=30) as response:
        body = response.read().decode()
        return response.status, json.loads(body) if body else {}


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    try:
        status, _ = request("/health")
        checks.append(("health", status == 200, str(status)))

        if not ACCESS_CODE:
            checks.append(("owner_session", False, "CALYX_OWNER_ACCESS_CODE not set"))
        else:
            status, session = request(
                "/api/mission-control/owner/session",
                method="POST",
                payload={"access_code": ACCESS_CODE},
            )
            token = session.get("token") or session.get("access_token") or ""
            checks.append(("owner_session", status == 200 and bool(token), str(status)))
            if token:
                status, _ = request(
                    "/api/mission-control/owner/session", token=token
                )
                checks.append(("owner_session_validate", status == 200, str(status)))
                status, _ = request(
                    "/api/mission-control/owner/permissions", token=token
                )
                checks.append(("owner_permissions", status == 200, str(status)))

        status, _ = request("/brain/mission-control/chat/status")
        checks.append(("mission_control_chat", status == 200, str(status)))
        status, _ = request("/brain/mission-control/runtime/status")
        checks.append(("runtime_status", status == 200, str(status)))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        checks.append(("request_failure", False, repr(exc)))

    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")
    return 0 if checks and all(passed for _, passed, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
