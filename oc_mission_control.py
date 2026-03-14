import os
import pandas as pd
import psycopg2
import streamlit as st

st.set_page_config(page_title="Orchid Continuum Mission Control",
                   layout="wide")

DB = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DB)


def query(sql):
    conn = get_conn()
    df = pd.read_sql(sql, conn)
    conn.close()
    return df


st.title("🌸 Orchid Continuum Mission Control")

# ---- Metrics ----
occ = query("SELECT COUNT(*) AS n FROM oc_occurrences")
occ_count = int(occ.iloc[0]["n"])

col1, col2, col3 = st.columns(3)

col1.metric("Total Occurrences", occ_count)

try:
    targets = query("SELECT COUNT(*) AS n FROM oc_harvest_targets")
    col2.metric("Harvest Targets", int(targets.iloc[0]["n"]))
except:
    col2.metric("Harvest Targets", "table missing")

try:
    jobs = query("SELECT COUNT(*) AS n FROM oc_job_queue")
    col3.metric("Jobs in Queue", int(jobs.iloc[0]["n"]))
except:
    col3.metric("Jobs in Queue", "table missing")

st.divider()

# ---- Job Queue ----
st.subheader("Job Queue")

try:
    q = query("""
    SELECT id, job_type, status, created_at
    FROM oc_job_queue
    ORDER BY id DESC
    LIMIT 20
    """)
    st.dataframe(q)
except:
    st.info("No job queue table found.")

st.divider()

# ---- Harvest Status ----
st.subheader("Harvest Status")

try:
    h = query("""
    SELECT state, COUNT(*) as count
    FROM oc_harvest_targets
    GROUP BY state
    """)
    st.bar_chart(h.set_index("state"))
except:
    st.info("No harvest targets table.")

st.divider()

# ---- Occurrence Sample ----
st.subheader("Occurrence Sample")

try:
    sample = query("""
    SELECT genus, decimal_latitude, decimal_longitude
    FROM oc_occurrences
    LIMIT 20
    """)
    st.dataframe(sample)
except:
    st.warning("Occurrence table missing.")
