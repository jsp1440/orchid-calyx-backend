import os

import folium
import pandas as pd
import psycopg2

_EXACT_ATLAS_ENABLE_VALUE = "YES_I_UNDERSTAND_THIS_EXPORTS_EXACT_ORCHID_LOCATIONS"


def require_exact_atlas_generation() -> None:
    """Require explicit operator acknowledgement before exact-site map export."""

    if os.getenv("OC_ALLOW_EXACT_ORCHID_ATLAS") != _EXACT_ATLAS_ENABLE_VALUE:
        raise PermissionError(
            "Exact orchid atlas generation is disabled by security policy. "
            "Use a generalized/aggregated Atlas product unless exact locality "
            "access is explicitly approved for the research purpose."
        )


def main() -> None:
    require_exact_atlas_generation()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    print("Connecting to Orchid Continuum database...")
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

    print("Loaded", len(df), "occurrence points")
    print("Building restricted exact orchid atlas map...")

    atlas = folium.Map(location=[0, 0], zoom_start=2)
    for _, row in df.iterrows():
        folium.CircleMarker(
            location=[row["decimal_latitude"], row["decimal_longitude"]],
            radius=2,
            color="purple",
            fill=True,
            fill_opacity=0.6,
        ).add_to(atlas)

    outfile = "orchid_atlas_RESTRICTED_EXACT.html"
    atlas.save(outfile)

    print("Restricted exact map created:", outfile)
    print("Do not publish or redistribute without locality-disclosure approval.")


if __name__ == "__main__":
    main()
