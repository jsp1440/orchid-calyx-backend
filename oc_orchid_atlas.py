import os

RESTRICTED_ATLAS_OUTPUT = "orchid_atlas_RESTRICTED_EXACT.html"


def require_internal_database_access() -> str:
    """Return the configured DB URL for trusted internal analysis.

    Possession of the server-side database credential is the authorization
    boundary for this local/operator utility. The script is not a public web
    endpoint. Exact coordinates remain available for scientific visualization
    and analysis while public disclosure is controlled elsewhere.
    """

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for internal exact-location analysis")
    return database_url


def main() -> None:
    database_url = require_internal_database_access()

    # Keep visualization dependencies lazy so importing this utility never
    # connects to the database or requires mapping packages.
    import folium
    import pandas as pd
    import psycopg2

    print("Connecting to Orchid Continuum database for internal analysis...")
    conn = psycopg2.connect(database_url)
    try:
        sql = """
        SELECT decimal_latitude, decimal_longitude
        FROM oc_occurrences
        WHERE decimal_latitude IS NOT NULL
          AND decimal_longitude IS NOT NULL
        LIMIT 20000
        """
        df = pd.read_sql(sql, conn)
    finally:
        conn.close()

    print("Loaded", len(df), "exact occurrence points")
    print("Building authenticated/internal exact orchid atlas map...")

    atlas = folium.Map(location=[0, 0], zoom_start=2)
    for _, row in df.iterrows():
        folium.CircleMarker(
            location=[row["decimal_latitude"], row["decimal_longitude"]],
            radius=2,
            color="purple",
            fill=True,
            fill_opacity=0.6,
        ).add_to(atlas)

    atlas.save(RESTRICTED_ATLAS_OUTPUT)
    try:
        os.chmod(RESTRICTED_ATLAS_OUTPUT, 0o600)
    except OSError:
        # Some platforms/filesystems do not implement POSIX file permissions.
        pass

    print("Internal exact map created:", RESTRICTED_ATLAS_OUTPUT)
    print("Exact coordinates remain available for analysis; do not publish the raw file.")


if __name__ == "__main__":
    main()
