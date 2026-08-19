from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.candidate_knowledge.models import EvidenceInput, SourceAnchor
from app.evidence_aggregation.models import CandidateInput
from app.semantic_index.models import IndexDocument

TYPES = {
    "EvidenceInput": EvidenceInput,
    "SourceAnchor": SourceAnchor,
    "CandidateInput": CandidateInput,
    "IndexDocument": IndexDocument,
}


def encode(value: Any) -> Any:
    if is_dataclass(value):
        return {"__type__": type(value).__name__, "value": encode(asdict(value))}
    if isinstance(value, dict):
        return {"__map__": [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, tuple):
        return {"__tuple__": [encode(x) for x in value]}
    if isinstance(value, set):
        return {"__set__": [encode(x) for x in value]}
    if isinstance(value, list):
        return [encode(x) for x in value]
    return value


def decode(value: Any) -> Any:
    if isinstance(value, list):
        return [decode(x) for x in value]
    if not isinstance(value, dict):
        return value
    if "__tuple__" in value:
        return tuple(decode(x) for x in value["__tuple__"])
    if "__set__" in value:
        return {decode(x) for x in value["__set__"]}
    if "__map__" in value:
        return {decode(k): decode(v) for k, v in value["__map__"]}
    if "__type__" in value:
        cls = TYPES[value["__type__"]]
        data = decode(value["value"])
        if cls is EvidenceInput:
            data["source_anchors"] = tuple(
                SourceAnchor(**x) if isinstance(x, dict) else x
                for x in data["source_anchors"]
            )
        for key in (
            "source_anchors",
            "source_anchor_ids",
            "citation_lineage",
            "taxon_links",
        ):
            if key in data and isinstance(data[key], list):
                data[key] = tuple(data[key])
        return cls(**data)
    return {k: decode(v) for k, v in value.items()}


def configured_database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")


class PostgresStateMixin:
    snapshot_kind: str
    lock_id: int
    state_attributes: tuple[str, ...]

    def __init_persistence__(self, database_url: str | None = None):
        self.database_url = database_url or configured_database_url()
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL is required for persistent BUILD-086 repositories"
            )
        self._bootstrap_runtime_snapshot_storage_if_missing()

    def _connect(self):
        import psycopg

        return psycopg.connect(
            self.database_url, row_factory=dict_row, connect_timeout=10
        )

    def _bootstrap_runtime_snapshot_storage_if_missing(self) -> None:
        """Create the additive BUILD-086 runtime store only when wholly absent.

        Production had the application code for durable semantic indexing but not
        the base 086d table, causing literature ingestion to fail before any
        evidence could be indexed.  A brand-new/partially provisioned deployment
        may safely bootstrap this shared persistence primitive because creation is
        additive and idempotent.  We intentionally do *not* rewrite constraints on
        an existing table; established databases still use explicit migrations for
        constraint changes.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('oc_candidate_knowledge.runtime_repository_snapshots') AS relation"
            )
            row = cur.fetchone()
            if row and row.get("relation"):
                return

            cur.execute("CREATE SCHEMA IF NOT EXISTS oc_candidate_knowledge")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.runtime_repository_snapshots(
                    repository_kind TEXT PRIMARY KEY CHECK(repository_kind IN(
                        'candidate_knowledge','evidence_aggregation','semantic_index'
                    )),
                    state JSONB NOT NULL,
                    revision BIGINT NOT NULL DEFAULT 1 CHECK(revision>0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.runtime_repository_audit(
                    audit_id BIGSERIAL PRIMARY KEY,
                    repository_kind TEXT NOT NULL,
                    revision BIGINT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS runtime_repository_audit_kind_idx
                ON oc_candidate_knowledge.runtime_repository_audit(
                    repository_kind,revision,created_at
                )
                """
            )
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION oc_candidate_knowledge.audit_runtime_snapshot()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO oc_candidate_knowledge.runtime_repository_audit(
                        repository_kind,revision,event_type,actor,details
                    ) VALUES(
                        NEW.repository_kind,
                        NEW.revision,
                        CASE WHEN TG_OP='INSERT' THEN 'SNAPSHOT_CREATED' ELSE 'SNAPSHOT_UPDATED' END,
                        'calyx-runtime-bootstrap',
                        jsonb_build_object('updated_at',NEW.updated_at)
                    );
                    RETURN NEW;
                END $$
                """
            )
            cur.execute(
                """
                DO $$ BEGIN
                    IF NOT EXISTS(
                        SELECT 1 FROM pg_trigger
                        WHERE tgname='runtime_repository_snapshot_audit'
                    ) THEN
                        CREATE TRIGGER runtime_repository_snapshot_audit
                        AFTER INSERT OR UPDATE
                        ON oc_candidate_knowledge.runtime_repository_snapshots
                        FOR EACH ROW
                        EXECUTE FUNCTION oc_candidate_knowledge.audit_runtime_snapshot();
                    END IF;
                END $$
                """
            )
            conn.commit()

    def _state(self):
        return {name: getattr(self, name) for name in self.state_attributes}

    def _restore(self, state):
        for name, value in state.items():
            setattr(self, name, value)

    def _load(self, cur):
        cur.execute(
            "SELECT state FROM oc_candidate_knowledge.runtime_repository_snapshots WHERE repository_kind=%s",
            (self.snapshot_kind,),
        )
        row = cur.fetchone()
        if row:
            self._restore(decode(row["state"]))

    def _save(self, cur):
        cur.execute(
            """INSERT INTO oc_candidate_knowledge.runtime_repository_snapshots(repository_kind,state,revision,updated_at)
  VALUES(%s,%s,1,NOW()) ON CONFLICT(repository_kind) DO UPDATE SET state=EXCLUDED.state,revision=oc_candidate_knowledge.runtime_repository_snapshots.revision+1,updated_at=NOW()""",
            (self.snapshot_kind, Jsonb(encode(self._state()))),
        )

    def refresh(self):
        with self._connect() as conn, conn.cursor() as cur:
            self._load(cur)
        return self

    def atomic(self, operation: Callable[[], Any]):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (self.lock_id,))
            self._load(cur)
            try:
                result = operation()
                self._save(cur)
                return result
            except Exception:
                conn.rollback()
                raise

    def lock_available(self) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (self.lock_id,))
            acquired = bool(cur.fetchone()["acquired"])
            if acquired:
                cur.execute("SELECT pg_advisory_unlock(%s)", (self.lock_id,))
            return acquired
