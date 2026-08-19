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

from app.readiness.occurrence_semantics import occurrence_predicate

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
    row_filters: dict[str, str] | None = None,
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
    _, taxonomy_reports = _probe_candidates(cur, taxonomy_tables)
    object_table, object_reports = _probe_candidates(cur, object_tables)

    discovery = {
        "taxonomy_candidates": taxonomy_reports,
        "object_candidates": object_reports,
    }

    # Every taxonomy relation that exists, not just the first. Which relation a
    # corpus anchors to is a fact about how it was ingested, and this schema does
    # not answer it the same way twice: oc_atlas.occurrences.taxon_id resolves
    # into oc_taxonomy.taxa, while the pollinator, mycorrhiza and habitat
    # relations all carry ids belonging to public.orchid_taxonomy. Picking one
    # anchor globally reported 695 habitat claims as 2, and two whole
    # relationships as absent, when the rows were there and pointed elsewhere.
    existing_taxonomy = [r["table"] for r in taxonomy_reports if r["exists"]]

    if not existing_taxonomy:
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

    obj_cols = _columns(cur, object_table)

    # Any of the relationship's defining columns being populated counts, not
    # just the first one that happens to exist. species_environment_profile
    # carries avg_, min_ and max_elevation_m; measuring only avg_ would report
    # absence while min_ and max_ sat populated beside it.
    value_columns = [c for c in required_value_columns if c in obj_cols]
    if required_value_columns and not value_columns:
        return _unavailable(
            name,
            "{} exists but carries none of the columns this relationship is "
            "defined by ({}).".format(object_table, ", ".join(required_value_columns)),
            discovery=discovery,
            object_table=object_table,
            object_columns=sorted(obj_cols),
        )

    obj_fk = next((c for c in object_taxon_keys if c in obj_cols), None)
    obj_name = next((c for c in object_name_columns if c in obj_cols), None)

    # Strongest first: an id join against any taxonomy relation outranks a name
    # join, because an identifier is an assertion the ingest made and a name
    # match is one this audit is making on its behalf.
    attempts_spec: list[tuple[str, str, str, str]] = []
    for tax_table in existing_taxonomy:
        tax_cols = _columns(cur, tax_table)
        tax_pk = next((c for c in taxonomy_keys if c in tax_cols), None)
        if tax_pk and obj_fk:
            attempts_spec.append(("relational_linkage_by_id", tax_table, tax_pk, obj_fk))
    for tax_table in existing_taxonomy:
        tax_cols = _columns(cur, tax_table)
        tax_name = next((c for c in taxonomy_name_columns if c in tax_cols), None)
        if tax_name and obj_name:
            attempts_spec.append(("relational_linkage_by_name", tax_table, tax_name, obj_name))

    if not attempts_spec:
        first_tax = existing_taxonomy[0]
        tax_cols = _columns(cur, first_tax)
        return _unavailable(
            name,
            f"{object_table} shares no join this audit recognises with any existing "
            "taxonomy relation: no taxon id foreign key and no scientific-name column pair.",
            discovery=discovery,
            taxonomy_tables_present=existing_taxonomy,
            object_table=object_table,
            taxonomy_columns=sorted(tax_cols),
            object_columns=sorted(obj_cols),
            object_key_found=obj_fk,
            object_name_column_found=obj_name,
        )

    o = _safe(object_table)
    total_objects = _scalar(cur, f"SELECT COUNT(*) FROM {o}")

    # A semantic filter on the object relation, applied when the selected table
    # mixes record kinds. This is what keeps a vendor listing out of an
    # occurrence count: the filter is on declared semantics, and it is reported
    # alongside the number so a count can never be read without the rule that
    # produced it.
    semantic_predicate = ""
    semantic_rule = None
    if row_filters and object_table in row_filters:
        semantic_predicate = " AND (" + row_filters[object_table] + ")"
        semantic_rule = {"table": object_table, "predicate": row_filters[object_table]}

    # Rows the semantics admit, which is what masking must compare against: a
    # five-million-row spine is not "larger" than a curated occurrence table if
    # only a fraction of it is occurrence evidence.
    semantically_eligible = total_objects
    if semantic_predicate:
        semantically_eligible = _scalar(
            cur, f"SELECT COUNT(*) FROM {o} o WHERE true{semantic_predicate}"
        )

    value_predicate = ""
    if value_columns:
        value_predicate = " AND (" + " OR ".join(
            f"o.{_safe(c)} IS NOT NULL" for c in value_columns
        ) + ")"

    results: list[dict[str, Any]] = []
    for mode, tax_table, left, right in attempts_spec:
        t = _safe(tax_table)
        lcol, rcol = _safe(left), _safe(right)
        # Name joins are case-folded on both sides; id joins are not. Scientific
        # names arrive from a dozen harvesters with inconsistent casing, and the
        # Knowledge Graph source registry already joins them this way
        # (lower(k.display_label) = lower(a.orchid_scientific_name)). Measuring
        # case-sensitively made elevation read 16,170 rows against the 306,359
        # the same join finds when folded -- a measurement of capitalisation,
        # not of the archive.
        if mode == "relational_linkage_by_name":
            join_on = f"lower(t.{lcol}) = lower(o.{rcol})"
            distinct_expr = f"lower(t.{lcol})"
        else:
            join_on = f"t.{lcol} = o.{rcol}"
            distinct_expr = f"t.{lcol}"
        predicate = f"o.{rcol} IS NOT NULL" + semantic_predicate + value_predicate
        linked_objects = _scalar(cur, f"SELECT COUNT(*) FROM {o} o WHERE {predicate}")
        matched_objects = _scalar(
            cur,
            f"SELECT COUNT(*) FROM {o} o JOIN {t} t ON {join_on} WHERE {predicate}",
        )
        taxa_reached = _scalar(
            cur,
            f"SELECT COUNT(DISTINCT {distinct_expr}) FROM {o} o "
            f"JOIN {t} t ON {join_on} WHERE {predicate}",
        )
        results.append(
            {
                "measurement": mode,
                "taxonomy_table": tax_table,
                "join": f"{object_table}.{right} -> {tax_table}.{left}",
                # A populated key pointing at nothing is a linkage defect, and a
                # different problem from a key nobody filled in. Both are reported.
                "rows_carrying_relationship": linked_objects,
                "rows_matching_taxonomy": matched_objects,
                "broken_taxonomy_targets": linked_objects - matched_objects,
                "taxa_reached": taxa_reached,
            }
        )

    # Attempts are already ordered id-before-name. Among them the best-resolving
    # one wins, so a sparse-but-authoritative id column cannot quietly outrank a
    # name join that reaches far more of the corpus -- and the loser is reported
    # rather than dropped, because "the id column exists and resolves 2 of 462"
    # is itself a finding. Absence is reported only when every supported join
    # ran and all of them found nothing.
    def _rank(r: dict[str, Any]) -> tuple[int, int]:
        # Reach first, id-over-name only to break a tie. Ranking by join
        # strength first would have picked the 2-row id join over the 347-row
        # name join on the mycorrhiza corpus and reported 0.4% coverage as the
        # measurement.
        return (
            r["rows_matching_taxonomy"],
            r["measurement"] == "relational_linkage_by_id",
        )

    resolving = [r for r in results if r["rows_matching_taxonomy"] > 0]
    chosen = max(resolving, key=_rank) if resolving else results[0]
    rejected = [r for r in results if r is not chosen]

    taxonomy_table = chosen["taxonomy_table"]
    total_taxa = _scalar(cur, f"SELECT COUNT(*) FROM {_safe(taxonomy_table)}")

    warnings = _masking_warnings(object_reports, semantically_eligible)
    for other in rejected:
        if other["rows_carrying_relationship"] > 0 and other["rows_matching_taxonomy"] == 0:
            warnings.append(
                "{} carries {:,} row(s) on {} but none resolve to {}; that join is "
                "populated and broken rather than empty.".format(
                    object_table,
                    other["rows_carrying_relationship"],
                    other["join"].split(" -> ")[0],
                    other["taxonomy_table"],
                )
            )
    if (
        chosen["measurement"] == "relational_linkage_by_name"
        and any(r["measurement"] == "relational_linkage_by_id" for r in results)
    ):
        best_id = max(
            (r for r in results if r["measurement"] == "relational_linkage_by_id"),
            key=lambda r: r["rows_matching_taxonomy"],
        )
        warnings.append(
            "Measured by name match. The stronger id join ({}) reaches {:,} of {:,} "
            "row(s); name matching is the documented fallback and is carrying this "
            "relationship.".format(
                best_id["join"], best_id["rows_matching_taxonomy"], total_objects
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
        "semantically_eligible_rows": semantically_eligible,
        "semantic_filter": semantic_rule,
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
# All of these are probed, and every existing one is joined against, because
# this schema does not anchor every corpus to the same taxonomy relation.
# Read-only diagnostic (docs/evidence/audit-measurement-002/) measured:
#   oc_atlas.occurrences.taxon_id      -> oc_taxonomy.taxa      26 of 26
#   pollinator .orchid_taxonomy_id     -> public.orchid_taxonomy 23 of 23, 0 to taxa
#   mycorrhiza .orchid_taxonomy_id     -> public.orchid_taxonomy  2 of 2,  0 to taxa
#   habitat    .taxonomy_id            -> public.orchid_taxonomy 695 of 695, 2 to taxa
#   orchid_occurrence.taxonomy_id      -> public.orchid_taxonomy 109,195 of 109,195
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
# scientific_binomial and scientific_name_clean are the columns public.records
# actually uses; measured resolution into oc_taxonomy.taxa.canonical_name was
# 847,517 and 651,007 rows respectively, against zero for its (entirely null)
# taxon_id_matched. Ordered by measured reach.
OBJECT_NAME_COLUMNS = (
    "scientific_name",
    "orchid_scientific_name",
    "scientific_binomial",
    "scientific_name_clean",
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
        # public.orchid_occurrence is measured first on evidence, not preference.
        # It holds 580,612 rows against oc_atlas.occurrences' 26, and
        # oc_views.occurrences_enriched is a view over that same 26-row table.
        # Its taxonomy_id resolves 109,195 of 109,195 into public.orchid_taxonomy.
        # The 26-row relation is kept as a candidate rather than removed, so if
        # it is ever the intended source the masking check will say so.
        "object_tables": (
            "public.orchid_occurrence",
            "oc_atlas.occurrences",
            "oc_views.occurrences_enriched",
            "public.orchid_occurrences",
            "public.occurrences",
            # Measured last, and only through the occurrence filter below. See
            # app/readiness/occurrence_semantics.py for what that admits.
            "public.records",
        ),
        # If public.records is ever the selected relation, only rows whose
        # declared type is occurrence evidence may be counted. Without this a
        # vendor listing, a video and a taxon profile would each register as
        # evidence that an orchid grew somewhere.
        "row_filters": {"public.records": occurrence_predicate("o", "record_type")},
    },
    {
        "name": "taxonomy_to_elevation",
        # oc_env.taxon_elevation_profiles, which the elevation adapter declares,
        # does not exist in production -- confirmed by catalog probe.
        #
        # public.records is measured FIRST here, and only here. The elevation
        # question asks whether the Continuum holds elevation for its taxa, and
        # the answer is in the raw harvest: 306,359 occurrence-typed rows carry
        # both an elevation and a name that reaches taxonomy, against 7 in the
        # curated projection, which has not backfilled elevation. Selecting the
        # projection first answered 7 and called it the state of the archive.
        #
        # This is not promoting the spine. The occurrence metric still reads
        # public.orchid_occurrence; only elevation reads the spine, and only
        # through the occurrence filter below, so a video or a vendor listing
        # carrying an elevation still cannot contribute one.
        "object_tables": (
            "public.records",
            "public.orchid_occurrence",
            "oc_env_intel.species_environment_profile",
            "oc_env.taxon_elevation_profiles",
            "oc_atlas.occurrences",
        ),
        # An occurrence row exists whether or not anyone recorded an elevation
        # for it. Only rows carrying one are evidence of this relationship.
        # Both spellings: oc_env.taxon_elevation_profiles uses minimum_/maximum_
        # per its adapter, species_environment_profile uses min_/max_. Any one of
        # them being populated is evidence, so all are listed.
        # Elevation is only occurrence evidence when the row it sits on is an
        # occurrence. 2,934,913 elevation values live on public.records, and
        # most of them belong to media, profiles and listings.
        "row_filters": {"public.records": occurrence_predicate("o", "record_type")},
        "required_value_columns": (
            "elevation_m",
            "mean_elevation_m",
            "avg_elevation_m",
            "minimum_elevation_m",
            "maximum_elevation_m",
            "min_elevation_m",
            "max_elevation_m",
            "minimum_elevation",
            "maximum_elevation",
            "elevation_meters",
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
        # oc_habitat.taxon_habitats, which the habitat adapter declares, does not
        # exist in production. public.oc_species_habitat_claims does, with 695
        # rows whose taxonomy_id resolves entirely into public.orchid_taxonomy.
        "object_tables": (
            "public.oc_species_habitat_claims",
            "oc_habitat.taxon_habitats",
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
                row_filters=spec.get("row_filters"),
            )
        except Exception as exc:  # noqa: BLE001 - reported, never silently dropped
            results[name] = _unavailable(
                name,
                f"Measurement raised {type(exc).__name__}: {exc}",
            )
    return results
