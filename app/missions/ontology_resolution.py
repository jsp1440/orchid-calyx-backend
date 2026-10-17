"""Deterministic handler for the ``ontology_resolution`` mission.

The BUILD-077 ontology registry (``oc_ontology``) resolves extracted entity
candidates to controlled ontology terms with
``app.ontology.services.DeterministicResolutionEngine``. This handler runs
that same engine over an owner-approved, bounded snapshot of terms and entity
candidates supplied in the mission ``input_manifest`` and returns a
resolution *proposal* report for human review.

It is deliberately narrow:

* no model/provider call and no network access;
* no database read or write of its own, so nothing is written to
  ``oc_ontology.candidate_resolutions`` and no term, synonym or registry
  changes (the mission framework stores the returned report as the mission
  output manifest in ``oc_missions``);
* term eligibility mirrors the repository lookup the resolution service uses:
  only terms in an ``ACTIVE`` registry with term status ``DRAFT`` or
  ``ACTIVE`` are matched;
* no decision: every proposal has status ``PROPOSED`` and a candidate with no
  match gets one ``UNRESOLVED`` / ``NEEDS_REVIEW`` entry. Nothing is ever
  ``ACCEPTED``; the report's state is always ``awaiting_human_review``. The
  engine's ``confidence`` is a string-match score, not scientific confidence.

Malformed or out-of-contract manifests fail closed with ``ValueError`` whose
message starts with ``ONTOLOGY_RESOLUTION_MANIFEST_INVALID`` so the mission
framework records a failed job instead of producing a partial report.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from app.ontology.normalizers import normalize_ontology_text
from app.ontology.services import DeterministicResolutionEngine

MAX_CANDIDATES = 50
MAX_TERMS = 500
MAX_SYNONYMS_PER_TERM = 20
# One engine row per synonym (or one per term without synonyms), as the
# repository's term lookup returns them.
MAX_TERM_ROWS = 1000
# Bounds the fuzzy-matching work: candidates x eligible term rows. With random
# 200-character inputs at this budget one local run (machine under load) took
# about 5 s, inside the registry's 60 s timeout.
MAX_COMPARISONS = 5_000
MAX_SOURCE_LENGTH = 500
MAX_TEXT_LENGTH = 200
MAX_NAMESPACE_LENGTH = 200
MAX_VERSION_LENGTH = 100
MAX_ID = 2**63 - 1
DEFAULT_FUZZY_THRESHOLD = 0.88
MIN_FUZZY_THRESHOLD = 0.75
MAX_FUZZY_THRESHOLD = 1.0

REGISTRY_STATUSES = frozenset({"DRAFT", "ACTIVE", "DEPRECATED", "RETIRED"})
TERM_STATUSES = frozenset({"DRAFT", "ACTIVE", "DEPRECATED"})
ELIGIBLE_REGISTRY_STATUSES = frozenset({"ACTIVE"})
ELIGIBLE_TERM_STATUSES = frozenset({"DRAFT", "ACTIVE"})

ALLOWED_MANIFEST_KEYS = frozenset({"source", "fuzzy_threshold", "terms", "candidates"})
REQUIRED_TERM_KEYS = frozenset(
    {
        "term_id",
        "registry_id",
        "canonical_key",
        "preferred_label",
        "namespace",
        "version",
        "registry_status",
        "term_status",
    }
)
ALLOWED_TERM_KEYS = REQUIRED_TERM_KEYS | {"synonyms"}
REQUIRED_CANDIDATE_KEYS = frozenset({"candidate_id", "name"})
ALLOWED_CANDIDATE_KEYS = REQUIRED_CANDIDATE_KEYS


def _invalid(detail: str) -> ValueError:
    return ValueError(f"ONTOLOGY_RESOLUTION_MANIFEST_INVALID:{detail}")


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{name}_not_string")
    if not value.strip():
        raise _invalid(f"{name}_required")
    if len(value) > limit:
        raise _invalid(f"{name}_too_long>{limit}")
    # Matching uses the value as supplied: the engine's EXACT tier compares
    # the raw string, and normalization is the engine's job.
    return value


def _identifier(value: Any, name: str) -> int:
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{name}_not_int")
    if not 1 <= value <= MAX_ID:
        raise _invalid(f"{name}_out_of_range")
    return value


def _check_keys(
    row: Mapping[str, Any],
    prefix: str,
    allowed: frozenset[str],
    required: frozenset[str],
) -> None:
    keys = set(row)
    unknown = sorted(str(key) for key in keys - allowed)
    if unknown:
        raise _invalid(f"{prefix}_unknown_fields={','.join(unknown)}")
    missing = sorted(required - keys)
    if missing:
        raise _invalid(f"{prefix}_missing_fields={','.join(missing)}")


def _fuzzy_threshold(value: Any) -> float:
    if value is None:
        return DEFAULT_FUZZY_THRESHOLD
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid("fuzzy_threshold_not_number")
    if (isinstance(value, float) and not math.isfinite(value)) or not (
        MIN_FUZZY_THRESHOLD <= value <= MAX_FUZZY_THRESHOLD
    ):
        raise _invalid(
            f"fuzzy_threshold_out_of_range={MIN_FUZZY_THRESHOLD}..{MAX_FUZZY_THRESHOLD}"
        )
    return float(value)


def _validate_term(index: int, row: Any) -> dict[str, Any]:
    prefix = f"term_{index}"
    if not isinstance(row, Mapping):
        raise _invalid(f"{prefix}_not_object")
    _check_keys(row, prefix, ALLOWED_TERM_KEYS, REQUIRED_TERM_KEYS)
    registry_status = row["registry_status"]
    if not isinstance(registry_status, str) or registry_status not in REGISTRY_STATUSES:
        raise _invalid(f"{prefix}_registry_status_not_allowed")
    term_status = row["term_status"]
    if not isinstance(term_status, str) or term_status not in TERM_STATUSES:
        raise _invalid(f"{prefix}_term_status_not_allowed")
    synonyms = row.get("synonyms")
    if synonyms is None:
        synonyms = []
    if not isinstance(synonyms, list):
        raise _invalid(f"{prefix}_synonyms_not_list")
    if len(synonyms) > MAX_SYNONYMS_PER_TERM:
        raise _invalid(f"{prefix}_too_many_synonyms>{MAX_SYNONYMS_PER_TERM}")
    return {
        "term_id": _identifier(row["term_id"], f"{prefix}_term_id"),
        "registry_id": _identifier(row["registry_id"], f"{prefix}_registry_id"),
        "canonical_key": _text(
            row["canonical_key"], f"{prefix}_canonical_key", MAX_TEXT_LENGTH
        ),
        "preferred_label": _text(
            row["preferred_label"], f"{prefix}_preferred_label", MAX_TEXT_LENGTH
        ),
        "namespace": _text(
            row["namespace"], f"{prefix}_namespace", MAX_NAMESPACE_LENGTH
        ),
        "version": _text(row["version"], f"{prefix}_version", MAX_VERSION_LENGTH),
        "registry_status": registry_status,
        "term_status": term_status,
        "synonyms": [
            _text(synonym, f"{prefix}_synonym", MAX_TEXT_LENGTH) for synonym in synonyms
        ],
    }


def _validate_candidate(index: int, row: Any) -> dict[str, Any]:
    prefix = f"candidate_{index}"
    if not isinstance(row, Mapping):
        raise _invalid(f"{prefix}_not_object")
    _check_keys(row, prefix, ALLOWED_CANDIDATE_KEYS, REQUIRED_CANDIDATE_KEYS)
    return {
        "candidate_id": _identifier(row["candidate_id"], f"{prefix}_candidate_id"),
        "name": _text(row["name"], f"{prefix}_name", MAX_TEXT_LENGTH),
    }


def validate_ontology_resolution_manifest(
    manifest: Any,
) -> tuple[str, float, list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(source, fuzzy_threshold, terms, candidates)`` or raise (fail closed)."""
    if not isinstance(manifest, Mapping):
        raise _invalid("manifest_not_object")
    unknown = sorted(str(key) for key in set(manifest) - ALLOWED_MANIFEST_KEYS)
    if unknown:
        raise _invalid(f"unknown_manifest_keys={','.join(unknown)}")
    source = manifest.get("source")
    if not isinstance(source, str):
        raise _invalid("source_not_string")
    source = source.strip()
    if not source:
        raise _invalid("source_required")
    if len(source) > MAX_SOURCE_LENGTH:
        raise _invalid(f"source_too_long>{MAX_SOURCE_LENGTH}")
    threshold = _fuzzy_threshold(manifest.get("fuzzy_threshold"))

    raw_terms = manifest.get("terms")
    if not isinstance(raw_terms, list) or not raw_terms:
        raise _invalid("terms_required")
    if len(raw_terms) > MAX_TERMS:
        raise _invalid(f"too_many_terms>{MAX_TERMS}")
    terms: list[dict[str, Any]] = []
    seen_terms: set[int] = set()
    seen_keys: set[tuple[int, str]] = set()
    registries: dict[int, tuple[str, str, str]] = {}
    for index, row in enumerate(raw_terms):
        term = _validate_term(index, row)
        if term["term_id"] in seen_terms:
            raise _invalid(f"term_{index}_duplicate_term_id")
        seen_terms.add(term["term_id"])
        # oc_ontology.ontology_terms is UNIQUE (registry_id, canonical_key).
        key = (term["registry_id"], term["canonical_key"])
        if key in seen_keys:
            raise _invalid(f"term_{index}_duplicate_canonical_key")
        seen_keys.add(key)
        identity = (term["namespace"], term["version"], term["registry_status"])
        if registries.setdefault(term["registry_id"], identity) != identity:
            # One registry row cannot carry two identities or two statuses.
            raise _invalid(f"term_{index}_registry_inconsistent")
        terms.append(term)

    raw_candidates = manifest.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise _invalid("candidates_required")
    if len(raw_candidates) > MAX_CANDIDATES:
        raise _invalid(f"too_many_candidates>{MAX_CANDIDATES}")
    candidates: list[dict[str, Any]] = []
    seen_candidates: set[int] = set()
    for index, row in enumerate(raw_candidates):
        candidate = _validate_candidate(index, row)
        if candidate["candidate_id"] in seen_candidates:
            raise _invalid(f"candidate_{index}_duplicate_candidate_id")
        seen_candidates.add(candidate["candidate_id"])
        candidates.append(candidate)
    return source, threshold, terms, candidates


def _engine_rows(
    terms: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    excluded = {"registry_not_active": 0, "term_deprecated": 0}
    for term in sorted(terms, key=lambda item: item["term_id"]):
        if term["registry_status"] not in ELIGIBLE_REGISTRY_STATUSES:
            excluded["registry_not_active"] += 1
            continue
        if term["term_status"] not in ELIGIBLE_TERM_STATUSES:
            excluded["term_deprecated"] += 1
            continue
        base = {
            "id": term["term_id"],
            "registry_id": term["registry_id"],
            "canonical_key": term["canonical_key"],
            "preferred_label": term["preferred_label"],
            "namespace": term["namespace"],
            "version": term["version"],
        }
        for synonym in term["synonyms"] or [None]:
            rows.append({**base, "synonym": synonym})
    return rows, excluded


def _proposals(
    engine: DeterministicResolutionEngine, name: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    # The engine yields one suggestion per matching row, so a term with several
    # matching synonyms appears more than once; keep its best-ranked entry.
    best: dict[int, dict[str, Any]] = {}
    for suggestion in engine.suggestions(name, rows):
        best.setdefault(suggestion["ontology_term_id"], suggestion)
    return list(best.values())


def _resolve(
    engine: DeterministicResolutionEngine,
    candidate: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    proposals = _proposals(engine, candidate["name"], rows)
    flags: list[str] = []
    if not proposals:
        state = "UNRESOLVED_NEEDS_REVIEW"
        proposals = [
            {
                # Same shape the resolution service records for no match.
                "ontology_term_id": None,
                "resolution_method": "UNRESOLVED",
                "confidence": 0.0,
                "status": "NEEDS_REVIEW",
                "normalized_input": normalize_ontology_text(
                    candidate["name"], scientific_name=True
                ),
                "matched_label": None,
                "ontology_namespace": None,
                "ontology_version": None,
                "explanation": {"reason": "NO_CONTROLLED_TERM_MATCH"},
                "provenance": {
                    "resolver": "deterministic-local-v1",
                    "candidate_id": candidate["candidate_id"],
                },
            }
        ]
    else:
        state = "PROPOSALS_AWAITING_HUMAN_REVIEW"
        top = (proposals[0]["resolution_method"], proposals[0]["confidence"])
        tied = [
            item
            for item in proposals
            if (item["resolution_method"], item["confidence"]) == top
        ]
        if len(tied) > 1:
            # Never break a tie on term id; a reviewer must choose.
            flags.append("AMBIGUOUS_TOP_MATCH")
        if top[0] == "FUZZY":
            flags.append("FUZZY_ONLY")
    return {
        "candidate_id": candidate["candidate_id"],
        "name": candidate["name"],
        "resolution_state": state,
        "review_flags": flags,
        "human_review_required": True,
        "proposals": proposals,
    }


def build_ontology_resolution_report(manifest: Any) -> dict[str, Any]:
    """Build a deterministic, human-review-only ontology resolution proposal report."""
    source, threshold, terms, candidates = validate_ontology_resolution_manifest(
        manifest
    )
    rows, excluded = _engine_rows(terms)
    if len(rows) > MAX_TERM_ROWS:
        raise _invalid(f"too_many_term_rows>{MAX_TERM_ROWS}")
    if len(rows) * len(candidates) > MAX_COMPARISONS:
        raise _invalid(f"too_many_comparisons>{MAX_COMPARISONS}")
    engine = DeterministicResolutionEngine(threshold)
    resolutions = [
        _resolve(engine, candidate, rows)
        for candidate in sorted(candidates, key=lambda item: item["candidate_id"])
    ]
    state_counts: dict[str, int] = {}
    for item in resolutions:
        state_counts[item["resolution_state"]] = (
            state_counts.get(item["resolution_state"], 0) + 1
        )
    summary = {
        "candidates_evaluated": len(resolutions),
        "terms_supplied": len(terms),
        "terms_eligible": len({row["id"] for row in rows}),
        "terms_excluded": excluded,
        "resolution_states": dict(sorted(state_counts.items())),
        "ambiguous_candidates": sum(
            "AMBIGUOUS_TOP_MATCH" in item["review_flags"] for item in resolutions
        ),
    }
    digest = hashlib.sha256(
        json.dumps(
            {
                "source": source,
                "fuzzy_threshold": threshold,
                "resolutions": resolutions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "status": "ok",
        "mission_type": "ontology_resolution",
        "artifact_type": "ontology_resolution_proposals",
        "review_state": "awaiting_human_review",
        "human_review_required": True,
        "scientific_authority": "none",
        "scientific_conclusions_published": False,
        "approval_recorded": False,
        "resolutions_persisted": False,
        "ontology_mutated": False,
        "provider_called": False,
        "external_network_called": False,
        "domain_database_written": False,
        "canonical_graph_mutated": False,
        "taxonomy_mutated": False,
        "resolver": "deterministic-local-v1",
        "score_semantics": "string_match_score_not_scientific_confidence",
        "snapshot_source": source,
        "fuzzy_threshold": threshold,
        "summary": summary,
        "resolutions": resolutions,
        "report_digest": digest,
    }
