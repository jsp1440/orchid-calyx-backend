"""Run exactly one bounded resumable Knowledge Graph staging step and emit evidence.

The operator is intentionally incapable of publishing. It either creates one
single-domain dry-run session and resumes it once, or resumes one explicitly
named existing dry-run session once. Production graph mutation is rejected.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get(
    "CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com"
).strip().rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")
EVIDENCE_PATH = Path(
    os.environ.get(
        "CALYX_BOUNDED_DRY_RUN_EVIDENCE_PATH",
        "calyx-bounded-dry-run-evidence.json",
    )
)
SELECTED_DOMAIN = os.environ.get("CALYX_BOUNDED_DRY_RUN_DOMAIN", "").strip()
EXISTING_RUN_ID = os.environ.get("CALYX_BOUNDED_DRY_RUN_RUN_ID", "").strip()
PREFERRED_DOMAINS = (
    "taxonomy",
    "species",
    "occurrences",
    "literature",
    "traits",
    "media",
)
TRANSIENT_HTTP_CODES = frozenset({502, 503, 504})


def request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str = "",
    retry_transient: bool = False,
    attempts: int = 3,
) -> tuple[int, dict[str, Any]]:
    """Issue one API request; retries are allowed only when explicitly enabled."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    max_attempts = attempts if retry_transient else 1
    for attempt in range(1, max_attempts + 1):
        try:
            with urlopen(req, timeout=120) as response:
                body = response.read().decode()
                return response.status, json.loads(body) if body else {}
        except HTTPError as exc:
            if (
                retry_transient
                and exc.code in TRANSIENT_HTTP_CODES
                and attempt < max_attempts
            ):
                time.sleep(float(attempt))
                continue
            response_body = exc.read().decode(errors="replace")[:1000]
            raise RuntimeError(
                f"{method} {path} -> HTTP {exc.code}: {response_body}"
            ) from exc
    raise RuntimeError(f"{method} {path} exhausted transient retries")


def choose_domain(ready_domains: list[str], requested: str = "") -> str:
    ready = {str(item) for item in ready_domains}
    if requested:
        if requested not in ready:
            raise ValueError(f"requested_domain_not_ready:{requested}")
        return requested
    for domain in PREFERRED_DOMAINS:
        if domain in ready:
            return domain
    if ready:
        return sorted(ready)[0]
    raise ValueError("no_ready_domains")


def require_staging_only(label: str, response: dict[str, Any]) -> None:
    if response.get("production_graph_mutation") is not False:
        raise RuntimeError(f"{label}:production_graph_mutation_not_explicitly_false")


def require_preflight_ready(preflight: dict[str, Any]) -> None:
    require_staging_only("deployment_preflight", preflight)
    if preflight.get("ready_for_live_resumable_dry_run") is not True:
        blockers = preflight.get("blockers") or ["preflight_not_ready"]
        raise RuntimeError(f"deployment_preflight_blocked:{blockers}")


def build_evidence(
    *,
    domain: str,
    session: dict[str, Any],
    resume: dict[str, Any],
    report: dict[str, Any],
    action: str = "start_and_resume",
    preflight: dict[str, Any] | None = None,
    ready_domains: list[str] | None = None,
    before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = {
        "schema_version": "2.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "backend_url": BASE_URL,
        "action": action,
        "domain": domain,
        "bounds": {"batch_size": 100, "max_batches_per_step": 1, "domains": 1},
        "deployment": {
            "commit": (preflight or {}).get("deployment", {}).get("commit"),
            "preflight_contract": (preflight or {}).get("contract"),
            "ready_for_live_resumable_dry_run": (preflight or {}).get(
                "ready_for_live_resumable_dry_run"
            ),
        },
        "ready_domains": list(ready_domains or []),
        "before": before,
        "session": session,
        "resume": resume,
        "report": report,
        "production_graph_mutation": False,
        "production_publication_authorized": False,
        "publication_endpoint_invoked": False,
    }
    canonical = json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), default=str
    )
    evidence["artifact_hash"] = sha256(canonical.encode()).hexdigest()
    return evidence


def write_evidence(evidence: dict[str, Any]) -> None:
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _authenticate() -> str:
    status, login = request(
        "/api/mission-control/owner/session-token",
        method="POST",
        payload={"access_code": ACCESS_CODE},
        retry_transient=True,
    )
    token = str(login.get("token") or "")
    if status != 200 or not token:
        raise RuntimeError(f"owner_session_token:{status}")
    return token


def _preflight(token: str) -> dict[str, Any]:
    status, preflight = request(
        "/api/platform/knowledge-graph/deployment-preflight",
        token=token,
        retry_transient=True,
    )
    if status != 200:
        raise RuntimeError(f"deployment_preflight:{status}")
    require_preflight_ready(preflight)
    return preflight


def _inventory(token: str) -> tuple[dict[str, Any], list[str]]:
    status, inventory = request(
        "/api/platform/knowledge-graph/full-integration",
        token=token,
        retry_transient=True,
    )
    if status != 200:
        raise RuntimeError(f"full_integration:{status}")
    ready_domains = [
        str(item)
        for item in inventory.get("source_projections", {}).get("ready_domains", [])
    ]
    return inventory, ready_domains


def _resume_existing(
    *, token: str, preflight: dict[str, Any], run_id: str
) -> dict[str, Any]:
    status, before = request(
        f"/api/platform/knowledge-graph/dry-runs/{run_id}",
        token=token,
        retry_transient=True,
    )
    if status != 200:
        raise RuntimeError(f"dry_run_before:{status}")
    require_staging_only("dry_run_before", before)
    session = dict(before.get("session") or {})
    domains = [str(item) for item in session.get("domains") or []]
    if len(domains) != 1:
        raise RuntimeError(f"existing_run_not_single_domain:{domains}")
    domain = domains[0]
    if SELECTED_DOMAIN and SELECTED_DOMAIN != domain:
        raise ValueError(
            f"existing_run_domain_mismatch:{SELECTED_DOMAIN}:{domain}"
        )
    if session.get("status") == "completed":
        raise RuntimeError("existing_run_already_completed")

    # Never retry this mutation-like staging operation automatically: an HTTP
    # response can be lost after the server has committed its checkpoint.
    status, resume = request(
        f"/api/platform/knowledge-graph/dry-runs/{run_id}/resume",
        method="POST",
        token=token,
    )
    if status != 200:
        raise RuntimeError(f"resume_dry_run:{status}")
    require_staging_only("resume_dry_run", resume)

    status, report = request(
        f"/api/platform/knowledge-graph/dry-runs/{run_id}",
        token=token,
        retry_transient=True,
    )
    if status != 200:
        raise RuntimeError(f"dry_run_report:{status}")
    require_staging_only("dry_run_report", report)
    return build_evidence(
        action="resume_existing",
        domain=domain,
        session=session,
        resume=resume,
        report=report,
        preflight=preflight,
        before=before,
    )


def _start_new(
    *, token: str, preflight: dict[str, Any]
) -> dict[str, Any]:
    _, ready_domains = _inventory(token)
    domain = choose_domain(ready_domains, SELECTED_DOMAIN)

    # Start and resume are intentionally not retried automatically because a
    # lost HTTP response could otherwise create or advance work twice.
    status, start = request(
        "/api/platform/knowledge-graph/dry-runs",
        method="POST",
        token=token,
        payload={"domains": [domain], "batch_size": 100, "max_batches_per_step": 1},
    )
    if status != 200:
        raise RuntimeError(f"start_dry_run:{status}")
    require_staging_only("start_dry_run", start)
    session = dict(start.get("session") or {})
    run_id = str(session.get("run_id") or "")
    if not run_id:
        raise RuntimeError("start_dry_run:missing_run_id")

    status, resume = request(
        f"/api/platform/knowledge-graph/dry-runs/{run_id}/resume",
        method="POST",
        token=token,
    )
    if status != 200:
        raise RuntimeError(f"resume_dry_run:{status}")
    require_staging_only("resume_dry_run", resume)

    status, report = request(
        f"/api/platform/knowledge-graph/dry-runs/{run_id}",
        token=token,
        retry_transient=True,
    )
    if status != 200:
        raise RuntimeError(f"dry_run_report:{status}")
    require_staging_only("dry_run_report", report)
    return build_evidence(
        action="start_and_resume",
        domain=domain,
        session=session,
        resume=resume,
        report=report,
        preflight=preflight,
        ready_domains=ready_domains,
    )


def main() -> int:
    if not ACCESS_CODE:
        print("FAIL CALYX_OWNER_ACCESS_CODE not set")
        return 1
    try:
        token = _authenticate()
        preflight = _preflight(token)
        evidence = (
            _resume_existing(token=token, preflight=preflight, run_id=EXISTING_RUN_ID)
            if EXISTING_RUN_ID
            else _start_new(token=token, preflight=preflight)
        )
        write_evidence(evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        print("PASS bounded resumable dry run completed exactly one staging step")
        print("SAFE STOP: production graph publication was not invoked")
        return 0
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(f"FAIL bounded_dry_run: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
