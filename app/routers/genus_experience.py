from __future__ import annotations

import os
import re
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/genus-experience", tags=["genus-experience"])
DATABASE_URL = os.environ.get("DATABASE_URL")

URL_COLUMNS = ["image_url", "media_url", "url", "public_url", "thumbnail_url", "medium_url", "original_url", "photo_url"]
NAME_COLUMNS = ["scientific_name", "canonical_name", "accepted_name", "taxon_name", "species", "name"]
BAD_IMAGE_WORDS = ["herbari", "specimen", "voucher", "barcode", "jstor", "sheet", "plate", "illustration", "drawing", "lineart", ".pdf", ".tif", ".tiff"]


def require_database_url() -> str:
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not configured")
    return DATABASE_URL


def ident(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise ValueError("unsafe identifier")
    return '"' + value + '"'


def table_exists(cur, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (table,))
    return cur.fetchone()[0] is not None


def columns_for(cur, table: str) -> set[str]:
    schema, name = (table.split(".", 1) if "." in table else ["public", table])
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
        (schema, name),
    )
    return {row[0] for row in cur.fetchall()}


def first(cols: set[str], names: list[str]) -> str | None:
    for name in names:
        if name in cols:
            return name
    return None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def canonical(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    parts = text.split()
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0].capitalize()
    return f"{parts[0].capitalize()} {parts[1].lower()}"


def living_url(value: Any, *metadata: Any) -> str | None:
    url = clean_text(value)
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    haystack = " ".join([url, *[str(x) for x in metadata if x is not None]]).lower()
    if any(word in haystack for word in BAD_IMAGE_WORDS):
        return None
    return url


def species_rows(cur, genus: str, limit: int) -> list[dict[str, Any]]:
    if not table_exists(cur, "public.taxonomy_species"):
        return []
    cols = columns_for(cur, "public.taxonomy_species")
    name_col = first(cols, NAME_COLUMNS)
    genus_col = first(cols, ["genus", "genus_name"])
    status_col = first(cols, ["status", "taxonomic_status", "accepted_status"])
    if not name_col:
        return []
    where = f"{ident(name_col)} ILIKE %s"
    params: list[Any] = [f"{genus} %"]
    if genus_col:
        where = f"({ident(genus_col)} ILIKE %s OR {ident(name_col)} ILIKE %s)"
        params = [genus, f"{genus} %"]
    status_sql = f", {ident(status_col)} AS status" if status_col else ", NULL::text AS status"
    cur.execute(
        f"SELECT DISTINCT {ident(name_col)} AS scientific_name {status_sql} FROM public.taxonomy_species WHERE {where} ORDER BY scientific_name LIMIT %s",
        (*params, limit),
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, status in cur.fetchall():
        sci = canonical(name)
        if not sci or sci.lower() in seen:
            continue
        seen.add(sci.lower())
        out.append({"scientific_name": sci, "taxonomic_status": clean_text(status)})
    return out


def image_rows(cur, table: str, genus: str, limit: int) -> list[dict[str, Any]]:
    if not table_exists(cur, table):
        return []
    cols = columns_for(cur, table)
    name_col = first(cols, NAME_COLUMNS)
    url_col = first(cols, URL_COLUMNS)
    source_col = first(cols, ["image_source", "source", "provider", "publisher", "credit", "photographer"])
    license_col = first(cols, ["image_license", "license", "rights"])
    if not name_col or not url_col:
        return []
    source_sql = f", {ident(source_col)} AS image_source" if source_col else ", NULL::text AS image_source"
    license_sql = f", {ident(license_col)} AS image_license" if license_col else ", NULL::text AS image_license"
    cur.execute(
        f"SELECT {ident(name_col)} AS scientific_name, {ident(url_col)} AS image_url {source_sql} {license_sql} FROM {table} WHERE {ident(name_col)} ILIKE %s AND {ident(url_col)} IS NOT NULL LIMIT %s",
        (f"{genus} %", max(limit * 4, 24)),
    )
    out: list[dict[str, Any]] = []
    seen_species: set[str] = set()
    seen_urls: set[str] = set()
    for name, url, source, license_value in cur.fetchall():
        sci = canonical(name)
        img_url = living_url(url, source, license_value)
        if not sci or not img_url or sci.lower() in seen_species or img_url in seen_urls:
            continue
        seen_species.add(sci.lower())
        seen_urls.add(img_url)
        out.append({
            "scientific_name": sci,
            "image_url": img_url,
            "image_urls": [img_url],
            "image_source": clean_text(source) or "Orchid Continuum image database",
            "image_license": clean_text(license_value),
        })
        if len(out) >= limit:
            break
    return out


def count_table(cur, table: str, genus: str, candidate_cols: list[str]) -> int:
    try:
        if not table_exists(cur, table):
            return 0
        cols = columns_for(cur, table)
        col = first(cols, candidate_cols)
        if not col:
            return 0
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {ident(col)} ILIKE %s", (f"{genus} %",))
        return int(cur.fetchone()[0] or 0)
    except Exception:
        return 0


def get_habitats(cur, genus: str, limit: int = 8) -> list[str]:
    table = "public.oc_species_habitat_claims"
    if not table_exists(cur, table):
        return []
    cols = columns_for(cur, table)
    name_col = first(cols, NAME_COLUMNS)
    value_col = first(cols, ["habitat", "habitat_type", "claim", "description"])
    if not name_col or not value_col:
        return []
    cur.execute(
        f"SELECT DISTINCT {ident(value_col)} FROM {table} WHERE {ident(name_col)} ILIKE %s AND {ident(value_col)} IS NOT NULL LIMIT %s",
        (f"{genus} %", limit),
    )
    return [x for (x,) in cur.fetchall() if clean_text(x)]


@router.get("/{genus}")
def genus_experience(genus: str, limit: int = Query(24, ge=1, le=100)) -> dict[str, Any]:
    clean_genus = genus.strip().capitalize()
    if not re.fullmatch(r"[A-Za-z][A-Za-z-]*", clean_genus):
        raise HTTPException(status_code=400, detail="Invalid genus")

    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            species = species_rows(cur, clean_genus, max(limit, 24))
            images = image_rows(cur, "public.orchid_images", clean_genus, limit)
            if not images:
                images = image_rows(cur, "public.oc_eol_orchid_images", clean_genus, limit)

            by_name = {item["scientific_name"].lower(): item for item in species}
            for img in images:
                by_name.setdefault(img["scientific_name"].lower(), {"scientific_name": img["scientific_name"]})
                by_name[img["scientific_name"].lower()]["image"] = img

            summary = {
                "occurrences": count_table(cur, "public.oc_occurrences", clean_genus, NAME_COLUMNS),
                "pollinator_records": count_table(cur, "public.advanced_orchid_pollinator_relationships", clean_genus, ["orchid_species", "scientific_name", "orchid_name", "species"]),
                "mycorrhizal_records": count_table(cur, "public.orchid_fungus_associations", clean_genus, ["orchid_species", "scientific_name", "orchid_name", "species"]),
                "habitat_claims": count_table(cur, "public.oc_species_habitat_claims", clean_genus, NAME_COLUMNS),
                "climate_profiles": count_table(cur, "public.species_climate_profile_monthly", clean_genus, NAME_COLUMNS),
            }
            habitats = get_habitats(cur, clean_genus)

    return {
        "genus": clean_genus,
        "source": "Orchid Continuum database only",
        "uses_inaturalist": False,
        "species_count_returned": len(by_name),
        "image_count_returned": len(images),
        "species": list(by_name.values())[: max(limit, 24)],
        "images": images,
        "relationship_summary": summary,
        "relationship_data": {
            "habitat": {"available_records": summary["habitat_claims"], "examples": habitats},
            "pollinators": {"available_records": summary["pollinator_records"]},
            "mycorrhiza": {"available_records": summary["mycorrhizal_records"]},
            "climate": {"available_records": summary["climate_profiles"]},
            "occurrences": {"available_records": summary["occurrences"]},
        },
    }
