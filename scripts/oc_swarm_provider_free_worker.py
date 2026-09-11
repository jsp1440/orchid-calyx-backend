#!/usr/bin/env python3
"""Deterministic provider-free Swarm worker.

This worker performs only explicit GitHub-state reconciliation. It never edits
repository files, invokes a model/provider, merges, deploys, or mutates
scientific data. The issue must opt in with machine-readable mode and terminal
disposition markers; missing or unknown metadata fails closed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from typing import Any

MODE = re.compile(
    r"^OC-SWARM-PROVIDER-FREE:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE
)
DISPOSITION = re.compile(
    r"^OC-SWARM-DISPOSITION:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE
)
ALLOWED_DISPOSITIONS = {"blocked", "done", "owner-gate"}


def _load_verifier():
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "oc_swarm_write_set_verifier.py",
    )
    spec = importlib.util.spec_from_file_location("oc_swarm_write_set_verifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("write-set verifier unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_receipt(
    issue: dict[str, Any],
    *,
    lease_comment: str,
    changed_files: list[str],
    integration_sha: str,
) -> dict[str, Any]:
    body = str(issue.get("body") or "")
    mode_match = MODE.search(body)
    disposition_match = DISPOSITION.search(body)
    if not mode_match or mode_match.group(1).lower() != "reconcile":
        raise ValueError("provider-free reconcile marker missing or unsupported")
    if not disposition_match:
        raise ValueError("provider-free disposition marker missing")
    disposition = disposition_match.group(1).lower()
    if disposition not in ALLOWED_DISPOSITIONS:
        raise ValueError("provider-free disposition is not fail-closed")
    if str(issue.get("state") or "").upper() != "OPEN":
        raise ValueError("provider-free worker requires an open issue")
    if not integration_sha:
        raise ValueError("integration SHA is required")

    verifier = _load_verifier()
    claim = verifier.parse_lease_claim(lease_comment)
    write_set = verifier.verify_write_set(changed_files, claim)
    if not write_set["passed"]:
        raise ValueError("actual write set exceeds the durable lease")

    return {
        "schema": "oc.swarm-provider-free-result.v1",
        "issue_number": int(issue["number"]),
        "mode": "reconcile",
        "disposition": disposition,
        "integration_sha": integration_sha,
        "write_set": write_set,
        "safety": {
            "provider_calls": False,
            "repository_writes": False,
            "merge_to_main": False,
            "production_deploy": False,
            "scientific_mutation": False,
            "sensitive_locality_access": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-json", required=True)
    parser.add_argument("--lease-comment", required=True)
    parser.add_argument("--files-json", default="[]")
    parser.add_argument("--integration-sha", required=True)
    args = parser.parse_args(argv)

    try:
        issue = json.loads(args.issue_json)
        changed_files = json.loads(args.files_json)
        if not isinstance(issue, dict):
            raise TypeError("issue-json must be an object")
        if not isinstance(changed_files, list) or not all(
            isinstance(path, str) for path in changed_files
        ):
            raise TypeError("files-json must be an array of strings")
        receipt = build_receipt(
            issue,
            lease_comment=args.lease_comment,
            changed_files=changed_files,
            integration_sha=args.integration_sha,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        json.dump(
            {
                "schema": "oc.swarm-provider-free-result.v1",
                "passed": False,
                "error": str(exc),
            },
            sys.stdout,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 2

    json.dump(receipt, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
