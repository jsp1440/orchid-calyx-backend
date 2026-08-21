#!/usr/bin/env python3
"""Darwin Core Archive exporter for harvested occurrence/image data.

BUILD-093 vendored exactly three mature harvesters (iNaturalist, GBIF,
EOL/TraitBank; see harvesters/__init__.py and harvesters/execution.py). Their
combined output lands in ``public.occurrences`` and ``public.images``
(schema owned by harvesters/gbif_api.py). This module adds a read-only
*export* capability on top of that existing data: it does not call any
external API, does not write to the database, and does not touch the
harvester control plane or the taxonomy/canonical-graph pipelines.

Ported from the legacy ``jsp1440/orchid-continuum`` repository's
``darwin_core_exporter.py`` (Flask/OrchidRecord era) and adapted to this
repo's actual schema and harvester conventions:

  * reuses ``harvesters.gbif_api`` connection/introspection helpers instead
    of assuming a fixed schema (mirrors ``insert_occurrences_if_possible`` /
    ``insert_images_if_possible``'s defensive column checks);
  * unlike the legacy exporter -- which stamped every record with one
    blanket institutional license -- this version preserves each source
    record's own ``license`` value (GBIF and iNaturalist occurrences carry
    per-record licenses; collapsing them to one blanket license would be a
    provenance/licensing regression), falling back to an explicit
    "UNKNOWN_LICENSE_SEE_SOURCE" marker rather than guessing;
  * every row keeps its harvester ``source`` and ``source_id`` as
    ``collectionCode`` / ``catalogNumber`` so a consumer (e.g. GBIF's own
    ingestion review) can trace each exported record back to the harvester
    run that produced it, consistent with this repo's provenance-first
    conventions;
  * exact decimal coordinates are omitted by default. Exporting exact
    coordinates requires both an explicit function argument and a high-
    friction server/operator acknowledgement. This is defense-in-depth for
    legacy/public-harvester export paths and is not a substitute for record-
    level policy and database RLS on future partner-restricted datasets.

Bounded by design: ``limit`` defaults to a finite cap so this cannot become
an unbounded full-table export by accident.
"""

from __future__ import annotations

import csv
import logging
import os
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("darwin_core_export")

DEFAULT_EXPORT_LIMIT = 20_000
UNKNOWN_LICENSE_MARKER = "UNKNOWN_LICENSE_SEE_SOURCE"
EXACT_COORDINATE_EXPORT_ACK = "YES_I_UNDERSTAND_THIS_EXPORTS_EXACT_ORCHID_LOCATIONS"


# harvesters.gbif_api raises at import time when DATABASE_URL is unset (see
# harvesters/__init__.py). This module is imported by tooling/tests that do
# not always have DATABASE_URL set, so -- exactly like
# harvesters/execution.py's dispatch functions -- the dependency is imported
# lazily, only once a DB call is actually made.
def _get_conn():
    from harvesters.gbif_api import get_conn

    return get_conn()


def _table_exists(conn, name: str, schema: str = "public") -> bool:
    from harvesters.gbif_api import table_exists

    return table_exists(conn, name, schema)


def _get_columns(conn, name: str, schema: str = "public") -> list[str]:
    from harvesters.gbif_api import get_columns

    return get_columns(conn, name, schema)


def _require_exact_coordinate_export() -> None:
    """Require deliberate operator acknowledgement before exact-site export."""

    if os.getenv("OC_ALLOW_EXACT_DWC_EXPORT") != EXACT_COORDINATE_EXPORT_ACK:
        raise PermissionError(
            "Exact Darwin Core coordinates are disabled by security policy. "
            "Use the default redacted export unless exact locality disclosure "
            "has been separately authorized."
        )


DWC_FIELDS = [
    "occurrenceID",
    "basisOfRecord",
    "scientificName",
    "taxonRank",
    "kingdom",
    "family",
    "genus",
    "specificEpithet",
    "decimalLatitude",
    "decimalLongitude",
    "country",
    "locality",
    "recordedBy",
    "associatedMedia",
    "license",
    "rightsHolder",
    "institutionCode",
    "collectionCode",
    "catalogNumber",
    "datasetName",
    "modified",
]

DWC_TERM_BASE = "http://rs.tdwg.org/dwc/terms/"
DC_TERM_BASE = "http://purl.org/dc/terms/"

# Terms that live under the Dublin Core namespace instead of Darwin Core.
_DC_FIELDS = {"license", "rightsHolder", "modified"}


def _term_uri(field: str) -> str:
    base = DC_TERM_BASE if field in _DC_FIELDS else DWC_TERM_BASE
    return f"{base}{field}"


def _fetch_merged_rows(conn, limit: int) -> list[dict[str, Any]]:
    """Merge ``public.occurrences`` and ``public.images`` by (source, source_id).

    Not every mature harvester writes both tables for every record: GBIF
    writes occurrences *and* images when media is present, while iNaturalist
    (harvesters/inat.py) writes only to ``images``. A FULL OUTER JOIN keyed
    on (source, source_id) is used so records from either harvester shape
    are represented exactly once, matching each harvester's own dedup key.
    """
    have_occurrences = _table_exists(conn, "occurrences")
    have_images = _table_exists(conn, "images")
    if not have_occurrences and not have_images:
        return []

    occ_cols = set(_get_columns(conn, "occurrences")) if have_occurrences else set()
    img_cols = set(_get_columns(conn, "images")) if have_images else set()

    def occ(col: str, default: str = "NULL") -> str:
        return f"o.{col}" if col in occ_cols else default

    def img(col: str, default: str = "NULL") -> str:
        return f"i.{col}" if col in img_cols else default

    both_joinable = (
        have_occurrences
        and have_images
        and {"source", "source_id"} <= occ_cols
        and {"source", "source_id"} <= img_cols
    )

    # Built explicitly per available table (rather than one templated query)
    # to avoid fragile string surgery when only one side of the join exists.
    if both_joinable:
        sql = f"""
            SELECT
                COALESCE(o.source, i.source) AS source,
                COALESCE(o.source_id, i.source_id) AS source_id,
                COALESCE({occ('scientific_name')}, {img('scientific_name')}) AS scientific_name,
                COALESCE({occ('genus')}, {img('genus')}) AS genus,
                COALESCE({occ('species')}, {img('species')}) AS species,
                {occ('taxon_rank')} AS taxon_rank,
                {img('country')} AS country,
                {img('latitude')} AS latitude,
                {img('longitude')} AS longitude,
                {img('photographer')} AS photographer,
                {img('license')} AS license,
                {img('url')} AS url
            FROM public.occurrences o
            FULL OUTER JOIN public.images i
                ON i.source = o.source AND i.source_id = o.source_id
            LIMIT %s
        """
    elif have_occurrences:
        sql = f"""
            SELECT
                o.source AS source,
                o.source_id AS source_id,
                {occ('scientific_name')} AS scientific_name,
                {occ('genus')} AS genus,
                {occ('species')} AS species,
                {occ('taxon_rank')} AS taxon_rank,
                NULL AS country, NULL AS latitude, NULL AS longitude,
                NULL AS photographer, NULL AS license, NULL AS url
            FROM public.occurrences o
            LIMIT %s
        """
    else:
        sql = f"""
            SELECT
                i.source AS source,
                i.source_id AS source_id,
                {img('scientific_name')} AS scientific_name,
                {img('genus')} AS genus,
                {img('species')} AS species,
                NULL AS taxon_rank,
                {img('country')} AS country,
                {img('latitude')} AS latitude,
                {img('longitude')} AS longitude,
                {img('photographer')} AS photographer,
                {img('license')} AS license,
                {img('url')} AS url
            FROM public.images i
            LIMIT %s
        """

    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        colnames = [d[0] for d in cur.description]
        rows = [dict(zip(colnames, row)) for row in cur.fetchall()]
    return rows


def to_dwc_record(
    row: dict[str, Any],
    *,
    institution_code: str,
    dataset_name: str,
    include_exact_coordinates: bool = False,
) -> dict[str, str]:
    """Map one merged occurrence/image row to a Darwin Core Occurrence record.

    License is preserved verbatim from the source row -- GBIF and
    iNaturalist both supply a per-record license -- and only falls back to
    ``UNKNOWN_LICENSE_MARKER`` when the harvested row genuinely has none.

    Exact coordinates are intentionally omitted unless the caller asks for
    them and the process has the explicit exact-locality acknowledgement.
    """
    source = (row.get("source") or "").strip()
    source_id = str(row.get("source_id") or "").strip()
    scientific_name = (row.get("scientific_name") or "").strip()
    genus = (row.get("genus") or "").strip()
    species = (row.get("species") or "").strip()
    lat = row.get("latitude")
    lon = row.get("longitude")
    license_value = (row.get("license") or "").strip() or UNKNOWN_LICENSE_MARKER

    if include_exact_coordinates:
        _require_exact_coordinate_export()
        latitude = "" if lat is None else str(lat)
        longitude = "" if lon is None else str(lon)
    else:
        latitude = ""
        longitude = ""

    return {
        "occurrenceID": f"{source}:{source_id}" if source and source_id else "",
        "basisOfRecord": "HumanObservation" if source == "inaturalist" else "Occurrence",
        "scientificName": scientific_name,
        "taxonRank": (row.get("taxon_rank") or "").strip(),
        "kingdom": "Plantae",
        "family": "Orchidaceae",
        "genus": genus,
        "specificEpithet": species,
        "decimalLatitude": latitude,
        "decimalLongitude": longitude,
        "country": (row.get("country") or "").strip(),
        "locality": "",
        "recordedBy": (row.get("photographer") or "").strip(),
        "associatedMedia": (row.get("url") or "").strip(),
        "license": license_value,
        "rightsHolder": (row.get("photographer") or "").strip(),
        "institutionCode": institution_code,
        "collectionCode": source,
        "catalogNumber": source_id,
        "datasetName": dataset_name,
        "modified": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_occurrence_txt(records: Iterable[dict[str, str]], output_file: str) -> int:
    count = 0
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DWC_FIELDS, delimiter="\t")
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in DWC_FIELDS})
            count += 1
    return count


def build_meta_xml() -> str:
    field_lines = []
    for index, field in enumerate(DWC_FIELDS):
        field_lines.append(f'    <field index="{index + 1}" term="{_term_uri(field)}"/>')
    fields_xml = "\n".join(field_lines)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<archive xmlns="http://rs.tdwg.org/dwc/text/" metadata="eml.xml">
  <core encoding="UTF-8" linesTerminatedBy="\\n" fieldsTerminatedBy="\\t" fieldsEnclosedBy="" ignoreHeaderLines="1" rowType="http://rs.tdwg.org/dwc/terms/Occurrence">
    <files>
      <location>occurrence.txt</location>
    </files>
    <id index="0"/>
{fields_xml}
  </core>
</archive>"""


def build_eml_xml(
    *,
    dataset_name: str,
    contact_org: str,
    contact_email: str,
    record_count: int,
    exact_coordinates_included: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    location_statement = (
        "Exact decimal coordinates are included under explicit locality-disclosure authorization."
        if exact_coordinates_included
        else "Exact decimal coordinates are omitted by the exporter security default."
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<eml:eml xmlns:eml="eml://ecoinformatics.org/eml-2.1.1"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="eml://ecoinformatics.org/eml-2.1.1 http://rs.gbif.org/schema/eml-gbif-profile/1.1/eml.xsd"
         packageId="orchid-continuum-calyx-{now.strftime('%Y%m%d%H%M%S')}" system="Orchid Continuum / Calyx">
  <dataset>
    <title>{dataset_name}</title>
    <creator>
      <organizationName>{contact_org}</organizationName>
      <electronicMailAddress>{contact_email}</electronicMailAddress>
    </creator>
    <pubDate>{now.strftime('%Y-%m-%d')}</pubDate>
    <language>en</language>
    <abstract>
      <para>Darwin Core occurrence export of {record_count} record(s) harvested by the Orchid
      Continuum's governed GBIF and iNaturalist harvesters (BUILD-093). Each record retains
      its original source and per-record license and preserves collectionCode/catalogNumber
      for traceability back to the originating harvester run. {location_statement}</para>
    </abstract>
    <keywordSet>
      <keyword>Orchidaceae</keyword>
      <keyword>occurrence</keyword>
      <keyword>Darwin Core</keyword>
    </keywordSet>
    <coverage>
      <taxonomicCoverage>
        <generalTaxonomicCoverage>Family Orchidaceae</generalTaxonomicCoverage>
        <taxonomicClassification>
          <taxonRankName>family</taxonRankName>
          <taxonRankValue>Orchidaceae</taxonRankValue>
        </taxonomicClassification>
      </taxonomicCoverage>
    </coverage>
    <contact>
      <organizationName>{contact_org}</organizationName>
      <electronicMailAddress>{contact_email}</electronicMailAddress>
    </contact>
  </dataset>
</eml:eml>"""


def create_zip_archive(output_dir: str, archive_file: str) -> str:
    with zipfile.ZipFile(archive_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("occurrence.txt", "meta.xml", "eml.xml"):
            zf.write(os.path.join(output_dir, name), name)
    return archive_file


def export_to_dwc_archive(
    output_dir: str = "dwc_export",
    *,
    limit: int = DEFAULT_EXPORT_LIMIT,
    institution_code: Optional[str] = None,
    dataset_name: Optional[str] = None,
    contact_org: Optional[str] = None,
    contact_email: Optional[str] = None,
    include_exact_coordinates: bool = False,
    conn=None,
) -> dict[str, Any]:
    """Export harvested occurrence/image data to a Darwin Core Archive zip.

    Read-only against ``public.occurrences`` / ``public.images``; makes no
    external API calls and performs no writes. ``limit`` bounds the export
    (default 20,000 rows) so a single call cannot become an unbounded dump.

    Exact coordinates are omitted by default. Opting in requires both
    ``include_exact_coordinates=True`` and the explicit environment
    acknowledgement enforced by ``_require_exact_coordinate_export``.
    """
    if include_exact_coordinates:
        _require_exact_coordinate_export()

    institution_code = institution_code or os.environ.get("DWC_INSTITUTION_CODE", "FCOS")
    dataset_name = dataset_name or os.environ.get(
        "DWC_DATASET_NAME", "Orchid Continuum Harvested Occurrence Index"
    )
    contact_org = contact_org or os.environ.get("DWC_CONTACT_ORG", "Five Cities Orchid Society")
    contact_email = contact_email or os.environ.get("DWC_CONTACT_EMAIL", "info@fivecitiescalifornia.org")

    owns_conn = conn is None
    conn = conn or _get_conn()
    try:
        rows = _fetch_merged_rows(conn, limit)
    finally:
        if owns_conn:
            conn.close()

    records = [
        to_dwc_record(
            row,
            institution_code=institution_code,
            dataset_name=dataset_name,
            include_exact_coordinates=include_exact_coordinates,
        )
        for row in rows
        if row.get("source") and row.get("source_id")
    ]

    os.makedirs(output_dir, exist_ok=True)
    occurrence_file = os.path.join(output_dir, "occurrence.txt")
    written = write_occurrence_txt(records, occurrence_file)

    with open(os.path.join(output_dir, "meta.xml"), "w", encoding="utf-8") as f:
        f.write(build_meta_xml())

    with open(os.path.join(output_dir, "eml.xml"), "w", encoding="utf-8") as f:
        f.write(
            build_eml_xml(
                dataset_name=dataset_name,
                contact_org=contact_org,
                contact_email=contact_email,
                record_count=written,
                exact_coordinates_included=include_exact_coordinates,
            )
        )

    archive_file = os.path.join(output_dir, "orchid_continuum_dwc_archive.zip")
    create_zip_archive(output_dir, archive_file)

    logger.info(
        "Darwin Core Archive exported: %s records -> %s (exact_coordinates=%s)",
        written,
        archive_file,
        include_exact_coordinates,
    )
    return {
        "record_count": written,
        "archive_file": archive_file,
        "output_dir": output_dir,
        "exact_coordinates_included": include_exact_coordinates,
    }


if __name__ == "__main__":
    result = export_to_dwc_archive()
    print(f"Exported {result['record_count']} records to {result['archive_file']}")
