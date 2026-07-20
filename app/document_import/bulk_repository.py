from __future__ import annotations
import os
from typing import Any
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class PostgresBulkImportRepository:
    def _connect(self): return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)

    def candidates(self, source_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return list(conn.execute("""SELECT d.*,r.revision_id,r.provenance->>'modified_timestamp' revision_modified_at
                FROM oc_sources.document_inventory d LEFT JOIN LATERAL
                (SELECT revision_id,provenance FROM oc_import.document_revisions WHERE registry_id=d.inventory_id ORDER BY revision_number DESC LIMIT 1) r ON TRUE
                WHERE d.source_id=%s ORDER BY d.folder_path,d.filename,d.inventory_id""",(source_id,)).fetchall())

    def source_id(self, run_id: int) -> str:
        with self._connect() as conn:
            row=conn.execute("SELECT source_id FROM oc_import.bulk_runs WHERE bulk_run_id=%s",(run_id,)).fetchone()
            if not row: raise LookupError("BULK_RUN_NOT_FOUND")
            return str(row["source_id"])

    def create_plan(self, source_id: str, actor: str, items: list[dict[str, Any]]) -> int:
        with self._connect() as conn:
            run_id=conn.execute("INSERT INTO oc_import.bulk_runs(source_id,actor,state,plan) VALUES (%s,%s,'PLANNED',%s) RETURNING bulk_run_id",(source_id,actor,Jsonb({"items":items}))).fetchone()["bulk_run_id"]
            for item in items:
                conn.execute("INSERT INTO oc_import.bulk_items(bulk_run_id,registry_id,classification,state) VALUES (%s,%s,%s,'PENDING')",(run_id,item["registry_id"],item["classification"]))
            return run_id

    def start(self, run_id: int, actor: str) -> None:
        with self._connect() as conn:
            row=conn.execute("UPDATE oc_import.bulk_runs SET state='RUNNING',started_at=COALESCE(started_at,NOW()),updated_at=NOW() WHERE bulk_run_id=%s AND state IN ('PLANNED','INTERRUPTED','RUNNING') RETURNING bulk_run_id",(run_id,)).fetchone()
            if not row: raise ValueError("BULK_RUN_NOT_RESUMABLE")

    def pending(self, run_id: int):
        with self._connect() as conn: return list(conn.execute("SELECT registry_id,classification FROM oc_import.bulk_items WHERE bulk_run_id=%s AND state='PENDING' ORDER BY registry_id",(run_id,)).fetchall())
    def cancelled(self, run_id: int) -> bool:
        with self._connect() as conn: return bool(conn.execute("SELECT state='CANCELLED' value FROM oc_import.bulk_runs WHERE bulk_run_id=%s",(run_id,)).fetchone()["value"])
    def record(self, run_id: int, registry_id: int, state: str, error: str|None, result: dict|None):
        with self._connect() as conn: conn.execute("UPDATE oc_import.bulk_items SET state=%s,error_code=%s,result=%s,updated_at=NOW() WHERE bulk_run_id=%s AND registry_id=%s",(state,error,Jsonb(result) if result else None,run_id,registry_id))
    def finish(self, run_id: int, elapsed_ms: float):
        with self._connect() as conn:
            counts=conn.execute("SELECT state,count(*) count FROM oc_import.bulk_items WHERE bulk_run_id=%s GROUP BY state",(run_id,)).fetchall(); summary={r["state"].lower():r["count"] for r in counts}
            current=conn.execute("SELECT state FROM oc_import.bulk_runs WHERE bulk_run_id=%s",(run_id,)).fetchone()["state"]
            state="CANCELLED" if current=="CANCELLED" else ("COMPLETED_WITH_ERRORS" if summary.get("failed") else "COMPLETED")
            conn.execute("UPDATE oc_import.bulk_runs SET state=%s,completed_at=CASE WHEN %s<>'CANCELLED' THEN NOW() ELSE completed_at END,updated_at=NOW() WHERE bulk_run_id=%s",(state,state,run_id))
            return {"bulk_run_id":run_id,"state":state,"imported":summary.get("imported",0),"updated":summary.get("updated",0),"skipped":summary.get("skipped",0),"failed":summary.get("failed",0),"duplicates":summary.get("duplicate",0),"elapsed_ms":elapsed_ms}
    def cancel(self, run_id: int, actor: str):
        with self._connect() as conn:
            row=conn.execute("UPDATE oc_import.bulk_runs SET state='CANCELLED',cancelled_at=NOW(),updated_at=NOW() WHERE bulk_run_id=%s AND state IN ('PLANNED','RUNNING','INTERRUPTED') RETURNING bulk_run_id,state,cancelled_at",(run_id,)).fetchone()
            if not row: raise ValueError("BULK_RUN_NOT_CANCELLABLE")
            conn.execute("UPDATE oc_import.bulk_items SET state='CANCELLED',updated_at=NOW() WHERE bulk_run_id=%s AND state='PENDING'",(run_id,)); return row
    def history(self, limit: int):
        with self._connect() as conn: return list(conn.execute("SELECT bulk_run_id,source_id,actor,state,plan,started_at,completed_at,cancelled_at,created_at FROM oc_import.bulk_runs ORDER BY created_at DESC LIMIT %s",(limit,)).fetchall())
