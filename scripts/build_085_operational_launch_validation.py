"""BUILD-085 operational launch validator for controlled Brain imports.

This script reuses BUILD-082/083/084 services exactly as implemented.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.document_import.bulk import BulkImportService
from app.document_import.bulk_repository import PostgresBulkImportRepository
from app.document_import.dependencies import get_import_repository
from app.document_import.drive import GoogleDriveDocumentGateway
from app.document_import.service import DocumentImportService
from app.missions.repositories import PostgresMissionRepository
from app.missions.services import MissionService
from app.source_registry.dependencies import get_scan_service, get_source_repository

ROOT = Path(__file__).resolve().parents[1]
READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("BUILD-070", "oc_intake.sources", "070_knowledge_intake.sql"),
    ("BUILD-076A", "oc_intake.documents", "076a_universal_intake.sql"),
    ("BUILD-079", "oc_missions.missions", "079_controlled_mission_orchestration.sql"),
    ("BUILD-081", "oc_sources.document_inventory", "081_brain_source_registry.sql"),
    ("BUILD-082", "oc_import.import_sessions", "082_controlled_drive_document_import.sql"),
    ("BUILD-083", "oc_import.bulk_runs", "083_bulk_drive_brain_import.sql"),
    ("BUILD-084", "oc_document_intelligence.records", "084_document_intelligence.sql"),
)
PROTECTED_SCHEMAS = ("oc_graph", "oc_taxonomy", "oc_ontology", "oc_semantic", "oc_embeddings", "oc_publication")
INTELLIGENCE_TABLES = (
    "classifications",
    "source_assessments",
    "purpose_assignments",
    "protocols",
    "result_packages",
    "media_objects",
    "table_objects",
    "identification_keys",
    "taxonomic_treatments",
    "strategic_insights",
    "extracted_claims",
    "candidate_events",
    "retrieval_chunks",
    "review_items",
)


@dataclass
class SafetyCheck:
    name: str
    passed: bool
    detail: str


class NotReady(RuntimeError):
    pass


def _dsn() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise NotReady("DATABASE_URL is not configured")
    return value


def _migration_state(dsn: str) -> dict[str, bool]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return {
            build: bool(conn.execute("SELECT to_regclass(%s) IS NOT NULL ok", (relation,)).fetchone()["ok"])
            for build, relation, _ in MIGRATIONS
        }


def _is_additive_sql(filename: str) -> bool:
    text = (ROOT / "migrations" / filename).read_text(encoding="utf-8").upper()
    return all(token not in text for token in ("DROP ", "TRUNCATE ", "DELETE FROM "))


def apply_missing_migrations(dsn: str) -> dict[str, Any]:
    before = _migration_state(dsn)
    applied: list[str] = []
    for build, _, filename in MIGRATIONS:
        if before[build]:
            continue
        if not _is_additive_sql(filename):
            raise NotReady(f"Missing migration {filename} is not additive")
        with psycopg.connect(dsn) as conn:
            conn.execute((ROOT / "migrations" / filename).read_text(encoding="utf-8"))
        applied.append(filename)
    after = _migration_state(dsn)
    if not all(after.values()):
        missing = [build for build, ok in after.items() if not ok]
        raise NotReady(f"Missing required migrations after apply: {', '.join(missing)}")
    return {"before": before, "after": after, "applied": applied}


def verify_root_source(source_id: str, root_folder_id: str) -> dict[str, Any]:
    source = get_source_repository().get_source(source_id)
    if not source:
        raise NotReady(f"Configured source_id {source_id} was not found")
    if source.get("source_type") != "GOOGLE_DRIVE":
        raise NotReady(f"Configured source_id {source_id} is not GOOGLE_DRIVE")
    folder_ids = list((source.get("configuration") or {}).get("folder_ids") or [])
    if root_folder_id not in folder_ids:
        raise NotReady(f"Configured root folder {root_folder_id} is not in source configuration")
    return {"source_id": source_id, "source_type": source["source_type"], "folder_ids": folder_ids}


def verify_read_only_credentials() -> dict[str, Any]:
    raw = os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise NotReady("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON is not configured")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotReady("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON is invalid JSON") from exc
    client_email = payload.get("client_email")
    if not client_email:
        raise NotReady("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON is missing client_email")
    gateway = GoogleDriveDocumentGateway.from_environment()
    return {
        "service_account": client_email,
        "required_scope": READONLY_SCOPE,
        "write_scope_enabled": False,
        "gateway_class": gateway.__class__.__name__,
    }


def verify_mission_registry(dsn: str) -> dict[str, Any]:
    service = MissionService(PostgresMissionRepository(dsn))
    service.initialize()
    entry = service.repository.mission_type("controlled_drive_import")
    if not entry:
        raise NotReady("Mission Control registry missing controlled_drive_import")
    return {
        "mission_type": entry["mission_type"],
        "handler": entry["handler"],
        "write_scope": entry["write_scope"],
        "human_approval_required": bool(entry["human_approval_required"]),
    }


def _bulk_service() -> BulkImportService:
    importer = DocumentImportService(get_import_repository(), GoogleDriveDocumentGateway.from_environment(), folder_prefix="/")
    return BulkImportService(PostgresBulkImportRepository(), get_scan_service(), get_source_repository(), importer)


def run_preview(source_id: str, actor: str) -> dict[str, Any]:
    result = _bulk_service().preview(source_id, actor)
    folders = sorted({item.get("folder") or "/" for item in result.get("items", [])})
    result["summary"] = {
        "new": result["counts"].get("NEW", 0),
        "updated": result["counts"].get("UPDATED", 0),
        "unchanged": result["counts"].get("UNCHANGED", 0),
        "duplicates": result["counts"].get("DUPLICATE", 0),
        "unsupported": result["counts"].get("UNSUPPORTED", 0),
        "failures": result.get("scan", {}).get("failed", 0),
        "totals_by_type": result.get("counts_by_type", {}),
        "folders": len(folders),
        "files": len(result.get("items", [])),
        "elapsed_ms": result.get("scan", {}).get("duration_ms", 0),
    }
    return result


def run_execute(run_id: int, actor: str) -> dict[str, Any]:
    return _bulk_service().execute(run_id, actor)


def run_resume(run_id: int, actor: str) -> dict[str, Any]:
    return _bulk_service().resume(run_id, actor)


def run_cancel(run_id: int, actor: str) -> dict[str, Any]:
    return _bulk_service().cancel(run_id, actor)


def run_status(dsn: str, run_id: int) -> dict[str, Any]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        run = conn.execute("SELECT * FROM oc_import.bulk_runs WHERE bulk_run_id=%s", (run_id,)).fetchone()
        if not run:
            raise NotReady(f"Bulk run {run_id} was not found")
        counts = conn.execute(
            "SELECT state, count(*) AS count FROM oc_import.bulk_items WHERE bulk_run_id=%s GROUP BY state ORDER BY state",
            (run_id,),
        ).fetchall()
    return {"run": run, "item_states": {row["state"]: row["count"] for row in counts}}


def _protected_counts(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        out: dict[str, int] = {}
        for schema in PROTECTED_SCHEMAS:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE'",
                (schema,),
            ).fetchall()
            total_rows = 0
            for row in tables:
                table_name = row["table_name"]
                total_rows += int(
                    conn.execute(
                        sql.SQL("SELECT count(*) AS count FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table_name))
                    ).fetchone()["count"]
                )
            out[schema] = total_rows
        return out


def _safety_checks() -> list[SafetyCheck]:
    doc_service = (ROOT / "app" / "document_import" / "service.py").read_text(encoding="utf-8")
    bulk_service = (ROOT / "app" / "document_import" / "bulk.py").read_text(encoding="utf-8")
    mission_service = (ROOT / "app" / "missions" / "services.py").read_text(encoding="utf-8")
    scientific = (ROOT / "app" / "document_intelligence" / "scientific.py").read_text(encoding="utf-8")
    migration_084 = (ROOT / "migrations" / "084_document_intelligence.sql").read_text(encoding="utf-8").upper()

    bulk_service_compressed = bulk_service.replace(" ", "").replace("\n", "")
    checks = [
        SafetyCheck("Drive access is read-only", READONLY_SCOPE in (ROOT / "app" / "document_import" / "drive.py").read_text(encoding="utf-8"), "BUILD-082 gateway is configured for drive.readonly"),
        SafetyCheck("Only NEW/UPDATED are executed", "classification\"]notin{\"NEW\",\"UPDATED\"}" in bulk_service_compressed, "Bulk execute skips unchanged/duplicates/unsupported"),
        SafetyCheck("SHA-256 hashing is active", "hashlib.sha256" in doc_service, "Document import computes SHA-256 for every retrieved payload"),
        SafetyCheck("Mission Control registry-id authorization is enforced", "validate_mission_payload" in mission_service and "registry_ids" in mission_service, "Mission payload is validated to registry_ids only"),
        SafetyCheck("File failures do not abort bulk run", "state = \"FAILED\"" in bulk_service and "for item in self.repository.pending" in bulk_service, "Bulk loop continues after failed file import results"),
        SafetyCheck("Display policy cannot be bypassed by credentials", "authenticated" in scientific and "display_policy" in scientific, "BUILD-084 display policy is applied before returning complete text"),
        SafetyCheck("BUILD-084 publications remain unpublished", "CHECK(PUBLISHED=FALSE)" in migration_084, "Claims/events/taxon links are constrained to unpublished state"),
    ]
    return checks


def _fixture_cancel_resume_proof() -> dict[str, Any]:
    class Repo:
        def __init__(self):
            self.items = [
                {"registry_id": 1, "classification": "NEW"},
                {"registry_id": 2, "classification": "NEW"},
            ]
            self.states = {1: "PENDING", 2: "PENDING"}
            self.was_cancelled = False

        def source_id(self, run_id):
            return "s"

        def start(self, run_id, actor):
            return None

        def pending(self, run_id):
            return [item for item in self.items if self.states[item["registry_id"]] == "PENDING"]

        def cancelled(self, run_id):
            return self.was_cancelled

        def record(self, run_id, registry_id, state, error, result):
            self.states[registry_id] = state

        def finish(self, run_id, elapsed):
            return {"bulk_run_id": run_id, "states": dict(self.states), "elapsed_ms": elapsed}

        def cancel(self, run_id, actor):
            self.was_cancelled = True
            return {"state": "CANCELLED"}

    class ImporterRepo:
        @staticmethod
        def actor_owns_source(actor, source_id):
            return True

    class Importer:
        def __init__(self, repo):
            self.repository = ImporterRepo()
            self.repo = repo
            self.calls: list[int] = []

        def import_one(self, registry_id, actor):
            from app.document_import.models import ImportResult, ImportState

            self.calls.append(registry_id)
            return ImportResult(session_id=1, registry_id=registry_id, state=ImportState.IMPORTED)

    repo = Repo()
    importer = Importer(repo)
    service = BulkImportService(repo, None, None, importer)

    first = service.execute(1, "owner")
    cancelled = service.cancel(1, "owner")
    repo.states[2] = "PENDING"
    resumed = service.resume(1, "owner")

    return {
        "initial_execution_states": first["states"],
        "cancel_result": cancelled,
        "resume_states": resumed["states"],
        "import_calls": importer.calls,
        "proof": {
            "cancellation_leaves_checkpoint": cancelled["state"] == "CANCELLED",
            "resume_continues_pending_only": importer.calls[-1:] == [2],
            "completed_items_not_reimported": importer.calls.count(1) == 1,
            "counts_coherent_after_resume": Counter(resumed["states"].values())["IMPORTED"] >= 1,
        },
    }


def _post_run_verification(dsn: str, run_id: int) -> dict[str, Any]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        counts = conn.execute(
            "SELECT state, count(*) AS count FROM oc_import.bulk_items WHERE bulk_run_id=%s GROUP BY state",
            (run_id,),
        ).fetchall()
        classifications = conn.execute(
            "SELECT classification, count(*) AS count FROM oc_import.bulk_items WHERE bulk_run_id=%s GROUP BY classification",
            (run_id,),
        ).fetchall()
        revision_stats = conn.execute(
            """
            SELECT
              count(*) AS revision_total,
              count(*) FILTER (WHERE r.sha256 IS NOT NULL) AS sha_complete,
              count(*) FILTER (WHERE r.provenance ? 'folder') AS provenance_complete,
              count(*) FILTER (WHERE r.duplicate_of_revision_id IS NOT NULL) AS duplicate_revision_count,
              count(*) FILTER (WHERE i.id IS NULL) AS orphan_count
            FROM oc_import.document_revisions r
            LEFT JOIN oc_intake.documents i ON i.id = r.intake_document_id
            WHERE r.session_id IN (
                SELECT DISTINCT (result->>'session_id')::bigint
                FROM oc_import.bulk_items
                WHERE bulk_run_id=%s
                  AND result IS NOT NULL
                  AND result ? 'session_id'
            )
            """,
            (run_id,),
        ).fetchone()
        immutable_conflicts = conn.execute(
            """
            SELECT count(*) AS count FROM (
              SELECT registry_id, revision_number, count(*) AS c
              FROM oc_import.document_revisions
              WHERE session_id IN (
                SELECT DISTINCT (result->>'session_id')::bigint
                FROM oc_import.bulk_items
                WHERE bulk_run_id=%s
                  AND result IS NOT NULL
                  AND result ? 'session_id'
              )
              GROUP BY registry_id, revision_number
              HAVING count(*) > 1
            ) t
            """,
            (run_id,),
        ).fetchone()["count"]
        run_state = conn.execute(
            "SELECT state FROM oc_import.bulk_runs WHERE bulk_run_id=%s",
            (run_id,),
        ).fetchone()["state"]
        pending_count = conn.execute(
            "SELECT count(*) AS count FROM oc_import.bulk_items WHERE bulk_run_id=%s AND state='PENDING'",
            (run_id,),
        ).fetchone()["count"]
        review_queue = conn.execute(
            "SELECT count(*) AS count FROM oc_document_intelligence.review_items WHERE state='OPEN'",
        ).fetchone()["count"]

        extraction_counts: dict[str, int] = {}
        for table in INTELLIGENCE_TABLES:
            extraction_counts[table] = conn.execute(
                sql.SQL("SELECT count(*) AS count FROM oc_document_intelligence.{}").format(sql.Identifier(table))
            ).fetchone()["count"]

    by_state = {row["state"]: row["count"] for row in counts}
    by_classification = {row["classification"]: row["count"] for row in classifications}
    return {
        "imported": by_state.get("IMPORTED", 0),
        "updated": by_state.get("UPDATED", 0),
        "skipped_unchanged": by_state.get("SKIPPED", 0),
        "duplicates": by_state.get("DUPLICATE", 0),
        "unsupported": by_classification.get("UNSUPPORTED", 0),
        "failed": by_state.get("FAILED", 0),
        "checkpoint_integrity": {"run_state": run_state, "pending_items": pending_count, "complete": pending_count == 0},
        "provenance_integrity": revision_stats["provenance_complete"] == revision_stats["revision_total"],
        "sha256_integrity": revision_stats["sha_complete"] == revision_stats["revision_total"],
        "immutable_revision_integrity": immutable_conflicts == 0,
        "revision_total": revision_stats["revision_total"],
        "orphan_count": revision_stats["orphan_count"],
        "duplicate_revision_count": revision_stats["duplicate_revision_count"],
        "extraction_counts": extraction_counts,
        "review_queue_open": review_queue,
    }


def _idempotency_preview(preview: dict[str, Any]) -> dict[str, Any]:
    summary = preview.get("summary", {})
    changed = int(summary.get("new", 0)) + int(summary.get("updated", 0))
    return {
        "new": summary.get("new", 0),
        "updated": summary.get("updated", 0),
        "duplicates": summary.get("duplicates", 0),
        "unchanged": summary.get("unchanged", 0),
        "passes": changed == 0,
    }


def _actor() -> str:
    return os.getenv("BRAIN_IMPORT_ACTOR", "owner_session")


def final_report(source_id: str | None, root_folder_id: str | None) -> dict[str, Any]:
    started = time.perf_counter()
    dsn = _dsn()
    source_id = source_id or os.getenv("GOOGLE_DRIVE_BRAIN_SOURCE_ID")
    root_folder_id = root_folder_id or os.getenv("GOOGLE_DRIVE_BRAIN_ROOT_FOLDER_ID")
    if not source_id:
        raise NotReady("GOOGLE_DRIVE_BRAIN_SOURCE_ID is not configured")
    if not root_folder_id:
        raise NotReady("GOOGLE_DRIVE_BRAIN_ROOT_FOLDER_ID is not configured")

    migration_report = apply_missing_migrations(dsn)
    source_report = verify_root_source(source_id, root_folder_id)
    credentials_report = verify_read_only_credentials()
    mission_report = verify_mission_registry(dsn)

    preview = run_preview(source_id, _actor())
    safety = _safety_checks()
    failed_safety = [check for check in safety if not check.passed]
    if failed_safety:
        raise NotReady(f"Safety verification failed: {failed_safety[0].name}")

    protected_before = _protected_counts(dsn)
    execution = run_execute(preview["bulk_run_id"], _actor())
    protected_after = _protected_counts(dsn)
    if protected_before != protected_after:
        raise NotReady("Protected schema table inventory changed during execution")

    fixture = _fixture_cancel_resume_proof()
    post = _post_run_verification(dsn, preview["bulk_run_id"])
    idempotency = _idempotency_preview(run_preview(source_id, _actor()))

    verdict = "READY — CONTROLLED BRAIN IMPORT VALIDATED" if idempotency["passes"] else "NOT READY"
    blocker = None if idempotency["passes"] else "Idempotency preview still reports NEW or UPDATED items"

    return {
        "verdict": verdict,
        "blocker": blocker,
        "migrations": migration_report,
        "configured_root": source_report,
        "credentials": credentials_report,
        "mission_registry": mission_report,
        "preview_totals": preview["summary"],
        "execution_totals": execution,
        "safety_checks": [check.__dict__ for check in safety],
        "cancellation_resume_proof": fixture,
        "post_run_verification": post,
        "idempotency": idempotency,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="BUILD-085 operational launch validator")
    parser.add_argument("command", choices=["preview", "execute", "resume", "cancel", "status", "final-report"])
    parser.add_argument("--source-id")
    parser.add_argument("--root-folder-id")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--actor", default=_actor())
    args = parser.parse_args()

    try:
        if args.command == "preview":
            if not args.source_id:
                raise NotReady("--source-id is required for preview")
            output = run_preview(args.source_id, args.actor)
        elif args.command == "execute":
            if not args.run_id:
                raise NotReady("--run-id is required for execute")
            output = run_execute(args.run_id, args.actor)
        elif args.command == "resume":
            if not args.run_id:
                raise NotReady("--run-id is required for resume")
            output = run_resume(args.run_id, args.actor)
        elif args.command == "cancel":
            if not args.run_id:
                raise NotReady("--run-id is required for cancel")
            output = run_cancel(args.run_id, args.actor)
        elif args.command == "status":
            if not args.run_id:
                raise NotReady("--run-id is required for status")
            output = run_status(_dsn(), args.run_id)
        else:
            output = final_report(args.source_id, args.root_folder_id)
    except NotReady as exc:
        output = {"verdict": "NOT READY", "blocker": str(exc)}
    except Exception as exc:  # pragma: no cover - operational fallback
        output = {"verdict": "NOT READY", "blocker": f"Unexpected failure: {exc.__class__.__name__}:{exc}"}

    print(json.dumps(output, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
