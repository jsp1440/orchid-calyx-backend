import os
import psycopg2
import pandas as pd

DB = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DB)

sql = """
SELECT
COUNT(*) AS occurrences
FROM oc_occurrences
"""

df = pd.read_sql(sql, conn)

print("")
print("Orchid Continuum Data Status")
print("-----------------------------")
print(df)

conn.close()
