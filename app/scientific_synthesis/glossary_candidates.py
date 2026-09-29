from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CandidateState = Literal[
    "UNRESOLVED",
    "CANDIDATES",
    "AMBIGUOUS",
    "MATCHED_PENDING_REVIEW",
    "REVIEWED_MATCH",
    "NEW_CONCEPT_CANDIDATE",
    "REJECTED",
]

_CANDIDATE_ID = re.compile(r"^[0-9a-f]{64}$")


class GlossaryCandidateRecord(BaseModel):
    """Immutable, provenance-bearing vocabulary candidate awaiting human review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    paper_id: str = Field(min_length=1, max_length=300)
    source_hash: str = Field(min_length=16, max_length=256)
    source_term_id: str = Field(min_length=1, max_length=500)
    term: str = Field(min_length=1, max_length=300)
    normalized_term: str = Field(min_length=1, max_length=300)
    source_status: str = Field(min_length=1, max_length=40)
    source_provenance: dict[str, Any]
    state: CandidateState
    matched_concept_id: str | None = None
    exact_concept_ids: tuple[str, ...] = ()
    resolution_reason: str = Field(min_length=1, max_length=500)
    review_required: Literal[True] = True
    canonical_promotion_authorized: Literal[False] = False
    knowledge_graph_publication_authorized: Literal[False] = False

    @classmethod
    def from_analysis(
        cls,
        *,
        paper_id: str,
        source_hash: str,
        analysis: dict[str, Any],
    ) -> GlossaryCandidateRecord:
        glossary = analysis.get("glossary")
        resolution = analysis.get("candidate_resolution")
        if not isinstance(glossary, dict) or not isinstance(resolution, dict):
            raise TypeError("analysis must contain glossary and candidate_resolution")

        identity = {
            "contract": "calyx-glossary-candidate-v1",
            "paper_id": paper_id,
            "source_hash": source_hash,
            "source_term_id": glossary.get("term_id"),
            "normalized_term": analysis.get("normalized_term"),
        }
        canonical_identity = json.dumps(
            identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        candidate_id = hashlib.sha256(canonical_identity.encode("utf-8")).hexdigest()
        return cls(
            candidate_id=candidate_id,
            paper_id=paper_id,
            source_hash=source_hash,
            source_term_id=glossary.get("term_id"),
            term=analysis.get("term"),
            normalized_term=analysis.get("normalized_term"),
            source_status=glossary.get("status"),
            source_provenance=glossary.get("provenance"),
            state=resolution.get("state"),
            matched_concept_id=resolution.get("matched_concept_id"),
            exact_concept_ids=tuple(sorted(resolution.get("exact_concept_ids") or ())),
            resolution_reason=resolution.get("reason"),
        )


class CandidateConflictError(RuntimeError):
    """The same source identity was replayed with different governed content."""


class CandidatePersistenceError(RuntimeError):
    """Persisted candidate state is unreadable or invalid and must fail closed."""


class CandidateSaveResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: GlossaryCandidateRecord
    created: bool


class JsonGlossaryCandidateRepository:
    """Atomic, restart-safe storage for immutable pre-publication candidates."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, candidate_id: str) -> Path:
        if not _CANDIDATE_ID.fullmatch(candidate_id):
            raise ValueError("candidate_id must be a lowercase SHA-256 digest")
        return self.root / f"{candidate_id}.json"

    @staticmethod
    def _serialize(candidate: GlossaryCandidateRecord) -> str:
        return json.dumps(
            candidate.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _load(path: Path) -> GlossaryCandidateRecord:
        try:
            return GlossaryCandidateRecord.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise CandidatePersistenceError(
                f"invalid persisted glossary candidate: {path.name}"
            ) from exc

    def save(self, candidate: GlossaryCandidateRecord) -> CandidateSaveResult:
        path = self._path(candidate.candidate_id)
        if path.exists():
            existing = self._load(path)
            if existing != candidate:
                raise CandidateConflictError(
                    "candidate identity already exists with different governed content"
                )
            return CandidateSaveResult(candidate=existing, created=False)

        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.root,
            prefix=f".{candidate.candidate_id}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(self._serialize(candidate))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                existing = self._load(path)
                if existing != candidate:
                    raise CandidateConflictError(
                        "candidate identity already exists with different governed content"
                    )
                return CandidateSaveResult(candidate=existing, created=False)
        finally:
            temporary.unlink(missing_ok=True)
        return CandidateSaveResult(candidate=candidate, created=True)

    def get(self, candidate_id: str) -> GlossaryCandidateRecord | None:
        path = self._path(candidate_id)
        return self._load(path) if path.is_file() else None

    def list(self) -> list[GlossaryCandidateRecord]:
        if not self.root.is_dir():
            return []
        records: list[GlossaryCandidateRecord] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.name):
            if not _CANDIDATE_ID.fullmatch(path.stem):
                raise CandidatePersistenceError(
                    f"unexpected glossary candidate file: {path.name}"
                )
            record = self._load(path)
            if record.candidate_id != path.stem:
                raise CandidatePersistenceError(
                    f"candidate identity does not match filename: {path.name}"
                )
            records.append(record)
        return records
