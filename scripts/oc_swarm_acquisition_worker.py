"""Dispatch a claimed acquisition to the existing authenticated backend runtime."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from http.client import HTTPException, HTTPSConnection
from pathlib import Path
from urllib.parse import urlsplit

from scripts.oc_swarm_claim import github, park_denied_worker
from scripts.oc_swarm_settlement import settle_worker, verified_issue


def backend_request(path, identity=None):
    base = os.environ.get("CALYX_BACKEND_URL", "").rstrip("/")
    parsed = urlsplit(base)
    key = os.environ.get("CALYX_API_KEY")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or not key:
        raise ValueError("authenticated backend configuration unavailable")
    connection = HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=600)
    try:
        connection.request("POST" if identity is not None else "GET", parsed.path + path,
                           body=json.dumps(identity) if identity is not None else None,
                           headers={"Content-Type": "application/json", "X-API-Key": key})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("backend request unconfirmed")
        content = response.read(2_000_001)
        if len(content) > 2_000_000:
            raise ValueError("backend receipt exceeds bounded response")
        return json.loads(content)
    finally:
        connection.close()


def backend_execute(identity):
    return backend_request("/api/literature-extraction/acquisition/execute", identity)


def refresh_coverage(path):
    destination = Path(path)
    destination.unlink(missing_ok=True)
    report = backend_request("/api/literature-extraction/acquisition/coverage")
    if report.get("schema") != "oc.matrix-acquisition-coverage.v1" or report.get("available") is not True:
        raise ValueError("canonical coverage unavailable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report), encoding="utf-8")


def execute_claim(*, repository, issue_number, run_id, run_attempt, comment_id,
                  dispatch=backend_execute, call=github):
    identity = {"repository": repository, "issue_number": issue_number, "run_id": run_id,
                "run_attempt": run_attempt, "comment_id": comment_id}
    issue = verified_issue(**identity, call=call)
    from app.provider_reservoir.routing import route_task
    if "firecrawl-acquisition" not in route_task(issue).blocking_provider_capabilities:
        raise ValueError("claim is not acquisition work")
    result = dispatch(identity)
    if (result.get("status") != "review_pending" or result.get("published") is not False
            or not result.get("sources") or result.get("validation", {}).get("status") != "passed"
            or any(result.get(key) != identity[key] for key in ("issue_number", "run_id", "run_attempt", "comment_id"))):
        raise ValueError("acquisition validation receipt incomplete")
    return settle_worker(**identity, result={**result, "disposition": "done"}, call=call)


def main(*, dispatch=backend_execute, call=github):
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-coverage")
    parser.add_argument("--repository")
    for name in ("issue-number", "run-id", "run-attempt", "comment-id"):
        parser.add_argument("--" + name, type=int)
    identity = vars(parser.parse_args())
    coverage = identity.pop("refresh_coverage")
    if coverage:
        refresh_coverage(coverage)
        return
    if any(value is None for value in identity.values()):
        parser.error("execution requires repository and complete lease identity")
    try:
        result = execute_claim(**identity, dispatch=dispatch, call=call)
    except (OSError, ValueError, TypeError, KeyError, HTTPException, subprocess.SubprocessError):
        # Uncertain HTTP completion never earns oc-done. The existing denial
        # settlement parks the task; source persistence is replay-safe.
        park_denied_worker(**identity, reason="ACQUISITION_RUNTIME_UNCONFIRMED",
                           provider_called=None, call=call)
        raise SystemExit("Acquisition runtime unconfirmed; canonical claim parked") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
