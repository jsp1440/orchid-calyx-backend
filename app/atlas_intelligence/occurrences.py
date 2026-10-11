"""Atlas occurrence exploration: viewport queries, clustering, and summaries.

The browser must never download a global occurrence corpus. Every request here
is bounded by a viewport, a zoom level, and a hard row limit, and the response
is either locality-safe points or grid clusters built from locality-safe
positions.

Trust boundary
--------------
* Repositories return full-precision records. Nothing leaves this module until
  it has passed through :func:`app.atlas_intelligence.locality.resolve_location`
  for the *public* access level.
* Clusters are binned on displayed (already generalised) coordinates, or, for
  the server-side SQL aggregate, on integer-degree cells that nest every policy
  cell, positioned at the cell centre. Neither path can reveal a protected site
  more precisely than the point policy would.
* With no owner-approved source configured, the service reports
  ``source_not_configured``. It never substitutes demo, fixture, or provider
  data for an unavailable store.
"""

from __future__ import annotations

import base64
import binascii
import math
import os
import re
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .locality import resolve_location

CONTRACT_VERSION = "oc-atlas-occurrence-query-v1"
SUMMARY_CONTRACT_VERSION = "oc-atlas-occurrence-summary-v1"
TAXON_SEARCH_CONTRACT_VERSION = "oc-atlas-taxon-search-v1"

MAX_LIMIT = 2000
DEFAULT_LIMIT = 500
MAX_SCAN_ROWS = 25_000
POINT_MODE_MIN_ZOOM = 7
POLICY_MAX_CELL_DEG = 1.0

# Cluster cell ladder by zoom. Coarse rungs are whole degrees aligned at 0, so
# every locality-policy cell (1, 0.5, 0.25, 0.1, 0.05 degrees) nests inside one
# of them; binning raw or generalised coordinates then lands in the same cell.
CLUSTER_CELL_LADDER: tuple[float, ...] = (
    20.0,
    10.0,
    5.0,
    2.0,
    1.0,
    0.5,
    0.25,
    0.1,
    0.05,
)

QueryMode = Literal["auto", "points", "clusters"]


def cell_deg_for_zoom(zoom: float) -> float:
    index = max(0, min(len(CLUSTER_CELL_LADDER) - 1, math.floor(zoom)))
    return CLUSTER_CELL_LADDER[index]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BBox:
    """A WGS84 viewport. ``west > east`` means the box crosses the antimeridian."""

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("west", self.west, 180),
            ("east", self.east, 180),
            ("south", self.south, 90),
            ("north", self.north, 90),
        ):
            if not math.isfinite(value) or abs(value) > limit:
                raise ValueError(f"bbox {name} must be a finite value within ±{limit}")
        if self.south >= self.north:
            raise ValueError("bbox south must be less than north")
        if self.west == self.east:
            raise ValueError("bbox west and east must differ")

    @classmethod
    def parse(cls, raw: str) -> BBox:
        parts = [part.strip() for part in (raw or "").split(",")]
        if len(parts) != 4:
            raise ValueError("bbox must be 'west,south,east,north'")
        try:
            west, south, east, north = (float(part) for part in parts)
        except ValueError as exc:
            raise ValueError("bbox values must be numbers") from exc
        return cls(west, south, east, north)

    @classmethod
    def world(cls) -> BBox:
        return cls(-180.0, -90.0, 180.0, 90.0)

    @property
    def crosses_antimeridian(self) -> bool:
        return self.west > self.east

    def lon_ranges(self) -> tuple[tuple[float, float], ...]:
        if self.crosses_antimeridian:
            return ((self.west, 180.0), (-180.0, self.east))
        return ((self.west, self.east),)

    def contains(self, lat: float, lng: float) -> bool:
        if not self.south <= lat <= self.north:
            return False
        return any(lo <= lng <= hi for lo, hi in self.lon_ranges())

    def key(self) -> str:
        return f"{self.west:.4f},{self.south:.4f},{self.east:.4f},{self.north:.4f}"


def usable_coordinate(lat: float | None, lng: float | None) -> bool:
    """0,0 is a data error, not a place; out-of-range values are never drawn."""
    if lat is None or lng is None:
        return False
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return False
    if abs(lat) > 90 or abs(lng) > 180:
        return False
    return not (lat == 0 and lng == 0)


# ---------------------------------------------------------------------------
# Records and queries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OccurrenceRecord:
    """A full-precision record as stored. Never serialised directly."""

    occurrence_id: str
    decimal_latitude: float
    decimal_longitude: float
    scientific_name: str
    genus: str | None = None
    taxon_id: str | None = None
    coordinate_uncertainty_in_meters: float | None = None
    country_code: str | None = None
    year: int | None = None
    month: int | None = None
    event_date: str | None = None
    basis_of_record: str | None = None
    dataset_name: str | None = None
    institution_code: str | None = None
    license: str | None = None
    rights_holder: str | None = None
    references_uri: str | None = None
    iucn_category: str | None = None
    conservation_status: str | None = None
    assessment_resolved: bool | None = None
    locality: str | None = None


@dataclass(frozen=True)
class OccurrenceQuery:
    bbox: BBox
    zoom: float = 2.0
    taxon_id: str | None = None
    genus: str | None = None
    scientific_name: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    months: tuple[int, ...] = ()
    basis_of_record: str | None = None
    limit: int = DEFAULT_LIMIT
    cursor: str | None = None
    mode: QueryMode = "auto"

    def __post_init__(self) -> None:
        if not 0 <= self.zoom <= 24:
            raise ValueError("zoom must be between 0 and 24")
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must not follow year_to")
        if any(not 1 <= month <= 12 for month in self.months):
            raise ValueError("months must be between 1 and 12")
        if self.genus is not None and not _SAFE_GENUS.match(self.genus):
            raise ValueError("genus must be a single capitalised Latin genus name")
        if self.taxon_id is not None and not _SAFE_IDENTIFIER.match(self.taxon_id):
            raise ValueError("taxon_id contains unsupported characters")
        if self.scientific_name is not None and not _SAFE_NAME.match(
            self.scientific_name
        ):
            raise ValueError("scientific_name contains unsupported characters")

    def filter_key(self) -> str:
        return "|".join(
            str(part)
            for part in (
                self.taxon_id,
                self.genus,
                (self.scientific_name or "").lower() or None,
                self.year_from,
                self.year_to,
                ",".join(str(m) for m in sorted(self.months)),
                self.basis_of_record,
            )
        )

    def cache_key(self) -> str:
        return "|".join(
            (
                self.bbox.key(),
                f"{self.zoom:.2f}",
                self.filter_key(),
                str(self.limit),
                str(self.cursor),
                self.mode,
            )
        )

    def matches(self, record: OccurrenceRecord) -> bool:
        """In-memory filter semantics; the SQL repository must mirror these."""
        if not usable_coordinate(record.decimal_latitude, record.decimal_longitude):
            return False
        if not self.bbox.contains(record.decimal_latitude, record.decimal_longitude):
            return False
        if self.taxon_id is not None and record.taxon_id != self.taxon_id:
            return False
        if self.genus is not None and record.genus != self.genus:
            return False
        if (
            self.scientific_name is not None
            and (record.scientific_name or "").lower() != self.scientific_name.lower()
        ):
            return False
        if self.year_from is not None and (
            record.year is None or record.year < self.year_from
        ):
            return False
        if self.year_to is not None and (
            record.year is None or record.year > self.year_to
        ):
            return False
        if self.months and record.month not in self.months:
            return False
        return not (
            self.basis_of_record is not None
            and record.basis_of_record != self.basis_of_record
        )


_SAFE_GENUS = re.compile(r"^[A-Z][a-z]+(?:-[a-z]+)?$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z .×'()-]{0,199}$")


def encode_cursor(occurrence_id: str) -> str:
    return (
        base64.urlsafe_b64encode(occurrence_id.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )


def decode_cursor(cursor: str | None) -> str | None:
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        return base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise ValueError("cursor is not valid") from exc


# ---------------------------------------------------------------------------
# Public response contract (Darwin Core term names on records)
# ---------------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PublicOccurrence(_Model):
    occurrenceID: str
    taxonID: str | None = None
    scientificName: str
    genus: str | None = None
    decimalLatitude: float
    decimalLongitude: float
    coordinateUncertaintyInMeters: float | None = None
    countryCode: str | None = None
    year: int | None = None
    month: int | None = None
    eventDate: str | None = None
    basisOfRecord: str | None = None
    datasetName: str | None = None
    institutionCode: str | None = None
    license: str | None = None
    rightsHolder: str | None = None
    references: str | None = None
    locality: str | None = None
    iucnCategory: str | None = None
    assessmentResolved: bool | None = None
    generalised: bool
    generalisationCellDeg: float
    generalisationReason: str
    generalisationNotice: str | None = None


class OccurrenceCluster(_Model):
    cell_id: str
    latitude: float
    longitude: float
    count: int = Field(ge=1)
    taxon_count: int = Field(ge=0)
    top_genera: list[str]
    year_min: int | None = None
    year_max: int | None = None
    generalised_count: int = Field(ge=0)
    position: Literal["displayed_centroid", "cell_centre"]


class LocalityDisclosure(_Model):
    access: Literal["public"] = "public"
    rule: str = "oc-atlas-locality-policy-v1"
    generalised_count: int = 0
    locality_withheld_count: int = 0
    statement: str = (
        "Threatened, imprecise, and unassessed records are generalised to grid-cell centres; "
        "precise sites and free-text localities are withheld where policy requires."
    )


class SourceAttribution(_Model):
    dataset_name: str
    record_count: int
    licenses: list[str]


class SourceDescription(_Model):
    source_id: str
    label: str
    configured: bool
    state: Literal["available", "source_not_configured", "unavailable"]
    detail: str | None = None
    supports_server_aggregation: bool = False


class OccurrenceQueryResponse(_Model):
    contract_version: Literal["oc-atlas-occurrence-query-v1"] = CONTRACT_VERSION
    generated_at: datetime
    source: SourceDescription
    mode: Literal["points", "clusters"]
    bbox: list[float]
    zoom: float
    cell_deg: float | None = None
    total_in_view: int
    total_is_exact: bool
    points: list[PublicOccurrence] = Field(default_factory=list)
    clusters: list[OccurrenceCluster] = Field(default_factory=list)
    next_cursor: str | None = None
    truncated: bool = False
    truncation_reason: str | None = None
    locality: LocalityDisclosure
    attribution: list[SourceAttribution] = Field(default_factory=list)
    cache: Literal["hit", "miss"] = "miss"


class CountBucket(_Model):
    key: str
    count: int


class OccurrenceSummaryResponse(_Model):
    contract_version: Literal["oc-atlas-occurrence-summary-v1"] = (
        SUMMARY_CONTRACT_VERSION
    )
    generated_at: datetime
    source: SourceDescription
    bbox: list[float]
    total: int
    total_is_exact: bool
    by_year: list[CountBucket]
    by_month: list[CountBucket]
    by_basis_of_record: list[CountBucket]
    top_taxa: list[CountBucket]
    top_genera: list[CountBucket]
    attribution: list[SourceAttribution]
    month_semantics: str = (
        "Month of the collection or observation event. It is not flowering phenology unless "
        "the source states the organism was in flower."
    )


class TaxonMatch(_Model):
    taxon_id: str
    scientific_name: str
    genus: str | None = None
    rank: Literal["genus", "species", "infraspecific", "unknown"]
    identifier_source: str


class TaxonSearchResponse(_Model):
    contract_version: Literal["oc-atlas-taxon-search-v1"] = (
        TAXON_SEARCH_CONTRACT_VERSION
    )
    query: str
    source: SourceDescription
    matches: list[TaxonMatch]


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AggregateCell:
    cell_lat_index: int
    cell_lng_index: int
    count: int
    taxon_count: int
    top_genera: tuple[str, ...]
    year_min: int | None
    year_max: int | None


class OccurrenceRepository(Protocol):
    def describe(self) -> SourceDescription: ...

    def count(self, query: OccurrenceQuery, *, cap: int) -> tuple[int, bool]:
        """Return (count, exact). When the count reaches ``cap`` it may stop early."""
        ...

    def fetch(
        self, query: OccurrenceQuery, *, after_id: str | None, max_rows: int
    ) -> list[OccurrenceRecord]:
        """Matching records ordered by occurrence_id, strictly after ``after_id``."""
        ...

    def aggregate(
        self, query: OccurrenceQuery, *, cell_deg: float
    ) -> list[AggregateCell] | None:
        """Server-side whole-degree aggregation, or None when unsupported."""
        ...

    def search_taxa(self, text: str, *, limit: int) -> list[TaxonMatch]: ...


class UnconfiguredOccurrenceRepository:
    """The honest default: no approved public-safe source has been configured."""

    def __init__(self, detail: str | None = None) -> None:
        self._detail = detail or (
            "No owner-approved Atlas occurrence relation is configured "
            "(ATLAS_OCCURRENCE_RELATION). No substitute data is served."
        )

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_id="unconfigured",
            label="Atlas occurrence store",
            configured=False,
            state="source_not_configured",
            detail=self._detail,
        )

    def count(self, query: OccurrenceQuery, *, cap: int) -> tuple[int, bool]:
        return 0, True

    def fetch(
        self, query: OccurrenceQuery, *, after_id: str | None, max_rows: int
    ) -> list[OccurrenceRecord]:
        return []

    def aggregate(
        self, query: OccurrenceQuery, *, cell_deg: float
    ) -> list[AggregateCell] | None:
        return None

    def search_taxa(self, text: str, *, limit: int) -> list[TaxonMatch]:
        return []


class InMemoryOccurrenceRepository:
    """Deterministic repository for tests and explicitly labelled fixtures."""

    def __init__(
        self, records: Iterable[OccurrenceRecord], *, source_id: str, label: str
    ) -> None:
        self._records = sorted(records, key=lambda r: r.occurrence_id)
        self._source_id = source_id
        self._label = label

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_id=self._source_id,
            label=self._label,
            configured=True,
            state="available",
        )

    def count(self, query: OccurrenceQuery, *, cap: int) -> tuple[int, bool]:
        total = sum(1 for record in self._records if query.matches(record))
        return total, True

    def fetch(
        self, query: OccurrenceQuery, *, after_id: str | None, max_rows: int
    ) -> list[OccurrenceRecord]:
        out: list[OccurrenceRecord] = []
        for record in self._records:
            if after_id is not None and record.occurrence_id <= after_id:
                continue
            if query.matches(record):
                out.append(record)
                if len(out) >= max_rows:
                    break
        return out

    def aggregate(
        self, query: OccurrenceQuery, *, cell_deg: float
    ) -> list[AggregateCell] | None:
        return None

    def search_taxa(self, text: str, *, limit: int) -> list[TaxonMatch]:
        needle = text.strip().lower()
        seen: dict[str, TaxonMatch] = {}
        for record in self._records:
            if (
                record.taxon_id
                and needle in record.scientific_name.lower()
                and record.taxon_id not in seen
            ):
                seen[record.taxon_id] = TaxonMatch(
                    taxon_id=record.taxon_id,
                    scientific_name=record.scientific_name,
                    genus=record.genus,
                    rank=_rank_of(record.scientific_name),
                    identifier_source=self._source_id,
                )
        return sorted(
            seen.values(),
            key=lambda m: (
                not m.scientific_name.lower().startswith(needle),
                m.scientific_name,
            ),
        )[:limit]


def _rank_of(name: str) -> Literal["genus", "species", "infraspecific", "unknown"]:
    words = [word for word in name.split() if word]
    if not words:
        return "unknown"
    if len(words) == 1:
        return "genus"
    if len(words) == 2:
        return "species"
    if any(marker in words for marker in ("var.", "subsp.", "f.", "ssp.")):
        return "infraspecific"
    return "unknown"


# ---------------------------------------------------------------------------
# PostgreSQL repository bound to an owner-approved relation
# ---------------------------------------------------------------------------

OCCURRENCE_COLUMNS: tuple[str, ...] = (
    "occurrence_id",
    "taxon_id",
    "scientific_name",
    "genus",
    "decimal_latitude",
    "decimal_longitude",
    "coordinate_uncertainty_in_meters",
    "country_code",
    "year",
    "month",
    "event_date",
    "basis_of_record",
    "dataset_name",
    "institution_code",
    "license",
    "rights_holder",
    "references_uri",
    "iucn_category",
    "conservation_status",
    "assessment_resolved",
    "locality",
)
_RELATION = re.compile(r"^[a-z_][a-z0-9_]{0,62}\.[a-z_][a-z0-9_]{0,62}$")
TAXONOMY_RELATION = "public.orchid_taxonomy"

DbExecute = Callable[[Callable[[Any], Any]], Any]


def validate_relation(name: str) -> str:
    if not _RELATION.match(name or ""):
        raise ValueError("relation must be a lowercase 'schema.name' identifier")
    return name


def build_where(
    query: OccurrenceQuery, *, after_id: str | None = None, use_postgis: bool = False
) -> tuple[str, list[Any]]:
    """Parameterised WHERE clause mirroring :meth:`OccurrenceQuery.matches`."""
    clauses = [
        "decimal_latitude IS NOT NULL",
        "decimal_longitude IS NOT NULL",
        "decimal_latitude BETWEEN -90 AND 90",
        "decimal_longitude BETWEEN -180 AND 180",
        "NOT (decimal_latitude = 0 AND decimal_longitude = 0)",
        "decimal_latitude BETWEEN %s AND %s",
    ]
    params: list[Any] = [query.bbox.south, query.bbox.north]
    ranges = query.bbox.lon_ranges()
    if use_postgis:
        envelopes = " OR ".join(
            "geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)" for _ in ranges
        )
        clauses.append(f"({envelopes})")
        for lo, hi in ranges:
            params.extend([lo, query.bbox.south, hi, query.bbox.north])
    else:
        clauses.append(
            "("
            + " OR ".join("decimal_longitude BETWEEN %s AND %s" for _ in ranges)
            + ")"
        )
        for lo, hi in ranges:
            params.extend([lo, hi])
    if query.taxon_id is not None:
        clauses.append("taxon_id::text = %s")
        params.append(query.taxon_id)
    if query.genus is not None:
        clauses.append("genus = %s")
        params.append(query.genus)
    if query.scientific_name is not None:
        clauses.append("lower(scientific_name) = lower(%s)")
        params.append(query.scientific_name)
    if query.year_from is not None:
        clauses.append("year >= %s")
        params.append(query.year_from)
    if query.year_to is not None:
        clauses.append("year <= %s")
        params.append(query.year_to)
    if query.months:
        clauses.append("month = ANY(%s)")
        params.append(list(query.months))
    if query.basis_of_record is not None:
        clauses.append("basis_of_record = %s")
        params.append(query.basis_of_record)
    if after_id is not None:
        clauses.append("occurrence_id::text > %s")
        params.append(after_id)
    return " AND ".join(clauses), params


class PostgresOccurrenceRepository:
    """Reads a relation that satisfies the Atlas public projection column contract.

    The relation is chosen by the owner (``ATLAS_OCCURRENCE_RELATION``); this
    class never guesses one. Its columns are verified against
    :data:`OCCURRENCE_COLUMNS` before any query runs, and a mismatch makes the
    store ``unavailable`` with the missing columns named.
    """

    def __init__(
        self, db_execute: DbExecute, relation: str, *, use_postgis: bool = False
    ) -> None:
        self._db = db_execute
        self._relation = validate_relation(relation)
        self._use_postgis = use_postgis
        self._verified: SourceDescription | None = None
        self._lock = threading.Lock()

    def describe(self) -> SourceDescription:
        with self._lock:
            if self._verified is not None and self._verified.state == "available":
                return self._verified
            schema, name = self._relation.split(".")

            def _work(cur: Any) -> list[str] | None:
                if cur is None:
                    return None
                cur.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
                    (schema, name),
                )
                return [str(row["column_name"]) for row in cur.fetchall()]

            try:
                columns = self._db(_work)
            except Exception:  # noqa: BLE001 - connection failure means unavailable, never fabricated
                columns = None
            if columns is None:
                return SourceDescription(
                    source_id=self._relation,
                    label="Atlas occurrence store",
                    configured=True,
                    state="unavailable",
                    detail="The configured occurrence store could not be reached.",
                )
            missing = [column for column in OCCURRENCE_COLUMNS if column not in columns]
            if self._use_postgis and "geom" not in columns:
                missing.append("geom")
            if missing:
                return SourceDescription(
                    source_id=self._relation,
                    label="Atlas occurrence store",
                    configured=True,
                    state="unavailable",
                    detail=f"Configured relation does not satisfy the Atlas projection contract; missing: {', '.join(missing)}.",
                )
            self._verified = SourceDescription(
                source_id=self._relation,
                label="Atlas occurrence store",
                configured=True,
                state="available",
                supports_server_aggregation=True,
            )
            return self._verified

    def count(self, query: OccurrenceQuery, *, cap: int) -> tuple[int, bool]:
        where, params = build_where(query, use_postgis=self._use_postgis)

        def _work(cur: Any) -> tuple[int, bool]:
            cur.execute(
                f"SELECT count(*) AS n FROM (SELECT 1 FROM {self._relation} WHERE {where} LIMIT %s) AS bounded",
                (*params, cap + 1),
            )
            n = int(cur.fetchone()["n"])
            return (min(n, cap), n <= cap)

        return self._db(_work)

    def fetch(
        self, query: OccurrenceQuery, *, after_id: str | None, max_rows: int
    ) -> list[OccurrenceRecord]:
        where, params = build_where(
            query, after_id=after_id, use_postgis=self._use_postgis
        )
        columns = ", ".join(OCCURRENCE_COLUMNS)

        def _work(cur: Any) -> list[OccurrenceRecord]:
            cur.execute(
                f"SELECT {columns} FROM {self._relation} WHERE {where} ORDER BY occurrence_id::text LIMIT %s",
                (*params, max_rows),
            )
            return [_record_from_row(row) for row in cur.fetchall()]

        return self._db(_work)

    def aggregate(
        self, query: OccurrenceQuery, *, cell_deg: float
    ) -> list[AggregateCell] | None:
        # Only whole-degree cells are aggregated in SQL: they nest every policy
        # cell, so positioning at the cell centre cannot reveal a protected site.
        if cell_deg < POLICY_MAX_CELL_DEG or cell_deg != math.floor(cell_deg):
            return None
        where, params = build_where(query, use_postgis=self._use_postgis)

        def _work(cur: Any) -> list[AggregateCell]:
            cur.execute(
                f"""
                SELECT floor(decimal_latitude / %s)::int AS ci,
                       floor(decimal_longitude / %s)::int AS cj,
                       count(*) AS n,
                       count(DISTINCT coalesce(taxon_id::text, lower(scientific_name))) AS taxa,
                       (array_agg(genus ORDER BY genus) FILTER (WHERE genus IS NOT NULL))[1:200] AS genera,
                       min(year) AS ymin,
                       max(year) AS ymax
                FROM {self._relation}
                WHERE {where}
                GROUP BY 1, 2
                ORDER BY 1, 2
                """,
                (cell_deg, cell_deg, *params),
            )
            cells: list[AggregateCell] = []
            for row in cur.fetchall():
                genera = Counter(row["genera"] or [])
                cells.append(
                    AggregateCell(
                        cell_lat_index=int(row["ci"]),
                        cell_lng_index=int(row["cj"]),
                        count=int(row["n"]),
                        taxon_count=int(row["taxa"]),
                        top_genera=tuple(g for g, _ in genera.most_common(3)),
                        year_min=row["ymin"],
                        year_max=row["ymax"],
                    )
                )
            return cells

        return self._db(_work)

    def search_taxa(self, text: str, *, limit: int) -> list[TaxonMatch]:
        pattern = text.strip()

        def _work(cur: Any) -> list[TaxonMatch]:
            if cur is None:
                return []
            cur.execute(
                f"""
                SELECT id::text AS id, scientific_name, genus
                FROM {TAXONOMY_RELATION}
                WHERE scientific_name ILIKE %s
                ORDER BY (scientific_name ILIKE %s) DESC, length(scientific_name), scientific_name
                LIMIT %s
                """,
                (f"%{_escape_like(pattern)}%", f"{_escape_like(pattern)}%", limit),
            )
            return [
                TaxonMatch(
                    taxon_id=str(row["id"]),
                    scientific_name=str(row["scientific_name"]),
                    genus=row.get("genus"),
                    rank=_rank_of(str(row["scientific_name"])),
                    identifier_source=TAXONOMY_RELATION,
                )
                for row in cur.fetchall()
            ]

        return self._db(_work) or []


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _record_from_row(row: dict[str, Any]) -> OccurrenceRecord:
    return OccurrenceRecord(
        occurrence_id=str(row["occurrence_id"]),
        taxon_id=_optional_str(row.get("taxon_id")),
        scientific_name=str(row.get("scientific_name") or ""),
        genus=_optional_str(row.get("genus")),
        decimal_latitude=float(row["decimal_latitude"]),
        decimal_longitude=float(row["decimal_longitude"]),
        coordinate_uncertainty_in_meters=_optional_float(
            row.get("coordinate_uncertainty_in_meters")
        ),
        country_code=_optional_str(row.get("country_code")),
        year=_optional_int(row.get("year")),
        month=_optional_int(row.get("month")),
        event_date=_optional_str(row.get("event_date")),
        basis_of_record=_optional_str(row.get("basis_of_record")),
        dataset_name=_optional_str(row.get("dataset_name")),
        institution_code=_optional_str(row.get("institution_code")),
        license=_optional_str(row.get("license")),
        rights_holder=_optional_str(row.get("rights_holder")),
        references_uri=_optional_str(row.get("references_uri")),
        iucn_category=_optional_str(row.get("iucn_category")),
        conservation_status=_optional_str(row.get("conservation_status")),
        assessment_resolved=row.get("assessment_resolved"),
        locality=_optional_str(row.get("locality")),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TTLCache:
    """Small thread-safe LRU with expiry; bounded so it cannot grow unchecked."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
        ttl_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            stored_at, value = hit
            if self._clock() - stored_at > self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (self._clock(), value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


def project_public(record: OccurrenceRecord) -> PublicOccurrence:
    shown = resolve_location(
        lat=record.decimal_latitude,
        lng=record.decimal_longitude,
        iucn_code=record.iucn_category,
        conservation_status=record.conservation_status,
        coordinate_uncertainty_m=record.coordinate_uncertainty_in_meters,
        assessment_resolved=record.assessment_resolved,
        access="public",
    )
    policy = shown.policy
    return PublicOccurrence(
        occurrenceID=record.occurrence_id,
        taxonID=record.taxon_id,
        scientificName=record.scientific_name,
        genus=record.genus,
        decimalLatitude=shown.lat,
        decimalLongitude=shown.lng,
        coordinateUncertaintyInMeters=record.coordinate_uncertainty_in_meters,
        countryCode=record.country_code,
        year=record.year,
        month=record.month,
        # A full event date narrows a protected site's visit history; keep only
        # year/month when the record is generalised for threat or precaution.
        eventDate=record.event_date if policy.locality_text_allowed else None,
        basisOfRecord=record.basis_of_record,
        datasetName=record.dataset_name,
        institutionCode=record.institution_code,
        license=record.license,
        rightsHolder=record.rights_holder,
        references=record.references_uri if policy.locality_text_allowed else None,
        locality=record.locality if policy.locality_text_allowed else None,
        iucnCategory=record.iucn_category,
        assessmentResolved=record.assessment_resolved,
        generalised=policy.generalised,
        generalisationCellDeg=policy.cell_deg,
        generalisationReason=policy.reason,
        generalisationNotice=policy.notice or None,
    )


def _attribution(records: Sequence[OccurrenceRecord]) -> list[SourceAttribution]:
    by_dataset: dict[str, tuple[int, set[str]]] = {}
    for record in records:
        name = record.dataset_name or "Unattributed source"
        count, licenses = by_dataset.get(name, (0, set()))
        if record.license:
            licenses.add(record.license)
        by_dataset[name] = (count + 1, licenses)
    return [
        SourceAttribution(
            dataset_name=name,
            record_count=count,
            licenses=sorted(licenses) or ["not stated"],
        )
        for name, (count, licenses) in sorted(
            by_dataset.items(), key=lambda item: (-item[1][0], item[0])
        )
    ]


def _cluster_from_points(
    points: Sequence[PublicOccurrence], cell_deg: float
) -> list[OccurrenceCluster]:
    bins: dict[tuple[int, int], list[PublicOccurrence]] = {}
    for point in points:
        key = (
            math.floor(point.decimalLatitude / cell_deg),
            math.floor(point.decimalLongitude / cell_deg),
        )
        bins.setdefault(key, []).append(point)
    clusters: list[OccurrenceCluster] = []
    for (ci, cj), members in sorted(bins.items()):
        years = [m.year for m in members if m.year is not None]
        taxa = {m.taxonID or m.scientificName.lower() for m in members}
        genera = Counter(m.genus for m in members if m.genus)
        clusters.append(
            OccurrenceCluster(
                cell_id=f"{cell_deg:g}:{ci}:{cj}",
                latitude=round(
                    sum(m.decimalLatitude for m in members) / len(members), 6
                ),
                longitude=round(
                    sum(m.decimalLongitude for m in members) / len(members), 6
                ),
                count=len(members),
                taxon_count=len(taxa),
                top_genera=[g for g, _ in genera.most_common(3)],
                year_min=min(years) if years else None,
                year_max=max(years) if years else None,
                generalised_count=sum(1 for m in members if m.generalised),
                position="displayed_centroid",
            )
        )
    return clusters


def _cluster_from_aggregate(
    cells: Sequence[AggregateCell], cell_deg: float
) -> list[OccurrenceCluster]:
    return [
        OccurrenceCluster(
            cell_id=f"{cell_deg:g}:{cell.cell_lat_index}:{cell.cell_lng_index}",
            latitude=max(-90.0, min(90.0, (cell.cell_lat_index + 0.5) * cell_deg)),
            longitude=max(-180.0, min(180.0, (cell.cell_lng_index + 0.5) * cell_deg)),
            count=cell.count,
            taxon_count=cell.taxon_count,
            top_genera=list(cell.top_genera),
            year_min=cell.year_min,
            year_max=cell.year_max,
            # Unknown per-record generalisation in the SQL path; the cell itself
            # is coarser than every policy cell, so nothing finer is disclosed.
            generalised_count=0,
            position="cell_centre",
        )
        for cell in cells
    ]


@dataclass
class OccurrenceService:
    repository: OccurrenceRepository
    cache: TTLCache = field(default_factory=TTLCache)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))

    def query(self, query: OccurrenceQuery) -> OccurrenceQueryResponse:
        source = self.repository.describe()
        bbox = [query.bbox.west, query.bbox.south, query.bbox.east, query.bbox.north]
        if source.state != "available":
            return OccurrenceQueryResponse(
                generated_at=self.clock(),
                source=source,
                mode="clusters",
                bbox=bbox,
                zoom=query.zoom,
                total_in_view=0,
                total_is_exact=False,
                locality=LocalityDisclosure(),
            )

        key = f"{source.source_id}|{query.cache_key()}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached.model_copy(update={"cache": "hit"})

        after_id = decode_cursor(query.cursor)
        total, exact = self.repository.count(query, cap=MAX_SCAN_ROWS)
        wants_points = query.mode == "points" or (
            query.mode == "auto"
            and query.zoom >= POINT_MODE_MIN_ZOOM
            and total <= query.limit
        )
        response = (
            self._points(query, source, bbox, total, exact, after_id)
            if wants_points
            else self._clusters(query, source, bbox, total, exact)
        )
        self.cache.put(key, response)
        return response

    def _points(
        self,
        query: OccurrenceQuery,
        source: SourceDescription,
        bbox: list[float],
        total: int,
        exact: bool,
        after_id: str | None,
    ) -> OccurrenceQueryResponse:
        rows = self.repository.fetch(query, after_id=after_id, max_rows=query.limit + 1)
        has_more = len(rows) > query.limit
        rows = rows[: query.limit]
        points = [project_public(row) for row in rows]
        return OccurrenceQueryResponse(
            generated_at=self.clock(),
            source=source,
            mode="points",
            bbox=bbox,
            zoom=query.zoom,
            total_in_view=total,
            total_is_exact=exact,
            points=points,
            next_cursor=encode_cursor(rows[-1].occurrence_id)
            if has_more and rows
            else None,
            locality=LocalityDisclosure(
                generalised_count=sum(1 for p in points if p.generalised),
                locality_withheld_count=sum(
                    1
                    for row, p in zip(rows, points, strict=True)
                    if row.locality and p.locality is None
                ),
            ),
            attribution=_attribution(rows),
        )

    def _clusters(
        self,
        query: OccurrenceQuery,
        source: SourceDescription,
        bbox: list[float],
        total: int,
        exact: bool,
    ) -> OccurrenceQueryResponse:
        cell_deg = cell_deg_for_zoom(query.zoom)
        truncated = False
        reason: str | None = None

        if total > MAX_SCAN_ROWS or not exact:
            # Too many records to project individually: aggregate on whole-degree
            # cells server-side, coarsening the cell if the zoom asked for finer.
            coarse = max(cell_deg, POLICY_MAX_CELL_DEG)
            cells = self.repository.aggregate(query, cell_deg=coarse)
            if cells is not None:
                return OccurrenceQueryResponse(
                    generated_at=self.clock(),
                    source=source,
                    mode="clusters",
                    bbox=bbox,
                    zoom=query.zoom,
                    cell_deg=coarse,
                    total_in_view=sum(cell.count for cell in cells),
                    total_is_exact=True,
                    clusters=_cluster_from_aggregate(cells, coarse),
                    truncated=coarse != cell_deg,
                    truncation_reason=(
                        "Viewport holds more records than can be projected individually; "
                        f"clustered at {coarse:g}° instead of {cell_deg:g}°."
                    )
                    if coarse != cell_deg
                    else None,
                    locality=LocalityDisclosure(),
                )
            truncated = True
            reason = f"Only the first {MAX_SCAN_ROWS} matching records were clustered; zoom in or filter to see all."

        rows = self.repository.fetch(query, after_id=None, max_rows=MAX_SCAN_ROWS)
        points = [project_public(row) for row in rows]
        return OccurrenceQueryResponse(
            generated_at=self.clock(),
            source=source,
            mode="clusters",
            bbox=bbox,
            zoom=query.zoom,
            cell_deg=cell_deg,
            total_in_view=total,
            total_is_exact=exact,
            clusters=_cluster_from_points(points, cell_deg),
            truncated=truncated,
            truncation_reason=reason,
            locality=LocalityDisclosure(
                generalised_count=sum(1 for p in points if p.generalised)
            ),
            attribution=_attribution(rows),
        )

    def summary(self, query: OccurrenceQuery) -> OccurrenceSummaryResponse:
        source = self.repository.describe()
        bbox = [query.bbox.west, query.bbox.south, query.bbox.east, query.bbox.north]
        if source.state != "available":
            return OccurrenceSummaryResponse(
                generated_at=self.clock(),
                source=source,
                bbox=bbox,
                total=0,
                total_is_exact=False,
                by_year=[],
                by_month=[],
                by_basis_of_record=[],
                top_taxa=[],
                top_genera=[],
                attribution=[],
            )
        rows = self.repository.fetch(query, after_id=None, max_rows=MAX_SCAN_ROWS + 1)
        exact = len(rows) <= MAX_SCAN_ROWS
        rows = rows[:MAX_SCAN_ROWS]

        def buckets(
            values: Iterable[Any], *, top: int | None = None, sort_by_key: bool = False
        ) -> list[CountBucket]:
            counts = Counter(str(v) for v in values if v is not None)
            items = sorted(counts.items()) if sort_by_key else counts.most_common(top)
            return [CountBucket(key=k, count=c) for k, c in items]

        return OccurrenceSummaryResponse(
            generated_at=self.clock(),
            source=source,
            bbox=bbox,
            total=len(rows),
            total_is_exact=exact,
            by_year=buckets((r.year for r in rows), sort_by_key=True),
            by_month=[
                CountBucket(key=str(m), count=sum(1 for r in rows if r.month == m))
                for m in range(1, 13)
            ],
            by_basis_of_record=buckets((r.basis_of_record for r in rows), top=10),
            top_taxa=buckets((r.scientific_name for r in rows), top=15),
            top_genera=buckets((r.genus for r in rows), top=15),
            attribution=_attribution(rows),
        )

    def search_taxa(self, text: str, *, limit: int = 10) -> TaxonSearchResponse:
        cleaned = " ".join((text or "").split())
        if len(cleaned) < 2 or not _SAFE_NAME.match(cleaned):
            raise ValueError("query must be at least two letters of a scientific name")
        source = self.repository.describe()
        matches = (
            self.repository.search_taxa(cleaned, limit=limit)
            if source.state == "available"
            else []
        )
        return TaxonSearchResponse(query=cleaned, source=source, matches=matches)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def repository_from_environment(
    env: dict[str, str] | None = None,
) -> OccurrenceRepository:
    env = dict(os.environ if env is None else env)
    relation = (env.get("ATLAS_OCCURRENCE_RELATION") or "").strip()
    if not relation:
        return UnconfiguredOccurrenceRepository()
    if not (env.get("DATABASE_URL") or "").strip():
        return UnconfiguredOccurrenceRepository(
            "ATLAS_OCCURRENCE_RELATION is set but DATABASE_URL is not."
        )
    try:
        validate_relation(relation)
    except ValueError as exc:
        return UnconfiguredOccurrenceRepository(
            f"ATLAS_OCCURRENCE_RELATION rejected: {exc}."
        )
    from app.routers.owner_operations import db_execute

    use_postgis = (env.get("ATLAS_OCCURRENCE_USE_POSTGIS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return PostgresOccurrenceRepository(db_execute, relation, use_postgis=use_postgis)
