"""Resume one existing bounded Knowledge Graph dry-run session and prove zero delta.

This operator never invokes production publication. It resumes the exact persisted
session named by CALYX_DRY_RUN_ID, then requires completion, healthy staging,
zero second-pass writes, and an explicit no-production-mutation report.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com").strip().rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")
RUN_ID = os.environ.get("CALYX_DRY_RUN_ID", "").strip()
EVIDENCE_PATH = Path(os.environ.get("CALYX_IDEMPOTENCY_EVIDENCE_PATH", "calyx-live-idempotency-evidence.json"))


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


def main() -> int:
    if not ACCESS_CODE:
        print("FAIL CALYX_OWNER_ACCESS_CODE not set")
        return 1
    if not RUN_ID:
        print("FAIL CALYX_DRY_RUN_ID not set")
        return 1
    try:
        _, login = request(
            "/api/mission-control/owner/session-token",
            method="POST",
            payload={"access_code": ACCESS_CODE},
        )
        token = str(login.get("token") or "")
        if not token:
            raise RuntimeError("owner session token missing")

        _, resume = request(
            f"/api/platform/knowledge-graph/dry-runs/{RUN_ID}/resume",
            method="POST",
            token=token,
        )
        _, report = request(
            f"/api/platform/knowledge-graph/dry-runs/{RUN_ID}",
            token=token,
        )

        session = report.get("session") or {}
        states = session.get("domain_states") or {}
        second_nodes = sum(int((state or {}).get("second_nodes") or 0) for state in states.values())
        second_edges = sum(int((state or {}).get("second_edges") or 0) for state in states.values())
        checks = {
            "status_completed": session.get("status") == "completed",
            "zero_delta": report.get("zero_delta") is True,
            "publication_authorization_ready": report.get("publication_authorization_ready") is True,
            "production_graph_mutation_false": report.get("production_graph_mutation") is False,
            "second_nodes_zero": second_nodes == 0,
            "second_edges_zero": second_edges == 0,
            "staging_healthy": (report.get("validation") or {}).get("healthy") is True,
            "blockers_empty": not (report.get("blockers") or []),
        }
        evidence = {
            "schema_version": "1.0",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "backend_url": BASE_URL,
            "run_id": RUN_ID,
            "resume": resume,
            "report": report,
            "second_pass_totals": {"nodes": second_nodes, "edges": second_edges},
            "checks": checks,
            "publication_endpoint_invoked": False,
            "production_graph_mutation": False,
        }
        canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
        evidence["artifact_hash"] = sha256(canonical.encode()).hexdigest()
        EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2, sort_keys=True))
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            print("FAIL idempotency checks: " + ", ".join(failed))
            return 1
        print("PASS resumable dry run completed with zero second-pass delta")
        print("SAFE STOP: production graph publication was not invoked")
        return 0
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(f"FAIL live_idempotency_proof: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
