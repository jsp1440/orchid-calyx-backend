from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from .source_binding import (
    CanonicalLiteratureSourceBinding,
    LiteratureSourceBindingError,
)


class CursorLike(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> Any: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...


@dataclass(frozen=True, slots=True)
class BindingScope:
    owner_id: str
    project_id: str

    def __post_init__(self) -> None:
        if not self.owner_id.strip():
            raise LiteratureSourceBindingError("OWNER_ID_REQUIRED")
        if not self.project_id.strip():
            raise LiteratureSourceBindingError("PROJECT_ID_REQUIRED")


@dataclass(frozen=True, slots=True)
class ResolvedLiteratureBinding:
    record_id: int
    analysis_id: str
    binding: CanonicalLiteratureSourceBinding


class DocumentIntelligenceBindingResolver:
    """Resolve literature evidence to existing canonical document identities.

    The resolver is deliberately conservative.  It never invents a canonical
    source object, chooses a "latest" extraction run, or guesses an anchor.  A
    source, source-object assignment, extraction run, and every evidence anchor
    must resolve uniquely or the handoff is blocked.
    """

    _USABLE_RUN_STATES = ("READY_FOR_REVIEW", "COMPLETED", "PARTIAL")

    @staticmethod
    def _rows(cursor: CursorLike, query: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        cursor.execute(query, params)
        return list(cursor.fetchall())

    def _record(self, cursor: CursorLike, source_hash: str) -> tuple[int, int]:
        rows = self._rows(
            cursor,
            """
            SELECT record_id, revision_id
            FROM oc_document_intelligence.records
            WHERE source_sha256 = %s
            ORDER BY record_id
            """,
            (source_hash,),
        )
        if not rows:
            raise LiteratureSourceBindingError(
                "SOURCE_BINDING_NOT_FOUND", {"source_hash": source_hash}
            )
        if len(rows) != 1:
            raise LiteratureSourceBindingError(
                "SOURCE_BINDING_AMBIGUOUS",
                {"source_hash": source_hash, "record_ids": [row[0] for row in rows]},
            )
        record_id, revision_id = rows[0]
        return int(record_id), int(revision_id)

    def _source_object(self, cursor: CursorLike, record_id: int) -> tuple[str, int]:
        rows = self._rows(
            cursor,
            """
            SELECT DISTINCT source_object_type, source_object_id
            FROM oc_document_intelligence.purpose_assignments
            WHERE record_id = %s AND source_object_id IS NOT NULL
            ORDER BY source_object_type, source_object_id
            """,
            (record_id,),
        )
        identities = {(str(row[0]), int(row[1])) for row in rows if row[0] and row[1]}
        if not identities:
            raise LiteratureSourceBindingError(
                "SOURCE_OBJECT_BINDING_NOT_FOUND", {"record_id": record_id}
            )
        if len(identities) != 1:
            raise LiteratureSourceBindingError(
                "SOURCE_OBJECT_BINDING_AMBIGUOUS",
                {"record_id": record_id, "identities": sorted(identities)},
            )
        return next(iter(identities))

    def _run_ids(self, cursor: CursorLike, record_id: int) -> list[int]:
        rows = self._rows(
            cursor,
            """
            SELECT extraction_run_id
            FROM oc_document_intelligence.extraction_runs
            WHERE record_id = %s AND state = ANY(%s)
            ORDER BY extraction_run_id
            """,
            (record_id, list(self._USABLE_RUN_STATES)),
        )
        if not rows:
            raise LiteratureSourceBindingError(
                "EXTRACTION_RUN_NOT_FOUND", {"record_id": record_id}
            )
        return [int(row[0]) for row in rows]

    def _anchor_for_span(
        self,
        cursor: CursorLike,
        *,
        revision_id: int,
        extraction_run_id: int,
        evidence_id: str,
        char_start: int | None,
        char_end: int | None,
    ) -> int:
        if char_start is None or char_end is None or char_end < char_start:
            raise LiteratureSourceBindingError(
                "EVIDENCE_SPAN_REQUIRED",
                {"evidence_id": evidence_id, "char_start": char_start, "char_end": char_end},
            )

        exact = self._rows(
            cursor,
            """
            SELECT anchor_id
            FROM oc_document_intelligence.source_anchors
            WHERE revision_id = %s
              AND extraction_run_id = %s
              AND char_start = %s
              AND char_end = %s
            ORDER BY anchor_id
            """,
            (revision_id, extraction_run_id, char_start, char_end),
        )
        if len(exact) == 1:
            return int(exact[0][0])
        if len(exact) > 1:
            raise LiteratureSourceBindingError(
                "ANCHOR_BINDING_AMBIGUOUS",
                {"evidence_id": evidence_id, "anchor_ids": [row[0] for row in exact]},
            )

        covering = self._rows(
            cursor,
            """
            SELECT anchor_id
            FROM oc_document_intelligence.source_anchors
            WHERE revision_id = %s
              AND extraction_run_id = %s
              AND char_start IS NOT NULL
              AND char_end IS NOT NULL
              AND char_start <= %s
              AND char_end >= %s
            ORDER BY anchor_id
            """,
            (revision_id, extraction_run_id, char_start, char_end),
        )
        if len(covering) == 1:
            return int(covering[0][0])
        if not covering:
            raise LiteratureSourceBindingError(
                "ANCHOR_BINDING_NOT_FOUND",
                {
                    "evidence_id": evidence_id,
                    "revision_id": revision_id,
                    "extraction_run_id": extraction_run_id,
                    "char_start": char_start,
                    "char_end": char_end,
                },
            )
        raise LiteratureSourceBindingError(
            "ANCHOR_BINDING_AMBIGUOUS",
            {"evidence_id": evidence_id, "anchor_ids": [row[0] for row in covering]},
        )

    def _anchors_for_run(
        self,
        cursor: CursorLike,
        *,
        paper: Any,
        revision_id: int,
        extraction_run_id: int,
    ) -> dict[str, int]:
        result: dict[str, int] = {}
        for evidence in paper.evidence:
            result[evidence.evidence_id] = self._anchor_for_span(
                cursor,
                revision_id=revision_id,
                extraction_run_id=extraction_run_id,
                evidence_id=evidence.evidence_id,
                char_start=evidence.span.char_start,
                char_end=evidence.span.char_end,
            )
        if not result:
            raise LiteratureSourceBindingError("LITERATURE_EVIDENCE_REQUIRED")
        return result

    def _unique_run_and_anchors(
        self,
        cursor: CursorLike,
        *,
        paper: Any,
        record_id: int,
        revision_id: int,
    ) -> tuple[int, dict[str, int]]:
        candidates: list[tuple[int, dict[str, int]]] = []
        failures: dict[int, str] = {}
        for run_id in self._run_ids(cursor, record_id):
            try:
                candidates.append(
                    (
                        run_id,
                        self._anchors_for_run(
                            cursor,
                            paper=paper,
                            revision_id=revision_id,
                            extraction_run_id=run_id,
                        ),
                    )
                )
            except LiteratureSourceBindingError as exc:
                failures[run_id] = exc.code
        if not candidates:
            raise LiteratureSourceBindingError(
                "EXTRACTION_RUN_WITH_EXACT_EVIDENCE_NOT_FOUND",
                {"record_id": record_id, "run_failures": failures},
            )
        if len(candidates) != 1:
            raise LiteratureSourceBindingError(
                "EXTRACTION_RUN_AMBIGUOUS",
                {"record_id": record_id, "extraction_run_ids": [item[0] for item in candidates]},
            )
        return candidates[0]

    def _display_policy(self, cursor: CursorLike, record_id: int) -> tuple[str, bool]:
        rows = self._rows(
            cursor,
            """
            SELECT display_state, internal_use_permission
            FROM oc_document_intelligence.display_policies
            WHERE record_id = %s
            """,
            (record_id,),
        )
        if len(rows) > 1:
            raise LiteratureSourceBindingError(
                "DISPLAY_POLICY_AMBIGUOUS", {"record_id": record_id}
            )
        if not rows:
            return "UNKNOWN_REQUIRES_REVIEW", False
        return str(rows[0][0]), bool(rows[0][1])

    def resolve(self, cursor: CursorLike, paper: Any, raw_bytes: bytes) -> ResolvedLiteratureBinding:
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        if raw_hash != paper.source.content_hash:
            raise LiteratureSourceBindingError(
                "RAW_SOURCE_HASH_MISMATCH",
                {"expected_source_hash": paper.source.content_hash, "actual_source_hash": raw_hash},
            )
        record_id, revision_id = self._record(cursor, raw_hash)
        source_object_type, source_object_id = self._source_object(cursor, record_id)
        extraction_run_id, anchor_ids = self._unique_run_and_anchors(
            cursor,
            paper=paper,
            record_id=record_id,
            revision_id=revision_id,
        )
        display_policy, internal_use_permission = self._display_policy(cursor, record_id)
        binding = CanonicalLiteratureSourceBinding(
            paper_id=paper.paper_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            revision_id=revision_id,
            extraction_run_id=extraction_run_id,
            anchor_ids=anchor_ids,
            display_policy=display_policy,
            internal_use_permission=internal_use_permission,
            language=paper.source.language or "und",
        ).with_verified_integrity(paper, raw_bytes)
        return ResolvedLiteratureBinding(
            record_id=record_id,
            analysis_id=paper.analysis_manifest.analysis_id,
            binding=binding,
        )


class PostgresLiteratureSourceBindingRepository:
    """Immutable, owner/project-scoped persistence for resolved bindings."""

    def get(
        self,
        cursor: CursorLike,
        *,
        scope: BindingScope,
        paper_id: str,
        analysis_id: str,
    ) -> ResolvedLiteratureBinding | None:
        cursor.execute(
            """
            SELECT binding_id, record_id, source_object_type, source_object_id,
                   revision_id, extraction_run_id, display_policy,
                   internal_use_permission, language, binding_fingerprint
            FROM oc_document_intelligence.literature_source_bindings
            WHERE owner_id = %s AND project_id = %s
              AND paper_id = %s AND analysis_id = %s
            """,
            (scope.owner_id, scope.project_id, paper_id, analysis_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        (
            binding_id,
            record_id,
            source_object_type,
            source_object_id,
            revision_id,
            extraction_run_id,
            display_policy,
            internal_use_permission,
            language,
            stored_fingerprint,
        ) = row
        cursor.execute(
            """
            SELECT evidence_id, anchor_id, source_hash, excerpt_hash, char_start,
                   char_end, section_id, evidence_type
            FROM oc_document_intelligence.literature_evidence_bindings
            WHERE binding_id = %s
            ORDER BY evidence_id
            """,
            (binding_id,),
        )
        evidence_integrity = {
            str(evidence_id): {
                "anchor_id": int(anchor_id),
                "source_hash": str(source_hash),
                "excerpt_hash": str(excerpt_hash),
                "char_start": char_start,
                "char_end": char_end,
                "section_id": section_id,
                "evidence_type": evidence_type,
            }
            for (
                evidence_id,
                anchor_id,
                source_hash,
                excerpt_hash,
                char_start,
                char_end,
                section_id,
                evidence_type,
            ) in cursor.fetchall()
        }
        binding = CanonicalLiteratureSourceBinding(
            paper_id=paper_id,
            source_object_type=str(source_object_type),
            source_object_id=int(source_object_id),
            revision_id=int(revision_id),
            extraction_run_id=int(extraction_run_id),
            anchor_ids={key: int(value["anchor_id"]) for key, value in evidence_integrity.items()},
            display_policy=str(display_policy),
            internal_use_permission=bool(internal_use_permission),
            language=str(language),
            evidence_integrity=evidence_integrity,
        )
        if binding.fingerprint != str(stored_fingerprint):
            raise LiteratureSourceBindingError(
                "PERSISTED_BINDING_FINGERPRINT_MISMATCH",
                {"paper_id": paper_id, "analysis_id": analysis_id},
            )
        return ResolvedLiteratureBinding(
            record_id=int(record_id), analysis_id=analysis_id, binding=binding
        )

    def create(
        self,
        cursor: CursorLike,
        *,
        scope: BindingScope,
        resolved: ResolvedLiteratureBinding,
    ) -> tuple[ResolvedLiteratureBinding, bool]:
        existing = self.get(
            cursor,
            scope=scope,
            paper_id=resolved.binding.paper_id,
            analysis_id=resolved.analysis_id,
        )
        if existing is not None:
            if existing.binding.fingerprint == resolved.binding.fingerprint:
                return existing, False
            raise LiteratureSourceBindingError(
                "BINDING_CONFLICT_REQUIRES_REVIEW",
                {
                    "paper_id": resolved.binding.paper_id,
                    "analysis_id": resolved.analysis_id,
                    "existing_fingerprint": existing.binding.fingerprint,
                    "requested_fingerprint": resolved.binding.fingerprint,
                },
            )

        binding = resolved.binding
        cursor.execute(
            """
            INSERT INTO oc_document_intelligence.literature_source_bindings (
                owner_id, project_id, paper_id, analysis_id, record_id,
                source_object_type, source_object_id, revision_id, extraction_run_id,
                source_hash, binding_fingerprint, display_policy,
                internal_use_permission, language
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING binding_id
            """,
            (
                scope.owner_id,
                scope.project_id,
                binding.paper_id,
                resolved.analysis_id,
                resolved.record_id,
                binding.source_object_type,
                binding.source_object_id,
                binding.revision_id,
                binding.extraction_run_id,
                next(iter(binding.evidence_integrity.values()))["source_hash"],
                binding.fingerprint,
                binding.display_policy,
                binding.internal_use_permission,
                binding.language,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise LiteratureSourceBindingError("BINDING_PERSISTENCE_FAILED")
        binding_id = int(row[0])
        for evidence_id in sorted(binding.evidence_integrity):
            proof = binding.evidence_integrity[evidence_id]
            cursor.execute(
                """
                INSERT INTO oc_document_intelligence.literature_evidence_bindings (
                    binding_id, evidence_id, anchor_id, source_hash, excerpt_hash,
                    char_start, char_end, section_id, evidence_type
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    binding_id,
                    evidence_id,
                    proof["anchor_id"],
                    proof["source_hash"],
                    proof["excerpt_hash"],
                    proof["char_start"],
                    proof["char_end"],
                    proof["section_id"],
                    proof["evidence_type"],
                ),
            )
        return resolved, True

    def resolve_and_create(
        self,
        cursor: CursorLike,
        *,
        resolver: DocumentIntelligenceBindingResolver,
        scope: BindingScope,
        paper: Any,
        raw_bytes: bytes,
    ) -> tuple[ResolvedLiteratureBinding, bool]:
        existing = self.get(
            cursor,
            scope=scope,
            paper_id=paper.paper_id,
            analysis_id=paper.analysis_manifest.analysis_id,
        )
        if existing is not None:
            existing.binding.validate_integrity(paper, raw_bytes)
            return existing, False
        resolved = resolver.resolve(cursor, paper, raw_bytes)
        return self.create(cursor, scope=scope, resolved=resolved)
