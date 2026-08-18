"""Read-only measurement paths for the executive audit's scientific relationships.

Before this module, eight of the ten relationships in ``AUDIT_RELATIONSHIPS``
had no measurement path at all and were reported as ``unmeasured``. That was the
honest report -- but "unmeasured" is a statement about this audit, not about the
Continuum, and leaving eight of ten there indefinitely means the audit cannot
answer the question it exists to answer.

Three rules govern everything here.

**Absence is only ever reported from a join that ran.** If discovery cannot find
a table, a key, or a column, the result is ``unavailable`` with the specific
reason -- never ``absent``. A schema-discovery failure is a fact about this
audit's assumptions; converting it into a finding about orchid biology is the
exact defect AUDIT-MEASUREMENT-001 was opened to fix.

**Every candidate is probed, not just the selected one.** ``_first_existing``
semantics mean a small legacy relation earlier in a list silently hides a larger
corpus behind it -- which is how the occurrence metric came to read 26 rows
while roughly 580,000 sat in another relation. Selection stays first-match so
headline numbers are not silently redefined, but the unselected candidates are
measured and reported.

**Join strength is reported, not smoothed over.** A foreign-key join and a
scientific-name string join are not equally good evidence, so the measurement
mode is carried in the result rather than averaged into a single number.

Everything in this module issues ``SELECT`` and catalog reads only. Nothing here
writes, and nothing here publishes graph edges.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

# Identifiers reach SQL by interpolation because PostgreSQL will not accept a
# bound parameter in a table or column position. Every one is drawn from a
# hardcoded candidate list AND confirmed against the live catalog before use;
# this guard is the third check, so a future edit to a candidate list cannot
# turn into injection.
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _safe(identifier: str) -> str:
    if not _SAFE_IDENT.fullmatch(identifier or ""):
        raise ValueError(f"Refusing to interpolate unsafe identifier: {identifier!r}")
    return identifier


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (table_name,))
    row = cur.fetchone()
    return bool(row[0] if not isinstance(row, dict) else row["present"])


def _columns(cur, table_name: str) -> set[str]:
    schema, _, table = table_name.partition(".")
    if not table:
        schema, table = "public", schema
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return {
        str(row[0] if not isinstance(row, dict) else row["column_name"])
        for row in cur.fetchall()
    }


def _scalar(cur, sql: str, params: Iterable[Any] = ()) -> int:
    cur.execute(sql, tuple(params))
    row = cur.fetchone()
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    return int(value or 0)


def _approximate_rows(cur, table_name: str) -> int | None:
    """Planner row estimate. Cheap on relations too large to count on every audit."""
    cur.execute(
        "SELECT relkind, reltuples FROM pg_class WHERE oid = to_regclass(%s)",
        (table_name,),
    )
    row = cur.fetchone()
    if not row:
        return None
    relkind = str(row[0] if not isinstance(row, dict) else row["relkind"])
    reltuples = row[1] if not isinstance(row, dict) else row["reltuples"]
    reltuples = float(reltuples) if reltuples is not None else -1.0
    return int(reltuples) if relkind == "r" and reltuples >= 0 else None


def _probe_candidates(cur, candidates: Sequence[str]) -> tuple[str | None, list[dict]]:
    """Select the first existing candidate while measuring all of them."""
    selected: str | None = None
    reports: list[dict] = []
    for table in candidates:
        exists = _table_exists(cur, table)
        if exists and selected is None:
            selected = table
        reports.append(
            {
                "table": table,
                "exists": exists,
                "selected": False,
                "approximate_rows": _approximate_rows(cur, table) if exists else None,
            }
        )
    for report in reports:
        report["selected"] = report["table"] == selected
    return selected, reports


MASKING_RATIO = 10
MASKING_FLOOR = 100


def _masking_warnings(reports: Sequence[dict], selected_rows: int | None) -> list[str]:
    """Flag an unselected candidate far larger than the selected one.

    The audit surfaces the discrepancy and stops there. Which relation is
    canonical is an owner and schema decision; a row count cannot settle it.
    """
    warnings: list[str] = []
    if selected_rows is None:
        return warnings
    for report in reports:
        if report["selected"] or not report["exists"]:
            continue
        approximate = report["approximate_rows"]
        if approximate is None:
            continue
        if approximate > MASKING_FLOOR and approximate > selected_rows * MASKING_RATIO:
            warnings.append(
                f"{report['table']} exists with approximately {approximate:,} row(s), "
                f"far more than the measured source ({selected_rows:,} row(s)); "
                "this relationship measurement may be reading a non-authoritative relation."
            )
    return warnings


def _unavailable(name: str, detail: str, **extra: Any) -> dict[str, Any]:
    """Build an unavailable result.

    Kept as one function so no caller can accidentally emit ``absent`` for a
    discovery failure.
    """
    return {
        "relationship": name,
        "state": "unavailable",
        "detail": detail,
        "interpretation": (
            "This audit could not measure the relationship. State is unknown; "
            "this is not a finding that the relationship is absent."
        ),
        **extra,
    }


def measure_link_relationship(
    cur,
    *,
    name: str,
    taxonomy_tables: Sequence[str],
    taxonomy_keys: Sequence[str],
    taxonomy_name_columns: Sequence[str] = (),
    object_tables: Sequence[str],
    object_taxon_keys: Sequence[str] = (),
    object_name_columns: Sequence[str] = (),
    required_value_columns: Sequence[str] = (),
) -> dict[str, Any]:
    """Measure whether taxonomy rows reach rows in a related relation.

    An id join is preferred and a scientific-name join is the documented
    fallback, because several corpora in this schema were ingested against names
    rather than against taxon ids. Whichever ran is reported in
    ``measurement``, so a weaker join is never mistaken for a stronger one.

    ``required_value_columns`` narrows the object side to rows actually carrying
    the attribute in question -- an occurrence row exists whether or not anyone
    recorded an elevation for it, and only the ones that did are evidence of a
    taxonomy-to-elevation relationship.
    """
    taxonomy_table, taxonomy_reports = _probe_candidates(cur, taxonomy_tables)
    object_table, object_reports = _probe_candidates(cur, object_tables)

    discovery = {
        "taxonomy_candidates": taxonomy_reports,
        "object_candidates": object_reports,
    }

    if not taxonomy_table:
        return _unavailable(
            name,
            "No canonical taxonomy relation from the candidate list exists.",
            discovery=discovery,
        )
    if not object_table:
        return _unavailable(
            name,
            "No relation carrying this relationship exists under any candidate name. "
            "The corpus may exist under a name this audit does not know.",
            discovery=discovery,
        )

    tax_cols = _columns(cur, taxonomy_table)
    obj_cols = _columns(cur, object_table)

    # An attribute the relationship is defined by must actually be a column.
    value_column = next((c for c in required_value_columns if c in obj_cols), None)
    if required_value_columns and not value_column:
        return _unavailable(
            name,
            "{} exists but carries none of the columns this relationship is "
            "defined by ({}).".format(object_table, ", ".join(required_value_columns)),
            discovery=discovery,
            taxonomy_table=taxonomy_table,
            object_table=object_table,
            object_columns=sorted(obj_cols),
        )

    tax_pk = next((c for c in taxonomy_keys if c in tax_cols), None)
    obj_fk = next((c for c in object_taxon_keys if c in obj_cols), None)
    tax_name = next((c for c in taxonomy_name_columns if c in tax_cols), None)
    obj_name = next((c for c in object_name_columns if c in obj_cols), None)

    # Every join this schema supports, strongest first. Both are attempted,
    # because preferring one and stopping there is how an audit reports absence
    # that is not there: oc_mycorrhiza.orchid_fungal_associations holds 462 rows
    # of which 2 carry orchid_taxonomy_id and neither resolves, while the source
    # registry joins that table on orchid_scientific_name. An id-only
    # measurement would have called 462 documented associations "absent".
    attempts: list[tuple[str, str, str]] = []
    if tax_pk and obj_fk:
        attempts.append(("relational_linkage_by_id", tax_pk, obj_fk))
    if tax_name and obj_name:
        attempts.append(("relational_linkage_by_name", tax_name, obj_name))

    if not attempts:
        # Report the columns each side actually has. An "unavailable" that only
        # says "no join recognised" leaves the reader to go and look; one that
        # names the available columns tells them exactly which candidate to add,
        # turning a dead end into a one-line fix.
        return _unavailable(
            name,
            f"{taxonomy_table} and {object_table} exist but share no join this audit recognises: no taxon id "
            "foreign key and no scientific-name column pair.",
            discovery=discovery,
            taxonomy_table=taxonomy_table,
            object_table=object_table,
            taxonomy_columns=sorted(tax_cols),
            object_columns=sorted(obj_cols),
            taxonomy_key_found=tax_pk,
            taxonomy_name_column_found=tax_name,
            object_key_found=obj_fk,
            object_name_column_found=obj_name,
        )

    t, o = _safe(taxonomy_table), _safe(object_table)
    total_taxa = _scalar(cur, f"SELECT COUNT(*) FROM {t}")
    total_objects = _scalar(cur, f"SELECT COUNT(*) FROM {o}")

    # Any of the relationship's defining columns being populated counts, not
    # just the first one that happens to exist. species_environment_profile
    # carries avg_, min_ and max_elevation_m; measuring only avg_ would report
    # absence while min_ and max_ sat populated beside it.
    value_columns = [c for c in required_value_columns if c in obj_cols]
    value_predicate = ""
    if value_columns:
        value_predicate = " AND (" + " OR ".join(
            f"o.{_safe(c)} IS NOT NULL" for c in value_columns
        ) + ")"

    results: list[dict[str, Any]] = []
    for mode, left, right in attempts:
        lcol, rcol = _safe(left), _safe(right)
        predicate = f"o.{rcol} IS NOT NULL" + value_predicate
        linked_objects = _scalar(cur, f"SELECT COUNT(*) FROM {o} o WHERE {predicate}")
        matched_objects = _scalar(
            cur,
            f"SELECT COUNT(*) FROM {o} o JOIN {t} t ON t.{lcol} = o.{rcol} WHERE {predicate}",
        )
        taxa_reached = _scalar(
            cur,
            f"SELECT COUNT(DISTINCT t.{lcol}) FROM {o} o "
            f"JOIN {t} t ON t.{lcol} = o.{rcol} WHERE {predicate}",
        )
        results.append(
            {
                "measurement": mode,
                "join": f"{object_table}.{right} -> {taxonomy_table}.{left}",
                # A populated key pointing at nothing is a linkage defect, and a
                # different problem from a key nobody filled in. Both are reported.
                "rows_carrying_relationship": linked_objects,
                "rows_matching_taxonomy": matched_objects,
                "broken_taxonomy_targets": linked_objects - matched_objects,
                "taxa_reached": taxa_reached,
            }
        )

    # The first attempt that found anything wins; absence is reported only when
    # every join this schema supports ran and all of them found nothing.
    chosen = next((r for r in results if r["rows_matching_taxonomy"] > 0), results[0])
    rejected = [r for r in results if r is not chosen]

    warnings = _masking_warnings(object_reports, total_objects)
    warnings.extend(_masking_warnings(taxonomy_reports, total_taxa))
    for other in rejected:
        if other["rows_carrying_relationship"] > 0 and other["rows_matching_taxonomy"] == 0:
            warnings.append(
                "{} carries {:,} row(s) on {} but none resolve to {}; that join is "
                "populated and broken rather than empty.".format(
                    object_table,
                    other["rows_carrying_relationship"],
                    other["join"].split(" -> ")[0],
                    taxonomy_table,
                )
            )

    taxa_reached = chosen["taxa_reached"]
    return {
        "relationship": name,
        # Absence is asserted only here, after every supported join has run.
        "state": "present" if chosen["rows_matching_taxonomy"] > 0 else "absent",
        "measurement": chosen["measurement"],
        "taxonomy_table": taxonomy_table,
        "object_table": object_table,
        "join": chosen["join"],
        "value_columns": value_columns,
        "total_taxa": total_taxa,
        "total_object_rows": total_objects,
        "rows_carrying_relationship": chosen["rows_carrying_relationship"],
        "rows_matching_taxonomy": chosen["rows_matching_taxonomy"],
        "broken_taxonomy_targets": chosen["broken_taxonomy_targets"],
        "taxa_reached": taxa_reached,
        "joins_attempted": results,
        "taxa_reached_percentage": (
            round((taxa_reached / total_taxa) * 100, 4) if total_taxa else None
        ),
        "source_warnings": warnings,
        "discovery": discovery,
        "interpretation": (
            "Relational linkage only. A populated join column is not the same fact "
            "as a published Knowledge Graph edge, and neither is a claim about "
            "whether the underlying biology has been studied."
        ),
    }


# Candidate relations per relationship, drawn from the Knowledge Graph source
# registry and adapters (runtime/knowledge_graph/) plus the relations the live
# metric probe already selects. Nothing here is invented: every table named
# below is one this repository already treats as a canonical source for that
# domain, or one the deployed metric probe already counts.
#
# Order is deliberate. The first existing candidate is measured, and the rest
# are probed so a smaller relation earlier in a list cannot hide a larger corpus
# without the report saying so.
TAXONOMY_TABLES = (
    "oc_taxonomy.taxa",
    "public.orchid_taxonomy",
    "oc_core.taxonomy",
    "public.taxonomy",
)
TAXONOMY_KEYS = ("taxon_id", "id", "taxonomy_id")
# canonical_name first: it is what oc_taxonomy.taxa actually calls its name
# column, and its absence from this list is why three relationships came back
# unavailable on the first production run.
TAXONOMY_NAME_COLUMNS = (
    "canonical_name",
    "scientific_name",
    "normalized_name",
    "accepted_name",
    "taxon_name",
    "name",
)

# Name columns used by corpora ingested against names rather than taxon ids --
# the mycorrhiza source registry joins on orchid_scientific_name, for one.
OBJECT_NAME_COLUMNS = (
    "scientific_name",
    "orchid_scientific_name",
    "taxon_name",
    "accepted_name",
    "species_name",
)
# Order matters, and it is a correctness question rather than a preference.
# oc_interactions.orchid_interaction_edges carries both orchid_taxonomy_id and
# partner_taxon_id; oc_mycorrhiza.orchid_fungal_associations carries both
# orchid_taxonomy_id and fungal_taxon_id. The orchid-side key is named first so
# a relationship to orchids can never be measured through the partner or the
# fungus. Matching is exact, so a generic "taxon_id" cannot pick up
# "partner_taxon_id" by accident either.
OBJECT_TAXON_KEYS = (
    "orchid_taxonomy_id",
    "taxon_id",
    "taxon_pk",
    "taxonomy_id",
    "accepted_taxon_id",
    "species_id",
)

RELATIONSHIP_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "taxonomy_to_occurrences",
        "object_tables": (
            "oc_atlas.occurrences",
            "oc_views.occurrences_enriched",
            "public.orchid_occurrence",
            "public.orchid_occurrences",
            "public.occurrences",
        ),
    },
    {
        "name": "taxonomy_to_elevation",
        "object_tables": (
            "oc_env.taxon_elevation_profiles",
            "oc_env_intel.species_environment_profile",
            "oc_atlas.occurrences",
        ),
        # An occurrence row exists whether or not anyone recorded an elevation
        # for it. Only rows carrying one are evidence of this relationship.
        # Both spellings: oc_env.taxon_elevation_profiles uses minimum_/maximum_
        # per its adapter, species_environment_profile uses min_/max_. Any one of
        # them being populated is evidence, so all are listed.
        "required_value_columns": (
            "mean_elevation_m",
            "avg_elevation_m",
            "minimum_elevation_m",
            "maximum_elevation_m",
            "min_elevation_m",
            "max_elevation_m",
            "elevation_m",
            "elevation",
        ),
    },
    {
        "name": "taxonomy_to_climate",
        "object_tables": ("oc_env_intel.species_environment_profile",),
        "required_value_columns": (
            "climate_proxy_zones",
            "environmental_readiness_label",
        ),
    },
    {
        "name": "taxonomy_to_literature",
        "object_tables": (
            "oc_graph.taxon_literature_edges",
            "oc_literature.papers",
            "oc_literature.documents",
            "oc_literature.literature_documents",
            "public.literature_documents",
            "public.research_documents",
        ),
    },
    {
        "name": "taxonomy_to_pollinators",
        "object_tables": (
            "oc_interactions.orchid_interaction_edges",
            "oc_interactions.relationships",
            "public.pollinator_relationships",
        ),
    },
    {
        "name": "taxonomy_to_mycorrhiza",
        "object_tables": (
            "oc_mycorrhiza.orchid_fungal_associations",
            "oc_mycorrhiza.relationships",
            "public.mycorrhiza_relationships",
            # Deliberately last, and only as a fallback: this relation is an
            # endpoint response cache, not a mycorrhizal corpus. Measuring it
            # would count cached HTTP responses as biology.
            "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
        ),
    },
    {
        "name": "taxonomy_to_habitat",
        "object_tables": (
            "oc_habitat.taxon_habitats",
            "public.oc_species_habitat_claims",
            "oc_habitat.habitat_claims",
        ),
    },
    {
        "name": "taxonomy_to_conservation",
        "object_tables": (
            "oc_conservation.conservation_records",
            "public.conservation_records",
        ),
    },
)


def measure_declared_relationships(cur) -> dict[str, dict[str, Any]]:
    """Measure every relationship carrying a spec, isolating per-relationship failure.

    One relationship whose relation has an unexpected shape must not take the
    other seven down with it, so each is wrapped: a raised error becomes an
    ``unavailable`` result naming the exception. An audit that returns nothing
    because one table surprised it is less useful than one that returns nine
    measurements and an explicit failure.
    """
    results: dict[str, dict[str, Any]] = {}
    for spec in RELATIONSHIP_SPECS:
        name = spec["name"]
        try:
            results[name] = measure_link_relationship(
                cur,
                name=name,
                taxonomy_tables=TAXONOMY_TABLES,
                taxonomy_keys=TAXONOMY_KEYS,
                taxonomy_name_columns=TAXONOMY_NAME_COLUMNS,
                object_tables=spec["object_tables"],
                object_taxon_keys=OBJECT_TAXON_KEYS,
                object_name_columns=OBJECT_NAME_COLUMNS,
                required_value_columns=spec.get("required_value_columns", ()),
            )
        except Exception as exc:  # noqa: BLE001 - reported, never silently dropped
            results[name] = _unavailable(
                name,
                f"Measurement raised {type(exc).__name__}: {exc}",
            )
    return results
