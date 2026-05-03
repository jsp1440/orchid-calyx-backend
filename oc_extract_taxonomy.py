import os
import sys

if os.getenv("OC_ALLOW_LEGACY_OC_SCRIPT_RUN") != "YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION":
    print("BLOCKED: This legacy Orchid Continuum/Calyx root-level script is write-capable or schema-stale and is disabled by default.")
    print("This safety guard prevents accidental production database writes.")
    print("To run intentionally, set OC_ALLOW_LEGACY_OC_SCRIPT_RUN=YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION after manual review.")
    sys.exit(2)

import psycopg2
import json

DB = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DB)
cur = conn.cursor()

cur.execute("""
SELECT occurrence_id, raw_json
FROM oc_occurrences
WHERE species_id IS NULL
LIMIT 5000
""")

rows = cur.fetchall()

updates = []

for occ_id, raw in rows:
    if not raw:
        continue

    data = raw

    species = data.get("speciesKey")
    genus = data.get("genusKey")
    country = data.get("countryCode")
    elevation = data.get("elevation")

    updates.append((species, genus, country, elevation, occ_id))

for species, genus, country, elevation, occ_id in updates:
    cur.execute(
        """
        UPDATE oc_occurrences
        SET
            species_id = %s,
            genus_id = %s,
            country = %s,
            elevation_m = %s
        WHERE occurrence_id = %s
    """, (species, genus, country, elevation, occ_id))

conn.commit()

print("Updated", len(updates), "records")

cur.close()
conn.close()
