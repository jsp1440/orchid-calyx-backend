from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

BASE_URL = os.environ.get("MISSION_CONTROL_BASE_URL", "https://orchid-calyx-backend.onrender.com").rstrip("/")
TOKEN = os.environ.get("MISSION_CONTROL_SMOKE_TOKEN", "").strip()
TIMEOUT = float(os.environ.get("MISSION_CONTROL_SMOKE_TIMEOUT", "30"))

EXPECTED = {
    "/api/executive/state": "MISSION-CONTROL-TELEMETRY-001A",
    "/api/executive/harvesters": "MISSION-CONTROL-TELEMETRY-001B",
    "/api/executive/intelligence": "MISSION-CONTROL-TELEMETRY-001D",
    "/api/executive/frontend-contract": "MISSION-CONTROL-TELEMETRY-001E",
    "/api/executive/release-readiness": "MISSION-CONTROL-TELEMETRY-001F",
}


def _request(path: str, *, authenticated: bool) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if authenticated:
        if not TOKEN:
            raise RuntimeError("MISSION_CONTROL_SMOKE_TOKEN is required for authenticated production smoke tests")
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(f"{BASE_URL}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            payload = {"raw": body}
        return exc.code, payload


def main() -> int:
    results: list[dict[str, Any]] = []
    health_status, health = _request("/health", authenticated=False)
    results.append({"endpoint": "/health", "status": health_status, "passed": health_status == 200})

    for path, expected_contract in EXPECTED.items():
        status, payload = _request(path, authenticated=True)
        observed = payload.get("contract_version")
        passed = status == 200 and observed == expected_contract
        results.append(
            {
                "endpoint": path,
                "status": status,
                "expected_contract": expected_contract,
                "observed_contract": observed,
                "passed": passed,
            }
        )

    readiness = next((item for item in results if item["endpoint"] == "/api/executive/release-readiness"), None)
    failed = [item for item in results if not item["passed"]]
    report = {
        "base_url": BASE_URL,
        "passed": not failed,
        "results": results,
        "failed_endpoints": [item["endpoint"] for item in failed],
        "release_readiness_contract_verified": bool(readiness and readiness["passed"]),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"base_url": BASE_URL, "passed": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(2)
