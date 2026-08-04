"""Verify deployed Knowledge Graph dry-run readiness without starting a run."""
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


def evaluate_preflight(report: dict) -> tuple[bool, list[str]]:
    ready = report.get("ready_for_live_resumable_dry_run") is True
    blockers = [str(item) for item in report.get("blockers", [])]
    if not ready and not blockers:
        blockers.append("preflight_not_ready_without_reported_blocker")
    return ready, blockers


def main() -> int:
    if not ACCESS_CODE:
        print("FAIL owner_session: CALYX_OWNER_ACCESS_CODE not set")
        return 1

    try:
        status, _ = request("/health")
        print(f"{'PASS' if status == 200 else 'FAIL'} health: {status}")
        if status != 200:
            return 1

        status, session = request(
            "/api/mission-control/owner/session",
            method="POST",
            payload={"access_code": ACCESS_CODE},
        )
        token = session.get("token") or session.get("access_token") or ""
        print(f"{'PASS' if status == 200 and token else 'FAIL'} owner_session: {status}")
        if status != 200 or not token:
            return 1

        status, report = request(
            "/api/platform/knowledge-graph/deployment-preflight",
            token=token,
        )
        print(f"{'PASS' if status == 200 else 'FAIL'} deployment_preflight: {status}")
        if status != 200:
            return 1

        ready, blockers = evaluate_preflight(report)
        print(json.dumps(report, indent=2, sort_keys=True))
        if not ready:
            for blocker in blockers:
                print(f"BLOCKER {blocker}")
            return 2

        print("PASS ready_for_live_resumable_dry_run: true")
        print("SAFE STOP: no dry run was started")
        return 0
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"FAIL request: {exc!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
