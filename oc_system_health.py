import os
import psycopg2
from fastapi import FastAPI

app = FastAPI()

DB = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DB)


@app.get("/")
def root():
    return {"status": "orchid continuum online"}


@app.get("/db")
def db_status():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oc_occurrences")
        n = cur.fetchone()[0]
        conn.close()
        return {"database": "connected", "occurrences": n}
    except:
        return {"database": "error"}
