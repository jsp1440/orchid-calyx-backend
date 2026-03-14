import os
import psycopg2

print("\n==============================")
print("ORCHID CONTINUUM SYSTEM CHECK")
print("==============================\n")

DB = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DB)
cur = conn.cursor()


def run(label, sql):
    print(f"\n--- {label} ---")
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        for r in rows:
            print(r)
    except Exception as e:
        print("ERROR:", e)
        conn.rollback()


# ------------------------------
# OCCURRENCES
# ------------------------------

run("Total Occurrence Records", """
SELECT count(*) FROM oc_occurrence_records;
""")

run("Distinct Species", """
SELECT count(DISTINCT species) FROM oc_occurrence_records;
""")

run("Distinct Genera", """
SELECT count(DISTINCT genus) FROM oc_occurrence_records;
""")

# ------------------------------
# IMAGES
# ------------------------------

run("Total Images", """
SELECT count(*) FROM oc_images;
""")

run("Images Linked To Taxa", """
SELECT count(*) 
FROM oc_images
WHERE taxon_id IS NOT NULL;
""")

run("Images Missing Taxonomy", """
SELECT count(*) 
FROM oc_images
WHERE taxon_id IS NULL;
""")

run(
    "Images By Source", """
SELECT source, count(*)
FROM oc_images
GROUP BY source
ORDER BY count(*) DESC;
""")

# ------------------------------
# TAXONOMY
# ------------------------------

run("Total Species In Taxonomy", """
SELECT count(*) 
FROM oc_taxa
WHERE rank='species';
""")

run("Total Genera", """
SELECT count(*) 
FROM oc_taxa
WHERE rank='genus';
""")

run(
    "Unresolved Taxa", """
SELECT count(*) 
FROM oc_taxa
WHERE accepted_id IS NULL
AND rank='species';
""")

# ------------------------------
# ATLAS GRID
# ------------------------------

run("Atlas Cells", """
SELECT count(*) FROM oc_atlas_cells;
""")

run("Atlas Cells With Records", """
SELECT count(DISTINCT cell_id)
FROM oc_occurrence_records;
""")

# ------------------------------
# ELEVATION DATA
# ------------------------------

run(
    "Records With Elevation", """
SELECT count(*) 
FROM oc_occurrence_records
WHERE elevation_m IS NOT NULL;
""")

run(
    "Elevation Range", """
SELECT min(elevation_m), max(elevation_m)
FROM oc_occurrence_records
WHERE elevation_m IS NOT NULL;
""")

# ------------------------------
# TRAITS
# ------------------------------

run("Trait Records", """
SELECT count(*) FROM oc_traits;
""")

run("Traits Linked To Taxa", """
SELECT count(*)
FROM oc_traits
WHERE taxon_id IS NOT NULL;
""")

# ------------------------------
# HARVESTERS
# ------------------------------

run("Registered Harvesters", """
SELECT name,status
FROM oc_harvesters;
""")

run(
    "Last Harvester Runs", """
SELECT harvester_name,
max(run_time)
FROM oc_harvester_runs
GROUP BY harvester_name;
""")

# ------------------------------
# MEDIA INTEGRITY
# ------------------------------

run("Images Without Files", """
SELECT count(*)
FROM oc_images
WHERE file_path IS NULL;
""")

run(
    "Duplicate Images", """
SELECT url,count(*)
FROM oc_images
GROUP BY url
HAVING count(*) > 1
LIMIT 20;
""")

print("\n==============================")
print("SYSTEM CHECK COMPLETE")
print("==============================\n")

cur.close()
conn.close()
