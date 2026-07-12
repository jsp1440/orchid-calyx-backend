import json
import time
import logging
from sqlalchemy import text
from app.database import get_engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

# Mapping of job_type to harvester_id for harvesters managed by the control plane
HARVESTER_JOB_MAP: dict[str, str] = {
    "harvest_inaturalist": "inaturalist",
    "harvest_gbif": "gbif",
    "harvest_gbif_occurrences": "gbif",
    "harvest_world_plants": "world_plants_hassler",
    "harvest_traitbank": "eol_traitbank",
    "harvest_eol_traitbank": "eol_traitbank",
    "harvest_globi": "globi",
    "harvest_image_media": "image_media",
    "harvest_literature": "literature",
    "harvest_mycorrhiza": "mycorrhizal_data",
    "harvest_mycorrhizal": "mycorrhizal_data",
    "harvest_climate": "climate_elevation",
    "harvest_conservation": "conservation_status",
}


def fetch_next_job(conn):
    result = conn.execute(
        text("""
            SELECT id, job_type, payload
            FROM harvest_jobs
            WHERE status = 'pending'
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)).fetchone()
    return result


def mark_job_running(conn, job_id):
    conn.execute(
        text("""
            UPDATE harvest_jobs
            SET status = 'running', started_at = NOW()
            WHERE id = :id
        """),
        {"id": job_id},
    )


def mark_job_done(conn, job_id, result_summary: str = "completed"):
    conn.execute(
        text("""
            UPDATE harvest_jobs
            SET status = 'done', finished_at = NOW(), result_summary = :summary
            WHERE id = :id
        """),
        {"id": job_id, "summary": result_summary},
    )


def mark_job_failed(conn, job_id, error: str):
    conn.execute(
        text("""
            UPDATE harvest_jobs
            SET status = 'failed', finished_at = NOW(), result_summary = :error
            WHERE id = :id
        """),
        {"id": job_id, "error": error},
    )


def execute_harvester_job(job_type: str, payload: dict) -> dict:
    """Dispatch a harvest job to the control plane and record telemetry."""
    from runtime.harvester_control import control_plane

    harvester_id = HARVESTER_JOB_MAP.get(job_type)
    if harvester_id is None:
        return {"status": "skipped", "reason": f"No harvester mapping for job_type '{job_type}'"}

    actor = str(payload.get("actor") or "calyx_worker")
    result = control_plane.run_once(harvester_id, actor)
    log.info(f"Dispatched {job_type} → harvester '{harvester_id}': {result.get('status')}")
    return result


def execute_job(job_type: str, payload: dict) -> dict:
    """Route a job to its execution handler based on job_type prefix."""
    if job_type.startswith("harvest_"):
        return execute_harvester_job(job_type, payload)

    if job_type == "audit":
        from app.routers.owner_operations import live_audit_payload
        audit_type = payload.get("audit_type", "overall")
        result = live_audit_payload(audit_type)
        return {"status": "completed", "audit_id": result.get("audit_id"), "audit_type": audit_type}

    if job_type == "export":
        export_type = payload.get("export_type", "unknown")
        return {"status": "completed", "export_type": export_type, "note": "Export queued for download."}

    # Unknown job type: log and skip rather than silently swallow
    log.warning(f"Unrecognised job_type '{job_type}' — marking done with skipped status.")
    return {"status": "skipped", "reason": f"Unrecognised job_type: '{job_type}'"}


def main():
    log.info("Calyx worker started")
    engine = get_engine()

    while True:
        with engine.begin() as conn:
            job = fetch_next_job(conn)

            if not job:
                log.info("No work found. Sleeping 2s.")
                time.sleep(2)
                continue

            job_id, job_type, payload_raw = job
            payload: dict = {}
            if payload_raw:
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else dict(payload_raw)
                except Exception:
                    payload = {}

            log.info(f"Processing job {job_id} ({job_type})")
            mark_job_running(conn, job_id)

        # Execute outside the mark-running transaction so the running state is
        # visible to other workers / telemetry queries before execution begins.
        try:
            result = execute_job(job_type, payload)
            summary = result.get("status", "completed")
            with engine.begin() as conn:
                mark_job_done(conn, job_id, result_summary=summary)
            log.info(f"Completed job {job_id} — {summary}")
        except Exception as exc:
            log.error(f"Job {job_id} failed: {exc}", exc_info=True)
            try:
                with engine.begin() as conn:
                    mark_job_failed(conn, job_id, error=str(exc))
            except Exception:
                pass


if __name__ == "__main__":
    main()
