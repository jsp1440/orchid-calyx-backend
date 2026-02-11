import time
import logging
from sqlalchemy import text
from app.database import get_engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")


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


def mark_job_done(conn, job_id):
    conn.execute(
        text("""
            UPDATE harvest_jobs
            SET status = 'done', finished_at = NOW()
            WHERE id = :id
        """),
        {"id": job_id},
    )


def main():
    log.info("Worker started")
    engine = get_engine()

    while True:
        with engine.begin() as conn:
            job = fetch_next_job(conn)

            if not job:
                log.info("No work found. Sleeping 2s.")
                time.sleep(2)
                continue

            job_id, job_type, payload = job
            log.info(f"Processing job {job_id} ({job_type})")

            mark_job_running(conn, job_id)

            # 🔧 Placeholder: actual harvester logic will go here
            time.sleep(1)

            mark_job_done(conn, job_id)
            log.info(f"Completed job {job_id}")


if __name__ == "__main__":
    main()
