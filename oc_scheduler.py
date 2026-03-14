import os
import time
import psycopg

DATABASE_URL = os.getenv("DATABASE_URL")


def enqueue_job(conn, target_id):
    with conn.cursor() as cur:
        cur.execute(
            """
        INSERT INTO oc_job_queue (job_type, payload, priority, status)
        VALUES (
            'harvest_gbif_occurrences',
            jsonb_build_object('target_id', %s),
            100,
            'pending'
        );
        """, (target_id, ))
        conn.commit()


def fetch_target(conn):
    with conn.cursor() as cur:
        cur.execute("""
        SELECT target_id
        FROM oc_harvest_targets
        WHERE state='queued'
        ORDER BY priority DESC, created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED;
        """)
        row = cur.fetchone()

        if row:
            target_id = row[0]

            cur.execute(
                """
            UPDATE oc_harvest_targets
            SET state='processing'
            WHERE target_id=%s;
            """, (target_id, ))
            conn.commit()

            return target_id

    return None


def main():
    conn = psycopg.connect(DATABASE_URL)

    while True:
        target_id = fetch_target(conn)

        if target_id:
            print("Queueing job for target:", target_id)
            enqueue_job(conn, target_id)
        else:
            time.sleep(5)


if __name__ == "__main__":
    main()
