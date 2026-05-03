import os
import sys

if os.getenv("OC_ALLOW_LEGACY_OC_SCRIPT_RUN") != "YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION":
    print("BLOCKED: This legacy Orchid Continuum/Calyx root-level script is write-capable or schema-stale and is disabled by default.")
    print("This safety guard prevents accidental production database writes.")
    print("To run intentionally, set OC_ALLOW_LEGACY_OC_SCRIPT_RUN=YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION after manual review.")
    sys.exit(2)

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
