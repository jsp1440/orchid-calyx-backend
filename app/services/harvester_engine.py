import uuid
import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("harvester_engine")


LEASE_TIMEOUT_MINUTES = 10


def claim_next_job(db: Session, worker_id: str):
    """
    Safely claim a job using lease semantics.
    Prevents multiple workers from processing the same job.
    """

    result = (
        db.execute(
            text(
                """
            UPDATE harvest_jobs
            SET lease_owner = :worker_id,
                leased_at = NOW(),
                status = 'running',
                attempts = COALESCE(attempts, 0) + 1,
                updated_at = NOW()
            WHERE id = (
                SELECT id
                FROM harvest_jobs
                WHERE (
                    status = 'pending'
                    OR (
                        status = 'running'
                        AND leased_at < NOW() - INTERVAL '10 minutes'
                    )
                )
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """
            ),
            {"worker_id": worker_id},
        )
        .mappings()
        .first()
    )

    return dict(result) if result else None


def log_event(db: Session, harvester_id: str, level: str, source: str, message: str):
    db.execute(
        text(
            """
            INSERT INTO harvest_logs (harvester_id, timestamp, level, source, message)
            VALUES (:hid, NOW(), :level, :source, :message)
            """
        ),
        {
            "hid": harvester_id,
            "level": level,
            "source": source,
            "message": message,
        },
    )


def complete_job(db: Session, job_id: int):
    db.execute(
        text(
            """
            UPDATE harvest_jobs
            SET status = 'complete',
                completed_at = NOW(),
                lease_owner = NULL,
                leased_at = NULL,
                updated_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": job_id},
    )


def fail_job(db: Session, job_id: int, error: str):
    db.execute(
        text(
            """
            UPDATE harvest_jobs
            SET status = 'failed',
                last_error = :error,
                lease_owner = NULL,
                leased_at = NULL,
                updated_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": job_id, "error": error},
    )


def run_single_job(db: Session, job: dict):
    """
    Placeholder execution logic.
    This is where real harvesting (API calls, scraping, etc.) will go.
    """

    job_id = job["id"]
    name = job.get("scientific_name")

    log_event(
        db, "engine", "info", "harvester_engine", f"Starting job {job_id} for {name}"
    )

    # SIMULATED WORK (safe baseline)
    db.execute(
        text(
            """
            UPDATE harvest_jobs
            SET current_image_count = COALESCE(current_image_count, 0) + 5
            WHERE id = :id
            """
        ),
        {"id": job_id},
    )

    log_event(db, "engine", "info", "harvester_engine", f"Completed job {job_id}")


def run_worker_cycle(db: Session):
    worker_id = str(uuid.uuid4())

    job = claim_next_job(db, worker_id)

    if not job:
        log.info("No jobs available.")
        return {"status": "idle"}

    try:
        run_single_job(db, job)
        complete_job(db, job["id"])
        db.commit()
        return {"status": "completed", "job_id": job["id"]}

    except Exception as e:
        db.rollback()
        fail_job(db, job["id"], str(e))
        db.commit()
        return {"status": "failed", "job_id": job["id"], "error": str(e)}
