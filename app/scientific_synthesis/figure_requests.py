"""Durable, review-gated figure requests for canonical glossary concepts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_REQUEST_ID = re.compile(r"^[0-9a-f]{64}$")


class FigureRequestType(StrEnum):
    DIAGRAM = "DIAGRAM"
    SKETCH = "SKETCH"
    COLOR_ILLUSTRATION = "COLOR_ILLUSTRATION"
    PHOTO_SET = "PHOTO_SET"
    ANIMATION = "ANIMATION"
    COMPARISON_PLATE = "COMPARISON_PLATE"
    DISSECTION = "DISSECTION"


class FigureRequestState(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FigureSourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_ref: str = Field(min_length=1, max_length=500)
    source_hash: str = Field(min_length=16, max_length=256)
    citation: str | None = Field(default=None, max_length=2000)


class FigureRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: UUID
    request_type: FigureRequestType
    production_brief: str = Field(min_length=1, max_length=2000)
    source_provenance: FigureSourceProvenance


class FigureRequestRecord(BaseModel):
    """Immutable production request; never scientific evidence or approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    concept_id: UUID
    request_type: FigureRequestType
    production_brief: str = Field(min_length=1, max_length=2000)
    source_provenance: FigureSourceProvenance
    state: FigureRequestState = FigureRequestState.PENDING_REVIEW
    review_required: Literal[True] = True
    scientific_evidence: Literal[False] = False
    figure_approval_authorized: Literal[False] = False
    canonical_mutation_authorized: Literal[False] = False
    knowledge_graph_publication_authorized: Literal[False] = False

    @classmethod
    def from_input(cls, payload: FigureRequestIn) -> FigureRequestRecord:
        normalized_brief = " ".join(payload.production_brief.split())
        identity = {
            "contract": "calyx-glossary-figure-request-v1",
            "concept_id": str(payload.concept_id),
            "request_type": payload.request_type.value,
            "production_brief": normalized_brief,
            "source_provenance": payload.source_provenance.model_dump(mode="json"),
        }
        canonical = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return cls(
            request_id=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            concept_id=payload.concept_id,
            request_type=payload.request_type,
            production_brief=normalized_brief,
            source_provenance=payload.source_provenance,
        )


class FigureRequestConflictError(RuntimeError):
    """The same request identity has different governed content."""


class FigureRequestPersistenceError(RuntimeError):
    """Persisted figure-request state is unreadable or invalid."""


class FigureRequestSaveResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: FigureRequestRecord
    created: bool


class JsonFigureRequestRepository:
    """Atomic, restart-safe storage for immutable pre-approval requests."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, request_id: str) -> Path:
        if not _REQUEST_ID.fullmatch(request_id):
            raise ValueError("request_id must be a lowercase SHA-256 digest")
        return self.root / f"{request_id}.json"

    @staticmethod
    def _serialize(request: FigureRequestRecord) -> str:
        return json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _load(path: Path) -> FigureRequestRecord:
        try:
            return FigureRequestRecord.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise FigureRequestPersistenceError(
                f"invalid persisted figure request: {path.name}"
            ) from exc

    def save(self, request: FigureRequestRecord) -> FigureRequestSaveResult:
        path = self._path(request.request_id)
        if path.exists():
            existing = self._load(path)
            if existing != request:
                raise FigureRequestConflictError(
                    "request identity already exists with different governed content"
                )
            return FigureRequestSaveResult(request=existing, created=False)

        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.root,
            prefix=f".{request.request_id}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(self._serialize(request))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                existing = self._load(path)
                if existing != request:
                    raise FigureRequestConflictError(
                        "request identity already exists with different governed content"
                    )
                return FigureRequestSaveResult(request=existing, created=False)
        finally:
            temporary.unlink(missing_ok=True)
        return FigureRequestSaveResult(request=request, created=True)

    def get(self, request_id: str) -> FigureRequestRecord | None:
        path = self._path(request_id)
        return self._load(path) if path.is_file() else None

    def list(self) -> list[FigureRequestRecord]:
        if not self.root.is_dir():
            return []
        records: list[FigureRequestRecord] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.name):
            if not _REQUEST_ID.fullmatch(path.stem):
                raise FigureRequestPersistenceError(
                    f"unexpected figure request file: {path.name}"
                )
            record = self._load(path)
            if record.request_id != path.stem:
                raise FigureRequestPersistenceError(
                    f"figure request identity does not match filename: {path.name}"
                )
            records.append(record)
        return records
