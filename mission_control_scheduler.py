import os
import psycopg2
from datetime import datetime
import time

DATABASE_URL = os.getenv("DATABASE_URL")


def db():
    return psycopg2.connect(DATABASE_URL)


def launch_gbif_harvest():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO oc_harvest_runs (
                job_type,
                status,
                created_at
            )
            VALUES (
                'harvest_gbif_occurrences',
                'pending',
                now()
            )
            RETURNING id;
            """)
            job_id = cur.fetchone()[0]
            print(f"Started GBIF harvest {job_id}")


def trigger_pipeline(name):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
            INSERT INTO pipeline_runs(
                pipeline_name,
                status,
                created_at
            )
            VALUES (%s,'pending',now())
            """,
                (name,),
            )
            print(f"Pipeline triggered: {name}")


def check_workers():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT worker_id,last_seen
            FROM oc_worker_registry
            ORDER BY last_seen DESC
            """)
            workers = cur.fetchall()
            print("Workers:", workers)


def mission_control_loop():
    print("Mission Control Online")

    while True:
        print("Checking orchestration")

        launch_gbif_harvest()

        trigger_pipeline("taxonomy_resolution")
        trigger_pipeline("trait_extraction")
        trigger_pipeline("image_validation")

        check_workers()

        time.sleep(3600)  # run hourly


if __name__ == "__main__":
    mission_control_loop()
