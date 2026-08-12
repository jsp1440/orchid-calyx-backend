"""Content-addressed, reproducible reports for governed Matrix sessions.

A report freezes the evidence/ranking state at one session revision. It is an
auditable candidate-ranking artifact, not a verified identification and not a
publication action. Generated Calyx prose is intentionally excluded from the
scientific report core because explanation text is not evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from runtime.matrix_identification_session import _write, evaluate_session, get_session

REPORT_SCHEMA_VERSION = "matrix-identification-report/v1"
MATRIX_EVALUATOR_VERSION = "matrix-identification-evaluator/v1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _vision_review_audit(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "suggestion_id": item.get("suggestion_id"),
            "analysis_id": item.get("analysis_id"),
            "vision_observation_id": item.get("vision_observation_id"),
            "image_id": item.get("image_id"),
            "character": item.get("character"),
            "state": item.get("state"),
            "proposed_value": item.get("proposed_value"),
            "accepted_value": item.get("accepted_value"),
            "machine_confidence": item.get("machine_confidence"),
            "measurement_basis": item.get("measurement_basis"),
            "vision_review_state": item.get("vision_review_state"),
            "matrix_observation_id": item.get("matrix_observation_id"),
            "review": item.get("review"),
            "limitations": item.get("limitations", []),
        }
        for item in session.get("vision_suggestions", [])
    ]


def build_report_core(evaluation: dict[str, Any]) -> dict[str, Any]:
    session = evaluation["session"]
    report = evaluation["report"]
    registry = report.get("registry") or session.get("registry") or {}
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": MATRIX_EVALUATOR_VERSION,
        "session_id": session["session_id"],
        "session_revision": int(session.get("revision", 0)),
        "session_owner": session.get("actor"),
        "registry": {
            "registry_id": registry.get("registry_id"),
            "version": registry.get("version"),
            "checksum_sha256": registry.get("checksum_sha256"),
            "publication_state": registry.get("publication_state"),
            "scope": registry.get("scope", {}),
        },
        "observations": [
            {
                "observation_id": item.get("observation_id"),
                "revision": item.get("revision"),
                "character": item.get("character"),
                "value": item.get("value"),
                "certainty": item.get("certainty"),
                "weight": item.get("weight"),
                "source": item.get("source"),
                "recorded_by": item.get("recorded_by"),
                "review_state": item.get("review_state"),
                "created_at": item.get("created_at"),
            }
            for item in session.get("observations", [])
        ],
        "ranking": {
            "candidates": report.get("candidates", []),
            "observation_count": report.get("observation_count"),
            "compared_character_count": report.get("compared_character_count"),
            "disclaimer": report.get("disclaimer"),
        },
        "next_observation": evaluation.get("next_observation"),
        "vision_review_audit": _vision_review_audit(session),
        "governance": {
            "artifact_type": "candidate_ranking_evidence_report",
            "verified_taxonomic_identification": False,
            "automatic_publication": False,
            "canonical_taxonomy_mutation": False,
            "calyx_narrative_is_evidence": False,
            "missing_candidate_state_is_biological_absence": False,
        },
    }


def finalize_report(
    session_id: str,
    *,
    access_actor: str | None = None,
    limit: int = 20,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    evaluation = evaluate_session(
        session_id,
        limit=limit,
        access_actor=access_actor,
        root=root,
        registry_root=registry_root,
    )
    core = build_report_core(evaluation)
    report_id = _digest(core)

    session = get_session(session_id, root=root, access_actor=access_actor)
    reports = session.setdefault("identification_reports", [])
    existing = next((item for item in reports if item.get("report_id") == report_id), None)
    if existing is not None:
        return {"created": False, "report": existing}

    record = {
        "report_id": report_id,
        "content_digest_sha256": report_id,
        "finalized_at": _now(),
        "core": core,
    }
    reports.append(record)
    session["updated_at"] = _now()
    _write(session, root=root)
    return {"created": True, "report": record}


def list_reports(
    session_id: str,
    *,
    access_actor: str | None = None,
    root=None,
) -> dict[str, Any]:
    session = get_session(session_id, root=root, access_actor=access_actor)
    items: list[dict[str, Any]] = []
    for item in session.get("identification_reports", []):
        core = item.get("core") or {}
        candidates = ((core.get("ranking") or {}).get("candidates") or [])
        items.append(
            {
                "report_id": item.get("report_id"),
                "content_digest_sha256": item.get("content_digest_sha256"),
                "finalized_at": item.get("finalized_at"),
                "session_revision": core.get("session_revision"),
                "registry": core.get("registry"),
                "leading_candidate": candidates[0].get("scientific_name") if candidates else None,
            }
        )
    return {"session_id": session_id, "reports": items}


def get_report(
    session_id: str,
    report_id: str,
    *,
    access_actor: str | None = None,
    root=None,
) -> dict[str, Any]:
    session = get_session(session_id, root=root, access_actor=access_actor)
    report = next(
        (item for item in session.get("identification_reports", []) if item.get("report_id") == report_id),
        None,
    )
    if report is None:
        raise FileNotFoundError(f"identification report not found: {report_id}")
    if _digest(report.get("core")) != report.get("content_digest_sha256"):
        raise ValueError("identification report content digest mismatch")
    return report
