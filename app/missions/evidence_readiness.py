"""Deterministic handler for the ``evidence_readiness_evaluation`` mission.

The handler applies the blocker rules of
``app.ontology.services.PublicationReadinessService`` to an owner-approved,
bounded snapshot of candidate readiness inputs and returns a report for human
reviewers. It is deliberately narrow:

* no model/provider call and no network access;
* no database read or write of its own (the mission framework stores the
  returned report as the mission output manifest in ``oc_missions``); in
  particular it never writes ``oc_ontology.publication_readiness``;
* it never changes, upgrades or infers an evidence, review or ontology state:
  every observed state is echoed verbatim and ``PENDING``, ``INVALID``,
  ``SUPERSEDED`` and ``ABSENT`` evidence stay distinct blockers;
* an input the snapshot does not supply is reported as ``UNKNOWN`` with the
  missing field named, never treated as satisfied;
* no scientific conclusion, approval, or publication: the best possible
  per-candidate outcome is ``CRITERIA_MET_AWAITING_HUMAN_REVIEW`` and the
  report's state is always ``awaiting_human_review``.

Malformed or out-of-contract manifests fail closed with ``ValueError`` so the
mission framework records a failed job instead of producing a partial report.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

MAX_CANDIDATES = 100
EVALUATION_VERSION = "evidence-readiness-mission-v1"
ALLOWED_MANIFEST_KEYS = frozenset({"source", "candidates"})
COMMON_CANDIDATE_KEYS = frozenset(
    {
        "candidate_id",
        "kind",
        "candidate_review_status",
        "session_stage",
        "candidate_provenance",
    }
)
KIND_KEYS = {
    "ENTITY": COMMON_CANDIDATE_KEYS | {"resolution_status", "registry_status"},
    "RELATIONSHIP": COMMON_CANDIDATE_KEYS
    | {"evidence_validation_status", "subject_ready", "object_ready"},
}
# Enumerations mirror migrations/076b_semantic_extraction.sql and
# app/ontology/models.py. "UNRESOLVED" and "ABSENT" let a snapshot state an
# explicit absence, which is different from a field it does not supply.
REVIEW_STATUSES = frozenset({"PENDING", "ACCEPTED", "REJECTED"})
SESSION_STAGES = frozenset(
    {
        "QUEUED",
        "PARSING",
        "ENTITY_EXTRACTION",
        "RELATIONSHIP_EXTRACTION",
        "EVIDENCE_GENERATION",
        "CANDIDATE_GENERATION",
        "READY_FOR_REVIEW",
        "FAILED",
    }
)
RESOLUTION_STATUSES = frozenset(
    {"PROPOSED", "ACCEPTED", "REJECTED", "NEEDS_REVIEW", "UNRESOLVED"}
)
REGISTRY_STATUSES = frozenset({"DRAFT", "ACTIVE", "DEPRECATED", "RETIRED"})
EVIDENCE_STATUSES = frozenset({"PENDING", "VALID", "INVALID", "SUPERSEDED", "ABSENT"})
EVIDENCE_BLOCKERS = {
    "PENDING": "EVIDENCE_PENDING_VALIDATION",
    "INVALID": "EVIDENCE_INVALID",
    "SUPERSEDED": "EVIDENCE_SUPERSEDED",
    "ABSENT": "EVIDENCE_MISSING",
}

MET, NOT_MET, UNKNOWN = "MET", "NOT_MET", "UNKNOWN"


def _invalid(detail: str) -> ValueError:
    return ValueError(f"EVIDENCE_READINESS_MANIFEST_INVALID:{detail}")


def _enum(
    candidate: Mapping[str, Any], key: str, allowed: frozenset[str], index: int
) -> str | None:
    value = candidate.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(f"candidate_{index}_{key}_out_of_contract")
    return value


def _flag(candidate: Mapping[str, Any], key: str, index: int) -> bool | None:
    value = candidate.get(key)
    if value is not None and not isinstance(value, bool):
        raise _invalid(f"candidate_{index}_{key}_not_boolean")
    return value


def validate_evidence_readiness_manifest(
    manifest: Any,
) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(source, candidates)`` or raise ``ValueError`` (fail closed)."""
    if not isinstance(manifest, Mapping):
        raise _invalid("manifest_not_object")
    unknown = sorted(set(manifest) - ALLOWED_MANIFEST_KEYS)
    if unknown:
        raise _invalid(f"unknown_manifest_keys={','.join(map(str, unknown))}")
    source = manifest.get("source")
    if not isinstance(source, str) or not source.strip():
        raise _invalid("source_required")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise _invalid("candidates_required")
    if len(candidates) > MAX_CANDIDATES:
        raise _invalid(f"too_many_candidates>{MAX_CANDIDATES}")
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise _invalid(f"candidate_{index}_not_object")
        kind = candidate.get("kind")
        if kind not in KIND_KEYS:
            raise _invalid(f"candidate_{index}_kind_out_of_contract")
        unknown_fields = sorted(set(candidate) - KIND_KEYS[kind])
        if unknown_fields:
            raise _invalid(
                f"candidate_{index}_unknown_fields={','.join(map(str, unknown_fields))}"
            )
        candidate_id = candidate.get("candidate_id")
        if isinstance(candidate_id, bool) or not (
            (isinstance(candidate_id, int) and candidate_id > 0)
            or (isinstance(candidate_id, str) and candidate_id.strip())
        ):
            raise _invalid(f"candidate_{index}_candidate_id_required")
        identity = str(candidate_id).strip()
        if identity in seen:
            raise _invalid(f"candidate_{index}_duplicate_candidate_id")
        seen.add(identity)
        provenance = candidate.get("candidate_provenance")
        if provenance is not None and not isinstance(provenance, Mapping):
            raise _invalid(f"candidate_{index}_candidate_provenance_not_object")
        cleaned.append(dict(candidate))
    return source.strip(), cleaned


def _criterion(state: str, observed: Any, blocker: str | None = None) -> dict[str, Any]:
    return {"state": state, "observed": observed, "blocker": blocker}


def _evaluate_candidate(candidate: Mapping[str, Any], index: int) -> dict[str, Any]:
    kind = candidate["kind"]
    criteria: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    review = _enum(candidate, "candidate_review_status", REVIEW_STATUSES, index)
    if review is None:
        missing.append("candidate_review_status")
        criteria["review"] = _criterion(UNKNOWN, None)
    elif review == "ACCEPTED":
        criteria["review"] = _criterion(MET, review)
    else:
        criteria["review"] = _criterion(NOT_MET, review, "CANDIDATE_NOT_ACCEPTED")

    stage = _enum(candidate, "session_stage", SESSION_STAGES, index)
    if stage is None:
        missing.append("session_stage")
        criteria["session"] = _criterion(UNKNOWN, None)
    elif stage == "READY_FOR_REVIEW":
        criteria["session"] = _criterion(MET, stage)
    else:
        criteria["session"] = _criterion(NOT_MET, stage, "SESSION_NOT_READY_FOR_REVIEW")

    provenance = candidate.get("candidate_provenance")
    if provenance is None:
        missing.append("candidate_provenance")
        criteria["provenance"] = _criterion(UNKNOWN, None)
    elif provenance:
        criteria["provenance"] = _criterion(MET, "PRESENT")
    else:
        criteria["provenance"] = _criterion(NOT_MET, "EMPTY", "PROVENANCE_INCOMPLETE")

    if kind == "ENTITY":
        resolution = _enum(candidate, "resolution_status", RESOLUTION_STATUSES, index)
        registry = _enum(candidate, "registry_status", REGISTRY_STATUSES, index)
        observed = {"resolution_status": resolution, "registry_status": registry}
        if resolution is None:
            missing.append("resolution_status")
            criteria["ontology"] = _criterion(UNKNOWN, observed)
        elif resolution == "UNRESOLVED":
            criteria["ontology"] = _criterion(NOT_MET, observed, "ONTOLOGY_UNRESOLVED")
        elif resolution != "ACCEPTED":
            criteria["ontology"] = _criterion(
                NOT_MET, observed, "ONTOLOGY_MATCH_NOT_ACCEPTED"
            )
        elif registry is None:
            missing.append("registry_status")
            criteria["ontology"] = _criterion(UNKNOWN, observed)
        elif registry != "ACTIVE":
            criteria["ontology"] = _criterion(
                NOT_MET, observed, "ONTOLOGY_VERSION_INACTIVE"
            )
        else:
            criteria["ontology"] = _criterion(MET, observed)
    else:
        evidence = _enum(
            candidate, "evidence_validation_status", EVIDENCE_STATUSES, index
        )
        if evidence is None:
            missing.append("evidence_validation_status")
            criteria["evidence"] = _criterion(UNKNOWN, None)
        elif evidence == "VALID":
            criteria["evidence"] = _criterion(MET, evidence)
        else:
            criteria["evidence"] = _criterion(
                NOT_MET, evidence, EVIDENCE_BLOCKERS[evidence]
            )
        for key, name, blocker in (
            ("subject_ready", "subject", "SUBJECT_NOT_READY"),
            ("object_ready", "object", "OBJECT_NOT_READY"),
        ):
            flag = _flag(candidate, key, index)
            if flag is None:
                missing.append(key)
                criteria[name] = _criterion(UNKNOWN, None)
            elif flag:
                criteria[name] = _criterion(MET, True)
            else:
                criteria[name] = _criterion(NOT_MET, False, blocker)

    blockers = [item["blocker"] for item in criteria.values() if item["blocker"]]
    unknown = sorted(
        name for name, item in criteria.items() if item["state"] == UNKNOWN
    )
    if blockers:
        readiness_state = "BLOCKED"
    elif unknown:
        readiness_state = "INDETERMINATE"
    else:
        readiness_state = "CRITERIA_MET_AWAITING_HUMAN_REVIEW"
    return {
        "candidate_id": candidate["candidate_id"],
        "kind": kind,
        "readiness_state": readiness_state,
        "criteria": criteria,
        "blockers": blockers,
        "missing_fields": missing,
        "unknown_criteria": unknown,
        "human_review_required": True,
    }


def build_evidence_readiness_report(manifest: Any) -> dict[str, Any]:
    """Build a deterministic, human-review-only evidence readiness report."""
    source, candidates = validate_evidence_readiness_manifest(manifest)
    evaluations = [
        _evaluate_candidate(candidate, index)
        for index, candidate in enumerate(candidates)
    ]
    counts = {
        state: sum(1 for item in evaluations if item["readiness_state"] == state)
        for state in ("BLOCKED", "INDETERMINATE", "CRITERIA_MET_AWAITING_HUMAN_REVIEW")
    }
    summary = {
        "candidates_evaluated": len(evaluations),
        "readiness_state_counts": counts,
        "candidates_with_missing_fields": sum(
            1 for item in evaluations if item["missing_fields"]
        ),
    }
    digest = hashlib.sha256(
        json.dumps(
            {
                "source": source,
                "evaluation_version": EVALUATION_VERSION,
                "evaluations": evaluations,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "status": "ok",
        "mission_type": "evidence_readiness_evaluation",
        "artifact_type": "evidence_readiness_report",
        "evaluation_version": EVALUATION_VERSION,
        "source": source,
        "review_state": "awaiting_human_review",
        "human_review_required": True,
        "scientific_authority": "none",
        "scientific_conclusions_published": False,
        "approval_recorded": False,
        "evidence_state_changed": False,
        "readiness_persisted": False,
        "provider_called": False,
        "external_network_called": False,
        "domain_database_written": False,
        "canonical_graph_mutated": False,
        "taxonomy_mutated": False,
        "summary": summary,
        "evaluations": evaluations,
        "report_digest": digest,
    }
