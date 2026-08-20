"""Read-only diagnosis and dry-run-by-default repair for two linkage gaps.

``oc_interactions.orchid_interaction_edges.orchid_taxonomy_id`` and
``oc_mycorrhiza.orchid_fungal_associations.orchid_taxonomy_id`` were measured in
DATA-INTEGRATION-REPAIR-001 (docs/DATA-INTEGRATION-REPAIR-001.md): every row that
carries a value in that column resolves correctly into ``public.orchid_taxonomy``
(23 of 23, 2 of 2). Neither table's populated ids are broken. The real gap is
that most rows never had the column filled in at all -- 460 of the 462
mycorrhiza rows carry a null ``orchid_taxonomy_id`` while carrying a
``orchid_scientific_name`` that the Knowledge Graph source registry
(``runtime/knowledge_graph/source_registry.py``) already resolves through a
case-folded name join.

This module builds the deterministic, provenance-preserving resolution that
turns that resolvable name into a candidate ``orchid_taxonomy_id`` -- and
nothing more. It never rewrites a populated id, never touches the partner-side
column (``partner_taxon_id`` / ``fungal_taxon_id``), and never invents a
resolution for a name that does not exactly and uniquely match.

Three rules, matching ``app/readiness/relationship_measurement.py``:

**Fail closed on ambiguity.** A name that normalizes to more than one distinct
``public.orchid_taxonomy`` row is never resolved automatically -- it goes to the
ambiguous queue for a human. This mirrors
``app.trait_genomics.taxon_target_resolver.CanonicalTaxonTargetResolver``, the
resolver this repository already uses for the same canonical table; the
normalization algorithm here is a self-contained copy of that resolver's regex
so this module stays free of its psycopg/pydantic import chain, not an
independent reimplementation of the matching policy.

**Only the orchid-side id column is ever written.** Every function in this
module takes a ``RepairTarget`` naming the exact column that may be set and the
partner column that may never be read for resolution or appear on the write
side of any statement this module builds.

**Nothing here executes a write by default.** ``measure_repair_candidates`` and
``generate_repair_sql`` issue or emit ``SELECT``-only SQL. Only
``apply_repair_plan`` can write, and only when its caller passes ``execute=True``
-- the owner-gated confirmation lives one layer up, in
``scripts/repair_pollinator_mycorrhiza_taxonomy_ids.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.readiness.relationship_measurement import _columns, _safe, _scalar, _table_exists

# A self-contained copy of the regex/normalization policy in
# app.trait_genomics.taxon_target_resolver._normalize_scientific_name. Kept
# local rather than imported so this read-only measurement module does not pull
# in that resolver's psycopg/pydantic dependency chain merely to reuse a regex.
# The matching *policy* -- exact normalized identity, fail closed on ambiguity,
# disambiguate only by an exact stored-text match -- is the thing being reused,
# and it is asserted identical to that resolver's behaviour in
# tests/test_taxonomy_id_repair.py.
_SCIENTIFIC_NAME_RE = re.compile(
    r"^([A-Za-z][A-Za-z-]+)\s+([a-z][a-z-]+)"
    r"(?:\s+(subsp\.|var\.|f\.)\s+([a-z][a-z-]+))?"
)


def _normalize_scientific_name(value: str) -> str | None:
    cleaned = " ".join((value or "").replace("_", " ").split())
    match = _SCIENTIFIC_NAME_RE.match(cleaned)
    if not match:
        return None
    genus, epithet, rank, infra = match.groups()
    normalized = f"{genus[:1].upper()}{genus[1:].lower()} {epithet.lower()}"
    if rank and infra:
        normalized += f" {rank} {infra.lower()}"
    return normalized


def _comparison_text(value: str) -> str:
    return " ".join((value or "").replace("_", " ").split()).casefold()


CANONICAL_TAXONOMY_TABLE = "public.orchid_taxonomy"
CANONICAL_TAXONOMY_ID_COLUMN = "id"
CANONICAL_TAXONOMY_NAME_COLUMN = "scientific_name"


@dataclass(frozen=True)
class RepairTarget:
    domain: str
    table: str
    primary_key: str
    orchid_taxonomy_id_column: str
    orchid_name_column: str
    partner_id_column: str


# The only two tables this module will ever read null candidates from or write
# to. oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache is deliberately
# absent -- it is an HTTP response cache, not a mycorrhizal corpus, exactly as
# documented in relationship_measurement.RELATIONSHIP_SPECS -- and any caller
# asking this module to touch a table outside this tuple is refused before a
# single query runs. See _require_known_target.
REPAIR_TARGETS: tuple[RepairTarget, ...] = (
    RepairTarget(
        domain="pollinators",
        table="oc_interactions.orchid_interaction_edges",
        primary_key="edge_id",
        orchid_taxonomy_id_column="orchid_taxonomy_id",
        orchid_name_column="orchid_scientific_name",
        partner_id_column="partner_taxon_id",
    ),
    RepairTarget(
        domain="mycorrhiza",
        table="oc_mycorrhiza.orchid_fungal_associations",
        primary_key="association_id",
        orchid_taxonomy_id_column="orchid_taxonomy_id",
        orchid_name_column="orchid_scientific_name",
        partner_id_column="fungal_taxon_id",
    ),
)

_ALLOWED_REPAIR_TABLES = frozenset(t.table for t in REPAIR_TARGETS)


def _require_known_target(target: RepairTarget) -> None:
    """Wrong-endpoint protection: refuse anything outside the fixed allowlist.

    Checked before any SQL is built or run, so a caller cannot point this
    module at the mycorrhiza endpoint cache, at the partner-side table, or at
    any other relation by constructing an ad hoc ``RepairTarget``.
    """
    if target.table not in _ALLOWED_REPAIR_TABLES or target not in REPAIR_TARGETS:
        raise ValueError(
            f"Refusing to repair {target.table!r}: not one of the two "
            f"documented repair targets ({sorted(_ALLOWED_REPAIR_TABLES)})."
        )
    if target.orchid_taxonomy_id_column == target.partner_id_column:
        raise ValueError(
            "Refusing to repair: orchid_taxonomy_id_column and "
            "partner_id_column must never be the same column."
        )


def _resolve_scientific_name(cur, orchid_name: str) -> dict[str, Any]:
    """Resolve one orchid scientific name against ``public.orchid_taxonomy``.

    Mirrors ``CanonicalTaxonTargetResolver.resolve``: normalize, then require an
    exact normalized-identity match. Multiple rows sharing that identity are
    disambiguated only by a single exact stored-text match; otherwise the name
    is ambiguous and no id is returned.
    """
    query_name = " ".join((orchid_name or "").split())
    normalized = _normalize_scientific_name(query_name)
    if normalized is None:
        return {
            "status": "invalid",
            "orchid_scientific_name": orchid_name,
            "normalized_name": None,
            "resolved_orchid_taxonomy_id": None,
            "candidates": [],
            "reason": "Not a parseable binomial or supported infraspecific scientific name.",
        }

    idc = _safe(CANONICAL_TAXONOMY_ID_COLUMN)
    namec = _safe(CANONICAL_TAXONOMY_NAME_COLUMN)
    tbl = _safe(CANONICAL_TAXONOMY_TABLE)
    cur.execute(
        f"SELECT {idc}, {namec} FROM {tbl} "
        f"WHERE lower({namec}) LIKE lower(%s) ORDER BY {idc} LIMIT 100",
        (f"{normalized}%",),
    )
    rows = [
        {"id": r[0], "scientific_name": r[1]} if not isinstance(r, dict) else r
        for r in cur.fetchall()
    ]

    matches = [
        row for row in rows
        if _normalize_scientific_name(str(row.get("scientific_name") or "")) == normalized
    ]
    if not matches:
        return {
            "status": "unresolved",
            "orchid_scientific_name": orchid_name,
            "normalized_name": normalized,
            "resolved_orchid_taxonomy_id": None,
            "candidates": [],
            "reason": (
                f"No {CANONICAL_TAXONOMY_TABLE} row has the same normalized "
                "scientific name. No synonym or fuzzy substitution was attempted."
            ),
        }

    if len(matches) > 1:
        query_text = _comparison_text(query_name)
        exact_text_matches = [
            row for row in matches
            if _comparison_text(str(row.get("scientific_name") or "")) == query_text
        ]
        if len(exact_text_matches) == 1:
            selected = exact_text_matches[0]
            return {
                "status": "resolved",
                "orchid_scientific_name": orchid_name,
                "normalized_name": normalized,
                "resolved_orchid_taxonomy_id": selected["id"],
                "candidates": [dict(m) for m in matches],
                "reason": (
                    "Multiple rows share the normalized taxon identity; selected "
                    "the sole row whose stored scientific-name text exactly "
                    "matches the submitted query."
                ),
            }
        return {
            "status": "ambiguous",
            "orchid_scientific_name": orchid_name,
            "normalized_name": normalized,
            "resolved_orchid_taxonomy_id": None,
            "candidates": [dict(m) for m in matches],
            "reason": (
                "Multiple canonical rows share the normalized scientific name "
                "and no unique exact-text row disambiguates the query; explicit "
                "human review is required before this row can be repaired."
            ),
        }

    selected = matches[0]
    return {
        "status": "resolved",
        "orchid_scientific_name": orchid_name,
        "normalized_name": normalized,
        "resolved_orchid_taxonomy_id": selected["id"],
        "candidates": [dict(selected)],
        "reason": "Resolved by exact normalized name against public.orchid_taxonomy.",
    }


def _fetch_null_candidates(cur, target: RepairTarget) -> list[tuple[Any, str]]:
    t = _safe(target.table)
    pk = _safe(target.primary_key)
    idcol = _safe(target.orchid_taxonomy_id_column)
    namecol = _safe(target.orchid_name_column)
    cur.execute(
        f"SELECT {pk}, {namecol} FROM {t} "
        f"WHERE {idcol} IS NULL AND {namecol} IS NOT NULL ORDER BY {pk}"
    )
    return [
        (r[0], r[1]) if not isinstance(r, dict) else (r[pk], r[namecol])
        for r in cur.fetchall()
    ]


def measure_repair_candidates(cur, target: RepairTarget) -> dict[str, Any]:
    """Read-only before/after candidate counts, unresolved and ambiguous queues.

    Issues ``SELECT`` and catalog reads only. Never reads or reports on
    ``target.partner_id_column`` -- the corresponding pollinator/fungal
    taxonomy id is a different relationship and out of scope for this repair.
    """
    _require_known_target(target)

    if not _table_exists(cur, target.table):
        return {
            "domain": target.domain,
            "table": target.table,
            "state": "unavailable",
            "reason": f"{target.table} does not exist.",
        }
    if not _table_exists(cur, CANONICAL_TAXONOMY_TABLE):
        return {
            "domain": target.domain,
            "table": target.table,
            "state": "unavailable",
            "reason": f"{CANONICAL_TAXONOMY_TABLE} does not exist.",
        }

    cols = _columns(cur, target.table)
    required = (target.primary_key, target.orchid_taxonomy_id_column, target.orchid_name_column)
    missing = [c for c in required if c not in cols]
    if missing:
        return {
            "domain": target.domain,
            "table": target.table,
            "state": "unavailable",
            "reason": f"{target.table} is missing required column(s): {missing}.",
        }

    t = _safe(target.table)
    idcol = _safe(target.orchid_taxonomy_id_column)

    total_rows = _scalar(cur, f"SELECT COUNT(*) FROM {t}")
    populated = _scalar(cur, f"SELECT COUNT(*) FROM {t} WHERE {idcol} IS NOT NULL")

    null_candidates = _fetch_null_candidates(cur, target)
    resolved: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    for row_pk, orchid_name in null_candidates:
        outcome = _resolve_scientific_name(cur, orchid_name)
        entry = {
            "table": target.table,
            "row_pk": row_pk,
            **outcome,
        }
        if outcome["status"] == "resolved":
            resolved.append(entry)
        elif outcome["status"] == "ambiguous":
            ambiguous.append(entry)
        elif outcome["status"] == "invalid":
            invalid.append(entry)
        else:
            unresolved.append(entry)

    return {
        "domain": target.domain,
        "table": target.table,
        "state": "measured",
        "before": {
            "total_rows": total_rows,
            "orchid_taxonomy_id_populated": populated,
            "orchid_taxonomy_id_null": total_rows - populated,
        },
        "after_dry_run_projection": {
            "orchid_taxonomy_id_populated": populated + len(resolved),
            "orchid_taxonomy_id_null": total_rows - populated - len(resolved),
        },
        "resolved_candidates": resolved,
        "ambiguous_queue": ambiguous,
        "unresolved_queue": unresolved,
        "invalid_queue": invalid,
        "partner_id_column_never_read_or_written": target.partner_id_column,
    }


def build_repair_plan(measurement: dict[str, Any]) -> dict[str, Any]:
    """Extract the deterministic write plan from a measurement result.

    Only rows whose resolution is unambiguous appear here. Ordered by
    ``row_pk`` so the same measurement always yields the same plan and the
    same generated SQL, byte for byte.
    """
    if measurement.get("state") != "measured":
        return {"table": measurement.get("table"), "actions": []}
    actions = sorted(
        (
            {
                "row_pk": entry["row_pk"],
                "resolved_orchid_taxonomy_id": entry["resolved_orchid_taxonomy_id"],
                "orchid_scientific_name": entry["orchid_scientific_name"],
                "join_method": "canonical_name_normalized_exact",
            }
            for entry in measurement["resolved_candidates"]
        ),
        key=lambda a: a["row_pk"],
    )
    return {"table": measurement["table"], "actions": actions}


def generate_repair_sql(target: RepairTarget, plan: dict[str, Any]) -> str:
    """Render the idempotent repair as reviewable SQL text. Never executes it.

    Every statement is guarded by ``{orchid_taxonomy_id_column} IS NULL``, so
    re-running this exact text after it has already applied touches zero rows
    -- the guard is what makes the migration idempotent, not an external
    bookkeeping table. The generated text never assigns
    ``target.partner_id_column``.
    """
    _require_known_target(target)
    actions = plan.get("actions", [])
    header = (
        f"-- Idempotent dry-run repair for {target.table}.{target.orchid_taxonomy_id_column}\n"
        f"-- {len(actions)} resolved candidate row(s). This is generated SQL for review only;\n"
        "-- it is not executed by generating it. Only the orchid-side taxonomy id\n"
        "-- column above is ever assigned; no other column on this table is touched.\n"
        "-- Safe to re-run: each statement only matches rows still NULL.\n"
    )
    if not actions:
        return header + "-- No resolvable candidates; nothing to do.\n"

    t = _safe(target.table)
    pk = _safe(target.primary_key)
    idcol = _safe(target.orchid_taxonomy_id_column)

    values_rows = ",\n".join(
        f"  ({action['row_pk']!r}, {action['resolved_orchid_taxonomy_id']!r})"
        for action in actions
    )
    body = (
        "BEGIN;\n"
        f"UPDATE {t} AS t\n"
        f"SET {idcol} = v.resolved_orchid_taxonomy_id\n"
        "FROM (VALUES\n"
        f"{values_rows}\n"
        f") AS v(row_pk, resolved_orchid_taxonomy_id)\n"
        f"WHERE t.{pk} = v.row_pk\n"
        f"  AND t.{idcol} IS NULL;\n"
        "COMMIT;\n"
    )
    return header + body


def apply_repair_plan(
    cur, target: RepairTarget, plan: dict[str, Any], *, execute: bool
) -> dict[str, Any]:
    """Apply (or refuse to apply) a repair plan.

    ``execute=False`` (the default posture callers must opt out of) performs no
    write of any kind -- it reports what would happen and returns without
    issuing a single ``UPDATE``. Only ``execute=True`` writes, one row at a
    time, each guarded by the same ``IS NULL`` idempotency check as
    ``generate_repair_sql`` so a partially-applied or re-run plan cannot
    double-write or clobber a row a concurrent process already populated.
    """
    _require_known_target(target)
    actions = plan.get("actions", [])

    if not execute:
        return {
            "status": "dry_run",
            "table": target.table,
            "would_update": len(actions),
        }

    t = _safe(target.table)
    pk = _safe(target.primary_key)
    idcol = _safe(target.orchid_taxonomy_id_column)

    rows_updated = 0
    for action in actions:
        cur.execute(
            f"UPDATE {t} SET {idcol} = %s WHERE {pk} = %s AND {idcol} IS NULL",
            (action["resolved_orchid_taxonomy_id"], action["row_pk"]),
        )
        rows_updated += getattr(cur, "rowcount", 0) or 0

    return {
        "status": "executed",
        "table": target.table,
        "planned": len(actions),
        "rows_updated": rows_updated,
    }
