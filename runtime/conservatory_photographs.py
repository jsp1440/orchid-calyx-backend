"""Photographs of a plant, stored without the coordinates of the grower's home.

WHY THIS REFUSES RATHER THAN DEGRADES

A phone photograph of an orchid on a windowsill routinely carries GPS
coordinates in its EXIF. Those coordinates are the grower's home address. This
collection is private, and a plant dossier can be shared, printed or served
behind a QR route, so the coordinates must never enter the store in the first
place — deleting them later does not un-write the file that already reached
disk.

Stripping needs an imaging library. If that library is missing, the choice is
between storing the image unstripped and refusing the upload. Storing it would
fail open on the one property this module exists to guarantee, and it would
fail silently: the photograph appears, everything looks fine, and the address
is on disk. So a missing library is a refusal, and the caller is told exactly
why.

The same reasoning covers a file the library cannot parse. An unreadable image
is not a safe image; it is one nobody has checked.

WHAT IS KEPT AND WHAT IS DROPPED

Everything EXIF is dropped, not just the GPS block. Camera serial numbers,
lens data, thumbnails and maker notes are all identifying to some degree, and
an allowlist of "safe" tags is a list that goes stale the first time a vendor
adds a field. Re-encoding from decoded pixels leaves nothing behind.

One EXIF value is read before it is discarded: when the photograph was taken.
That is genuinely useful — a chronology of a plant's growth is a chronology of
when the pictures were taken, not of when somebody got round to uploading them
— and it is recorded as its own field, separate from `recorded_at`. Absent
when the file did not carry it. Never inferred from the upload time, because a
photograph from three years ago would then claim to be from today.

NOT EVIDENCE

A photograph is a collection record. It shows what somebody pointed a camera
at, which is not the same as a determination, a measurement or a voucher, and
nothing here may be promoted into the knowledge graph on its own.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

__all__ = [
    "ACCEPTED_CONTENT_TYPES",
    "MAX_PHOTOGRAPH_BYTES",
    "ConservatoryPhotographStore",
    "PhotographError",
]


class PhotographError(Exception):
    """A refusal, carrying a code the API turns into a status."""


#: What may be stored. Anything else is refused rather than sniffed: guessing a
#: format from bytes is how a file that is not an image ends up on disk under a
#: name that says it is.
ACCEPTED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

#: Bounded so one upload cannot exhaust the volume the whole collection lives on.
MAX_PHOTOGRAPH_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class Photograph:
    id: str
    plant_id: str
    content_type: str
    byte_size: int
    #: When the camera says the picture was taken. Absent when the file did not
    #: say, and never filled in from the upload time.
    taken_at: str | None
    #: When it reached the Continuum. Always known, and never the same claim.
    recorded_at: str
    caption: str | None
    #: Stated on every record so a reader cannot infer that a stored photograph
    #: was checked for anything.
    is_scientific_evidence: bool = False
    exif_stripped: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _State:
    photographs: list[dict[str, Any]] = field(default_factory=list)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PhotographError(code)


def _load_image_library():
    """The imaging library, or a refusal.

    Imported lazily so that a deployment without it still serves every other
    conservatory route; only uploading a photograph fails, and it fails loudly.
    """
    try:
        from PIL import Image
    except Exception as exc:
        raise PhotographError("IMAGE_PROCESSING_UNAVAILABLE") from exc
    return Image


def _taken_at_from(image: Any) -> str | None:
    """The capture time the file claims, normalised, or None.

    EXIF stores this as "YYYY:MM:DD HH:MM:SS" with no timezone. The date is
    kept and the missing zone is left missing rather than assumed to be UTC:
    a photograph taken at 7pm in one hemisphere is not the same instant as the
    same string read as UTC, and the difference lands in the wrong day.
    """
    try:
        exif = image.getexif()
    except Exception:  # noqa: BLE001
        return None
    if not exif:
        return None
    # 36867 DateTimeOriginal, 306 DateTime. Original first: it is when the
    # shutter fired, while DateTime can be when the file was last written.
    for tag in (36867, 306):
        raw = exif.get(tag)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            # Left naive on purpose. EXIF carries no zone, and stamping one
            # on would turn "7pm somewhere" into a specific instant the camera
            # never recorded, landing in the wrong day either side of midnight.
            parsed = datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")  # noqa: DTZ007
        except ValueError:
            continue
        return parsed.isoformat()
    return None


class ConservatoryPhotographStore:
    """Atomic JSON index beside the image files themselves."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.images = self.root / "photographs"
        self.images.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "photographs.json"
        self._lock = threading.Lock()

    def _read(self) -> _State:
        if not self.path.exists():
            return _State()
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return _State()
        return _State(photographs=list(raw.get("photographs") or []))

    def _write(self, state: _State) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"photographs": state.photographs}, indent=2))
        os.replace(temporary, self.path)

    def store(
        self,
        *,
        plant_id: str,
        content: bytes,
        content_type: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Strip, re-encode and store one photograph, or refuse."""
        _require(bool(plant_id), "PLANT_REQUIRED")
        _require(bool(content), "EMPTY_UPLOAD")
        _require(len(content) <= MAX_PHOTOGRAPH_BYTES, "PHOTOGRAPH_TOO_LARGE")
        _require(content_type in ACCEPTED_CONTENT_TYPES, "CONTENT_TYPE_NOT_ACCEPTED")

        Image = _load_image_library()
        try:
            source = Image.open(BytesIO(content))
            source.load()
        except PhotographError:
            raise
        except Exception as exc:
            # An unreadable image is not a safe image; it is one nobody has
            # checked. It does not reach disk.
            raise PhotographError("PHOTOGRAPH_UNREADABLE") from exc

        taken_at = _taken_at_from(source)

        # Re-encoded from decoded pixels. Nothing from the original container
        # survives — not the GPS block, not the maker notes, not the thumbnail,
        # which can itself be a full second copy of the scene.
        buffer = BytesIO()
        target = ACCEPTED_CONTENT_TYPES[content_type]
        if target == "jpg":
            source.convert("RGB").save(buffer, format="JPEG", quality=90)
        elif target == "png":
            source.save(buffer, format="PNG")
        else:
            source.save(buffer, format="WEBP", quality=90)
        stripped = buffer.getvalue()

        record = Photograph(
            id=str(uuid.uuid4()),
            plant_id=plant_id,
            content_type=content_type,
            byte_size=len(stripped),
            taken_at=taken_at,
            recorded_at=datetime.now(UTC).isoformat(),
            caption=(caption or "").strip() or None,
        ).as_dict()

        with self._lock:
            (self.images / f"{record['id']}.{target}").write_bytes(stripped)
            state = self._read()
            state.photographs.append(record)
            self._write(state)
        return record

    def for_plant(self, plant_id: str) -> list[dict[str, Any]]:
        """This plant's photographs, oldest capture first.

        Ordered by when the picture was taken so the list reads as a
        chronology of the plant. Photographs with no capture time sort after
        the dated ones rather than being guessed into the sequence — a
        position in a chronology is a claim about when something happened.
        """
        with self._lock:
            rows = [
                row for row in self._read().photographs if row["plant_id"] == plant_id
            ]
        dated = sorted(
            (row for row in rows if row.get("taken_at")),
            key=lambda row: row["taken_at"],
        )
        undated = sorted(
            (row for row in rows if not row.get("taken_at")),
            key=lambda row: row["recorded_at"],
        )
        return dated + undated

    def get(self, photograph_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next(
                (row for row in self._read().photographs if row["id"] == photograph_id),
                None,
            )

    def bytes_for(self, photograph_id: str) -> bytes | None:
        record = self.get(photograph_id)
        if record is None:
            return None
        extension = ACCEPTED_CONTENT_TYPES[record["content_type"]]
        path = self.images / f"{photograph_id}.{extension}"
        return path.read_bytes() if path.exists() else None
