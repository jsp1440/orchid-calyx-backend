# orchid_climate_engine.py
# Orchid Continuum Climate Envelope Generator

import os
import psycopg2
import pandas as pd
import numpy as np

print("Starting Orchid Climate Engine...")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

conn = psycopg2.connect(DATABASE_URL)

print("Connected to database")

query = """
SELECT
    genus,
    decimal_latitude,
    decimal_longitude
FROM oc_occurrences
WHERE decimal_latitude IS NOT NULL
AND decimal_longitude IS NOT NULL
AND genus IS NOT NULL
LIMIT 50000
"""

df = pd.read_sql(query, conn)

print(f"Loaded {len(df)} occurrence records")

# climate approximations

df["temp_estimate"] = 30 - (abs(df["decimal_latitude"]) * 0.4)
df["rainfall_estimate"] = 2000 - (abs(df["decimal_latitude"]) * 15)

df["rainfall_estimate"] = df["rainfall_estimate"].clip(lower=200)
df["temp_estimate"] = df["temp_estimate"].clip(lower=-5)

summary = df.groupby("genus").agg(temp_min=("temp_estimate", "min"),
                                  temp_max=("temp_estimate", "max"),
                                  temp_mean=("temp_estimate", "mean"),
                                  rain_min=("rainfall_estimate", "min"),
                                  rain_max=("rainfall_estimate", "max"),
                                  rain_mean=("rainfall_estimate", "mean"),
                                  observations=("genus",
                                                "count")).reset_index()

summary = summary.round(2)

print(f"Generated climate envelopes for {len(summary)} genera")

output_file = "orchid_climate_profiles.csv"

summary.to_csv(output_file, index=False)

print("")
print("Climate profiles generated successfully")
print(f"Output file: {output_file}")
print("")
print("Orchid Climate Engine complete.")
