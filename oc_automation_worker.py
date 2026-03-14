import os
import time
import psycopg
import requests

DATABASE_URL = os.getenv("DATABASE_URL")


def get_job(conn):
    with conn.cursor() as cur:
        cur.execute("""
        SELECT id, payload
        FROM oc_job_queue
        WHERE status='pending'
        ORDER BY priority DESC, available_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED;
        """)
        row = cur.fetchone()

        if row:
            job_id, payload = row

            cur.execute(
                """
            UPDATE oc_job_queue
            SET status='running'
            WHERE id=%s;
            """, (job_id, ))
            conn.commit()

            return job_id, payload

    return None, None


def complete_job(conn, job_id):
    with conn.cursor() as cur:
        cur.execute(
            """
        UPDATE oc_job_queue
        SET status='completed', finished_at=now()
        WHERE id=%s;
        """, (job_id, ))
        conn.commit()


def harvest_gbif(genus):
    url = f"https://api.gbif.org/v1/occurrence/search?genus={genus}&limit=300"
    r = requests.get(url)
    return r.json()


def store_occurrences(conn, records):
    with conn.cursor() as cur:
        for rec in records:
            lat = rec.get("decimalLatitude")
            lon = rec.get("decimalLongitude")

            if lat and lon:
                cur.execute(
                    """
                INSERT INTO oc_occurrences
                (decimal_latitude, decimal_longitude, source, raw_json)
                VALUES (%s,%s,'GBIF',%s)
                """, (lat, lon, psycopg.types.json.Json(rec)))

        conn.commit()


def main():
    conn = psycopg.connect(DATABASE_URL)

    while True:
        job_id, payload = get_job(conn)

        if not job_id:
            time.sleep(5)
            continue

        target_id = payload["target_id"]

        with conn.cursor() as cur:
            cur.execute(
                """
            SELECT genus FROM oc_harvest_targets
            WHERE target_id=%s
            """, (target_id, ))
            genus = cur.fetchone()[0]

        print("Harvesting genus:", genus)

        data = harvest_gbif(genus)

        records = data.get("results", [])

        store_occurrences(conn, records)

        complete_job(conn, job_id)


if __name__ == "__main__":
    main()
