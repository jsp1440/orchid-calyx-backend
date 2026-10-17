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

import asyncio
import concurrent.futures
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

from . import drive_archive
from .schemas import (
    CurationDecisionIn,
    FieldObservationCreate,
    FieldObservationListOut,
    FieldObservationOut,
    MediaArchiveOut,
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


# -- Google Drive archive of originals ---------------------------------------------------

ARCHIVE_RETRY_DEFAULT_BATCH = 20
ARCHIVE_RETRY_MAX_BATCH = 50
_TIMEOUT_ERRORS = (TimeoutError, asyncio.TimeoutError, concurrent.futures.TimeoutError)


def _archive_state_of(record: dict[str, Any]) -> dict[str, Any]:
    archive = (record.get("provenance") or {}).get("archive")
    return dict(archive) if isinstance(archive, dict) else {}


def _not_attempted_state(config: drive_archive.ArchiveConfig) -> dict[str, Any]:
    if config.error_code:
        return {
            "provider": drive_archive.PROVIDER,
            "state": drive_archive.STATE_PENDING,
            "error_code": config.error_code,
            "last_attempt_at": datetime.now(tz=timezone.utc).isoformat(),
        }
    return {
        "provider": drive_archive.PROVIDER,
        "state": drive_archive.STATE_NOT_CONFIGURED,
        "error_code": drive_archive.ERROR_NOT_CONFIGURED,
    }


def _pending_state(previous: dict[str, Any], error_code: str) -> dict[str, Any]:
    return {
        "provider": drive_archive.PROVIDER,
        "state": drive_archive.STATE_PENDING,
        "error_code": error_code,
        "last_attempt_at": datetime.now(tz=timezone.utc).isoformat(),
        "attempts": int(previous.get("attempts") or 0) + 1,
    }


def _verified_state(receipt: drive_archive.ArchiveReceipt) -> dict[str, Any]:
    return {"provider": drive_archive.PROVIDER, "state": drive_archive.STATE_VERIFIED, **receipt.as_dict()}


def _archive_call(archive: drive_archive.DriveMediaArchive, observation_id: str, record: dict[str, Any], data: bytes):
    provenance = record.get("provenance") or {}
    return lambda: archive.archive(
        observation_id=observation_id,
        data=data,
        sha256=str(record["content_hash"]),
        display_filename=str(provenance.get("original_filename") or "original"),
        mime_type=_base_content_type(provenance.get("content_type")) or "application/octet-stream",
        client_media_id=provenance.get("client_media_id"),
    )


def _outcome_state(previous: dict[str, Any], receipt: Any = None, exc: BaseException | None = None) -> dict[str, Any]:
    if exc is not None:
        code = drive_archive.ERROR_TIMEOUT if isinstance(exc, _TIMEOUT_ERRORS) else drive_archive.error_code_for(exc)
        return _pending_state(previous, code)
    return _verified_state(receipt)


async def archive_original_async(
    service: FieldObservationService, observation_id: str, record: dict[str, Any], data: bytes
) -> dict[str, Any]:
    """Archive after the local preserve, bounded by the archive timeout. Never raises."""
    previous = _archive_state_of(record)
    if previous.get("state") == drive_archive.STATE_VERIFIED:
        return previous
    config = drive_archive.get_field_media_archive()
    if config.archive is None:
        state = _not_attempted_state(config)
    else:
        future = drive_archive.submit_bounded(_archive_call(config.archive, observation_id, record, data))
        try:
            receipt = await asyncio.wait_for(asyncio.wrap_future(future), timeout=config.archive.timeout_seconds)
            state = _outcome_state(previous, receipt=receipt)
        except Exception as exc:  # noqa: BLE001 - a Drive failure never fails the upload
            state = _outcome_state(previous, exc=exc)
    service.set_media_archive(observation_id, str(record["content_hash"]), state)
    return state


def archive_original_sync(
    service: FieldObservationService,
    config: drive_archive.ArchiveConfig,
    observation_id: str,
    record: dict[str, Any],
    data: bytes,
) -> dict[str, Any]:
    previous = _archive_state_of(record)
    if config.archive is None:
        state = _not_attempted_state(config)
        service.set_media_archive(observation_id, str(record["content_hash"]), state)
        return state
    future = drive_archive.submit_bounded(_archive_call(config.archive, observation_id, record, data))
    try:
        state = _outcome_state(previous, receipt=future.result(timeout=config.archive.timeout_seconds))
    except Exception as exc:  # noqa: BLE001 - recorded as an error code, never raised
        state = _outcome_state(previous, exc=exc)
    service.set_media_archive(observation_id, str(record["content_hash"]), state)
    return state


def _archive_out(state: dict[str, Any]) -> MediaArchiveOut | None:
    if not state.get("state"):
        return None
    return MediaArchiveOut(
        state=state["state"],
        drive_file_id=state.get("drive_file_id"),
        verified_at=state.get("verified_at"),
        error_code=state.get("error_code"),
    )


def _local_original_exists(storage: LocalImmutableStorage, storage_key: str) -> bool:
    if not re.fullmatch(r"sha256/[0-9a-f]{2}/[0-9a-f]{64}", storage_key):
        return False
    return (storage.root / storage_key).is_file()


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


def _require_reviewer(auth: dict[str, Any], x_auth_subject: str | None) -> None:
    subject = resolve_observer_subject(auth, x_auth_subject)
    if _is_scoped_member(auth, subject):
        raise HTTPException(status_code=403, detail="The media archive is managed by the owner, not by observers")


@router.get("/archive/status")
def archive_status(
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
    probe: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    """Counts of original media by archive state. No ids, names, observers or locality.

    ``probe=true`` additionally makes one read-only Drive call (look up the
    archive's own root folder) to prove the credentials work.
    """
    _require_reviewer(auth, x_auth_subject)
    config = drive_archive.get_field_media_archive()
    storage = field_media_storage()
    counts = {"verified": 0, "pending": 0, "not_configured": 0, "untracked": 0}
    pending_error_codes: dict[str, int] = {}
    unarchived_without_local_bytes = 0
    for row in service.iter_media_records():
        state = _archive_state_of(row)
        name = state.get("state") if state.get("state") in counts else "untracked"
        counts[name] += 1
        if name == "verified":
            continue
        if state.get("error_code"):
            pending_error_codes[state["error_code"]] = pending_error_codes.get(state["error_code"], 0) + 1
        if not _local_original_exists(storage, str(row.get("storage_key") or "")):
            unarchived_without_local_bytes += 1
    result: dict[str, Any] = {
        "provider": drive_archive.PROVIDER,
        "configured": config.configured,
        "configuration_error": config.error_code,
        "counts": counts,
        "total": sum(counts.values()),
        "error_codes": pending_error_codes,
        "unarchived_without_local_bytes": unarchived_without_local_bytes,
        "retry_batch_limit": ARCHIVE_RETRY_MAX_BATCH,
    }
    if probe:
        if config.archive is None:
            result["probe"] = {"ok": False, "error_code": config.error_code or drive_archive.ERROR_NOT_CONFIGURED}
        else:
            future = drive_archive.submit_bounded(config.archive.find_root_folder)
            try:
                root = future.result(timeout=config.archive.timeout_seconds)
                result["probe"] = {"ok": True, "archive_folder_present": root is not None}
            except Exception as exc:  # noqa: BLE001 - reported as an error code only
                code = drive_archive.ERROR_TIMEOUT if isinstance(exc, _TIMEOUT_ERRORS) else drive_archive.error_code_for(exc)
                result["probe"] = {"ok": False, "error_code": code}
    return result


@router.post("/archive/retry")
def retry_archive(
    auth: Auth,
    service: Service,
    x_auth_subject: AuthSubjectHeader = None,
    limit: Annotated[int, Query(ge=1, le=ARCHIVE_RETRY_MAX_BATCH)] = ARCHIVE_RETRY_DEFAULT_BATCH,
) -> dict[str, Any]:
    """Retry the archive copy for at most ``limit`` unarchived originals still held locally."""
    _require_reviewer(auth, x_auth_subject)
    config = drive_archive.get_field_media_archive()
    if config.archive is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The Google Drive archive is not configured",
                "error_code": config.error_code or drive_archive.ERROR_NOT_CONFIGURED,
            },
        )
    storage = field_media_storage()
    attempted = verified = still_pending = skipped_missing = remaining = 0
    for row in service.iter_media_records():
        if _archive_state_of(row).get("state") == drive_archive.STATE_VERIFIED:
            continue
        if attempted >= limit:
            remaining += 1
            continue
        observation_id = str(row["observation_id"])
        try:
            data = storage.read(str(row.get("storage_key") or ""))
        except (FileNotFoundError, ValueError):
            skipped_missing += 1
            service.set_media_archive(
                observation_id,
                str(row["content_hash"]),
                _pending_state(_archive_state_of(row), drive_archive.ERROR_LOCAL_BYTES_MISSING),
            )
            continue
        attempted += 1
        state = archive_original_sync(service, config, observation_id, row, data)
        if state.get("state") == drive_archive.STATE_VERIFIED:
            verified += 1
        else:
            still_pending += 1
    return {
        "provider": drive_archive.PROVIDER,
        "attempted": attempted,
        "verified": verified,
        "still_pending": still_pending,
        "skipped_local_bytes_missing": skipped_missing,
        "remaining": remaining,
    }


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

    After the local preserve the original is copied to the Google Drive archive
    when it is configured (bounded by ``FIELD_MEDIA_DRIVE_TIMEOUT_SECONDS``).
    ``durability`` is ``durable`` once Drive's checksum and size match the
    original, or when the operator has declared the local storage durable (see
    :func:`field_media_durability`). A Drive failure never fails the upload: the
    archive stays ``pending`` and is retried by a re-upload or by
    ``POST /api/field-observations/archive/retry``.
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
        # Re-uploading the same bytes is the frontend's idempotent retry, and so
        # also the retry path for a pending archive copy.
        record = service.photo_record_by_hash(observation_id, stored.sha256)
        archive_state = await archive_original_async(service, observation_id, record, data)
        verified = archive_state.get("state") == drive_archive.STATE_VERIFIED
        return stored_media.model_copy(
            update={
                "durability": "durable" if verified else field_media_durability(),
                "archive": _archive_out(archive_state),
            }
        )
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
    provenance = record.get("provenance") or {}
    filename = sanitize_filename(str(provenance.get("original_filename") or content_hash))
    source = "server"
    storage = field_media_storage()
    try:
        data = storage.read(str(record["storage_key"]))
    except FileNotFoundError as exc:
        # The record survived (database) but the local bytes did not (a
        # redeploy wiped ephemeral storage). Fall back to the verified Drive copy.
        data = _read_from_archive(record, content_hash, exc)
        source = "google_drive_archive"
        try:
            storage.preserve(data, filename)
        except OSError:
            pass
    return Response(
        content=data,
        media_type=_served_content_type(provenance.get("content_type")),
        headers={
            "Content-Disposition": _content_disposition(filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Field-Media-Source": source,
        },
    )


def _read_from_archive(record: dict[str, Any], content_hash: str, missing: FileNotFoundError) -> bytes:
    archive_state = _archive_state_of(record)
    if archive_state.get("state") != drive_archive.STATE_VERIFIED:
        raise HTTPException(status_code=410, detail=MEDIA_GONE_DETAIL) from missing
    config = drive_archive.get_field_media_archive()
    if config.archive is None:
        raise HTTPException(
            status_code=503,
            detail="The original is archived in Google Drive but the archive is not configured on this server.",
        ) from missing
    future = drive_archive.submit_bounded(
        lambda: config.archive.fetch(archive_state, expected_sha256=content_hash)  # type: ignore[union-attr]
    )
    try:
        return future.result(timeout=config.archive.timeout_seconds)
    except drive_archive.ArchiveError as exc:
        if exc.error_code == drive_archive.ERROR_VERIFICATION_FAILED:
            raise HTTPException(status_code=502, detail="The archived copy failed checksum verification.") from None
        raise HTTPException(status_code=503, detail="The Google Drive archive is temporarily unavailable.") from None
    except Exception:  # noqa: BLE001 - provider detail is never echoed
        raise HTTPException(status_code=503, detail="The Google Drive archive is temporarily unavailable.") from None


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
