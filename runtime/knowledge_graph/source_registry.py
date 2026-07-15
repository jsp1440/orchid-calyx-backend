"""Configuration-driven registry of read-only source queries (BUILD-062).

Every scientific domain's connection to real production data is described by a
single :class:`SourceQuery` entry here.  There is exactly one place where the
per-domain projection SQL lives; adapters and the orchestrator never embed SQL.

Design
------
* Each enabled entry carries a SELECT-only projection that emits the publisher
  contract: at minimum ``source_pk`` and ``taxon_pk``, plus the optional value /
  provenance / quality columns the domain adapter reads.
* ``taxon_pk`` is always the taxonomy identity used by the canonical graph
  backbone ``oc_graph.kg_nodes`` (node_type ``taxon``, ``source_pk`` =
  ``public.taxonomy_species.id``).  Every query filters to taxa that exist in
  that backbone so projected edges always resolve.
* Domains whose real production source could not be located, or whose taxon
  mapping is not established, are recorded with ``enabled=False`` and a
  ``blocked_reason`` — they are never silently dropped.

Nothing here opens a connection.  :func:`enabled_queries` returns the plain
``{domain: sql}`` mapping consumed by :class:`PostgresSourceProvider`.

Taxon mapping methods
---------------------
``direct``      — the source table carries a taxon id in the backbone id space.
``resolved_view`` — a curated view already resolved the taxon id (traits).
``name_join``   — the source has no backbone taxon id; join on exact (case-
  insensitive) scientific name to ``kg_nodes.display_label``.  This is an exact
  relational join on a natural key, not fuzzy matching; name collisions can fan
  a source row out to multiple taxa and are reported as a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceQuery:
    domain: str
    query_id: str
    sql: str | None
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...] = ()
    expected_tables: tuple[str, ...] = ()
    taxon_mapping: str = "direct"
    provenance_columns: tuple[str, ...] = ()
    quality_columns: tuple[str, ...] = ()
    enabled: bool = True
    blocked_reason: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "query_id": self.query_id,
            "enabled": self.enabled,
            "blocked_reason": self.blocked_reason,
            "expected_tables": list(self.expected_tables),
            "taxon_mapping": self.taxon_mapping,
            "required_columns": list(self.required_columns),
            "optional_columns": list(self.optional_columns),
            "provenance_columns": list(self.provenance_columns),
            "quality_columns": list(self.quality_columns),
            "has_sql": bool(self.sql),
            "notes": self.notes,
        }


CONTRACT_REQUIRED = ("source_pk", "taxon_pk")

# --- SQL safety -------------------------------------------------------------

_FORBIDDEN = (
    "insert", "update", "delete", "merge", "create", "alter", "drop",
    "truncate", "grant", "revoke", "copy", "call", "do", "vacuum",
    "comment", "reindex", "refresh", "lock", "listen", "notify", "execute",
)


class UnsafeSQLError(ValueError):
    """Raised when a registered query is not a read-only single SELECT."""


def _strip_sql_comments(sql: str) -> str:
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        two = sql[i : i + 2]
        if two == "--":
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif two == "/*":
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def assert_safe_sql(sql: str) -> None:
    """Reject anything that is not a single read-only SELECT/WITH statement."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("empty SQL")
    body = _strip_sql_comments(sql).strip().rstrip(";").strip()
    if ";" in body:
        raise UnsafeSQLError("multiple statements are not allowed")
    lowered = body.lower()
    head = lowered.lstrip("(").lstrip()
    if not (head.startswith("select") or head.startswith("with")):
        raise UnsafeSQLError("only SELECT/WITH read queries are allowed")
    import re

    tokens = set(re.findall(r"[a-z_]+", lowered))
    hits = sorted(tokens & set(_FORBIDDEN))
    if hits:
        raise UnsafeSQLError(f"forbidden SQL keyword(s): {', '.join(hits)}")


# --- taxon backbone filter helpers -----------------------------------------

_KG = "oc_graph.kg_nodes"
_KG_TAXON = f"{_KG} k"


def _direct(inner: str, taxon_expr: str) -> str:
    return (
        f"{inner}\n  and exists (select 1 from {_KG_TAXON} "
        f"where k.node_type='taxon' and k.source_pk={taxon_expr}::text)"
    )


# --- the registry -----------------------------------------------------------

_OCCURRENCES = SourceQuery(
    domain="occurrences",
    query_id="occurrences_v1",
    expected_tables=("oc_atlas.occurrences", "oc_graph.kg_nodes"),
    taxon_mapping="direct",
    required_columns=CONTRACT_REQUIRED,
    optional_columns=(
        "locality", "scientific_name", "latitude", "longitude", "elevation",
        "country", "event_date", "basis_of_record", "source_name",
    ),
    provenance_columns=("source_name", "created_at", "updated_at"),
    quality_columns=("evidence_class",),
    sql="""
        select o.occurrence_id as source_pk, o.taxon_id as taxon_pk,
               o.locality, o.scientific_name, o.latitude, o.longitude, o.elevation,
               o.country, o.event_date, o.basis_of_record, o.source_name,
               o.source_name as evidence_class, o.created_at, o.updated_at
        from oc_atlas.occurrences o
        where o.taxon_id is not null
          and exists (select 1 from oc_graph.kg_nodes k
                      where k.node_type='taxon' and k.source_pk=o.taxon_id::text)
    """,
)

_CONSERVATION = SourceQuery(
    domain="conservation",
    query_id="conservation_v1",
    expected_tables=("oc_conservation.conservation_records", "oc_graph.kg_nodes"),
    taxon_mapping="direct",
    required_columns=CONTRACT_REQUIRED,
    optional_columns=(
        "iucn_category", "cites_appendix", "scientific_name", "population_trend",
        "assessment_year", "region", "source_name",
    ),
    provenance_columns=("source_name", "created_at", "updated_at"),
    quality_columns=("evidence_class",),
    sql="""
        select c.conservation_id as source_pk, c.taxon_id as taxon_pk,
               c.iucn_category, c.cites_appendix, c.scientific_name,
               c.population_trend, c.assessment_year, c.region, c.source_name,
               c.source_name as evidence_class, c.created_at, c.updated_at
        from oc_conservation.conservation_records c
        where c.taxon_id is not null
          and exists (select 1 from oc_graph.kg_nodes k
                      where k.node_type='taxon' and k.source_pk=c.taxon_id::text)
    """,
)

_MEDIA = SourceQuery(
    domain="media",
    query_id="media_gallery_v1",
    expected_tables=("oc_api.species_media_gallery_v1", "oc_graph.kg_nodes"),
    taxon_mapping="direct",
    required_columns=CONTRACT_REQUIRED,
    optional_columns=(
        "scientific_name", "caption", "media_url", "thumbnail_url", "media_type",
        "license", "rights_holder", "source_name",
    ),
    provenance_columns=("source_name", "created_at"),
    quality_columns=(),
    notes=(
        "oc_core.media_assets.taxon_id is unpopulated (all NULL); the curated "
        "gallery view carries the resolved taxonomy_id and is used instead."
    ),
    sql="""
        select md5(g.taxonomy_id::text || '|' || coalesce(g.media_url,'')) as source_pk,
               g.taxonomy_id as taxon_pk, g.scientific_name, g.caption, g.media_url,
               g.thumbnail_url, g.media_type, g.license, g.rights_holder,
               g.source_name, g.generated_at as created_at
        from oc_api.species_media_gallery_v1 g
        where g.taxonomy_id is not null and g.media_url is not null
          and exists (select 1 from oc_graph.kg_nodes k
                      where k.node_type='taxon' and k.source_pk=g.taxonomy_id::text)
    """,
)

_TRAITS = SourceQuery(
    domain="traits",
    query_id="traits_resolved_v4",
    expected_tables=("oc_views.trait_resolved_v4", "oc_graph.kg_nodes"),
    taxon_mapping="resolved_view",
    required_columns=CONTRACT_REQUIRED,
    optional_columns=("trait_name", "trait_value", "support_count"),
    provenance_columns=(),
    quality_columns=("confidence_score", "confidence_label"),
    notes=(
        "oc_traits.traits carries no taxon column; the curated consensus view "
        "trait_resolved_v4 resolves taxonomy_id. source_pk is a deterministic "
        "hash of (taxonomy_id, trait_name, trait_value)."
    ),
    sql="""
        select md5(t.taxonomy_id::text || '|' || t.trait_name || '|'
                   || coalesce(t.trait_value,'')) as source_pk,
               t.taxonomy_id as taxon_pk, t.trait_name, t.trait_value,
               t.support_count, t.source_level as confidence_label,
               t.confidence_ratio as confidence_score
        from oc_views.trait_resolved_v4 t
        where t.taxonomy_id is not null and t.trait_name is not null
          and exists (select 1 from oc_graph.kg_nodes k
                      where k.node_type='taxon' and k.source_pk=t.taxonomy_id::text)
    """,
)

_LITERATURE = SourceQuery(
    domain="literature",
    query_id="literature_taxon_edges_v1",
    expected_tables=("oc_graph.taxon_literature_edges", "oc_graph.kg_nodes"),
    taxon_mapping="name_join",
    required_columns=CONTRACT_REQUIRED,
    optional_columns=("title", "doi", "year", "edge_strength"),
    provenance_columns=("created_at",),
    quality_columns=("confidence_score",),
    notes=(
        "Literature edge tables key taxa by scientific_name only (no backbone "
        "taxon id). Exact case-insensitive name join to kg_nodes.display_label; "
        "name collisions may fan one edge to multiple taxa (reported)."
    ),
    sql="""
        select l.taxon_edge_id as source_pk, k.source_pk::bigint as taxon_pk,
               l.title, l.doi, l.publication_year as year,
               l.trust_score as confidence_score, l.edge_strength, l.created_at
        from oc_graph.taxon_literature_edges l
        join oc_graph.kg_nodes k
          on k.node_type='taxon' and lower(k.display_label)=lower(l.scientific_name)
    """,
)

_POLLINATORS = SourceQuery(
    domain="pollinators",
    query_id="pollinators_interaction_edges_v1",
    expected_tables=("oc_interactions.orchid_interaction_edges", "oc_graph.kg_nodes"),
    taxon_mapping="name_join",
    required_columns=CONTRACT_REQUIRED,
    optional_columns=(
        "partner_taxon_name", "interaction_type", "interaction_group",
        "evidence_citation",
    ),
    provenance_columns=("created_at",),
    quality_columns=("evidence_class", "confidence_score"),
    notes=(
        "orchid_interaction_edges.orchid_taxonomy_id is in the oc_taxonomy id "
        "space (values > backbone max) with no verified crosswalk to the graph "
        "backbone, so an exact scientific-name join is used instead."
    ),
    sql="""
        select e.edge_id as source_pk, k.source_pk::bigint as taxon_pk,
               e.partner_taxon_name, e.interaction_type, e.interaction_group,
               e.evidence_source as evidence_class, e.evidence_citation,
               e.confidence_score, e.created_at
        from oc_interactions.orchid_interaction_edges e
        join oc_graph.kg_nodes k
          on k.node_type='taxon' and lower(k.display_label)=lower(e.orchid_scientific_name)
    """,
)

_MYCORRHIZA = SourceQuery(
    domain="mycorrhiza",
    query_id="mycorrhiza_associations_v1",
    expected_tables=("oc_mycorrhiza.orchid_fungal_associations", "oc_graph.kg_nodes"),
    taxon_mapping="name_join",
    required_columns=CONTRACT_REQUIRED,
    optional_columns=(
        "fungal_name", "fungal_taxon_id", "association_type", "life_stage",
        "citation", "doi",
    ),
    provenance_columns=("citation", "doi", "created_at", "updated_at"),
    quality_columns=("evidence_class", "confidence_score", "confidence_label"),
    notes=(
        "orchid_fungal_associations.orchid_taxonomy_id is in the oc_taxonomy id "
        "space with no verified backbone crosswalk; exact scientific-name join "
        "is used. Name collisions fan some associations to multiple taxa."
    ),
    sql="""
        select a.association_id as source_pk, k.source_pk::bigint as taxon_pk,
               a.fungal_name, a.fungal_taxon_id, a.association_type, a.life_stage,
               a.evidence_type as evidence_class, a.citation, a.doi,
               a.confidence_score, a.confidence_band as confidence_label,
               a.created_at, a.updated_at
        from oc_mycorrhiza.orchid_fungal_associations a
        join oc_graph.kg_nodes k
          on k.node_type='taxon' and lower(k.display_label)=lower(a.orchid_scientific_name)
    """,
)

_CLIMATE = SourceQuery(
    domain="climate",
    query_id="climate_env_proxy_v1",
    expected_tables=("oc_env_intel.species_environment_profile", "oc_graph.kg_nodes"),
    taxon_mapping="direct",
    required_columns=CONTRACT_REQUIRED,
    optional_columns=(
        "scientific_name", "environmental_readiness_label", "climate_proxy_zones",
        "avg_elevation_m", "min_elevation_m", "max_elevation_m",
    ),
    provenance_columns=("build_id", "created_at"),
    quality_columns=("evidence_class", "confidence_score", "confidence_label"),
    notes=(
        "No direct climate table exists (oc_env.climate_summaries absent). This "
        "is an OCCURRENCE-DERIVED environmental proxy (elevation + qualitative "
        "climate_proxy_zones), not modelled bioclim/WorldClim values. True "
        "bioclim requires a future derivation pipeline from occurrence "
        "coordinates. Classified PARTIALLY CONNECTED for this reason."
    ),
    sql="""
        select e.taxonomy_id as source_pk, e.taxonomy_id as taxon_pk,
               e.scientific_name, e.environmental_readiness_label,
               e.climate_proxy_zones, e.avg_elevation_m, e.min_elevation_m,
               e.max_elevation_m, e.environmental_evidence_score as confidence_score,
               e.confidence_label, e.build_id as evidence_class, e.created_at
        from oc_env_intel.species_environment_profile e
        where e.taxonomy_id is not null
          and exists (select 1 from oc_graph.kg_nodes k
                      where k.node_type='taxon' and k.source_pk=e.taxonomy_id::text)
    """,
)


SOURCE_QUERIES: tuple[SourceQuery, ...] = (
    _OCCURRENCES,
    _TRAITS,
    _POLLINATORS,
    _MYCORRHIZA,
    _CONSERVATION,
    _CLIMATE,
    _LITERATURE,
    _MEDIA,
)


def registry_by_domain() -> dict[str, SourceQuery]:
    return {q.domain: q for q in SOURCE_QUERIES}


def enabled_queries() -> dict[str, str]:
    """The ``{domain: sql}`` map consumed by ``PostgresSourceProvider``.

    Every returned query is validated read-only before it is handed out.
    """
    out: dict[str, str] = {}
    for q in SOURCE_QUERIES:
        if q.enabled and q.sql:
            assert_safe_sql(q.sql)
            out[q.domain] = q.sql
    return out


def blocked_domains() -> dict[str, str]:
    return {
        q.domain: (q.blocked_reason or "disabled")
        for q in SOURCE_QUERIES
        if not q.enabled
    }
