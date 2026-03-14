import os
import psycopg2
import pandas as pd
from datetime import datetime

DB = os.getenv("DATABASE_URL")


def run(sql):
    conn = psycopg2.connect(DB)
    df = pd.read_sql(sql, conn)
    conn.close()
    return df


print("")
print("========================================")
print("   ORCHID CONTINUUM CONTROL PANEL")
print("========================================")
print("Time:", datetime.now())
print("")

# ------------------------------------------------
# Total Occurrences
# ------------------------------------------------

try:
    df = run("""
        SELECT COUNT(*) AS occurrences
        FROM oc_occurrences
    """)
    print("Total Occurrences:", int(df.iloc[0]["occurrences"]))
except Exception as e:
    print("Occurrences error:", e)

print("")

# ------------------------------------------------
# Species Count
# ------------------------------------------------

try:
    df = run("""
        SELECT COUNT(DISTINCT species_id) AS species
        FROM oc_occurrences
        WHERE species_id IS NOT NULL
    """)
    print("Species Represented:", int(df.iloc[0]["species"]))
except:
    print("Species count unavailable")

print("")

# ------------------------------------------------
# Genus Count
# ------------------------------------------------

try:
    df = run("""
        SELECT COUNT(DISTINCT genus_id) AS genera
        FROM oc_occurrences
        WHERE genus_id IS NOT NULL
    """)
    print("Genera Represented:", int(df.iloc[0]["genera"]))
except:
    print("Genus count unavailable")

print("")

# ------------------------------------------------
# Geographic Spread
# ------------------------------------------------

try:
    df = run("""
        SELECT COUNT(DISTINCT country) AS countries
        FROM oc_occurrences
        WHERE country IS NOT NULL
    """)
    print("Countries Represented:", int(df.iloc[0]["countries"]))
except:
    print("Country data unavailable")

print("")

# ------------------------------------------------
# Elevation Stats
# ------------------------------------------------

try:
    df = run("""
        SELECT
            MIN(elevation_m) AS min_elev,
            MAX(elevation_m) AS max_elev,
            AVG(elevation_m) AS avg_elev
        FROM oc_occurrences
        WHERE elevation_m IS NOT NULL
    """)
    print("Elevation Range (m):")
    print(df)
except:
    print("Elevation data unavailable")

print("")
print("========================================")
print(" Control Panel Complete")
print("========================================")
