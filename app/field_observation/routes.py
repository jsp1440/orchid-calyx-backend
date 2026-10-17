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

import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)

from app.security import verify_owner_or_api_key
from app.storage import INTAKE_STORAGE_DIR, LocalImmutableStorage, sanitize_filename

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
DEFAULT_FIELD_MEDIA_MAX_BYTES = 200 * 1024 * 1024

Auth = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]
AuthSubjectHeader = Annotated[str | None, Header(alias="X-Auth-Subject")]


def get_service() -> FieldObservationService:
    return FieldObservationService(get_store())


Service = Annotated[FieldObservationService, Depends(get_service)]


def field_media_storage() -> LocalImmutableStorage:
    """Storage for original field media. Tests point this at tmp_path; production must mount durable private storage."""
    root = Path(os.environ.get("FIELD_MEDIA_STORAGE_DIR", str(INTAKE_STORAGE_DIR / "field-journal")))
    return LocalImmutableStorage(root=root)


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def field_media_durability() -> str:
    """Truthful durability of the server copy of uploaded originals.

    Nothing in this repository proves that ``FIELD_MEDIA_STORAGE_DIR`` sits on a
    persistent disk, so durability is claimed only when the operator explicitly
    declares it with ``FIELD_MEDIA_STORAGE_DURABLE=true`` after mounting durable,
    backed-up private storage at that path.
    """
    declared = os.environ.get("FIELD_MEDIA_STORAGE_DURABLE", "").strip().lower()
    return "durable" if declared in _TRUE_VALUES else "not_guaranteed"


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


def _parse_captured_at(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="captured_at must be an ISO-8601 datetime") from exc


#: Content types an original may be served back as. Camera originals are raster
#: images or video; anything else (notably ``image/svg+xml``, which a browser
#: executes as a document) is served as an opaque download.
SERVABLE_ORIGINAL_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/heic",
        "image/heif",
        "image/avif",
        "image/tiff",
        "image/bmp",
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "video/3gpp",
        "video/x-m4v",
        "video/mpeg",
        "video/ogg",
    }
)
MEDIA_GONE_DETAIL = (
    "The original is no longer held by the server; the device copy is authoritative. "
    "Re-upload it from the Field Journal."
)


def _base_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _served_content_type(stored: str | None) -> str:
    base = _base_content_type(stored)
    return base if base in SERVABLE_ORIGINAL_TYPES else "application/octet-stream"


def _content_disposition(filename: str) -> str:
    """RFC 6266/5987 attachment header that survives non-ASCII names.

    Starlette encodes headers as latin-1, so a raw ``orquídea.jpg`` or CJK
    name raised a 500. Send an ASCII fallback plus the exact UTF-8 name.
    """
    def _ascii(text: str) -> str:
        folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^A-Za-z0-9._ ()\-]+", "_", folded).strip(" ._")

    name = Path(filename)
    stem = _ascii(name.stem).strip("_") or "original"
    suffix = _ascii(name.suffix)
    ascii_name = f"{stem}.{suffix}" if suffix else stem
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _media_kind(content_type: str | None, requested: str | None) -> str:
    if "svg" in _base_content_type(content_type) or _base_content_type(content_type).endswith("+xml"):
        raise HTTPException(status_code=422, detail="SVG/XML is not accepted as original field media; upload the camera photo or video")
    if content_type and content_type.startswith("image/"):
        derived = "photo"
    elif content_type and content_type.startswith("video/"):
        derived = "video"
    else:
        raise HTTPException(status_code=422, detail="Only image/* or video/* original media are accepted")
    if requested and requested != derived:
        raise HTTPException(status_code=422, detail="media_kind does not match the uploaded content type")
    return derived


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
    """Attach provenance for media the storage layer already holds (opaque key, SHA-256)."""
    subject = resolve_observer_subject(auth, x_auth_subject)
    _authorise_record(auth, subject, _load(service, observation_id))
    return service.attach_photo(observation_id, payload)


@router.post("/{observation_id}/media", response_model=PhotoOut, status_code=201)
async def upload_original_media(
    observation_id: str,
    auth: Auth,
    service: Service,
    file: Annotated[UploadFile, File()],
    x_auth_subject: AuthSubjectHeader = None,
    captured_at: Annotated[str | None, Form()] = None,
    media_kind: Annotated[str | None, Form()] = None,
    client_media_id: Annotated[str | None, Form(max_length=120)] = None,
) -> PhotoOut:
    """Preserve one original photo/video byte-for-byte, then attach its provenance.

    The storage adapter is content-addressed and immutable: re-uploading the
    same bytes for the same observation returns the same attached media record,
    which is the sync idempotency boundary for the Saturday MVP.

    ``durability`` reports whether the server copy is on storage the operator
    has declared durable; see :func:`field_media_durability`.
    """
    subject = resolve_observer_subject(auth, x_auth_subject)
    _authorise_record(auth, subject, _load(service, observation_id))
    kind = _media_kind(file.content_type, media_kind)
    max_bytes = int(os.environ.get("FIELD_MEDIA_MAX_BYTES", str(DEFAULT_FIELD_MEDIA_MAX_BYTES)))
    data = await file.read(max_bytes + 1)
    try:
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail="The media file exceeds FIELD_MEDIA_MAX_BYTES")
        stored = field_media_storage().preserve(data, file.filename or f"{kind}.bin")
        attach = PhotoAttachRequest(
            storage_key=stored.storage_key,
            content_hash=stored.sha256,
            media_kind=kind,
            # Owner sessions may identify a person by email. The existing media
            # contract intentionally stores only opaque subject tokens; the
            # parent observation already carries the observer identity.
            photographer_subject=subject if "@" not in subject else None,
            captured_at=_parse_captured_at(captured_at),
            license=None,
            provenance={
                "source": "field_journal_mvp",
                "original_filename": stored.display_filename,
                "content_type": file.content_type or "application/octet-stream",
                "byte_size": stored.byte_size,
                "client_media_id": client_media_id,
                "offline_original_preserved": True,
                # Originals are stored unmodified, so camera EXIF (which may hold
                # device GPS) is retained in the private master. Readback is
                # authenticated and observer-scoped; nothing here is public.
                "embedded_metadata": "original_unmodified_may_include_device_location",
                "uploaded_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        )
        stored_media = service.attach_photo(observation_id, attach)
        return stored_media.model_copy(update={"durability": field_media_durability()})
    finally:
        await file.close()


@router.get("/{observation_id}/media/{content_hash}/original")
def download_original_media(
    observation_id: str,
    content_hash: str,
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
) -> Response:
    """Read back an original exactly as uploaded. Authenticated and never cached."""
    subject = resolve_observer_subject(auth, x_auth_subject)
    _authorise_record(auth, subject, _load(service, observation_id))
    try:
        record = service.photo_record_by_hash(observation_id, content_hash)
    except ObservationNotFound as exc:
        raise HTTPException(status_code=404, detail="Media not found") from exc
    try:
        data = field_media_storage().read(str(record["storage_key"]))
    except FileNotFoundError as exc:
        # The record survived (database) but the bytes did not (storage not
        # declared durable, or a redeploy wiped it). Say so rather than 500.
        raise HTTPException(status_code=410, detail=MEDIA_GONE_DETAIL) from exc
    provenance = record.get("provenance") or {}
    filename = sanitize_filename(str(provenance.get("original_filename") or content_hash))
    return Response(
        content=data,
        media_type=_served_content_type(provenance.get("content_type")),
        headers={
            "Content-Disposition": _content_disposition(filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


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
