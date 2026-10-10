"""Owner-gated API for governed Matrix contributor-image intake and review.

Wires the Phase-1 governed intake pathway (PR #1793) into the FastAPI router
architecture. Authentication, actor scoping, and error mapping follow the
existing Matrix session/vision routers exactly:

* ``verify_owner_or_api_key`` authenticates every endpoint.
* API-key callers are trusted automation (``access_actor=None``); owner
  sessions are tenant-scoped and fail closed across owners.
* Machine-extracted characters remain review-required suggestions; only an
  explicit reviewer decision moves them into Matrix scoring, via the governed
  session runtime.

Nothing here deploys, merges migrations, or calls paid providers.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.contributor_intake_service import get_batch_manifest, intake_batch
from runtime.matrix_contributor_bridge import (
    attach_contributor_extractions,
    build_contributor_evidence_record,
    list_contributor_suggestions,
    review_contributor_suggestion,
)
from runtime.matrix_identification_session import evaluate_session, get_session
from runtime.matrix_identification_workflow import build_identification_report

router = APIRouter(
    prefix="/api/matrix-contributor",
    tags=["matrix-contributor-intake"],
)


class ContributorSubmissionInput(BaseModel):
    original_filename: str = Field(min_length=1, max_length=300)
    content_base64: str | None = None
    content_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    original_object_ref: str | None = Field(default=None, max_length=500)
    mime_type: str | None = Field(default=None, max_length=100)
    submission_id: str | None = Field(default=None, max_length=200)
    contributor_id: str | None = Field(
        default=None,
        max_length=200,
        description="Honored only for trusted API-key automation; ignored for owner sessions.",
    )
    contributor_display_name: str | None = Field(default=None, max_length=200)
    permission_grant: str | None = Field(default=None, max_length=60)
    rights_holder_affirmed: bool | None = None
    taxon_name: str | None = Field(default=None, max_length=300)
    taxon_certainty: Literal[
        "determined_by_contributor", "suggested", "unknown"
    ] = "unknown"
    candidate_taxa: list[dict[str, Any]] | None = None
    provenance: dict[str, Any] | None = None


class ContributorIntakeRequest(BaseModel):
    batch_id: str | None = Field(default=None, min_length=1, max_length=120)
    submissions: list[ContributorSubmissionInput] = Field(min_length=1, max_length=500)
    open_sessions: bool = False
    registry_id: str | None = Field(default=None, max_length=120)
    registry_version: str | None = Field(default=None, max_length=120)
    canonical_lookup: dict[str, str] | None = None


class ContributorExtractionInput(BaseModel):
    character: str = Field(min_length=1, max_length=120)
    value: Any
    machine_confidence: float | None = Field(default=None, ge=0, le=1)
    extractor: str | None = Field(default=None, max_length=200)
    extractor_version: str | None = Field(default=None, max_length=60)
    extraction_method: str | None = Field(default=None, max_length=200)
    limitations: list[str] | None = None


class ContributorExtractionAttachRequest(BaseModel):
    submission_id: str = Field(min_length=1, max_length=200)
    extractions: list[ContributorExtractionInput] = Field(min_length=1, max_length=200)


class ContributorSuggestionReviewRequest(BaseModel):
    decision: Literal["accept", "revise", "reject"]
    certainty: Literal["certain", "probable", "uncertain", "unknown"] | None = None
    revised_value: Any = None
    comments: str | None = Field(default=None, max_length=2000)


class ContributorEvaluateRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


class ContributorEvidenceRecordRequest(BaseModel):
    submission_id: str = Field(min_length=1, max_length=200)
    source_assertions: list[dict[str, Any]] | None = None


class IdentificationReportRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    ambiguity_epsilon: float = Field(default=0.05, ge=0, le=1)
    synonym_entries: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Optional governed synonym entries "
            "({canonical_taxon_id, accepted_name, synonyms[]}) used to reconcile "
            "candidate names for reporting. Never mutates canonical taxonomy."
        ),
    )
    source_assertions: list[dict[str, Any]] | None = None


def _actor(auth: Any) -> str:
    if not isinstance(auth, dict):
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    actor = str(auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    return actor


def _access_actor(auth: Any) -> str | None:
    """Owner sessions are tenant-scoped; API-key callers are trusted system automation."""
    if not isinstance(auth, dict):
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    if auth.get("auth_type") == "api_key":
        return None
    return _actor(auth)


def _service_unavailable(exc: RuntimeError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "MATRIX_CONTRIBUTOR_INTAKE_UNAVAILABLE", "message": str(exc)},
    )


def _session_image(session: dict[str, Any], submission_id: str) -> dict[str, Any]:
    """Resolve the governed staged-image record for one submission.

    Already-attached images live in the session record. Before first attach,
    the authoritative copy is the persisted batch manifest named by the
    session's own provenance metadata.
    """
    image = (session.get("contributor_images") or {}).get(submission_id)
    if image:
        return image
    metadata = session.get("metadata") or {}
    batch_id = metadata.get("contributor_batch_id")
    if batch_id:
        try:
            manifest = get_batch_manifest(str(batch_id))
        except (FileNotFoundError, ValueError):
            manifest = None
        if manifest:
            for staged in manifest.get("staged", []):
                if staged.get("submission_id") == submission_id:
                    return staged
    raise HTTPException(
        status_code=422,
        detail=(
            f"staged contributor image not found for this session: {submission_id}"
        ),
    )


@router.post("/intake")
def intake(
    payload: ContributorIntakeRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return intake_batch(
            [item.model_dump() for item in payload.submissions],
            actor=_actor(auth),
            batch_id=payload.batch_id,
            allow_contributor_override=(
                isinstance(auth, dict) and auth.get("auth_type") == "api_key"
            ),
            open_sessions=payload.open_sessions,
            registry_id=payload.registry_id,
            registry_version=payload.registry_version,
            canonical_lookup=payload.canonical_lookup,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: str,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return get_batch_manifest(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/extractions")
def attach_extractions(
    session_id: str,
    payload: ContributorExtractionAttachRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    access_actor = _access_actor(auth)
    try:
        session = get_session(session_id, access_actor=access_actor)
        image = _session_image(session, payload.submission_id)
        return attach_contributor_extractions(
            session_id,
            image,
            [item.model_dump() for item in payload.extractions],
            access_actor=access_actor,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.get("/sessions/{session_id}/suggestions")
def get_suggestions(
    session_id: str,
    state: str | None = None,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return list_contributor_suggestions(
            session_id,
            access_actor=_access_actor(auth),
            state=state,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.post("/sessions/{session_id}/suggestions/{suggestion_id}/review")
def review_suggestion(
    session_id: str,
    suggestion_id: str,
    payload: ContributorSuggestionReviewRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return review_contributor_suggestion(
            session_id,
            suggestion_id,
            decision=payload.decision,
            reviewer=_actor(auth),
            certainty=payload.certainty,
            revised_value=payload.revised_value,
            comments=payload.comments,
            access_actor=_access_actor(auth),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.post("/sessions/{session_id}/evaluate")
def evaluate(
    session_id: str,
    payload: ContributorEvaluateRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Rank candidates from reviewed observations only (existing Matrix scoring)."""
    try:
        return evaluate_session(
            session_id,
            limit=payload.limit,
            access_actor=_access_actor(auth),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.post("/sessions/{session_id}/evidence-record")
def evidence_record(
    session_id: str,
    payload: ContributorEvidenceRecordRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    access_actor = _access_actor(auth)
    try:
        session = get_session(session_id, access_actor=access_actor)
        image = _session_image(session, payload.submission_id)
        return build_contributor_evidence_record(
            session_id,
            image,
            source_assertions=payload.source_assertions,
            access_actor=access_actor,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.post("/sessions/{session_id}/identification")
def identification_report(
    session_id: str,
    payload: IdentificationReportRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Full governed identification report for one session.

    Ranked candidates with per-candidate supporting / partial / contradicting /
    missing characters, taxonomic resolution with explicit synonym
    reconciliation, contributor-image provenance links, review-gate state,
    ambiguity detection, and honest identification limitations. Candidate
    ranking is hypothesis-generating evidence, never a determination.
    """
    try:
        return build_identification_report(
            session_id,
            limit=payload.limit,
            ambiguity_epsilon=payload.ambiguity_epsilon,
            synonym_entries=payload.synonym_entries,
            source_assertions=payload.source_assertions,
            access_actor=_access_actor(auth),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc
