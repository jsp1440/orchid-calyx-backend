from fastapi import FastAPI
import psycopg2
import os

app = FastAPI()

DB = os.getenv("DATABASE_URL")


@app.get("/orchid_points")
def orchid_points():

    conn = psycopg2.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT decimal_latitude, decimal_longitude
        FROM oc_occurrences
        WHERE decimal_latitude IS NOT NULL
        AND decimal_longitude IS NOT NULL
        LIMIT 20000
    """)

    rows = cur.fetchall()

    conn.close()

    points = [{"lat": r[0], "lon": r[1]} for r in rows]

    return {"points": points}
