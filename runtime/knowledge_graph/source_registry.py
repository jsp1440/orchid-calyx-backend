"""Configuration-driven read-only source registry for the Knowledge Graph.

Every adapter domain is registered here. Domains with a verified production
projection expose SELECT-only SQL; domains whose source contract has not yet
been verified remain explicit, disabled, and fail closed instead of silently
falling out of the graph build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
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
    metadata: dict[str, Any] = field(default_factory=dict)

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
            "metadata": dict(self.metadata),
        }


CONTRACT_REQUIRED = ("source_pk", "taxon_pk")
_FORBIDDEN = {
    "insert", "update", "delete", "merge", "create", "alter", "drop",
    "truncate", "grant", "revoke", "copy", "call", "do", "vacuum",
    "comment", "reindex", "refresh", "lock", "listen", "notify", "execute",
}


class UnsafeSQLError(ValueError):
    """Raised when registered SQL is not a single read-only SELECT/WITH."""


def _strip_sql_comments(sql: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(sql):
        if sql[i : i + 2] == "--":
            end = sql.find("\n", i)
            i = len(sql) if end == -1 else end
        elif sql[i : i + 2] == "/*":
            end = sql.find("*/", i + 2)
            i = len(sql) if end == -1 else end + 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def assert_safe_sql(sql: str) -> None:
    if not sql or not sql.strip():
        raise UnsafeSQLError("empty SQL")
    body = _strip_sql_comments(sql).strip().rstrip(";").strip()
    if ";" in body:
        raise UnsafeSQLError("multiple statements are not allowed")
    head = body.lower().lstrip("(").lstrip()
    if not head.startswith(("select", "with")):
        raise UnsafeSQLError("only SELECT/WITH read queries are allowed")
    hits = sorted(set(re.findall(r"[a-z_]+", body.lower())) & _FORBIDDEN)
    if hits:
        raise UnsafeSQLError(f"forbidden SQL keyword(s): {', '.join(hits)}")


def _verified(
    *,
    domain: str,
    query_id: str,
    expected_tables: tuple[str, ...],
    taxon_mapping: str,
    optional_columns: tuple[str, ...],
    provenance_columns: tuple[str, ...] = (),
    quality_columns: tuple[str, ...] = (),
    sql: str,
    notes: str = "",
) -> SourceQuery:
    return SourceQuery(
        domain=domain,
        query_id=query_id,
        sql=sql,
        required_columns=CONTRACT_REQUIRED,
        optional_columns=optional_columns,
        expected_tables=expected_tables,
        taxon_mapping=taxon_mapping,
        provenance_columns=provenance_columns,
        quality_columns=quality_columns,
        notes=notes,
    )


def _blocked(domain: str, query_id: str, table: str) -> SourceQuery:
    reason = (
        "Source table is known from the adapter contract, but its production "
        "projection and backbone taxon mapping have not been verified for a "
        "publication build. Registered explicitly and disabled fail-closed."
    )
    return SourceQuery(
        domain=domain,
        query_id=query_id,
        sql=None,
        required_columns=CONTRACT_REQUIRED,
        expected_tables=(table, "oc_graph.kg_nodes"),
        taxon_mapping="direct",
        enabled=False,
        blocked_reason=reason,
        notes=reason,
    )


_OCCURRENCES = _verified(
    domain="occurrences",
    query_id="occurrences_v1",
    expected_tables=("oc_atlas.occurrences", "oc_graph.kg_nodes"),
    taxon_mapping="direct",
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

_TRAITS = _verified(
    domain="traits",
    query_id="traits_resolved_v4",
    expected_tables=("oc_views.trait_resolved_v4", "oc_graph.kg_nodes"),
    taxon_mapping="resolved_view",
    optional_columns=("trait_name", "trait_value", "support_count"),
    quality_columns=("confidence_score", "confidence_label"),
    notes=(
        "The curated trait_resolved_v4 view resolves taxonomy_id; source_pk is a "
        "deterministic hash of taxonomy_id, trait_name and trait_value."
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

_POLLINATORS = _verified(
    domain="pollinators",
    query_id="pollinators_interaction_edges_v1",
    expected_tables=("oc_interactions.orchid_interaction_edges", "oc_graph.kg_nodes"),
    taxon_mapping="name_join",
    optional_columns=(
        "partner_taxon_name", "interaction_type", "interaction_group",
        "evidence_citation",
    ),
    provenance_columns=("created_at",),
    quality_columns=("evidence_class", "confidence_score"),
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

_MYCORRHIZA = _verified(
    domain="mycorrhiza",
    query_id="mycorrhiza_associations_v1",
    expected_tables=("oc_mycorrhiza.orchid_fungal_associations", "oc_graph.kg_nodes"),
    taxon_mapping="name_join",
    optional_columns=(
        "fungal_name", "fungal_taxon_id", "association_type", "life_stage",
        "citation", "doi",
    ),
    provenance_columns=("citation", "doi", "created_at", "updated_at"),
    quality_columns=("evidence_class", "confidence_score", "confidence_label"),
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

_CONSERVATION = _verified(
    domain="conservation",
    query_id="conservation_v1",
    expected_tables=("oc_conservation.conservation_records", "oc_graph.kg_nodes"),
    taxon_mapping="direct",
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

_CLIMATE = _verified(
    domain="climate",
    query_id="climate_env_proxy_v1",
    expected_tables=("oc_env_intel.species_environment_profile", "oc_graph.kg_nodes"),
    taxon_mapping="direct",
    optional_columns=(
        "scientific_name", "environmental_readiness_label", "climate_proxy_zones",
        "avg_elevation_m", "min_elevation_m", "max_elevation_m",
    ),
    provenance_columns=("build_id", "created_at"),
    quality_columns=("evidence_class", "confidence_score", "confidence_label"),
    notes=(
        "Occurrence-derived environmental proxy only; not modelled bioclim. "
        "Metadata keeps this scientific surface BLOCKED for climate claims."
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

_LITERATURE = _verified(
    domain="literature",
    query_id="literature_taxon_edges_v1",
    expected_tables=("oc_graph.taxon_literature_edges", "oc_graph.kg_nodes"),
    taxon_mapping="name_join",
    optional_columns=("title", "doi", "year", "edge_strength"),
    provenance_columns=("created_at",),
    quality_columns=("confidence_score",),
    notes=(
        "Literature source has no taxon id; exact scientific-name join is used "
        "until an upstream identifier is available."
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

_MEDIA = _verified(
    domain="media",
    query_id="media_gallery_v1",
    expected_tables=("oc_api.species_media_gallery_v1", "oc_graph.kg_nodes"),
    taxon_mapping="direct",
    optional_columns=(
        "scientific_name", "caption", "media_url", "thumbnail_url", "media_type",
        "license", "rights_holder", "source_name",
    ),
    provenance_columns=("source_name", "created_at"),
    notes=(
        "Curated gallery view carries the resolved taxonomy_id; the raw media "
        "asset taxon linkage is not used."
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

# BUILD-068 expanded adapters. Their source table names are known from the
# adapter contract, but no current-main evidence establishes a safe publication
# projection/taxon crosswalk. Register them explicitly, disabled, until verified.
_GEOGRAPHY = _blocked("geography", "geography_unverified_v1", "oc_geo.taxon_places")
_HABITAT = _blocked("habitat", "habitat_unverified_v1", "oc_habitat.taxon_habitats")
_ELEVATION = _blocked("elevation", "elevation_unverified_v1", "oc_env.taxon_elevation_profiles")
_GLOSSARY = _blocked("glossary", "glossary_unverified_v1", "oc_glossary.taxon_terms")
_EVIDENCE = _blocked("evidence", "evidence_unverified_v1", "oc_claims.evidence_item")
_MOLECULAR = _blocked("molecular", "molecular_unverified_v1", "oc_phylogeny.taxon_molecular_records")
_EDUCATION = _blocked("education", "education_unverified_v1", "ocu.taxon_learning_objects")


SOURCE_QUERIES: tuple[SourceQuery, ...] = (
    _OCCURRENCES,
    _GEOGRAPHY,
    _HABITAT,
    _CLIMATE,
    _ELEVATION,
    _TRAITS,
    _GLOSSARY,
    _LITERATURE,
    _EVIDENCE,
    _POLLINATORS,
    _MYCORRHIZA,
    _CONSERVATION,
    _MOLECULAR,
    _EDUCATION,
    _MEDIA,
)


def _meta(
    status: str,
    identifier_strategy: str,
    join_strategy: str,
    crosswalk_required: bool,
    confidence: str,
    expected: int,
    actual: int,
    notes: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "identifier_strategy": identifier_strategy,
        "join_strategy": join_strategy,
        "crosswalk_required": crosswalk_required,
        "confidence": confidence,
        "expected_record_count": expected,
        "actual_record_count": actual,
        "last_verification": "2026-07-15",
        "operator_notes": notes,
    }


_BUILD064_META: dict[str, dict[str, Any]] = {
    "occurrences": _meta(
        "READY WITH OPERATOR REVIEW", "direct taxon_id", "direct_id", False,
        "high", 580000, 26,
        "Curated occurrence source maps directly; bulk alternatives require a verified crosswalk.",
    ),
    "traits": _meta(
        "READY WITH OPERATOR REVIEW", "resolved consensus taxonomy_id", "resolved_view_id",
        False, "medium", 33791, 2807,
        "Resolved-view id join; missing rows represent incomplete trait coverage.",
    ),
    "pollinators": _meta(
        "READY WITH OPERATOR REVIEW", "orchid taxonomy id plus canonical-name bridge",
        "name_join (crosswalk-upgradable)", True, "high", 23, 23,
        "Small clean source; crosswalk remains required for an identifier-only bridge.",
    ),
    "mycorrhiza": _meta(
        "PARTIALLY READY", "orchid taxonomy id plus canonical-name bridge",
        "name_join (crosswalk-upgradable)", True, "medium", 462, 626,
        "Name collisions and orphan names require review before population.",
    ),
    "conservation": _meta(
        "PARTIALLY READY", "direct taxon_id", "direct_id", False, "high", 2, 2,
        "Production conservation source is currently sparse.",
    ),
    "climate": _meta(
        "BLOCKED", "direct taxonomy_id but source is a proxy not climate", "direct_id",
        False, "low", 0, 19263,
        "Environmental proxy only, not modelled bioclim; blocked for climate claims.",
    ),
    "literature": _meta(
        "PARTIALLY READY", "NO taxon id on source (scientific_name only)", "name_join",
        True, "medium", 35, 29,
        "No taxon id exists upstream; unmatched names cannot be crosswalked yet.",
    ),
    "media": _meta(
        "READY", "direct taxonomy_id", "direct_id", False, "high", 51, 51,
        "Direct id join through the authoritative gallery view.",
    ),
}

for _domain in (
    "geography", "habitat", "elevation", "glossary", "evidence", "molecular", "education"
):
    _BUILD064_META[_domain] = _meta(
        "BLOCKED",
        "adapter source named but taxon mapping not verified",
        "unverified_fail_closed",
        True,
        "low",
        0,
        0,
        "Explicit fail-closed registration only; verify projection, provenance, and taxon mapping before enabling.",
    )

SOURCE_QUERIES = tuple(
    replace(query, metadata={**_BUILD064_META[query.domain], **query.metadata})
    for query in SOURCE_QUERIES
)


def registry_by_domain() -> dict[str, SourceQuery]:
    return {query.domain: query for query in SOURCE_QUERIES}


def enabled_queries() -> dict[str, str]:
    out: dict[str, str] = {}
    for query in SOURCE_QUERIES:
        if query.enabled and query.sql:
            assert_safe_sql(query.sql)
            out[query.domain] = query.sql
    return out


def blocked_domains() -> dict[str, str]:
    return {
        query.domain: (query.blocked_reason or "disabled")
        for query in SOURCE_QUERIES
        if not query.enabled
    }
