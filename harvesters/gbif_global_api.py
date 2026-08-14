from __future__ import annotations

import logging
import time
from typing import Any

import requests

from harvesters import gbif_api

log = logging.getLogger("gbif_global_harvest")

GBIF_OCC_SEARCH = "https://api.gbif.org/v1/occurrence/search"
DEFAULT_FAMILYKEY_ORCHIDACEAE = 7689
SOURCE = "gbif_global_v2"
USER_AGENT = "OrchidContinuum/1.0 (orchid research platform)"
PAGE_SIZE = 300
SEARCH_HARD_LIMIT = 100_000
SLEEP_SECONDS = 0.25


def _ensure_state_table(conn) -> None:
    gbif_api.ensure_state_table(conn)


def _load_state(conn) -> dict[str, int]:
    _ensure_state_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_offset, total_inserted FROM public.oc_harvest_state WHERE source = %s",
            (SOURCE,),
        )
        row = cur.fetchone()
    if not row:
        return {"offset": 0, "total": 0}
    return {"offset": int(row[0]), "total": int(row[1])}


def _save_state(conn, *, offset: int, total_delta: int) -> None:
    _ensure_state_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.oc_harvest_state (source, last_offset, total_inserted)
            VALUES (%s, %s, %s)
            ON CONFLICT (source)
            DO UPDATE SET
              last_offset = EXCLUDED.last_offset,
              total_inserted = public.oc_harvest_state.total_inserted + EXCLUDED.total_inserted,
              updated_at = now()
            """,
            (SOURCE, offset, total_delta),
        )
    conn.commit()


def _fetch_page(
    session: requests.Session,
    *,
    family_key: int,
    offset: int,
    limit: int = PAGE_SIZE,
) -> tuple[list[dict[str, Any]], bool]:
    if offset + limit > SEARCH_HARD_LIMIT:
        return [], True
    response = session.get(
        GBIF_OCC_SEARCH,
        params={
            "familyKey": family_key,
            # Deliberately no mediaType filter. We harvest the global occurrence
            # backbone and extract media opportunistically from records that have it.
            "limit": limit,
            "offset": offset,
        },
        timeout=30,
    )
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        delay = min(30.0, max(2.0, float(retry_after or 5)))
        log.warning("GBIF rate-limited; sleeping %.1fs", delay)
        time.sleep(delay)
        return [], False
    response.raise_for_status()
    payload = response.json()
    records = [item for item in payload.get("results", []) if isinstance(item, dict)]
    return records, bool(payload.get("endOfRecords", False))


def run(
    family_key: int = DEFAULT_FAMILYKEY_ORCHIDACEAE,
    *,
    max_pages: int = 10,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    """Harvest global Orchidaceae occurrences plus any attached media.

    This search-mode worker intentionally stops at GBIF's 100k search ceiling.
    Full historical retrieval beyond that boundary must move to the authenticated
    asynchronous GBIF Download API rather than attempting to evade the limit.
    """

    conn = gbif_api.get_conn()
    try:
        state = _load_state(conn)
        offset = int(state["offset"])
        start_offset = offset
        if offset >= SEARCH_HARD_LIMIT:
            return {
                "occurrences_added": 0,
                "images_added": 0,
                "records_examined": 0,
                "next_offset": offset,
                "pages": 0,
                "end_of_records": False,
                "bulk_download_required": True,
                "reason": "GBIF occurrence/search has a 100000-record hard query limit",
            }

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        started = time.time()
        pages = 0
        total_occ = 0
        total_img = 0
        end = False

        while (
            not end
            and pages < max(1, int(max_pages))
            and (time.time() - started) < max(10.0, float(max_runtime_seconds))
        ):
            remaining = SEARCH_HARD_LIMIT - offset
            if remaining <= 0:
                break
            page_limit = min(PAGE_SIZE, remaining)
            items, end = _fetch_page(
                session,
                family_key=family_key,
                offset=offset,
                limit=page_limit,
            )
            if not items:
                if end:
                    break
                # A transient empty/rate-limited response should not advance the
                # checkpoint; the next cycle can retry safely.
                break

            new_occ = gbif_api.insert_occurrences_if_possible(conn, items)
            new_img = gbif_api.insert_images_if_possible(conn, items)
            total_occ += new_occ
            total_img += new_img
            pages += 1
            offset += len(items)
            log.info(
                "GBIF global offset %s: occurrences +%s, images +%s, page_items=%s",
                offset - len(items),
                new_occ,
                new_img,
                len(items),
            )
            time.sleep(SLEEP_SECONDS)

        _save_state(conn, offset=offset, total_delta=total_occ + total_img)
        bulk_required = offset >= SEARCH_HARD_LIMIT and not end
        return {
            "occurrences_added": total_occ,
            "images_added": total_img,
            "records_examined": max(0, offset - start_offset),
            "next_offset": offset,
            "pages": pages,
            "end_of_records": end,
            "bulk_download_required": bulk_required,
            "reason": (
                "GBIF occurrence/search hard limit reached; authenticated Download API required"
                if bulk_required
                else None
            ),
        }
    finally:
        conn.close()
