# harvesters/inat.py
#!/usr/bin/env python3
"""
iNaturalist Orchidaceae harvester (cursor-based).

Uses public.oc_harvest_state.last_offset as the cursor:
- last_offset == last iNat observation id harvested (id_above)
"""

import os
import time
import logging
from typing import Dict, Any, List, Tuple, Optional

import psycopg2
import requests

from harvesters.state_helper import get_state, save_state

DATABASE_URL = os.environ.get("DATABASE_URL")

INAT_API = "https://api.inaturalist.org/v1/observations"
ORCHIDACEAE_TAXON_ID = 47217
SOURCE_KEY = "inaturalist"

# Be a good citizen + reduce 403 headaches
USER_AGENT = os.environ.get(
    "INAT_USER_AGENT",
    "OrchidContinuumHarvester/1.0 (contact: fcos.org; platform: replit)")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("inat_harvester")


def _db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in environment.")
    return psycopg2.connect(DATABASE_URL)


def fetch_batch(
        id_above: int,
        per_page: int = 200) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """
    Fetch one batch using id_above cursor. Returns:
      - list of processed image records
      - next_cursor (max observation id seen) or None if no results
    """
    params = {
        "quality_grade": "research",
        "taxon_id": ORCHIDACEAE_TAXON_ID,
        "photos": "true",
        "order": "asc",
        "order_by": "id",
        "per_page": per_page,
        "id_above": id_above,
    }

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    r = requests.get(INAT_API, params=params, headers=headers, timeout=60)

    # If iNat ever rate-limits or blocks, show *exactly* why.
    if r.status_code != 200:
        raise RuntimeError(f"iNat API error {r.status_code}: {r.text[:300]}")

    data = r.json()
    results = data.get("results", [])
    if not results:
        return [], None

    next_cursor = max(
        int(o.get("id", 0)) for o in results if o.get("id") is not None)

    out: List[Dict[str, Any]] = []
    for obs in results:
        taxon = obs.get("taxon") or {}
        name = (taxon.get("name") or "").strip()

        genus = ""
        species = ""
        if name and " " in name:
            parts = name.split()
            genus = parts[0]
            species = parts[1] if len(parts) > 1 else ""

        # Coordinates (may be missing for obscured observations)
        geojson = obs.get("geojson") or {}
        coords = geojson.get("coordinates") or []
        lon = coords[0] if len(coords) >= 2 else None
        lat = coords[1] if len(coords) >= 2 else None

        place_guess = obs.get("place_guess") or None
        if place_guess:
            place_guess = place_guess[:100]

        photos = obs.get("photos") or []
        if not photos:
            continue

        obs_id = str(obs.get("id", ""))

        # Save up to 2 photos per observation (you can raise this later)
        for photo in photos[:2]:
            url = photo.get("url") or ""
            if not url:
                continue

            # Upgrade size
            image_url = url.replace("square", "large")

            out.append({
                "source": SOURCE_KEY,
                "url": image_url,
                "genus": genus,
                "species": species,
                "scientific_name": name or None,
                "country": place_guess,
                "latitude": lat,
                "longitude": lon,
                "photographer": (photo.get("attribution") or "")[:255],
                "license": (photo.get("license_code") or "")[:50],
                "source_id": obs_id,
            })

    return out, next_cursor


def insert_images(records: List[Dict[str, Any]]) -> int:
    if not records:
        return 0

    inserted = 0
    sql = """
    INSERT INTO images
      (source, url, genus, species, scientific_name, country, latitude, longitude, photographer, license, source_id)
    VALUES
      (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (url) DO NOTHING
    """

    with _db_conn() as conn:
        with conn.cursor() as cur:
            for rec in records:
                cur.execute(
                    sql,
                    (rec["source"], rec["url"], rec["genus"], rec["species"],
                     rec["scientific_name"], rec["country"], rec["latitude"],
                     rec["longitude"], rec["photographer"], rec["license"],
                     rec["source_id"]))
                if cur.rowcount > 0:
                    inserted += 1
        conn.commit()

    return inserted


def harvest_images(limit_batches: int = 1,
                   per_page: int = 200,
                   sleep_s: float = 1.2) -> Dict[str, Any]:
    """
    Harvest iNat images using cursor stored in oc_harvest_state.last_offset.
    limit_batches = how many API batches to pull this run (NOT a lifetime limit).
    """
    state = get_state(SOURCE_KEY)
    cursor = int(state.get("last_offset", 0))

    log.info(
        f"Starting iNat harvest. Cursor(last_offset/id_above)={cursor}. batches={limit_batches}, per_page={per_page}"
    )

    total_new = 0
    batches_done = 0

    while batches_done < limit_batches:
        log.info(
            f"Fetching batch {batches_done + 1}/{limit_batches} with id_above={cursor} ..."
        )

        records, next_cursor = fetch_batch(cursor, per_page=per_page)

        if next_cursor is None:
            log.info("No results returned. Harvest complete for now.")
            break

        new_count = insert_images(records)
        total_new += new_count

        # Advance cursor regardless of insert count to avoid getting stuck on duplicates
        cursor = int(next_cursor)
        save_state(SOURCE_KEY, last_offset=cursor, increment_total=new_count)

        log.info(
            f"Batch {batches_done + 1}: fetched_records={len(records)}, inserted_new={new_count}, new_cursor={cursor}"
        )

        batches_done += 1
        time.sleep(sleep_s)

    log.info(f"Done. Total NEW inserted this run: {total_new}")
    return {"images": total_new, "batches": batches_done, "cursor": cursor}


def harvest_all(limit: int = 1) -> Dict[str, Any]:
    # Orchestrator entry point
    return harvest_images(limit_batches=limit)


if __name__ == "__main__":
    # Default: 1 batch if run directly
    harvest_images(limit_batches=int(os.environ.get("INAT_BATCHES", "1")))
