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

Every resolution -- including the ones that deliberately resolve to nothing --
is emitted as a provenance record by ``build_provenance_mapping``, so the
mapping handed to a human reviewer states where each candidate id came from,
which policy produced it, what the alternatives were, and which column was
never touched.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any

from app.readiness.relationship_measurement import _columns, _safe, _scalar, _table_exists

# Identifies the resolution policy that produced a mapping row. Bump this when
# the matching rules change, so an old mapping artifact can never be silently
# mistaken for one produced under the current policy.
REPAIR_PACKAGE = "DATA-INTEGRATION-REPAIR-002"
RESOLUTION_POLICY = "canonical-orchid-taxonomy-normalized-exact/v1"

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

# Postgres base type names are lower-case identifiers (uuid, int8, text,
# varchar). Anything else -- an array type, a quoted or schema-qualified type,
# a value that did not come from the catalog -- is refused rather than
# interpolated into generated SQL.
_SAFE_TYPE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

MATCH_METHOD_EXACT = "canonical_name_normalized_exact"
MATCH_METHOD_EXACT_TEXT_DISAMBIGUATED = "canonical_name_normalized_exact_text_disambiguated"
MATCH_METHOD_NONE = "none"


def _sql_text_literal(value: Any) -> str:
    """Render one value as a quoted Postgres string literal.

    Deliberately *not* ``repr()``. ``repr()`` of a ``uuid.UUID`` -- the likely
    type of ``edge_id``/``association_id`` -- is ``UUID('...')``, which is not
    SQL at all, and ``repr()`` of a name containing an apostrophe produces a
    double-quoted string, which Postgres reads as an *identifier*. Both would
    yield generated migration text that fails or means something other than it
    reads as. Every value is rendered the same way here, as text, and the
    caller casts it to the column's real type.
    """
    if value is None:
        raise ValueError("Refusing to render NULL as a repair literal.")
    text = str(value)
    if "\x00" in text:
        raise ValueError("Refusing to render a value containing a NUL byte.")
    escaped = text.replace("'", "''")
    return f"'{escaped}'"


def _cast_suffix(type_name: str | None) -> str:
    """``'::uuid'`` for a catalog type we can vouch for, ``''`` otherwise."""
    if type_name and _SAFE_TYPE_NAME.fullmatch(type_name):
        return f"::{type_name}"
    return ""


def _column_udt_types(cur, table_name: str) -> dict[str, str]:
    """Base type name per column, read from the catalog. Read-only."""
    schema, _, table = table_name.partition(".")
    if not table:
        schema, table = "public", schema
    cur.execute(
        """
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    types: dict[str, str] = {}
    for row in cur.fetchall():
        if isinstance(row, dict):
            name, udt = row["column_name"], row["udt_name"]
        else:
            name, udt = row[0], row[1]
        types[str(name)] = str(udt) if udt is not None else ""
    return types


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
            "match_method": MATCH_METHOD_NONE,
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
            "match_method": MATCH_METHOD_NONE,
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
                "match_method": MATCH_METHOD_EXACT_TEXT_DISAMBIGUATED,
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
            "match_method": MATCH_METHOD_NONE,
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
        "match_method": MATCH_METHOD_EXACT,
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

    column_types = _column_udt_types(cur, target.table)

    null_candidates = _fetch_null_candidates(cur, target)
    resolved: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    # One canonical lookup per *distinct* name rather than per row. The two
    # targets repeat the same orchid across many rows (462 mycorrhiza
    # associations span 218 taxa per DATA-INTEGRATION-REPAIR-001), and this
    # measurement runs against production, so the duplicate reads are worth
    # not issuing. Resolution depends only on the name, so the cached outcome
    # is identical to the one a repeat query would have produced.
    resolution_cache: dict[str, dict[str, Any]] = {}

    for row_pk, orchid_name in null_candidates:
        cache_key = " ".join((orchid_name or "").split())
        outcome = resolution_cache.get(cache_key)
        if outcome is None:
            outcome = _resolve_scientific_name(cur, orchid_name)
            resolution_cache[cache_key] = outcome
        entry = {
            "table": target.table,
            "row_pk": row_pk,
            **outcome,
            # The cache is keyed on the whitespace-collapsed name, so a cached
            # outcome may carry a sibling row's raw text. Provenance records
            # this row's own stored value.
            "orchid_scientific_name": orchid_name,
            "candidates": [dict(c) for c in outcome["candidates"]],
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
        "repair_package": REPAIR_PACKAGE,
        "resolution_policy": RESOLUTION_POLICY,
        "canonical_table": CANONICAL_TAXONOMY_TABLE,
        "column_types": {
            target.primary_key: column_types.get(target.primary_key, ""),
            target.orchid_taxonomy_id_column: column_types.get(
                target.orchid_taxonomy_id_column, ""
            ),
        },
        "canonical_lookups": {
            "null_rows_examined": len(null_candidates),
            "distinct_names_resolved": len(resolution_cache),
        },
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
        return {"table": measurement.get("table"), "actions": [], "column_types": {}}
    actions = sorted(
        (
            {
                "row_pk": entry["row_pk"],
                "resolved_orchid_taxonomy_id": entry["resolved_orchid_taxonomy_id"],
                "orchid_scientific_name": entry["orchid_scientific_name"],
                "join_method": entry.get("match_method", MATCH_METHOD_EXACT),
                # The canonical rows this id was chosen from. Carried on the
                # action so apply_repair_plan can verify, at the write
                # boundary, that the id it is about to write really came out
                # of public.orchid_taxonomy for this row -- a hand-edited or
                # otherwise substituted plan cannot smuggle a partner-side
                # taxon id into the orchid column.
                "canonical_source": CANONICAL_TAXONOMY_TABLE,
                "resolved_from_candidates": [c["id"] for c in entry.get("candidates", [])],
            }
            for entry in measurement["resolved_candidates"]
        ),
        key=lambda a: str(a["row_pk"]),
    )
    return {
        "table": measurement["table"],
        "actions": actions,
        "column_types": dict(measurement.get("column_types") or {}),
    }


# Column order of the provenance mapping artifact. Fixed and explicit so a
# reviewer diffing two runs sees only real changes, never a reordered header.
MAPPING_FIELDS: tuple[str, ...] = (
    "repair_package",
    "resolution_policy",
    "domain",
    "source_table",
    "source_row_pk",
    "source_name_column",
    "source_scientific_name",
    "normalized_scientific_name",
    "source_id_column",
    "prior_orchid_taxonomy_id",
    "prior_state",
    "canonical_table",
    "canonical_id_column",
    "canonical_name_column",
    "resolution_status",
    "match_method",
    "resolved_orchid_taxonomy_id",
    "candidate_count",
    "candidate_ids",
    "action",
    "partner_id_column",
    "partner_id_column_written",
    "reason",
)

_ACTION_BY_STATUS = {
    "resolved": "write_candidate",
    "ambiguous": "human_review",
    "unresolved": "no_action",
    "invalid": "no_action",
}


def build_provenance_mapping(target: RepairTarget, measurement: dict[str, Any]) -> list[dict[str, Any]]:
    """Every candidate row's resolution, including the ones resolving to nothing.

    This is the provenance-preserving mapping output: for each null-id row it
    records the stored name, the normalized form the policy derived, the
    canonical relation and columns consulted, every candidate that relation
    offered, which one was selected and by which rule, and the fact that the
    partner-side column was not written. Rows that fail closed -- ambiguous,
    unresolved, unparseable -- appear here too, with their reason, so the
    artifact is a complete account of the measurement rather than only the
    writable subset of it. Unavailable is never rendered as an empty mapping:
    an unmeasured target returns no rows at all and the caller reports the
    ``unavailable`` state from the measurement.
    """
    _require_known_target(target)
    if measurement.get("state") != "measured":
        return []

    records: list[dict[str, Any]] = []
    for queue in ("resolved_candidates", "ambiguous_queue", "unresolved_queue", "invalid_queue"):
        for entry in measurement.get(queue, []):
            candidates = entry.get("candidates") or []
            records.append(
                {
                    "repair_package": REPAIR_PACKAGE,
                    "resolution_policy": RESOLUTION_POLICY,
                    "domain": target.domain,
                    "source_table": target.table,
                    "source_row_pk": entry["row_pk"],
                    "source_name_column": target.orchid_name_column,
                    "source_scientific_name": entry["orchid_scientific_name"],
                    "normalized_scientific_name": entry["normalized_name"],
                    "source_id_column": target.orchid_taxonomy_id_column,
                    # Candidates are drawn exclusively from rows where the id
                    # is NULL, so the pre-state is known, not merely absent.
                    "prior_orchid_taxonomy_id": None,
                    "prior_state": "null",
                    "canonical_table": CANONICAL_TAXONOMY_TABLE,
                    "canonical_id_column": CANONICAL_TAXONOMY_ID_COLUMN,
                    "canonical_name_column": CANONICAL_TAXONOMY_NAME_COLUMN,
                    "resolution_status": entry["status"],
                    "match_method": entry.get("match_method", MATCH_METHOD_NONE),
                    "resolved_orchid_taxonomy_id": entry["resolved_orchid_taxonomy_id"],
                    "candidate_count": len(candidates),
                    "candidate_ids": ";".join(str(c["id"]) for c in candidates),
                    "action": _ACTION_BY_STATUS[entry["status"]],
                    "partner_id_column": target.partner_id_column,
                    "partner_id_column_written": False,
                    "reason": entry["reason"],
                }
            )
    records.sort(key=lambda r: (str(r["source_row_pk"]), r["resolution_status"]))
    return records


def mapping_to_csv(records: list[dict[str, Any]]) -> str:
    """Render the provenance mapping as deterministic CSV for human review."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(MAPPING_FIELDS), extrasaction="raise", lineterminator="\n"
    )
    writer.writeheader()
    for record in records:
        writer.writerow({field: record.get(field) for field in MAPPING_FIELDS})
    return buffer.getvalue()


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
        f"-- {REPAIR_PACKAGE} / policy {RESOLUTION_POLICY}\n"
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

    # Values are rendered as text literals and cast to the columns' real
    # catalog types. Without the cast an unknown-typed literal in a VALUES
    # list resolves to text, and joining text against a uuid or bigint key
    # fails outright -- so an uncastable run is flagged loudly rather than
    # emitting SQL that only looks correct.
    column_types = plan.get("column_types") or {}
    pk_cast = _cast_suffix(column_types.get(target.primary_key))
    id_cast = _cast_suffix(column_types.get(target.orchid_taxonomy_id_column))
    if not pk_cast or not id_cast:
        header += (
            "-- WARNING: the catalog types of "
            f"{target.primary_key}/{target.orchid_taxonomy_id_column} were not\n"
            "-- available when this was generated, so no explicit casts were emitted.\n"
            "-- Confirm the column types before running this against any database.\n"
        )

    values_rows = ",\n".join(
        f"  ({_sql_text_literal(action['row_pk'])}, "
        f"{_sql_text_literal(action['resolved_orchid_taxonomy_id'])})"
        for action in actions
    )
    body = (
        "BEGIN;\n"
        f"UPDATE {t} AS t\n"
        f"SET {idcol} = v.resolved_orchid_taxonomy_id{id_cast}\n"
        "FROM (VALUES\n"
        f"{values_rows}\n"
        f") AS v(row_pk, resolved_orchid_taxonomy_id)\n"
        f"WHERE t.{pk} = v.row_pk{pk_cast}\n"
        f"  AND t.{idcol} IS NULL;\n"
        "COMMIT;\n"
    )
    return header + body


def verify_plan_provenance(target: RepairTarget, plan: dict[str, Any]) -> None:
    """Refuse a plan whose ids cannot be traced back to the canonical table.

    Fails closed. A plan built by ``build_repair_plan`` always satisfies this;
    a plan assembled or edited by hand must carry the same provenance to be
    executable, which is what stops an id from another registry -- a partner
    or fungal taxon id in particular -- being written into the orchid column.
    """
    _require_known_target(target)
    for action in plan.get("actions", []):
        if action.get("canonical_source") != CANONICAL_TAXONOMY_TABLE:
            raise ValueError(
                f"Refusing to write row {action.get('row_pk')!r}: action does not "
                f"record {CANONICAL_TAXONOMY_TABLE} as the id's canonical source."
            )
        candidates = action.get("resolved_from_candidates")
        if not candidates or action.get("resolved_orchid_taxonomy_id") not in candidates:
            raise ValueError(
                f"Refusing to write row {action.get('row_pk')!r}: "
                f"{action.get('resolved_orchid_taxonomy_id')!r} is not among the "
                "canonical candidates this row resolved to."
            )


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

    Before the first write, every action is checked against the canonical
    candidates the measurement recorded for that row. An action whose id did
    not come out of ``public.orchid_taxonomy`` for that row -- or that carries
    no provenance at all -- aborts the whole apply, so no partner-side taxon id
    can reach the orchid-side column through a substituted plan.
    """
    _require_known_target(target)
    actions = plan.get("actions", [])

    if not execute:
        return {
            "status": "dry_run",
            "table": target.table,
            "would_update": len(actions),
        }

    verify_plan_provenance(target, plan)

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
