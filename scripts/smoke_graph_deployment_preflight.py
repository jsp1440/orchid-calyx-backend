"""Verify deployed Knowledge Graph dry-run readiness without starting a run."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com").rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")
EVIDENCE_PATH = Path(os.environ.get("CALYX_PREFLIGHT_EVIDENCE_PATH", "calyx-deployed-preflight-evidence.json"))
COMMIT_SHA = os.environ.get("GITHUB_SHA", "")


def request(path: str, *, method: str = "GET", payload: dict | None = None, token: str = ""):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(req, timeout=30) as response:
        body = response.read().decode()
        return response.status, json.loads(body) if body else {}


def step_request(step: str, path: str, **kwargs):
    try:
        return request(path, **kwargs)
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"FAIL {step}: HTTP {exc.code} {body}".rstrip())
        raise
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"FAIL {step}: {exc!r}")
        raise


def evaluate_preflight(report: dict) -> tuple[bool, list[str]]:
    ready = report.get("ready_for_live_resumable_dry_run") is True
    blockers = [str(item) for item in report.get("blockers", [])]
    if not ready and not blockers:
        blockers.append("preflight_not_ready_without_reported_blocker")
    return ready, sorted(set(blockers))


def build_evidence(*, report: dict[str, Any], ready: bool, blockers: list[str], health_status: int, owner_session_status: int, preflight_status: int) -> dict[str, Any]:
    evidence = {
        "schema_version": "1.1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "backend_url": BASE_URL,
        "deployed_commit_sha": COMMIT_SHA,
        "health_status": health_status,
        "owner_session_status": owner_session_status,
        "preflight_status": preflight_status,
        "ready_for_live_resumable_dry_run": ready,
        "blockers": sorted(set(blockers)),
        "report": report,
        "dry_run_started": False,
        "production_action_authorized": False,
    }
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
    evidence["artifact_hash"] = sha256(canonical.encode()).hexdigest()
    return evidence


def write_evidence(evidence: dict[str, Any]) -> None:
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def main() -> int:
    health_status = owner_session_status = preflight_status = 0
    report: dict[str, Any] = {}
    blockers: list[str] = []
    ready = False
    try:
        health_status, _ = step_request("health", "/health")
        print(f"{'PASS' if health_status == 200 else 'FAIL'} health: {health_status}")
        if health_status != 200:
            blockers.append("health_check_failed")
            return_code = 1
        elif not ACCESS_CODE:
            blockers.append("missing:CALYX_OWNER_ACCESS_CODE")
            print("FAIL owner_session: CALYX_OWNER_ACCESS_CODE not set")
            return_code = 1
        else:
            return_code = 0

        token = ""
        if return_code == 0:
            owner_session_status, session = step_request(
                "owner_session",
                "/api/mission-control/owner/session-token",
                method="POST",
                payload={"access_code": ACCESS_CODE, "owner": "owner"},
            )
            token = session.get("token") or session.get("access_token") or ""
            print(f"{'PASS' if owner_session_status == 200 and token and token != 'cookie' else 'FAIL'} owner_session: {owner_session_status}")
            if owner_session_status != 200 or not token or token == "cookie":
                blockers.append("owner_session_failed")
                return_code = 1

        if return_code == 0:
            preflight_status, report = step_request(
                "deployment_preflight",
                "/api/platform/knowledge-graph/deployment-preflight",
                token=token,
            )
            print(f"{'PASS' if preflight_status == 200 else 'FAIL'} deployment_preflight: {preflight_status}")
            if preflight_status != 200:
                blockers.append("deployment_preflight_failed")
                return_code = 1

        if return_code == 0:
            ready, report_blockers = evaluate_preflight(report)
            blockers.extend(report_blockers)
            print(json.dumps(report, indent=2, sort_keys=True))
            if not ready:
                for blocker in sorted(set(blockers)):
                    print(f"BLOCKER {blocker}")
                return_code = 2
            else:
                print("PASS ready_for_live_resumable_dry_run: true")
                print("SAFE STOP: no dry run was started")

        write_evidence(build_evidence(report=report, ready=ready, blockers=blockers, health_status=health_status, owner_session_status=owner_session_status, preflight_status=preflight_status))
        return return_code
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        blockers.append(f"request_failed:{type(exc).__name__}")
        write_evidence(build_evidence(report=report, ready=False, blockers=blockers, health_status=health_status, owner_session_status=owner_session_status, preflight_status=preflight_status))
        return 1


if __name__ == "__main__":
    sys.exit(main())
