#!/usr/bin/env python3
"""Deterministic provider-free Swarm worker.

Two modes, both of which never edit repository files, invoke a model/provider,
merge, deploy, or mutate scientific data. The issue must opt in with
machine-readable mode and terminal disposition markers; missing or unknown
metadata fails closed.

``reconcile`` performs GitHub-state reconciliation only and settles the issue at
the disposition the issue declares.

``validate`` runs the bounded validation commands the issue names, from the
registry in ``oc_validation_commands``, and settles from their exit codes. The
declared disposition still bounds the *best* outcome available, but it cannot
manufacture one: a failing, timed-out, or unrunnable command settles ``blocked``
whatever the issue asked for. That asymmetry is the whole point — a task may
declare what success would mean, never that it happened.
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
#: Repeatable declaration of which registered validation command to run. The
#: value is an identifier resolved against the registry, never a command line:
#: an issue body is untrusted text and this worker holds a GitHub token.
VALIDATE = re.compile(
    r"^OC-SWARM-VALIDATE:\s*([a-z0-9][a-z0-9-]*)\s*$", re.IGNORECASE | re.MULTILINE
)
ALLOWED_DISPOSITIONS = {"blocked", "done", "owner-gate"}
SUPPORTED_MODES = {"reconcile", "validate"}
VALIDATION_EVIDENCE_SCHEMA = "oc.provider-free-validation-evidence.v1"


def declared_validation_commands(body: str) -> list[str]:
    """Return the validation command ids an issue declares, in declared order."""
    return [match.group(1).lower() for match in VALIDATE.finditer(body or "")]


def execution_plan(issue: dict[str, Any]) -> dict[str, Any]:
    """Say which executor an issue asks for and what it declares, before running.

    The workflow needs this to decide whether to run validation commands at all,
    and it must read the markers exactly as ``build_receipt`` will. Parsing them
    a second time in shell is how the two answers drift apart, so there is one
    parser and the job asks it.
    """
    body = str(issue.get("body") or "")
    mode_match = MODE.search(body)
    mode = mode_match.group(1).lower() if mode_match else ""
    return {
        "schema": "oc.provider-free-execution-plan.v1",
        "issue_number": int(issue.get("number") or 0),
        "mode": mode if mode in SUPPORTED_MODES else "",
        "supported": mode in SUPPORTED_MODES,
        "commands": declared_validation_commands(body),
    }


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
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = str(issue.get("body") or "")
    mode_match = MODE.search(body)
    disposition_match = DISPOSITION.search(body)
    if not mode_match or mode_match.group(1).lower() not in SUPPORTED_MODES:
        raise ValueError(
            "provider-free mode marker missing or unsupported; this lane "
            f"implements {sorted(SUPPORTED_MODES)}"
        )
    mode = mode_match.group(1).lower()
    if not disposition_match:
        raise ValueError("provider-free disposition marker missing")
    disposition = disposition_match.group(1).lower()
    if disposition not in ALLOWED_DISPOSITIONS:
        raise ValueError("provider-free disposition is not fail-closed")
    if str(issue.get("state") or "").upper() != "OPEN":
        raise ValueError("provider-free worker requires an open issue")
    if not integration_sha:
        raise ValueError("integration SHA is required")

    declared_commands = declared_validation_commands(body)
    if mode == "reconcile":
        if validation is not None:
            raise ValueError("reconcile mode does not run validation commands")
        if declared_commands:
            raise ValueError(
                "validation commands are declared but the mode is reconcile"
            )
    else:
        disposition = _validated_disposition(
            disposition, validation, declared_commands
        )

    verifier = _load_verifier()
    claim = verifier.parse_lease_claim(lease_comment)
    write_set = verifier.verify_write_set(changed_files, claim)
    if not write_set["passed"]:
        raise ValueError("actual write set exceeds the durable lease")

    receipt = {
        "schema": "oc.swarm-provider-free-result.v1",
        "issue_number": int(issue["number"]),
        "mode": mode,
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
    if mode == "validate":
        receipt["validation"] = validation
        receipt["declared_commands"] = declared_commands
    return receipt


def _validated_disposition(
    declared: str, validation: dict[str, Any] | None, declared_commands: list[str]
) -> str:
    """Settle a validation task from what ran, not from what it hoped for.

    Absent evidence is not a neutral state here. A caller that lost the result
    file, or that never ran the commands, must not be able to settle the issue
    on the declared disposition — so missing, malformed, or mismatched evidence
    is a failure, and a failure is ``blocked`` whatever the issue declared.
    """
    if not declared_commands:
        raise ValueError("validate mode declares no OC-SWARM-VALIDATE command")
    if validation is None:
        raise ValueError("validate mode requires validation evidence")
    if not isinstance(validation, dict) or validation.get("schema") != VALIDATION_EVIDENCE_SCHEMA:
        raise ValueError("validation evidence schema is unrecognised")
    executed = [str(row.get("command_id")) for row in validation.get("results") or []]
    # De-duplicated in declared order, matching how the registry resolves them.
    expected: list[str] = []
    for name in declared_commands:
        if name not in expected:
            expected.append(name)
    if executed != expected:
        raise ValueError("validation evidence does not cover the declared commands")
    return declared if validation.get("passed") is True else "blocked"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-json", required=True)
    parser.add_argument("--lease-comment", default="")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the execution plan for this issue and exit without running anything.",
    )
    parser.add_argument("--files-json", default="[]")
    parser.add_argument("--integration-sha", default="")
    parser.add_argument(
        "--validation-json",
        default="",
        help="oc.provider-free-validation-evidence.v1 produced by oc_provider_free_validate",
    )
    args = parser.parse_args(argv)

    if args.plan:
        try:
            planned = json.loads(args.issue_json)
            if not isinstance(planned, dict):
                raise TypeError("issue-json must be an object")
        except (TypeError, json.JSONDecodeError) as exc:
            json.dump(
                {"schema": "oc.provider-free-execution-plan.v1", "error": str(exc)},
                sys.stdout,
                sort_keys=True,
            )
            sys.stdout.write("\n")
            return 2
        json.dump(execution_plan(planned), sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if not args.lease_comment or not args.integration_sha:
        parser.error("a receipt requires --lease-comment and --integration-sha")

    try:
        issue = json.loads(args.issue_json)
        changed_files = json.loads(args.files_json)
        validation = json.loads(args.validation_json) if args.validation_json.strip() else None
        if validation is not None and not isinstance(validation, dict):
            raise TypeError("validation-json must be an object")
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
            validation=validation,
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
