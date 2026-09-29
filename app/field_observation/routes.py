"""Journey 5 — field observation routes (``/api/field-observations``).

Every route requires the owner session or the backend API key: the record is
the observer's own report and the notes are free text, so nothing here is
anonymous. Callers authenticated with the API key name the observer through
``X-Auth-Subject`` (an opaque token, never an email address) and are scoped to
that observer; the owner session and the bare service identity may read any
observer's records and curate them.

The Journey 6 hypothesis loop mounts ``/{observation_id}/hypotheses`` under the
same prefix from ``app.field_hypotheses``; the paths are disjoint and every
observation returned here names its own ``hypotheses_path``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from app.security import verify_owner_or_api_key

from .schemas import (
    CurationDecisionIn,
    FieldObservationCreate,
    FieldObservationListOut,
    FieldObservationOut,
    ObservationCurationState,
    PhotoAttachRequest,
    PhotoOut,
)
from .service import FieldObservationService, ObservationNotFound, get_store

router = APIRouter(prefix="/api/field-observations", tags=["field-observation"])

SERVICE_SUBJECT = "backend_api_key"

Auth = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]
AuthSubjectHeader = Annotated[str | None, Header(alias="X-Auth-Subject")]


def get_service() -> FieldObservationService:
    return FieldObservationService(get_store())


Service = Annotated[FieldObservationService, Depends(get_service)]


def resolve_observer_subject(auth: dict[str, Any], header_subject: str | None) -> str:
    """Who the observation belongs to.

    Owner session: the owner. API key: the ``X-Auth-Subject`` header when
    present (the frontend's authenticated member), else the service identity.
    """
    if auth.get("auth_type") == "api_key":
        subject = (header_subject or "").strip()
        if not subject:
            return SERVICE_SUBJECT
        if "@" in subject or len(subject) > 120:
            raise HTTPException(
                status_code=422,
                detail="X-Auth-Subject must be an opaque token of at most 120 characters, never an email address",
            )
        return subject
    return str(auth.get("actor") or "owner")


def _is_scoped_member(auth: dict[str, Any], subject: str) -> bool:
    return auth.get("auth_type") == "api_key" and subject != SERVICE_SUBJECT


def _authorise_record(auth: dict[str, Any], subject: str, observation: FieldObservationOut) -> None:
    if _is_scoped_member(auth, subject) and observation.observer_subject != subject:
        raise HTTPException(status_code=404, detail="Observation not found")


def _load(service: FieldObservationService, observation_id: str) -> FieldObservationOut:
    try:
        return service.get(observation_id)
    except ObservationNotFound as exc:
        raise HTTPException(status_code=404, detail="Observation not found") from exc


@router.post("", response_model=FieldObservationOut, status_code=201)
def create_observation(
    payload: FieldObservationCreate,
    response: Response,
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
) -> FieldObservationOut:
    """Record an observer's report. Idempotent per observer and ``client_draft_id``."""
    subject = resolve_observer_subject(auth, x_auth_subject)
    observation, created = service.create(subject, payload)
    if not created:
        response.status_code = 200
    return observation


@router.get("", response_model=FieldObservationListOut)
def list_observations(
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
    observer_subject: Annotated[str | None, Query(max_length=120)] = None,
    curation_state: Annotated[ObservationCurationState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FieldObservationListOut:
    """List one observer's reports, newest first. Members see only their own."""
    subject = resolve_observer_subject(auth, x_auth_subject)
    target = observer_subject or subject
    if _is_scoped_member(auth, subject) and target != subject:
        raise HTTPException(status_code=403, detail="Members may list only their own observations")
    return service.list_for(target, curation_state=curation_state, limit=limit, offset=offset)


@router.get("/{observation_id}", response_model=FieldObservationOut)
def get_observation(
    observation_id: str,
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
) -> FieldObservationOut:
    subject = resolve_observer_subject(auth, x_auth_subject)
    observation = _load(service, observation_id)
    _authorise_record(auth, subject, observation)
    return observation


@router.get("/{observation_id}/photos", response_model=list[PhotoOut])
def list_photos(
    observation_id: str,
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
) -> list[PhotoOut]:
    subject = resolve_observer_subject(auth, x_auth_subject)
    _authorise_record(auth, subject, _load(service, observation_id))
    return service.list_photos(observation_id)


@router.post("/{observation_id}/photos", response_model=PhotoOut, status_code=201)
def attach_photo(
    observation_id: str,
    payload: PhotoAttachRequest,
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
) -> PhotoOut:
    """Attach provenance for a photo the storage layer already holds (opaque key, SHA-256)."""
    subject = resolve_observer_subject(auth, x_auth_subject)
    _authorise_record(auth, subject, _load(service, observation_id))
    return service.attach_photo(observation_id, payload)


@router.post("/{observation_id}/curation", response_model=FieldObservationOut)
def curate_observation(
    observation_id: str,
    decision: CurationDecisionIn,
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
) -> FieldObservationOut:
    """Human curation boundary: owner session or service identity only."""
    subject = resolve_observer_subject(auth, x_auth_subject)
    if _is_scoped_member(auth, subject):
        raise HTTPException(status_code=403, detail="Curation is a reviewer action, not an observer action")
    _load(service, observation_id)
    return service.curate(observation_id, decision, auth)
