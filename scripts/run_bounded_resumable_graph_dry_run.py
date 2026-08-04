"""Run one bounded resumable Knowledge Graph dry-run step and emit evidence.

This operator creates a dry-run session and processes at most one small staging
batch. It never invokes a production publication endpoint.
"""
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

BASE_URL = os.environ.get("CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com").strip().rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")
EVIDENCE_PATH = Path(os.environ.get("CALYX_BOUNDED_DRY_RUN_EVIDENCE_PATH", "calyx-bounded-dry-run-evidence.json"))
PREFERRED_DOMAINS = ("taxonomy", "species", "occurrences", "literature", "traits", "media")


def request(path: str, *, method: str = "GET", payload: dict | None = None, token: str = "") -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=120) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else {}
    except HTTPError as exc:
        response_body = exc.read().decode(errors="replace")[:1000]
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {response_body}") from exc


def choose_domain(ready_domains: list[str]) -> str:
    ready = {str(item) for item in ready_domains}
    for domain in PREFERRED_DOMAINS:
        if domain in ready:
            return domain
    if ready:
        return sorted(ready)[0]
    raise ValueError("no_ready_domains")


def build_evidence(*, domain: str, session: dict[str, Any], resume: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "backend_url": BASE_URL,
        "domain": domain,
        "bounds": {"batch_size": 100, "max_batches_per_step": 1, "domains": 1},
        "session": session,
        "resume": resume,
        "report": report,
        "production_graph_mutation": False,
        "production_publication_authorized": False,
        "publication_endpoint_invoked": False,
    }
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
    evidence["artifact_hash"] = sha256(canonical.encode()).hexdigest()
    return evidence


def write_evidence(evidence: dict[str, Any]) -> None:
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def main() -> int:
    if not ACCESS_CODE:
        print("FAIL CALYX_OWNER_ACCESS_CODE not set")
        return 1
    try:
        status, login = request(
            "/api/mission-control/owner/session-token",
            method="POST",
            payload={"access_code": ACCESS_CODE},
        )
        token = str(login.get("token") or "")
        if status != 200 or not token:
            print(f"FAIL owner_session_token: {status}")
            return 1

        status, inventory = request("/api/platform/knowledge-graph/full-integration", token=token)
        if status != 200:
            print(f"FAIL full_integration: {status}")
            return 1
        domain = choose_domain(inventory.get("source_projections", {}).get("ready_domains", []))

        status, start = request(
            "/api/platform/knowledge-graph/dry-runs",
            method="POST",
            token=token,
            payload={"domains": [domain], "batch_size": 100, "max_batches_per_step": 1},
        )
        if status != 200:
            print(f"FAIL start_dry_run: {status}")
            return 1
        session = start.get("session") or {}
        run_id = str(session.get("run_id") or "")
        if not run_id:
            print("FAIL start_dry_run: missing run_id")
            return 1

        status, resume = request(
            f"/api/platform/knowledge-graph/dry-runs/{run_id}/resume",
            method="POST",
            token=token,
        )
        if status != 200:
            print(f"FAIL resume_dry_run: {status}")
            return 1

        status, report = request(f"/api/platform/knowledge-graph/dry-runs/{run_id}", token=token)
        if status != 200:
            print(f"FAIL dry_run_report: {status}")
            return 1

        evidence = build_evidence(domain=domain, session=session, resume=resume, report=report)
        write_evidence(evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        print("PASS bounded resumable dry run completed one staging step")
        print("SAFE STOP: production graph publication was not invoked")
        return 0
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(f"FAIL bounded_dry_run: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
