from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from psycopg.rows import dict_row

from .source_binding import (
    CanonicalLiteratureSourceBinding,
    LiteratureSourceBindingError,
)


_READY_STATES = ("READY_FOR_REVIEW", "COMPLETED")


@dataclass(frozen=True, slots=True)
class ResolvedLiteratureSourceBinding:
    binding: CanonicalLiteratureSourceBinding
    binding_id: int
    created: bool


class PostgresLiteratureSourceBindingResolver:
    """Resolve literature evidence to canonical Document Intelligence anchors.

    Resolution is deliberately strict: a source hash must identify exactly one
    canonical record, exactly one eligible extraction run, and each evidence
    span must identify exactly one source anchor. Ambiguity fails closed.
    """

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def resolve(
        self,
        paper: Any,
        *,
        actor: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> ResolvedLiteratureSourceBinding:
        if not actor.strip():
            raise LiteratureSourceBindingError("BINDING_ACTOR_REQUIRED")
        source_hash = str(paper.source.content_hash).lower()
        if len(source_hash) != 64:
            raise LiteratureSourceBindingError(
                "SOURCE_HASH_MISMATCH", {"source_hash": source_hash}
            )

        connection = self._connection_factory()
        with connection:
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cursor:
                    record = self._resolve_record(cursor, source_hash)
                    run = self._resolve_run(cursor, int(record["record_id"]))
                    anchors = self._resolve_anchors(
                        cursor,
                        paper,
                        revision_id=int(record["revision_id"]),
                        extraction_run_id=int(run["extraction_run_id"]),
                    )
                    policy = self._display_policy(cursor, int(record["record_id"]))
                    binding = CanonicalLiteratureSourceBinding(
                        paper_id=paper.paper_id,
                        source_object_type="document_intelligence_record",
                        source_object_id=int(record["record_id"]),
                        revision_id=int(record["revision_id"]),
                        extraction_run_id=int(run["extraction_run_id"]),
                        anchor_ids=anchors,
                        display_policy=policy["display_state"],
                        internal_use_permission=bool(
                            policy["internal_use_permission"]
                        ),
                        language="en",
                    )
                    binding.validate_against_paper(paper)
                    return self._persist(
                        cursor,
                        paper,
                        binding,
                        source_hash=source_hash,
                        actor=actor,
                        tenant_id=tenant_id,
                        project_id=project_id,
                    )

    def get(self, paper_id: str, analysis_id: str) -> CanonicalLiteratureSourceBinding | None:
        connection = self._connection_factory()
        with connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT binding_id, paper_id, analysis_id, record_id, revision_id,
                           extraction_run_id
                    FROM oc_document_intelligence.literature_source_bindings
                    WHERE paper_id = %s AND analysis_id = %s
                    """,
                    (paper_id, analysis_id),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    """
                    SELECT evidence_id, anchor_id
                    FROM oc_document_intelligence.literature_evidence_bindings
                    WHERE binding_id = %s
                    ORDER BY evidence_id
                    """,
                    (row["binding_id"],),
                )
                anchors = {
                    item["evidence_id"]: int(item["anchor_id"])
                    for item in cursor.fetchall()
                }
                policy = self._display_policy(cursor, int(row["record_id"]))
                return CanonicalLiteratureSourceBinding(
                    paper_id=row["paper_id"],
                    source_object_type="document_intelligence_record",
                    source_object_id=int(row["record_id"]),
                    revision_id=int(row["revision_id"]),
                    extraction_run_id=int(row["extraction_run_id"]),
                    anchor_ids=anchors,
                    display_policy=policy["display_state"],
                    internal_use_permission=bool(policy["internal_use_permission"]),
                    language="en",
                )

    @staticmethod
    def _resolve_record(cursor: Any, source_hash: str) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT record_id, revision_id, source_sha256
            FROM oc_document_intelligence.records
            WHERE lower(source_sha256) = %s
            ORDER BY record_id
            FOR SHARE
            """,
            (source_hash,),
        )
        rows = cursor.fetchall()
        if not rows:
            raise LiteratureSourceBindingError(
                "SOURCE_BINDING_NOT_FOUND", {"source_hash": source_hash}
            )
        if len(rows) != 1:
            raise LiteratureSourceBindingError(
                "BINDING_CONFLICT_REQUIRES_REVIEW",
                {
                    "source_hash": source_hash,
                    "record_ids": [int(row["record_id"]) for row in rows],
                },
            )
        return rows[0]

    @staticmethod
    def _resolve_run(cursor: Any, record_id: int) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT extraction_run_id, record_id, state
            FROM oc_document_intelligence.extraction_runs
            WHERE record_id = %s AND state = ANY(%s)
            ORDER BY extraction_run_id
            FOR SHARE
            """,
            (record_id, list(_READY_STATES)),
        )
        rows = cursor.fetchall()
        if not rows:
            raise LiteratureSourceBindingError(
                "EXTRACTION_RUN_MISMATCH", {"record_id": record_id}
            )
        if len(rows) != 1:
            raise LiteratureSourceBindingError(
                "BINDING_CONFLICT_REQUIRES_REVIEW",
                {
                    "record_id": record_id,
                    "extraction_run_ids": [
                        int(row["extraction_run_id"]) for row in rows
                    ],
                },
            )
        return rows[0]

    @staticmethod
    def _resolve_anchors(
        cursor: Any,
        paper: Any,
        *,
        revision_id: int,
        extraction_run_id: int,
    ) -> dict[str, int]:
        resolved: dict[str, int] = {}
        for evidence in sorted(paper.evidence, key=lambda item: item.evidence_id):
            cursor.execute(
                """
                SELECT anchor_id, revision_id, extraction_run_id, char_start, char_end
                FROM oc_document_intelligence.source_anchors
                WHERE revision_id = %s
                  AND extraction_run_id = %s
                  AND char_start = %s
                  AND char_end = %s
                ORDER BY anchor_id
                FOR SHARE
                """,
                (
                    revision_id,
                    extraction_run_id,
                    evidence.span.char_start,
                    evidence.span.char_end,
                ),
            )
            rows = cursor.fetchall()
            if not rows:
                raise LiteratureSourceBindingError(
                    "ANCHOR_BINDING_NOT_FOUND",
                    {
                        "evidence_id": evidence.evidence_id,
                        "char_start": evidence.span.char_start,
                        "char_end": evidence.span.char_end,
                    },
                )
            if len(rows) != 1:
                raise LiteratureSourceBindingError(
                    "ANCHOR_BINDING_AMBIGUOUS",
                    {
                        "evidence_id": evidence.evidence_id,
                        "anchor_ids": [int(row["anchor_id"]) for row in rows],
                    },
                )
            resolved[evidence.evidence_id] = int(rows[0]["anchor_id"])
        return resolved

    @staticmethod
    def _display_policy(cursor: Any, record_id: int) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT display_state, internal_use_permission
            FROM oc_document_intelligence.display_policies
            WHERE record_id = %s
            """,
            (record_id,),
        )
        row = cursor.fetchone()
        return row or {
            "display_state": "UNKNOWN_REQUIRES_REVIEW",
            "internal_use_permission": False,
        }

    def _persist(
        self,
        cursor: Any,
        paper: Any,
        binding: CanonicalLiteratureSourceBinding,
        *,
        source_hash: str,
        actor: str,
        tenant_id: str | None,
        project_id: str | None,
    ) -> ResolvedLiteratureSourceBinding:
        fingerprint = self._binding_fingerprint(
            paper.analysis_manifest.analysis_id, source_hash, binding
        )
        cursor.execute(
            """
            SELECT binding_id, binding_fingerprint, tenant_id, project_id
            FROM oc_document_intelligence.literature_source_bindings
            WHERE paper_id = %s AND analysis_id = %s
            FOR UPDATE
            """,
            (paper.paper_id, paper.analysis_manifest.analysis_id),
        )
        existing = cursor.fetchone()
        if existing is not None:
            if existing["tenant_id"] != tenant_id or existing["project_id"] != project_id:
                raise LiteratureSourceBindingError(
                    "CROSS_TENANT_BINDING_FORBIDDEN",
                    {"paper_id": paper.paper_id},
                )
            if existing["binding_fingerprint"] != fingerprint:
                raise LiteratureSourceBindingError(
                    "BINDING_CONFLICT_REQUIRES_REVIEW",
                    {"paper_id": paper.paper_id},
                )
            return ResolvedLiteratureSourceBinding(
                binding=binding,
                binding_id=int(existing["binding_id"]),
                created=False,
            )

        cursor.execute(
            """
            INSERT INTO oc_document_intelligence.literature_source_bindings (
                paper_id, analysis_id, source_sha256, record_id, revision_id,
                extraction_run_id, binding_fingerprint, actor, tenant_id, project_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING binding_id
            """,
            (
                paper.paper_id,
                paper.analysis_manifest.analysis_id,
                source_hash,
                binding.source_object_id,
                binding.revision_id,
                binding.extraction_run_id,
                fingerprint,
                actor,
                tenant_id,
                project_id,
            ),
        )
        binding_id = int(cursor.fetchone()["binding_id"])
        evidence_by_id = {item.evidence_id: item for item in paper.evidence}
        for evidence_id, anchor_id in sorted(binding.anchor_ids.items()):
            evidence = evidence_by_id[evidence_id]
            cursor.execute(
                """
                INSERT INTO oc_document_intelligence.literature_evidence_bindings (
                    binding_id, evidence_id, anchor_id, char_start, char_end, source_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    binding_id,
                    evidence_id,
                    anchor_id,
                    evidence.span.char_start,
                    evidence.span.char_end,
                    source_hash,
                ),
            )
        return ResolvedLiteratureSourceBinding(
            binding=binding, binding_id=binding_id, created=True
        )

    @staticmethod
    def _binding_fingerprint(
        analysis_id: str,
        source_hash: str,
        binding: CanonicalLiteratureSourceBinding,
    ) -> str:
        payload = {
            "analysis_id": analysis_id,
            "source_hash": source_hash,
            "binding": binding.to_dict(),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
