#!/usr/bin/env python3
"""Swarm v3 post-build write-set verifier.

Compares a worker's durable Swarm v2 lease claim with the files actually changed
in its integration PR.  The verifier is deterministic, provider-free, and
fail-closed for runtime/configuration paths it cannot classify.

A changed file may require one or more write resources.  Reads never authorize a
write.  Test/docs-only ancillary changes are allowed without an additional lock;
unknown production/configuration files require the worker's exclusive coarse
``lane-*`` fallback or an explicit ``repo-global`` write claim.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

LEASE_PREFIX = "[OC-SWARM-V2] Resource-aware worker lease claimed:"
_JSON_IN_BACKTICKS = re.compile(r"`(\{.*?\})`", re.DOTALL)

# Ordered from most specific to broadest. A path may map to multiple resources.
PATH_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("control-plane", (".github/workflows/", "scripts/oc_swarm", "scripts/oc_portfolio_", "scripts/oc_control_plane", "scripts/oc_operations_", "scripts/oc_lane_", "scripts/oc_model_router", "scripts/oc_no_api_")),
    ("taxonomy", ("taxonomy", "hassler", "world_plants", "world-orchids")),
    ("occurrence", ("occurrence", "gbif", "idigbio", "inaturalist", "inat_")),
    ("literature", ("literature", "document_intelligence", "citation", "bibliograph", "source_binding")),
    ("images", ("image", "vision", "media")),
    ("molecular", ("molecular", "genbank", "sequence", "accession")),
    ("habitat", ("habitat", "elevation", "climate")),
    ("geospatial", ("geospatial", "mapbox", "google_earth", "locality", "coordinate")),
    ("atlas", ("atlas", "planetary", "tour")),
    ("knowledge-graph", ("knowledge_graph", "knowledge-graph", "kg_material", "graph_")),
    ("brain-reasoning", ("brain", "reasoning", "synthesis", "cognitive")),
    ("scientific-memory", ("scientific_memory", "scientific-memory", "memory_ledger", "ledger")),
    ("research-station", ("research_station", "research-station", "research_executor", "research-executor")),
    ("frontend-api", ("frontend", "operator_ui", "router", "routes.py", "showos", "show_companion")),
    ("security-observability", ("security", "observability", "telemetry", "sbom", "audit")),
    ("pollinator", ("pollinator", "pollination")),
    ("mycorrhiza", ("mycorrhiza", "fungal")),
    ("traits", ("trait", "phenotype")),
    ("conservation", ("conservation", "iucn", "cites")),
)

GLOBAL_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "Dockerfile",
    "render.yaml",
}


def parse_lease_claim(comment: str) -> dict[str, list[str]]:
    """Extract and validate the resource claim from a Swarm v2 lease comment."""
    if LEASE_PREFIX not in (comment or ""):
        raise ValueError("not a Swarm v2 lease receipt")
    match = _JSON_IN_BACKTICKS.search(comment)
    if not match:
        raise ValueError("lease receipt has no JSON resource claim")
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError("lease resource claim is invalid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("lease resource claim must be an object")
    reads = raw.get("reads") or []
    writes = raw.get("writes") or []
    if not isinstance(reads, list) or not isinstance(writes, list):
        raise ValueError("lease reads/writes must be arrays")
    if not all(isinstance(item, str) and item for item in reads + writes):
        raise ValueError("lease resources must be non-empty strings")
    writes_set = set(writes)
    return {
        "reads": sorted(set(reads) - writes_set),
        "writes": sorted(writes_set),
    }


def _path_resources(path: str) -> tuple[set[str], str]:
    """Return (required resources, classification) for one changed path."""
    normal = str(PurePosixPath(path)).lower()
    basename = PurePosixPath(normal).name
    resources: set[str] = set()

    if normal.startswith("migrations/") or "/migrations/" in normal:
        resources.add("database-schema")

    for resource, needles in PATH_RULES:
        if any(needle in normal for needle in needles):
            resources.add(resource)

    if basename in {name.lower() for name in GLOBAL_FILES}:
        resources.add("repo-global")

    if resources:
        return resources, "classified"

    # Non-runtime collateral is allowed to follow an otherwise authorized write.
    if normal.startswith("tests/") or "/tests/" in normal:
        return set(), "ancillary-test"
    if normal.startswith("docs/") or normal.endswith(".md"):
        return set(), "ancillary-doc"

    # Unknown runtime/configuration change: fail closed unless the worker held a
    # coarse fallback lane lock or explicitly declared repo-global.
    return {"repo-global"}, "unclassified-runtime"


def verify_write_set(files: Iterable[str], claim: dict[str, list[str]]) -> dict[str, Any]:
    """Verify changed paths against the worker's write resources."""
    writes = set(claim.get("writes") or [])
    reads = set(claim.get("reads") or [])
    coarse_fallback = any(resource.startswith("lane-") for resource in writes)

    checked: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for raw_path in files:
        path = str(raw_path)
        required, classification = _path_resources(path)
        missing = sorted(required - writes)
        if required == {"repo-global"} and coarse_fallback:
            missing = []
            classification = "coarse-lane-fallback"
        row = {
            "path": path,
            "classification": classification,
            "required_writes": sorted(required),
            "missing_writes": missing,
        }
        checked.append(row)
        if missing:
            violations.append(row)

    return {
        "schema": "oc.swarm-write-set-verification.v1",
        "passed": not violations,
        "lease": {"reads": sorted(reads), "writes": sorted(writes)},
        "changed_file_count": len(checked),
        "violations": violations,
        "checked": checked,
        "safety": {
            "reads_authorize_writes": False,
            "unclassified_runtime_fail_closed": True,
            "provider_calls": False,
            "repository_mutation": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lease-comment", required=True)
    parser.add_argument("--files-json", required=True, help="JSON array of changed paths")
    parser.add_argument("--issue-number", type=int)
    args = parser.parse_args(argv)

    try:
        claim = parse_lease_claim(args.lease_comment)
        files = json.loads(args.files_json)
        if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
            raise ValueError("files-json must be a JSON array of strings")
        result = verify_write_set(files, claim)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema": "oc.swarm-write-set-verification.v1",
            "passed": False,
            "issue_number": args.issue_number,
            "error": str(exc),
        }
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 2

    if args.issue_number is not None:
        result["issue_number"] = args.issue_number
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
