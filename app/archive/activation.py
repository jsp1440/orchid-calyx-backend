from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from app.archive.policy import ArchivePolicy, ArchivePolicyError
from app.archive.registry import ArchiveRegistry
from app.calyx_orchestrator.artifact_registry import ArtifactRegistration, ImmutableArtifactRegistry

REQUIRED_ARCHIVE_TABLES = (
    "archive_documents",
    "archive_files",
    "archive_entities",
    "archive_relationships",
    "archive_import_runs",
    "archive_provenance",
    "archive_checkpoints",
)
REQUIRED_HARDENING_COLUMNS = (
    "dispatch_reference",
    "lease_owner",
    "lease_expires_at",
    "heartbeat_at",
    "attempt_count",
    "cancel_requested",
)
SCHEMA_VERSION = "calyx-institutional-archive-activation/v1"


@dataclass(frozen=True, slots=True)
class ArchiveContractInventory:
    documents: str = "archive_documents"
    files: str = "archive_files"
    entities: str = "archive_entities"
    relationships: str = "archive_relationships"
    provenance: str = "archive_provenance"
    checkpoints: str = "archive_checkpoints"
    import_runs: str = "archive_import_runs"


@dataclass(frozen=True, slots=True)
class ArchiveActivationEvidence:
    schema_version: str
    generated_at: str
    database_configured: bool
    archive_schema_complete: bool
    hardening_complete: bool
    allowed_source_roots_configured: bool
    allowed_source_root_count: int
    unrestricted_filesystem_scanning_authorized: bool
    production_import_authorized: bool
    graph_publication_authorized: bool
    deployment_authorized: bool
    missing_tables: tuple[str, ...]
    missing_hardening_columns: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence_digest: str


class ArchiveActivationInspector:
    """Read-only activation certification for the existing institutional archive subsystem."""

    def __init__(
        self,
        registry: ArchiveRegistry | None = None,
        *,
        artifacts: ImmutableArtifactRegistry | None = None,
        policy_factory: Callable[[], ArchivePolicy] = ArchivePolicy.from_environment,
    ) -> None:
        self.registry = registry or ArchiveRegistry()
        self.artifacts = artifacts or ImmutableArtifactRegistry()
        self.policy_factory = policy_factory

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _schema_state(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        missing_tables: list[str] = []
        missing_columns: list[str] = []
        try:
            with self.registry.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = ANY(%s)
                    """,
                    (list(REQUIRED_ARCHIVE_TABLES),),
                ).fetchall()
                present = {str(row["table_name"]) for row in rows}
                missing_tables = sorted(set(REQUIRED_ARCHIVE_TABLES) - present)
                if "archive_import_runs" in present:
                    column_rows = conn.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'archive_import_runs'
                          AND column_name = ANY(%s)
                        """,
                        (list(REQUIRED_HARDENING_COLUMNS),),
                    ).fetchall()
                    present_columns = {str(row["column_name"]) for row in column_rows}
                    missing_columns = sorted(set(REQUIRED_HARDENING_COLUMNS) - present_columns)
                else:
                    missing_columns = list(REQUIRED_HARDENING_COLUMNS)
        except Exception:
            return tuple(REQUIRED_ARCHIVE_TABLES), tuple(REQUIRED_HARDENING_COLUMNS)
        return tuple(missing_tables), tuple(missing_columns)

    def inspect(self) -> ArchiveActivationEvidence:
        database_configured = bool(os.getenv("DATABASE_URL", "").strip())
        missing_tables, missing_columns = self._schema_state() if database_configured else (
            tuple(REQUIRED_ARCHIVE_TABLES),
            tuple(REQUIRED_HARDENING_COLUMNS),
        )
        try:
            policy = self.policy_factory()
            root_count = len(policy.allowed_roots)
            roots_configured = root_count > 0
        except ArchivePolicyError:
            root_count = 0
            roots_configured = False

        blockers: list[str] = []
        if not database_configured:
            blockers.append("DATABASE_NOT_CONFIGURED")
        if missing_tables:
            blockers.append("ARCHIVE_MIGRATION_106_NOT_CERTIFIED")
        if missing_columns:
            blockers.append("ARCHIVE_HARDENING_107_NOT_CERTIFIED")
        if not roots_configured:
            blockers.append("ARCHIVE_ALLOWED_ROOTS_NOT_CONFIGURED")

        base = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self._now(),
            "database_configured": database_configured,
            "archive_schema_complete": not missing_tables,
            "hardening_complete": not missing_columns,
            "allowed_source_roots_configured": roots_configured,
            "allowed_source_root_count": root_count,
            "unrestricted_filesystem_scanning_authorized": False,
            "production_import_authorized": False,
            "graph_publication_authorized": False,
            "deployment_authorized": False,
            "missing_tables": missing_tables,
            "missing_hardening_columns": missing_columns,
            "blockers": tuple(blockers),
        }
        digest = self._digest(base)
        return ArchiveActivationEvidence(**base, evidence_digest=digest)

    def contract_inventory(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "contracts": asdict(ArchiveContractInventory()),
            "bounded_import": True,
            "safe_zip_extraction_required": True,
            "duplicate_fingerprint_handling_required": True,
            "malformed_file_continuation_required": True,
            "checkpoint_resume_required": True,
            "canonical_graph_write_authorized": False,
        }

    def sanitized_evidence(self) -> dict[str, Any]:
        evidence = asdict(self.inspect())
        content = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        result = self.artifacts.register(
            ArtifactRegistration(
                artifact_id=f"archive-activation:{evidence['evidence_digest']}",
                content=content,
                media_type="application/json",
                source_uri=f"calyx://archive/activation/{evidence['evidence_digest']}",
                producer_assignment_id="CALYX-474-institutional-archive-activation",
                evidence_uris=("calyx://archive/contracts/build-080",),
                metadata={
                    "sanitized": True,
                    "contains_secrets": False,
                    "contains_source_paths": False,
                    "production_import_authorized": False,
                },
            )
        )
        return {
            "activation": evidence,
            "artifact": {
                "artifact_id": result.record.artifact_id,
                "checksum": result.record.checksum,
                "created": result.created,
            },
            "sanitized": True,
            "contains_secrets": False,
            "contains_source_paths": False,
        }
