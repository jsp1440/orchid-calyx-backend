"""OC-COMPLETE-003: canonical scientific coverage and backfill matrix.

Produces one machine-readable current-state matrix that tells the orchestrator
what is actually complete, stale, missing, unlinked, or backfill-required across
all major scientific domains.

Rules that govern this module mirror those in relationship_measurement.py:

**Absence is only reported from a join that ran.** A schema-discovery failure
is ``unavailable``, never ``absent``.

**No KG mutation.** This module issues SELECT and catalog reads only.

**No fabricated zero.** Any domain whose table cannot be confirmed returns
``unknown`` state with the specific reason. ``0`` only appears when a live
COUNT(*) returned zero.

**generated_at and evidence_state on every metric.** Consumers must be able
to tell fresh from stale measurements and confirmed from estimated row counts.
"""

from __future__ import annotations

import datetime
from typing import Any

from app.readiness.relationship_measurement import (
    OBJECT_NAME_COLUMNS,
    OBJECT_TAXON_KEYS,
    TAXONOMY_KEYS,
    TAXONOMY_NAME_COLUMNS,
    TAXONOMY_TABLES,
    _unavailable,
    measure_declared_relationships,
    measure_link_relationship,
)

SCHEMA_VERSION = "oc-coverage-matrix/v1"

# Domains not yet in the canonical RELATIONSHIP_SPECS.
_TRAITS_SPEC: dict[str, Any] = {
    "name": "taxonomy_to_traits",
    "object_tables": (
        "oc_traits.trait_records",
        "oc_traits.traits",
        "public.trait_measurements",
        "public.orchid_traits",
        "oc_knowledge.trait_records",
    ),
    "required_value_columns": (
        "trait_value",
        "normalized_value",
        "value",
    ),
}

_IMAGES_SPEC: dict[str, Any] = {
    "name": "taxonomy_to_images",
    "object_tables": (
        "oc_media.media",
        "oc_media.images",
        "public.orchid_images",
        "public.media_records",
        "oc_media.orchid_media",
    ),
    "required_value_columns": (
        "image_url",
        "url",
        "media_url",
        "file_path",
    ),
}

# Ordered list for backfill priority output.
_ALL_DOMAIN_NAMES = (
    "taxonomy_to_occurrences",
    "taxonomy_to_elevation",
    "taxonomy_to_climate",
    "taxonomy_to_literature",
    "taxonomy_to_pollinators",
    "taxonomy_to_mycorrhiza",
    "taxonomy_to_habitat",
    "taxonomy_to_conservation",
    "taxonomy_to_traits",
    "taxonomy_to_images",
)


def _measure_extra_domain(cur, spec: dict[str, Any]) -> dict[str, Any]:
    """Measure a domain not yet in RELATIONSHIP_SPECS, isolating exceptions."""
    name = spec["name"]
    try:
        return measure_link_relationship(
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
        return _unavailable(name, f"Measurement raised {type(exc).__name__}: {exc}")


def _kg_domain_readiness(cur) -> dict[str, Any]:
    """Check KG domain readiness via catalog probes. No writes."""
    domains: dict[str, Any] = {}
    kg_tables = {
        "taxon_literature_edges": "oc_graph.taxon_literature_edges",
        "interaction_edges": "oc_interactions.orchid_interaction_edges",
        "fungal_associations": "oc_mycorrhiza.orchid_fungal_associations",
        "conservation_records": "oc_conservation.conservation_records",
        "habitat_claims": "public.oc_species_habitat_claims",
    }
    for domain_key, table in kg_tables.items():
        try:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (table,))
            row = cur.fetchone()
            present = bool(row[0] if not isinstance(row, dict) else row["present"])
            if present:
                cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                count_row = cur.fetchone()
                count = int(
                    count_row[0] if not isinstance(count_row, dict)
                    else next(iter(count_row.values()))
                )
                domains[domain_key] = {
                    "table": table,
                    "row_count": count,
                    "state": "measured",
                    "evidence_state": "live_count",
                    "graph_mutation": False,
                }
            else:
                domains[domain_key] = _unavailable(
                    domain_key,
                    f"Table {table!r} does not exist in catalog.",
                )
        except Exception as exc:  # noqa: BLE001
            domains[domain_key] = _unavailable(
                domain_key,
                f"Catalog probe raised {type(exc).__name__}: {exc}",
            )
    return domains


def _taxonomy_summary(cur) -> dict[str, Any]:
    """Return canonical taxon count from first existing taxonomy table."""
    for table in TAXONOMY_TABLES:
        try:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (table,))
            row = cur.fetchone()
            if not (row[0] if not isinstance(row, dict) else row["present"]):
                continue
            cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            count_row = cur.fetchone()
            count = int(
                count_row[0] if not isinstance(count_row, dict)
                else next(iter(count_row.values()))
            )
            return {
                "source_table": table,
                "taxon_count": count,
                "evidence_state": "live_count",
                "state": "measured",
            }
        except Exception:  # noqa: BLE001
            continue
    return _unavailable(
        "taxonomy",
        "No taxonomy table from the candidate list is reachable.",
    )


def _prioritized_backfill(domains: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ordered backfill items for domains in unavailable or zero state."""
    items: list[dict[str, Any]] = []
    # Priority order: domains we know are foundational first.
    ordered = [
        ("taxonomy_to_occurrences", "P1", "Primary field observation record"),
        ("taxonomy_to_literature", "P1", "Scientific source corpus"),
        ("taxonomy_to_traits", "P2", "Phenotypic trait binding"),
        ("taxonomy_to_images", "P2", "Media and herbarium specimen coverage"),
        ("taxonomy_to_elevation", "P2", "Elevation and habitat envelope data"),
        ("taxonomy_to_pollinators", "P2", "Pollination interaction network"),
        ("taxonomy_to_mycorrhiza", "P2", "Mycorrhizal association network"),
        ("taxonomy_to_habitat", "P3", "Species habitat claims"),
        ("taxonomy_to_conservation", "P3", "Conservation status records"),
        ("taxonomy_to_climate", "P3", "Climate envelope profiles"),
    ]
    for domain_name, priority, rationale in ordered:
        m = domains.get(domain_name, {})
        state = m.get("state", "unavailable")
        if state == "unavailable":
            items.append({
                "domain": domain_name,
                "priority": priority,
                "action": "measure_or_ingest",
                "rationale": rationale,
                "current_state": "unavailable",
                "detail": m.get("detail", "No measurement available"),
            })
        elif state == "measured":
            linked = (
                m["linked_object_count"] if "linked_object_count" in m
                else m.get("row_count")
            )
            if isinstance(linked, int) and linked == 0:
                items.append({
                    "domain": domain_name,
                    "priority": priority,
                    "action": "ingest",
                    "rationale": rationale,
                    "current_state": "empty",
                    "detail": "Measurement ran but returned zero linked rows.",
                })
        # Masking warnings from the measurement
        for warning in m.get("masking_warnings", []):
            items.append({
                "domain": domain_name,
                "priority": priority,
                "action": "review_source_selection",
                "rationale": "Possible non-authoritative relation selected",
                "current_state": "masked",
                "detail": warning,
            })
    return items


def build_coverage_matrix(
    cur,
    *,
    literature_repository=None,
) -> dict[str, Any]:
    """Build the canonical scientific coverage matrix.

    Args:
        cur: A live DB cursor for SELECT and catalog queries, or None.  When
            None, all domains report ``unavailable`` with the specific reason;
            the matrix is still returned with schema_version and generated_at so
            callers can record that a measurement attempt was made.
        literature_repository: Optional ``LiteratureResultRepository`` for
            extraction pipeline stats.  Absent means that section reports
            ``unavailable``.

    Returns:
        Machine-readable coverage matrix dict.  ``graph_mutation`` is always
        False; ``schema_version`` and ``generated_at`` are always present.
    """
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if cur is None:
        detail = (
            "No live database cursor was available for this matrix run. "
            "All domain measurements are unknown; this is not a finding that "
            "any domain is absent."
        )
        unavailable_all = {
            name: _unavailable(name, detail) for name in _ALL_DOMAIN_NAMES
        }
        taxonomy = _unavailable("taxonomy", detail)
        kg_domains: dict[str, Any] = {
            k: _unavailable(k, detail)
            for k in (
                "taxon_literature_edges",
                "interaction_edges",
                "fungal_associations",
                "conservation_records",
                "habitat_claims",
            )
        }
        backfill = _prioritized_backfill(unavailable_all)
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "graph_mutation": False,
            "db_available": False,
            "taxonomy": taxonomy,
            "domains": unavailable_all,
            "kg_domain_readiness": kg_domains,
            "literature_pipeline": _unavailable("literature_pipeline", detail),
            "backfill_priority_list": backfill,
        }

    taxonomy = _taxonomy_summary(cur)
    declared = measure_declared_relationships(cur)
    extra_traits = _measure_extra_domain(cur, _TRAITS_SPEC)
    extra_images = _measure_extra_domain(cur, _IMAGES_SPEC)

    domains: dict[str, Any] = dict(declared)
    domains["taxonomy_to_traits"] = extra_traits
    domains["taxonomy_to_images"] = extra_images

    kg_domains = _kg_domain_readiness(cur)

    if literature_repository is not None:
        from app.literature_extraction.coverage_audit import (
            audit_literature_extraction_coverage,
        )
        literature_pipeline: dict[str, Any] = audit_literature_extraction_coverage(
            cur, literature_repository
        )
    else:
        literature_pipeline = _unavailable(
            "literature_pipeline",
            "No literature_repository supplied; extraction pipeline stats not available.",
        )

    backfill = _prioritized_backfill(domains)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "graph_mutation": False,
        "db_available": True,
        "taxonomy": taxonomy,
        "domains": domains,
        "kg_domain_readiness": kg_domains,
        "literature_pipeline": literature_pipeline,
        "backfill_priority_list": backfill,
    }
