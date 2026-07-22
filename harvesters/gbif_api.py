import os
import time
import logging
import requests
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gbif_harvest")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is not set")

GBIF_OCC_SEARCH = "https://api.gbif.org/v1/occurrence/search"
DEFAULT_FAMILYKEY_ORCHIDACEAE = 7689

SOURCE = "gbif"  # IMPORTANT: matches what your DB already shows
USER_AGENT = "OrchidContinuum/1.0 (orchid research platform)"

BATCH_SIZE = 500
MAX_RUNTIME_SECONDS = 600
SLEEP_SECONDS = 0.25


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def table_exists(conn, table_name: str, schema: str = "public") -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM information_schema.tables
              WHERE table_schema = %s AND table_name = %s
            )
            """,
            (schema, table_name),
        )
        return bool(cur.fetchone()[0])


def get_columns(conn, table_name: str, schema: str = "public"):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table_name),
        )
        return [r[0] for r in cur.fetchall()]


def ensure_state_table(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.oc_harvest_state (
              source TEXT PRIMARY KEY,
              last_offset INTEGER NOT NULL DEFAULT 0,
              total_inserted BIGINT NOT NULL DEFAULT 0,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
    conn.commit()


def load_state(conn):
    ensure_state_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_offset, total_inserted FROM public.oc_harvest_state WHERE source = %s",
            (SOURCE,),
        )
        row = cur.fetchone()
        if not row:
            return {"offset": 0, "total": 0}
        return {"offset": int(row[0]), "total": int(row[1])}


def save_state(conn, offset: int, total_delta: int):
    ensure_state_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.oc_harvest_state (source, last_offset, total_inserted)
            VALUES (%s, %s, %s)
            ON CONFLICT (source)
            DO UPDATE SET
              last_offset = EXCLUDED.last_offset,
              total_inserted = public.oc_harvest_state.total_inserted + EXCLUDED.total_inserted,
              updated_at = now();
            """,
            (SOURCE, offset, total_delta),
        )
    conn.commit()


def fetch_gbif_page(session: requests.Session, family_key: int, offset: int, limit: int):
    params = {
        "familyKey": family_key,
        "mediaType": "StillImage",
        "limit": limit,
        "offset": offset,
    }
    resp = session.get(GBIF_OCC_SEARCH, params=params, timeout=30)

    if resp.status_code == 429:
        logger.warning("GBIF rate-limited (429). Sleeping 5 seconds.")
        time.sleep(5)
        return [], False

    resp.raise_for_status()
    data = resp.json()
    return data.get("results", []), bool(data.get("endOfRecords", False))


def normalize_species(scientific_name: str, species_field: str):
    if species_field:
        return species_field
    if scientific_name and " " in scientific_name:
        parts = scientific_name.split()
        if len(parts) >= 2:
            return parts[1]
    return ""


def insert_occurrences_if_possible(conn, gbif_items):
    """
    Inserts minimal Tier 1 index into public.occurrences if that table exists.
    Expected columns (based on your screenshot): source, source_id, scientific_name, genus, species, taxon_rank
    """
    if not table_exists(conn, "occurrences"):
        return 0

    cols = set(get_columns(conn, "occurrences"))
    needed = {"source", "source_id", "scientific_name", "genus", "species"}
    if not needed.issubset(cols):
        logger.warning(f"public.occurrences exists but missing required columns. Has: {sorted(cols)}")
        return 0

    # taxon_rank is optional
    use_taxon_rank = "taxon_rank" in cols

    rows = []
    for item in gbif_items:
        gbif_key = item.get("key")
        if gbif_key is None:
            continue

        scientific_name = item.get("scientificName", "") or ""
        genus = item.get("genus", "") or ""
        species = normalize_species(scientific_name, item.get("species", "") or "")
        taxon_rank = item.get("taxonRank", "") or ""

        if use_taxon_rank:
            rows.append((SOURCE, str(gbif_key), scientific_name, genus, species, taxon_rank))
        else:
            rows.append((SOURCE, str(gbif_key), scientific_name, genus, species))

    if not rows:
        return 0

    with conn.cursor() as cur:
        if use_taxon_rank:
            sql = """
                INSERT INTO public.occurrences (source, source_id, scientific_name, genus, species, taxon_rank)
                VALUES %s
                ON CONFLICT DO NOTHING
            """
        else:
            sql = """
                INSERT INTO public.occurrences (source, source_id, scientific_name, genus, species)
                VALUES %s
                ON CONFLICT DO NOTHING
            """
        execute_values(cur, sql, rows, page_size=1000)

        # rowcount can be unreliable with execute_values + ON CONFLICT; still useful as a rough indicator
        inserted = cur.rowcount

    conn.commit()
    return max(inserted, 0)


def insert_images_if_possible(conn, gbif_items):
    """
    Inserts image URLs into public.images if table exists AND has url/source columns.
    Only inserts first still-image identifier per GBIF record.
    """
    if not table_exists(conn, "images"):
        return 0

    cols = set(get_columns(conn, "images"))
    if "url" not in cols or "source" not in cols:
        logger.warning(f"public.images exists but missing url/source columns. Has: {sorted(cols)}")
        return 0

    # Build a row dict and only include columns that exist
    possible_fields = [
        ("source", lambda r: SOURCE),
        ("url", lambda r: r["url"]),
        ("genus", lambda r: r.get("genus", "")),
        ("species", lambda r: r.get("species", "")),
        ("scientific_name", lambda r: r.get("scientific_name", "")),
        ("country", lambda r: r.get("country", "")),
        ("latitude", lambda r: r.get("latitude")),
        ("longitude", lambda r: r.get("longitude")),
        ("photographer", lambda r: r.get("photographer", "")),
        ("license", lambda r: r.get("license", "")),
        ("source_id", lambda r: r.get("source_id", "")),
        ("gbif_occurrence_id", lambda r: r.get("gbif_occurrence_id")),
    ]

    active_fields = [(name, fn) for (name, fn) in possible_fields if name in cols]
    active_colnames = [name for name, _ in active_fields]

    prepared = []
    for item in gbif_items:
        media = item.get("media") or []
        if not media:
            continue

        image_url = media[0].get("identifier")
        if not image_url:
            continue

        gbif_key = item.get("key")
        scientific_name = item.get("scientificName", "") or ""
        genus = item.get("genus", "") or ""
        species = normalize_species(scientific_name, item.get("species", "") or "")

        rec = {
            "url": image_url,
            "genus": genus,
            "species": species,
            "scientific_name": scientific_name,
            "country": item.get("country", "") or "",
            "latitude": item.get("decimalLatitude"),
            "longitude": item.get("decimalLongitude"),
            "photographer": item.get("recordedBy", "") or "",
            "license": item.get("license", "") or "",
            "source_id": str(gbif_key) if gbif_key is not None else "",
            "gbif_occurrence_id": gbif_key,
        }

        prepared.append(tuple(fn(rec) for _, fn in active_fields))

    if not prepared:
        return 0

    placeholders_cols = ", ".join(active_colnames)
    sql = f"""
        INSERT INTO public.images ({placeholders_cols})
        VALUES %s
        ON CONFLICT DO NOTHING
    """

    with conn.cursor() as cur:
        execute_values(cur, sql, prepared, page_size=1000)
        inserted = cur.rowcount

    conn.commit()
    return max(inserted, 0)


def run(family_key: int = DEFAULT_FAMILYKEY_ORCHIDACEAE):
    conn = get_conn()
    try:
        state = load_state(conn)
        offset = state["offset"]

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        logger.info(f"Starting GBIF harvest: familyKey={family_key}, offset={offset}, batch={BATCH_SIZE}")

        start_time = time.time()
        total_new_occ = 0
        total_new_img = 0
        end = False

        while not end and (time.time() - start_time) < MAX_RUNTIME_SECONDS:
            items, end = fetch_gbif_page(session, family_key, offset, BATCH_SIZE)

            if not items:
                logger.info(f"GBIF offset {offset}: no items returned")
                offset += BATCH_SIZE
                time.sleep(SLEEP_SECONDS)
                continue

            new_occ = insert_occurrences_if_possible(conn, items)
            new_img = insert_images_if_possible(conn, items)

            total_new_occ += new_occ
            total_new_img += new_img

            logger.info(
                f"GBIF offset {offset}: occurrences +{new_occ}, images +{new_img}, page_items={len(items)}"
            )

            offset += BATCH_SIZE
            time.sleep(SLEEP_SECONDS)

        # Save the NEXT offset to continue from
        save_state(conn, offset=offset, total_delta=(total_new_occ + total_new_img))

        elapsed = time.time() - start_time
        logger.info(
            f"GBIF done in {elapsed:.1f}s. Added occurrences={total_new_occ}, images={total_new_img}. Next offset={offset}"
        )

        return {"occurrences_added": total_new_occ, "images_added": total_new_img, "next_offset": offset}

    finally:
        conn.close()


if __name__ == "__main__":
    run()