from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from threading import RLock
from typing import Any


class LiteratureSourceBindingError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class CanonicalLiteratureSourceBinding:
    paper_id: str
    source_object_type: str
    source_object_id: int
    revision_id: int
    extraction_run_id: int
    anchor_ids: dict[str, int]
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    internal_use_permission: bool = False
    language: str = "en"
    evidence_integrity: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.paper_id.strip():
            raise LiteratureSourceBindingError("PAPER_ID_REQUIRED")
        if not self.source_object_type.strip():
            raise LiteratureSourceBindingError("SOURCE_OBJECT_TYPE_REQUIRED")
        if min(self.source_object_id, self.revision_id, self.extraction_run_id) <= 0:
            raise LiteratureSourceBindingError("CANONICAL_SOURCE_BINDING_REQUIRED")
        if not self.anchor_ids or any(value <= 0 for value in self.anchor_ids.values()):
            raise LiteratureSourceBindingError("CANONICAL_ANCHOR_BINDINGS_REQUIRED")

    @property
    def fingerprint(self) -> str:
        payload = {
            "paper_id": self.paper_id,
            "source_object_type": self.source_object_type,
            "source_object_id": self.source_object_id,
            "revision_id": self.revision_id,
            "extraction_run_id": self.extraction_run_id,
            "anchor_ids": dict(sorted(self.anchor_ids.items())),
            "display_policy": self.display_policy,
            "internal_use_permission": self.internal_use_permission,
            "language": self.language,
            "evidence_integrity": {
                key: self.evidence_integrity[key]
                for key in sorted(self.evidence_integrity)
            },
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def validate_against_paper(self, paper: Any) -> None:
        if paper.paper_id != self.paper_id:
            raise LiteratureSourceBindingError(
                "CROSS_PAPER_BINDING",
                {"binding_paper_id": self.paper_id, "paper_id": paper.paper_id},
            )
        known = {item.evidence_id for item in paper.evidence}
        supplied = set(self.anchor_ids)
        foreign = sorted(supplied - known)
        missing = sorted(known - supplied)
        if foreign:
            raise LiteratureSourceBindingError(
                "ANCHOR_EVIDENCE_IDS_NOT_IN_PAPER", {"evidence_ids": foreign}
            )
        if missing:
            raise LiteratureSourceBindingError(
                "CANONICAL_EVIDENCE_BINDING_MISSING",
                {"evidence_ids": missing},
            )

    def with_verified_integrity(
        self, paper: Any, raw_bytes: bytes
    ) -> CanonicalLiteratureSourceBinding:
        self.validate_against_paper(paper)
        source_hash = _sha256_bytes(raw_bytes)
        if source_hash != paper.source.content_hash:
            raise LiteratureSourceBindingError(
                "RAW_SOURCE_HASH_MISMATCH",
                {
                    "paper_id": paper.paper_id,
                    "expected_source_hash": paper.source.content_hash,
                    "actual_source_hash": source_hash,
                },
            )
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LiteratureSourceBindingError("RAW_SOURCE_NOT_UTF8") from exc

        proofs: dict[str, dict[str, Any]] = {}
        for evidence in paper.evidence:
            start = evidence.span.char_start
            end = evidence.span.char_end
            if (
                start is None
                or end is None
                or end < start
                or end > len(raw_text)
                or raw_text[start:end] != evidence.excerpt
            ):
                raise LiteratureSourceBindingError(
                    "EVIDENCE_SOURCE_SPAN_INVALID",
                    {
                        "evidence_id": evidence.evidence_id,
                        "char_start": start,
                        "char_end": end,
                    },
                )
            proofs[evidence.evidence_id] = {
                "anchor_id": self.anchor_ids[evidence.evidence_id],
                "source_hash": source_hash,
                "excerpt_hash": _sha256_text(evidence.excerpt),
                "char_start": start,
                "char_end": end,
                "section_id": evidence.span.section_id,
                "evidence_type": evidence.evidence_type,
            }
        return replace(self, evidence_integrity=proofs)

    def validate_integrity(self, paper: Any, raw_bytes: bytes) -> None:
        self.validate_against_paper(paper)
        known = {item.evidence_id for item in paper.evidence}
        proof_ids = set(self.evidence_integrity)
        if proof_ids != known:
            raise LiteratureSourceBindingError(
                "SOURCE_INTEGRITY_PROOF_INCOMPLETE",
                {
                    "missing_evidence_ids": sorted(known - proof_ids),
                    "foreign_evidence_ids": sorted(proof_ids - known),
                },
            )

        expected = self.with_verified_integrity(paper, raw_bytes)
        for evidence_id in sorted(known):
            actual_proof = self.evidence_integrity[evidence_id]
            expected_proof = expected.evidence_integrity[evidence_id]
            if actual_proof != expected_proof:
                raise LiteratureSourceBindingError(
                    "SOURCE_INTEGRITY_PROOF_MISMATCH",
                    {
                        "evidence_id": evidence_id,
                        "expected": expected_proof,
                        "actual": actual_proof,
                    },
                )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "binding_fingerprint": self.fingerprint}


class FileLiteratureSourceBindingRepository:
    """Atomic, durable, additive persistence for canonical literature bindings."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = RLock()

    def _path(self, paper_id: str) -> Path:
        if not paper_id or Path(paper_id).name != paper_id:
            raise LiteratureSourceBindingError("INVALID_PAPER_ID")
        return self.root / paper_id / "source-binding.json"

    def get(self, paper_id: str) -> CanonicalLiteratureSourceBinding | None:
        path = self._path(paper_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("binding_fingerprint", None)
        return CanonicalLiteratureSourceBinding(**payload)

    def create(
        self, binding: CanonicalLiteratureSourceBinding
    ) -> tuple[CanonicalLiteratureSourceBinding, bool]:
        if not binding.evidence_integrity:
            raise LiteratureSourceBindingError("SOURCE_INTEGRITY_PROOF_REQUIRED")
        path = self._path(binding.paper_id)
        with self._lock:
            existing = self.get(binding.paper_id)
            if existing is not None:
                if existing.fingerprint == binding.fingerprint:
                    return existing, False
                raise LiteratureSourceBindingError(
                    "CONFLICTING_SOURCE_REBIND",
                    {
                        "paper_id": binding.paper_id,
                        "existing_fingerprint": existing.fingerprint,
                        "requested_fingerprint": binding.fingerprint,
                    },
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".json.tmp")
            temp.write_text(
                json.dumps(binding.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
            return binding, True
