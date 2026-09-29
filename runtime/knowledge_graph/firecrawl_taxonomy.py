"""Read existing World Plants source rows and stable species API identities.

This adapter selects an explicitly configured release; it neither activates a
staged release nor allocates taxon identifiers. Ambiguous name joins fail closed.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime

from .canonical_taxonomy import (
    CanonicalRegistry,
    CanonicalTaxon,
    WorldPlantsRelease,
    canonical_name_of,
    is_hybrid,
    rank_of,
)


def load_persistent_canonical_registry(connect, *, snapshot_id: str | None = None):
    snapshot_id = snapshot_id or os.environ.get("FIRECRAWL_TAXONOMY_SNAPSHOT_ID", "")
    if not snapshot_id:
        raise ValueError("PINNED_CANONICAL_TAXONOMY_SNAPSHOT_REQUIRED")
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_jsonb(s) FROM oc_source.source_snapshots s "
            "WHERE s.snapshot_id::text = %s", (snapshot_id,),
        )
        snapshots = [row[0] for row in cursor.fetchall()]
        if len(snapshots) != 1:
            raise ValueError("CANONICAL_TAXONOMY_SNAPSHOT_NOT_UNIQUE")
        source = snapshots[0]
        authority = source.get("source_system", "").lower()
        if not any(token in authority for token in ("world_plants", "worldplants", "hassler")):
            raise ValueError("WORLD_PLANTS_AUTHORITY_REQUIRED")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", source.get("file_sha256") or ""):
            raise ValueError("CANONICAL_TAXONOMY_SOURCE_HASH_REQUIRED")
        # to_jsonb permits source revisions with additional columns without
        # guessing those columns. A missing snapshot association is NOT a match.
        cursor.execute(
            "SELECT to_jsonb(w) FROM oc_source.world_plants_load w "
            "WHERE to_jsonb(w)->>'snapshot_id' = %s", (snapshot_id,),
        )
        source_rows = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT id, scientific_name FROM public.orchid_taxonomy")
        identity_rows = cursor.fetchall()
    if not source_rows:
        raise ValueError("PINNED_WORLD_PLANTS_SOURCE_ROWS_UNAVAILABLE")
    identities = defaultdict(list)
    for ident, name in identity_rows:
        identities[canonical_name_of(name)].append((int(ident), name))
    counts = defaultdict(int)
    for row in source_rows:
        counts[canonical_name_of(row.get("name"))] += 1
    taxa = {}
    index = {}
    for row in source_rows:
        status = str(row.get("taxonomic_status") or row.get("status") or "accepted").lower()
        if status != "accepted" or rank_of(row.get("taxon_code")) == "unknown":
            continue
        scientific_name = row.get("name") or ""
        name = canonical_name_of(scientific_name)
        matches = identities.get(name, [])
        if not name or counts[name] != 1 or len(matches) != 1:
            continue
        ident, _ = matches[0]
        taxa[ident] = CanonicalTaxon(
            canonical_id=ident, scientific_name=scientific_name,
            canonical_name=name, authorship=scientific_name[len(name):].strip() or None,
            rank=rank_of(row.get("taxon_code")), status="accepted",
            is_hybrid=is_hybrid(scientific_name),
            provenance={"authority": "world_plants", "snapshot_id": snapshot_id,
                        "source_table": "oc_source.world_plants_load",
                        "identity_table": "public.orchid_taxonomy",
                        "identity_namespace": "orchid_taxonomy",
                        "file_sha256": source["file_sha256"], "match_method": "unique_exact_name",
                        "source_row_count": len(source_rows)},
        )
        index[name] = ident
    if not taxa:
        raise ValueError("NO_UNAMBIGUOUS_CANONICAL_TAXONOMY_IDENTITIES")
    acquired = source.get("acquired_at_utc") or source.get("acquired_at")
    release = WorldPlantsRelease(
        snapshot_id=snapshot_id, source_system=source["source_system"],
        version_label=source.get("version_label"), file_sha256=source["file_sha256"],
        row_count=len(source_rows), acquired_at=datetime.fromisoformat(acquired) if acquired else None,
        status="canonical", notes=f"Explicitly pinned source; no activation performed; {len(taxa)} of {len(source_rows)} source rows bound to unique persistent identities.",
    )
    return CanonicalRegistry(release, taxa, index)
