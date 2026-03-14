import os
import psycopg2
import pandas as pd
import folium

DB = os.getenv("DATABASE_URL")

print("Connecting to Orchid Continuum database...")

conn = psycopg2.connect(DB)

sql = """
SELECT decimal_latitude, decimal_longitude
FROM oc_occurrences
WHERE decimal_latitude IS NOT NULL
AND decimal_longitude IS NOT NULL
LIMIT 20000
"""

df = pd.read_sql(sql, conn)

conn.close()

print("Loaded", len(df), "occurrence points")

print("Building orchid atlas map...")

m = folium.Map(location=[0, 0], zoom_start=2)

for _, row in df.iterrows():
    folium.CircleMarker(
        location=[row["decimal_latitude"], row["decimal_longitude"]],
        radius=2,
        color="purple",
        fill=True,
        fill_opacity=0.6).add_to(m)

outfile = "orchid_atlas.html"

m.save(outfile)

print("Map created:", outfile)
print("Open this file in your browser.")
