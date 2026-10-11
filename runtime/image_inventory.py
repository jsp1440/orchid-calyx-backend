"""Image inventory, coverage and gap analysis by accepted species and genus.

Two layers:

* :func:`compute_coverage` is a pure function over reference-image records,
  accepted taxa, and description/key indexes. It scales linearly and handles
  the ~30,000 accepted orchid species in memory.
* :class:`ImageInventoryRepository` is a bounded, read-only probe of the image
  tables that already exist in the Calyx database (``public.orchid_images``,
  legacy harvester ``public.images``, ``oc_core.media_assets`` /
  ``oc_core.record_media_link`` and ``oc_vision.reference_image_set_items``).
  It only runs ``information_schema`` lookups and ``GROUP BY`` aggregates -
  it never downloads images, never writes, and reports a table as
  ``unavailable`` rather than inventing zero counts when it is absent.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from runtime.reference_images import (
    DIAGNOSTIC_FLORAL_ORGANS,
    DIAGNOSTIC_FLORAL_VIEWPOINTS,
    VEGETATIVE_ORGANS,
    ReferenceImageRecord,
)

COVERAGE_SCHEMA_VERSION = "oc-image-coverage/v1"

COVERAGE_FLAGS = (
    "accessible_images",
    "multiple_images",
    "verified_reference_images",
    "diagnostic_floral_views",
    "vegetative_views",
    "herbarium_images",
    "usable_descriptions",
    "identification_keys",
)


@dataclass(frozen=True)
class AcceptedTaxon:
    taxon_id: str
    scientific_name: str
    genus: str
    rank: str = "species"


@dataclass(frozen=True)
class SpeciesCoverage:
    taxon_id: str
    scientific_name: str
    genus: str
    image_count: int
    accessible_image_count: int
    distinct_specimen_count: int
    verified_reference_count: int
    licensed_image_count: int
    accessible_images: bool
    multiple_images: bool
    verified_reference_images: bool
    diagnostic_floral_views: bool
    vegetative_views: bool
    herbarium_images: bool
    usable_descriptions: bool
    identification_keys: bool
    insufficient_evidence: bool
    gaps: tuple[str, ...]
    priority_score: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_diagnostic_floral(record: ReferenceImageRecord) -> bool:
    return record.organ in DIAGNOSTIC_FLORAL_ORGANS and (
        record.viewpoint in DIAGNOSTIC_FLORAL_VIEWPOINTS
        or record.organ in {"labellum", "column"}
    )


def _species_coverage(
    taxon: AcceptedTaxon,
    records: list[ReferenceImageRecord],
    *,
    has_description: bool,
    has_key: bool,
) -> SpeciesCoverage:
    usable = [r for r in records if r.accessible and r.quality != "poor"]
    specimens = {r.specimen_group_key for r in usable}
    verified = [r for r in usable if r.expert_confirmed and r.license_allowed]
    floral = any(_is_diagnostic_floral(r) for r in usable)
    vegetative = any(r.organ in VEGETATIVE_ORGANS for r in usable)
    herbarium = any(
        r.record_kind == "preserved_specimen" or r.organ == "herbarium_sheet"
        for r in usable
    )
    flags = {
        "accessible_images": bool(usable),
        "multiple_images": len(specimens) > 1,
        "verified_reference_images": bool(verified),
        "diagnostic_floral_views": floral,
        "vegetative_views": vegetative,
        "herbarium_images": herbarium,
        "usable_descriptions": has_description,
        "identification_keys": has_key,
    }
    gaps = tuple(name for name, present in flags.items() if not present)
    # Sufficient evidence for reference-based identification: a verified
    # reference image, a diagnostic floral view and a formal description.
    insufficient = not (
        flags["verified_reference_images"] and floral and has_description
    )
    # Priority favours scientifically useful gaps: a verified diagnostic floral
    # image matters more than another unverified habit shot.
    priority = (
        (3.0 if not flags["verified_reference_images"] else 0.0)
        + (2.0 if not floral else 0.0)
        + (1.5 if not has_description else 0.0)
        + (1.0 if not has_key else 0.0)
        + (0.5 if not vegetative else 0.0)
        # Species with *some* accessible but unverified imagery are cheaper
        # to close through expert verification than species with none.
        + (0.75 if usable and not verified else 0.0)
    )
    return SpeciesCoverage(
        taxon_id=taxon.taxon_id,
        scientific_name=taxon.scientific_name,
        genus=taxon.genus,
        image_count=len(records),
        accessible_image_count=len(usable),
        distinct_specimen_count=len(specimens),
        verified_reference_count=len(verified),
        licensed_image_count=sum(1 for r in usable if r.license_allowed),
        insufficient_evidence=insufficient,
        gaps=gaps,
        priority_score=round(priority, 3),
        **flags,
    )


def compute_coverage(
    records: Iterable[ReferenceImageRecord],
    accepted_taxa: Iterable[AcceptedTaxon],
    *,
    described_taxon_ids: Iterable[str] = (),
    keyed_taxon_ids: Iterable[str] = (),
    taxonomy_version: str | None = None,
    gap_limit: int = 100,
) -> dict[str, Any]:
    """Coverage by accepted species and genus, plus a prioritised gap list.

    Images whose accepted taxon is not in ``accepted_taxa`` are reported as
    ``unmatched`` rather than silently dropped or forced onto a species.
    """
    taxa = {t.taxon_id: t for t in accepted_taxa if t.rank == "species"}
    described = set(described_taxon_ids)
    keyed = set(keyed_taxon_ids)
    by_taxon: dict[str, list[ReferenceImageRecord]] = defaultdict(list)
    unmatched = 0
    unresolved = 0
    version_mismatch = 0
    for record in records:
        if not record.accepted_taxon_id:
            unresolved += 1
            continue
        if record.accepted_taxon_id not in taxa:
            unmatched += 1
            continue
        if (
            taxonomy_version
            and record.taxonomy_version
            and record.taxonomy_version != taxonomy_version
        ):
            version_mismatch += 1
        by_taxon[record.accepted_taxon_id].append(record)

    species = [
        _species_coverage(
            taxon,
            by_taxon.get(taxon_id, []),
            has_description=taxon_id in described,
            has_key=taxon_id in keyed,
        )
        for taxon_id, taxon in sorted(taxa.items())
    ]

    totals = {
        flag: sum(1 for s in species if getattr(s, flag)) for flag in COVERAGE_FLAGS
    }
    totals["insufficient_evidence"] = sum(1 for s in species if s.insufficient_evidence)
    total_species = len(species)

    genera: dict[str, dict[str, Any]] = {}
    for s in species:
        g = genera.setdefault(
            s.genus,
            {
                "genus": s.genus,
                "species_count": 0,
                "image_count": 0,
                **{f: 0 for f in COVERAGE_FLAGS},
                "insufficient_evidence": 0,
            },
        )
        g["species_count"] += 1
        g["image_count"] += s.accessible_image_count
        for flag in (*COVERAGE_FLAGS, "insufficient_evidence"):
            g[flag] += int(getattr(s, flag))
    for g in genera.values():
        n = g["species_count"] or 1
        g["verified_reference_fraction"] = round(g["verified_reference_images"] / n, 4)
        g["accessible_image_fraction"] = round(g["accessible_images"] / n, 4)

    gaps = sorted(
        (s for s in species if s.insufficient_evidence),
        key=lambda s: (-s.priority_score, s.genus, s.scientific_name),
    )[: max(0, gap_limit)]

    return {
        "schema_version": COVERAGE_SCHEMA_VERSION,
        "taxonomy_version": taxonomy_version,
        "accepted_species": total_species,
        "totals": totals,
        "fractions": {
            k: round(v / total_species, 4) if total_species else None
            for k, v in totals.items()
        },
        "image_records": {
            "matched": sum(len(v) for v in by_taxon.values()),
            "unresolved_taxon": unresolved,
            "unmatched_taxon": unmatched,
            "taxonomy_version_mismatch": version_mismatch,
        },
        "genera": sorted(genera.values(), key=lambda g: g["genus"]),
        "priority_gaps": [g.as_dict() for g in gaps],
        "species": [s.as_dict() for s in species],
        "rules": [
            "coverage counts images per accepted species, never per verbatim name",
            "images without a resolved accepted taxon are reported, not assigned",
            "verified reference requires expert verification and an allowed license",
            "sufficient evidence requires a verified reference, a diagnostic floral view and a description",
        ],
    }


# -- read-only database inventory -------------------------------------------

# Candidate tables in probe order; each entry names the columns that, when
# present, carry the taxon link, URL, license, and occurrence reference.
INVENTORY_TABLES: tuple[dict[str, Any], ...] = (
    {
        "table": "public.orchid_images",
        "taxon": ("taxonomy_id", "taxon_id", "accepted_taxon_id"),
        "url": ("image_url",),
        "license": ("image_license",),
        "occurrence": ("gbif_occurrence_key",),
        "source": ("image_source",),
    },
    {
        "table": "public.images",
        "taxon": ("scientific_name",),
        "url": ("url",),
        "license": ("license",),
        "occurrence": ("source_id",),
        "source": ("source",),
    },
    {
        "table": "oc_core.media_assets",
        "taxon": ("taxon_id", "accepted_taxon_id"),
        "url": ("url", "media_url", "access_uri"),
        "license": ("license", "license_code"),
        "occurrence": ("source_record_id", "occurrence_id"),
        "source": ("source",),
    },
    {
        "table": "oc_vision.reference_image_set_items",
        "taxon": ("taxon_id",),
        "url": ("image_id",),
        "license": ("license",),
        "occurrence": ("media_id",),
        "source": ("source",),
    },
)

Executor = Callable[[str, Mapping[str, Any]], list[Mapping[str, Any]]]


class ImageInventoryRepository:
    """Bounded read-only inventory over the existing image tables.

    ``execute`` runs one SQL statement with bound parameters and returns rows
    as mappings; it is injected so tests run without Postgres and so callers
    can wrap it in a read-only transaction.
    """

    def __init__(self, execute: Executor, *, max_sources: int = 50) -> None:
        self._execute = execute
        self._max_sources = max_sources

    def _columns(self, table: str) -> set[str]:
        schema, name = table.split(".", 1)
        rows = self._execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :name",
            {"schema": schema, "name": name},
        )
        return {str(r["column_name"]) for r in rows}

    @staticmethod
    def _pick(columns: set[str], options: tuple[str, ...]) -> str | None:
        return next((c for c in options if c in columns), None)

    def probe_table(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        table = spec["table"]
        try:
            columns = self._columns(table)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - driver specific
            return {
                "table": table,
                "state": "unavailable",
                "reason": type(exc).__name__,
            }
        if not columns:
            return {"table": table, "state": "unavailable", "reason": "table_not_found"}
        taxon = self._pick(columns, spec["taxon"])
        url = self._pick(columns, spec["url"])
        lic = self._pick(columns, spec["license"])
        occ = self._pick(columns, spec["occurrence"])
        src = self._pick(columns, spec["source"])

        # Identifiers below come only from the fixed allowlist above, never
        # from request input, so interpolating them is safe.
        def nn(col: str | None) -> str:
            return (
                f"COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col}::text <> '')"
                if col
                else "NULL"
            )

        summary_sql = (
            f"SELECT COUNT(*) AS total, {nn(url)} AS with_url, {nn(taxon)} AS with_taxon, "
            f"{nn(lic)} AS with_license, {nn(occ)} AS with_occurrence, "
            f"COUNT(DISTINCT {taxon}) AS distinct_taxa FROM {table}"
            if taxon
            else f"SELECT COUNT(*) AS total, {nn(url)} AS with_url, NULL AS with_taxon, "
            f"{nn(lic)} AS with_license, {nn(occ)} AS with_occurrence, NULL AS distinct_taxa FROM {table}"
        )
        try:
            summary = dict(self._execute(summary_sql, {})[0])
            by_source = (
                [
                    dict(r)
                    for r in self._execute(
                        f"SELECT {src}::text AS source, COUNT(*) AS images FROM {table} "
                        f"GROUP BY 1 ORDER BY 2 DESC LIMIT :limit",
                        {"limit": self._max_sources},
                    )
                ]
                if src
                else []
            )
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - driver specific
            return {
                "table": table,
                "state": "unavailable",
                "reason": type(exc).__name__,
            }
        return {
            "table": table,
            "state": "available",
            "columns_used": {
                "taxon": taxon,
                "url": url,
                "license": lic,
                "occurrence": occ,
                "source": src,
            },
            "taxon_link_kind": "name"
            if taxon == "scientific_name"
            else ("id" if taxon else "none"),
            "counts": {
                k: (int(v) if v is not None else None) for k, v in summary.items()
            },
            "by_source": by_source,
        }

    def inventory(self) -> dict[str, Any]:
        tables = [self.probe_table(spec) for spec in INVENTORY_TABLES]
        return {
            "schema_version": "oc-image-inventory/v1",
            "read_only": True,
            "downloads_performed": 0,
            "tables": tables,
            "available_tables": [
                t["table"] for t in tables if t["state"] == "available"
            ],
            "notes": [
                "counts are aggregates over rows; image files were not fetched or verified",
                "an unavailable table is not evidence of zero images",
                "public.images links taxa by name only and needs exact reconciliation before coverage use",
            ],
        }

    def species_image_counts(self, *, limit: int = 50000) -> dict[str, Any]:
        """Images and distinct occurrences per ``taxonomy_id`` in orchid_images."""
        spec = INVENTORY_TABLES[0]
        columns = self._columns(spec["table"])
        taxon = self._pick(columns, spec["taxon"])
        if not columns or not taxon:
            return {"state": "unavailable", "rows": []}
        url = self._pick(columns, spec["url"]) or taxon
        occ = self._pick(columns, spec["occurrence"])
        lic = self._pick(columns, spec["license"])
        dup = (
            "AND COALESCE(i.is_duplicate, false) = false"
            if "is_duplicate" in columns
            else ""
        )
        rows = self._execute(
            f"SELECT i.{taxon}::text AS taxon_id, COUNT(*) AS images, "
            f"COUNT(DISTINCT {('i.' + occ) if occ else 'NULL'}) AS occurrences, "
            f"COUNT(*) FILTER (WHERE {('i.' + lic) if lic else 'NULL'} IS NOT NULL) AS licensed "
            f"FROM {spec['table']} i WHERE i.{url} IS NOT NULL {dup} "
            f"GROUP BY 1 ORDER BY 1 LIMIT :limit",
            {"limit": limit},
        )
        return {"state": "available", "rows": [dict(r) for r in rows]}
