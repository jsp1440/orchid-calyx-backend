"""Provider-free acceptance pipeline for #218.

question/reasoning artifact -> evaluation -> bounded candidate -> target-module
routing -> validation receipt. The receipt records what was checked; it is a
maker-side self-check and says so (``independent: false``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contract import checksum
from .discovery_adapter import to_candidates
from .evaluator import evaluate
from .presentations import build_presentations, core_fingerprint, verify_presentation

RECEIPT_SCHEMA = "calyx_validation_receipt.v1"


def run(artifact: Mapping[str, Any], *, known_fingerprints: frozenset[str] = frozenset()) -> dict[str, Any]:
    advisory = evaluate(artifact)
    candidates = to_candidates(advisory, artifact, known_fingerprints=known_fingerprints)

    claims = {c["id"]: c for c in artifact.get("claims") or []}
    before = {cid: core_fingerprint(c) for cid, c in claims.items()}
    presentations = {cid: build_presentations(c) for cid, c in claims.items()}
    for cid, tiers in presentations.items():
        for tier in tiers.values():
            verify_presentation(claims[cid], tier)
    after = {cid: {t["core_fingerprint"] for t in tiers.values()} for cid, tiers in presentations.items()}

    checks = {
        "scientific_core_unchanged": all(after[cid] == {before[cid]} for cid in claims),
        "all_findings_scientific_effect_none": all(
            f["scientific_effect"] == "none" for f in advisory["findings"]
        ),
        "no_protected_locality": True,  # evaluate() raises before reaching here otherwise
        "candidates_require_human_review": all(c["requires_human_review"] for c in candidates),
        "candidate_routes_known": all(c["target_module"] for c in candidates),
    }
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "artifact_id": advisory["artifact_id"],
        "artifact_checksum": advisory["artifact_checksum"],
        "advisory_checksum": checksum(advisory),
        "candidate_fingerprints": [c["fingerprint"] for c in candidates],
        "routes": sorted({c["target_module"] for c in candidates}),
        "checks": checks,
        "passed": all(checks.values()),
        "independent": False,
        "certifier": "calyx_advisory.pipeline.deterministic_invariants",
    }
    return {
        "advisory": advisory,
        "candidates": candidates,
        "presentations": presentations,
        "receipt": receipt,
    }
