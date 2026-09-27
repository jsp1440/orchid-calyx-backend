"""Neon (or any CSV) member import into the society CRM.

Contract (issue #1655):

* **Dry run is the default** and performs zero writes -- not even an audit event.
* The column mapping is **explicit**. Nothing is inferred from header names: every
  CSV header the import reads is named in a :class:`ColumnMapping`. Headers the
  mapping does not mention are reported (``unknown_headers``) and ignored. A mapping
  that lacks a required canonical field, or names a header the file does not have,
  rejects the whole import before any write.
* Each row is keyed by ``(source_system, "member", source_record_id)`` in
  ``oc_constituent.external_record_links``. One link row carries both the created
  ``constituent_id`` and ``membership_id`` plus the sha256 of the canonicalized row.
* A row whose key is already linked is compared with the current OC record:
  identical -> ``unchanged``; different -> ``conflict`` with a field-level diff.
  **This version never overwrites OC data**; conflicts are for a human to resolve.
* An unlinked row whose email already belongs to a person in this organization is
  ``possible_duplicate`` and is not created. A source id or email that repeats inside
  the file is ``duplicate_in_file`` for the second and later occurrences.
* Every other valid row is ``create``: in apply mode one atomic unit per row
  (person, email, phone, address, membership, external link). A failing row rolls
  back alone and is reported ``invalid``. Rows never disappear::

      total_rows == create + unchanged + conflict + possible_duplicate + invalid + duplicate_in_file

  (``create`` means "created" when ``dry_run=False`` and "would be created" in a dry run.)
* Dates are parsed only with the formats the mapping lists. A value matching no
  format is ``DATE_INVALID``; a value two formats read as *different* dates (e.g.
  ``03/04/2026`` under both ``%m/%d/%Y`` and ``%d/%m/%Y``) is ``DATE_AMBIGUOUS``.
  Neither is ever guessed.

Membership status and the renewal ledger
----------------------------------------
Imported memberships are created with the status and dates the source system
reports (``create_membership(status=..., starts_at=..., expires_at=...,
source_kind="import", source_ref="<system>:<id>")``). No ``membership_renewals`` row
is written: that ledger records renewals Orchid Continuum itself applied, and
``renew_membership`` computes a *new* term from ``as_of`` -- it cannot reproduce the
source system's paid-through date without fabricating a renewal date. The import's
provenance lives on the membership (``source_kind``/``source_ref``), the external
link, and the audit trail instead. A source status of ``cancelled`` is created as
``pending`` (with its dates) and then cancelled through the normal audited
transition with a reason naming the source record, because a membership cannot be
created cancelled.

Audit: apply mode writes ``import.started`` and ``import.completed`` (or
``import.failed``) with counts, hashes and the import id only -- never names,
emails, or other row content. Per-row repository writes are audited by the
repository as usual.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import psycopg

from .authorization import SocietyCapability
from .domain import MembershipStatus, normalize_email
from .society_service import CRMPrincipal, SocietyCRMService

SOURCE_RECORD_TYPE = "member"
MAX_IMPORT_ROWS = 20000

ADDRESS_FIELDS = ("line1", "line2", "locality", "administrative_area", "postal_code", "country_code")
CANONICAL_FIELDS = frozenset(
    {
        "source_record_id",
        "display_name",
        "first_name",
        "last_name",
        "email",
        "phone",
        *ADDRESS_FIELDS,
        "level_code",
        "status",
        "starts_at",
        "expires_at",
    }
)

ROW_STATUSES = ("create", "unchanged", "conflict", "possible_duplicate", "invalid", "duplicate_in_file")

_LEVEL_CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_PHONE = re.compile(r"\+?[0-9]{7,15}")


class ImportMappingError(ValueError):
    """Raised by :meth:`ColumnMapping.require_valid` for a structurally invalid mapping."""


@dataclass(frozen=True)
class ColumnMapping:
    """Explicit CSV header -> canonical field mapping.

    ``columns`` maps a CSV header (exact text) to one of :data:`CANONICAL_FIELDS`.
    Required: ``source_record_id``, ``level_code``, and either ``display_name`` or
    both ``first_name`` and ``last_name``.

    ``level_value_map`` maps source level names to OC level codes. When non-empty, every
    level value in the file must appear in it (keys match case-insensitively after
    trimming). When omitted or empty, the cell value itself (lower-cased) must be an
    existing OC level code.

    ``status_value_map`` maps source status names to :class:`MembershipStatus`
    values. When omitted, cells must already be OC statuses. When ``status`` is not
    mapped at all, every created membership is ``pending``.

    ``country_value_map`` maps source country text (e.g. ``United States``) to ISO
    3166-1 alpha-2 codes. Unmapped values must already be two letters.

    ``date_formats`` lists the only ``strptime`` formats dates are parsed with.
    """

    columns: Mapping[str, str]
    level_value_map: Mapping[str, str] | None = None
    status_value_map: Mapping[str, str] | None = None
    country_value_map: Mapping[str, str] | None = None
    date_formats: tuple[str, ...] = ("%Y-%m-%d",)

    def field_headers(self) -> dict[str, str]:
        """canonical field -> CSV header."""
        return {canonical: header for header, canonical in self.columns.items()}

    def errors(self) -> list[dict[str, str]]:
        problems: list[dict[str, str]] = []
        seen: dict[str, str] = {}
        for header, canonical in self.columns.items():
            if canonical not in CANONICAL_FIELDS:
                problems.append(_fatal("UNKNOWN_CANONICAL_FIELD",
                                       f"Header '{header}' is mapped to '{canonical}', which is not a supported "
                                       f"field. Supported fields: {', '.join(sorted(CANONICAL_FIELDS))}."))
            elif canonical in seen:
                problems.append(_fatal("CANONICAL_FIELD_MAPPED_TWICE",
                                       f"Both '{seen[canonical]}' and '{header}' are mapped to '{canonical}'; "
                                       "map exactly one header to each field."))
            else:
                seen[canonical] = header
        if "source_record_id" not in seen:
            problems.append(_fatal("SOURCE_RECORD_ID_UNMAPPED",
                                   "No header is mapped to 'source_record_id'. Map the source system's stable "
                                   "record id (for Neon, the Account ID) so repeated imports are idempotent."))
        if "display_name" not in seen and not {"first_name", "last_name"} <= set(seen):
            problems.append(_fatal("NAME_UNMAPPED",
                                   "Map a header to 'display_name', or map headers to both 'first_name' and "
                                   "'last_name'."))
        if "level_code" not in seen:
            problems.append(_fatal("LEVEL_UNMAPPED", "No header is mapped to 'level_code' (membership level)."))
        if not self.date_formats:
            problems.append(_fatal("DATE_FORMATS_REQUIRED", "List at least one date format in 'date_formats'."))
        for source, target in (self.status_value_map or {}).items():
            if target not in {status.value for status in MembershipStatus}:
                problems.append(_fatal("STATUS_MAP_TARGET_INVALID",
                                       f"status_value_map maps '{source}' to '{target}', which is not an OC status "
                                       f"({', '.join(status.value for status in MembershipStatus)})."))
        for source, target in (self.level_value_map or {}).items():
            if not _LEVEL_CODE.fullmatch(str(target)):
                problems.append(_fatal("LEVEL_MAP_TARGET_INVALID",
                                       f"level_value_map maps '{source}' to '{target}', which is not a valid level "
                                       "code."))
        for source, target in (self.country_value_map or {}).items():
            if not re.fullmatch(r"[A-Z]{2}", str(target)):
                problems.append(_fatal("COUNTRY_MAP_TARGET_INVALID",
                                       f"country_value_map maps '{source}' to '{target}'; targets must be two "
                                       "upper-case letters (ISO 3166-1 alpha-2)."))
        return problems

    def require_valid(self) -> None:
        problems = self.errors()
        if problems:
            raise ImportMappingError(problems[0]["code"])

    def fingerprint(self) -> str:
        return _sha256_json(
            {
                "columns": dict(sorted(self.columns.items())),
                "level_value_map": dict(sorted((self.level_value_map or {}).items())),
                "status_value_map": dict(sorted((self.status_value_map or {}).items())),
                "country_value_map": dict(sorted((self.country_value_map or {}).items())),
                "date_formats": list(self.date_formats),
            }
        )


# UNVERIFIED ASSUMPTION. These header names and value maps are what a Neon CRM
# "Accounts with memberships" export is *believed* to contain. They have not been
# checked against a real FCOS export. Before any apply run, compare every header and
# every distinct Membership Level / Membership Status / Country value in the actual
# file with this mapping (docs/operations/OC-CRM-IMPORT-EXPORT-001.md, "Mapping
# verification checklist"), copy it, and fix what differs. ``level_value_map`` is
# intentionally empty: OC level codes are the society's own and must be filled in.
NEON_DEFAULT_MAPPING = ColumnMapping(
    columns={
        "Account ID": "source_record_id",
        "First Name": "first_name",
        "Last Name": "last_name",
        "Email 1": "email",
        "Phone 1": "phone",
        "Address Line 1": "line1",
        "Address Line 2": "line2",
        "City": "locality",
        "State/Province": "administrative_area",
        "Zip/Postal Code": "postal_code",
        "Country": "country_code",
        "Membership Level": "level_code",
        "Membership Status": "status",
        "Start Date": "starts_at",
        "Expiration Date": "expires_at",
    },
    level_value_map={},
    status_value_map={
        "Active": MembershipStatus.ACTIVE.value,
        "Grace": MembershipStatus.GRACE.value,
        "Lapsed": MembershipStatus.LAPSED.value,
        "Pending": MembershipStatus.PENDING.value,
        "Cancelled": MembershipStatus.CANCELLED.value,
    },
    country_value_map={"United States": "US", "USA": "US"},
    date_formats=("%m/%d/%Y",),
)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@dataclass
class RowResult:
    row_number: int
    source_record_id: str | None
    status: str
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diff: dict[str, dict[str, Any]] | None = None
    constituent_id: int | None = None
    membership_id: int | None = None
    source_payload_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "row_number": self.row_number,
            "source_record_id": self.source_record_id,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "messages": list(self.messages),
            "warnings": list(self.warnings),
        }
        if self.diff is not None:
            out["diff"] = self.diff
        if self.constituent_id is not None:
            out["constituent_id"] = self.constituent_id
        if self.membership_id is not None:
            out["membership_id"] = self.membership_id
        if self.source_payload_sha256 is not None:
            out["source_payload_sha256"] = self.source_payload_sha256
        return out


@dataclass
class ImportReport:
    import_id: str
    organization_id: int
    source_system: str
    dry_run: bool
    accepted: bool
    mapping_sha256: str
    csv_sha256: str
    total_rows: int = 0
    fatal_errors: list[dict[str, str]] = field(default_factory=list)
    unknown_headers: list[str] = field(default_factory=list)
    rows: list[RowResult] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in ROW_STATUSES}
        for row in self.rows:
            counts[row.status] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "organization_id": self.organization_id,
            "source_system": self.source_system,
            "dry_run": self.dry_run,
            "accepted": self.accepted,
            "mapping_sha256": self.mapping_sha256,
            "csv_sha256": self.csv_sha256,
            "total_rows": self.total_rows,
            "counts": self.counts,
            "fatal_errors": list(self.fatal_errors),
            "unknown_headers": list(self.unknown_headers),
            "rows": [row.to_dict() for row in self.rows],
        }


# ---------------------------------------------------------------------------
# Parsing and canonicalization (shared with crm_reconcile)
# ---------------------------------------------------------------------------


def _fatal(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())[:limit]
    return cleaned or None


def _lookup(value_map: Mapping[str, str], raw: str) -> str | None:
    wanted = raw.strip().casefold()
    for key, target in value_map.items():
        if str(key).strip().casefold() == wanted:
            return target
    return None


@dataclass
class ParsedCSV:
    headers: list[str]
    records: list[tuple[int, dict[str, str], bool]]  # (row_number, cells, shape_ok)
    fatal_errors: list[dict[str, str]]
    unknown_headers: list[str]


def parse_csv(csv_text: str, mapping: ColumnMapping) -> ParsedCSV:
    fatal = list(mapping.errors())
    text = csv_text[1:] if csv_text.startswith("﻿") else csv_text
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        return ParsedCSV([], [], fatal + [_fatal("CSV_EMPTY", "The file has no header row.")], [])
    except csv.Error:
        return ParsedCSV([], [], fatal + [_fatal("CSV_UNREADABLE", "The header row is not valid CSV.")], [])
    duplicates = sorted({h for h in headers if headers.count(h) > 1})
    for header in duplicates:
        fatal.append(_fatal("DUPLICATE_HEADER", f"Header '{header}' appears more than once; headers must be unique."))
    for header in mapping.columns:
        if header not in headers:
            fatal.append(_fatal("MAPPED_HEADER_MISSING",
                                f"The mapping reads header '{header}' but the file has no such column. Check the "
                                "export settings or remove that entry from the mapping."))
    unknown = [h for h in headers if h not in mapping.columns]
    records: list[tuple[int, dict[str, str], bool]] = []
    try:
        for index, cells in enumerate(reader, start=2):
            if not cells:
                continue
            if len(records) >= MAX_IMPORT_ROWS:
                fatal.append(_fatal("TOO_MANY_ROWS", f"The file has more than {MAX_IMPORT_ROWS} rows; split it."))
                break
            shape_ok = len(cells) == len(headers)
            records.append((index, dict(zip(headers, cells)), shape_ok))
    except csv.Error as exc:
        fatal.append(_fatal("CSV_UNREADABLE", f"The file is not valid CSV near line {reader.line_num}: {exc}."))
    return ParsedCSV(headers, records, fatal, unknown)


@dataclass
class CanonicalRow:
    row_number: int
    source_record_id: str | None
    values: dict[str, Any]
    errors: list[tuple[str, str]]
    warnings: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors

    def payload_sha256(self, source_system: str) -> str:
        return _sha256_json({"source_system": source_system, **self.values})


def _parse_date(raw: str, formats: tuple[str, ...]) -> tuple[date | None, str | None]:
    readings: set[date] = set()
    for fmt in formats:
        try:
            readings.add(datetime.strptime(raw, fmt).date())
        except ValueError:
            continue
    if not readings:
        return None, "DATE_INVALID"
    if len(readings) > 1:
        return None, "DATE_AMBIGUOUS"
    return readings.pop(), None


def canonicalize_row(
    row_number: int,
    cells: dict[str, str],
    shape_ok: bool,
    mapping: ColumnMapping,
    levels: Mapping[str, Mapping[str, Any]],
    *,
    as_of: datetime | None = None,
) -> CanonicalRow:
    """Validate one CSV record into canonical OC values. Only mapped fields appear."""

    headers = mapping.field_headers()
    errors: list[tuple[str, str]] = []
    warnings: list[str] = []
    prefix = f"Row {row_number}"

    def cell(name: str) -> str:
        header = headers.get(name)
        return (cells.get(header) or "").strip() if header else ""

    source_id = _text(cell("source_record_id"), 200)
    if not shape_ok:
        errors.append(("ROW_FIELD_COUNT_MISMATCH",
                       f"{prefix}: the number of cells does not match the header row; check for unquoted commas."))
    if not source_id:
        errors.append(("SOURCE_RECORD_ID_MISSING",
                       f"{prefix}: '{headers.get('source_record_id')}' is empty; every row needs the source "
                       "record id."))
    values: dict[str, Any] = {"source_record_id": source_id}

    first = _text(cell("first_name"), 100)
    last = _text(cell("last_name"), 100)
    if "first_name" in headers:
        values["first_name"] = first
    if "last_name" in headers:
        values["last_name"] = last
    display = _text(cell("display_name"), 200) if "display_name" in headers else None
    display = display or _text(" ".join(part for part in (first, last) if part), 200)
    values["display_name"] = display
    if not display:
        errors.append(("NAME_MISSING", f"{prefix}: the member has no name."))

    if "email" in headers:
        raw_email = cell("email")
        email = None
        if raw_email:
            try:
                email = normalize_email(raw_email)
            except ValueError:
                errors.append(("EMAIL_INVALID", f"{prefix}: email '{raw_email}' is not a valid address."))
        values["email"] = email

    if "phone" in headers:
        raw_phone = cell("phone")
        phone = re.sub(r"[^0-9+]", "", raw_phone) if raw_phone else None
        if raw_phone and not _PHONE.fullmatch(phone or ""):
            errors.append(("PHONE_INVALID", f"{prefix}: phone '{raw_phone}' is not a valid phone number."))
            phone = None
        values["phone"] = phone

    if any(name in headers for name in ADDRESS_FIELDS):
        limits = {"line1": 200, "line2": 200, "locality": 120, "administrative_area": 120, "postal_code": 20}
        address: dict[str, Any] = {name: _text(cell(name), limits[name]) for name in limits}
        raw_country = cell("country_code")
        country = None
        if raw_country:
            mapped = _lookup(mapping.country_value_map or {}, raw_country)
            candidate = mapped or raw_country.upper()
            if re.fullmatch(r"[A-Z]{2}", candidate):
                country = candidate
            else:
                errors.append(("COUNTRY_INVALID",
                               f"{prefix}: country '{raw_country}' is not a two-letter code; add it to "
                               "country_value_map."))
        address["country_code"] = country
        if not any(address.values()):
            values["address"] = None
        else:
            if not address["line1"]:
                errors.append(("ADDRESS_LINE1_REQUIRED", f"{prefix}: an address is present but line 1 is empty."))
            if not country and raw_country == "":
                errors.append(("ADDRESS_COUNTRY_REQUIRED",
                               f"{prefix}: an address is present but the country is empty."))
            values["address"] = address

    raw_level = cell("level_code")
    level_code: str | None = None
    if not raw_level:
        errors.append(("LEVEL_MISSING", f"{prefix}: the membership level is empty."))
    elif mapping.level_value_map:
        level_code = _lookup(mapping.level_value_map, raw_level)
        if level_code is None:
            errors.append(("LEVEL_NOT_MAPPED",
                           f"{prefix}: level '{raw_level}' has no mapping; add it to level_value_map or create "
                           "the level."))
    else:
        level_code = raw_level.strip().lower()
    if level_code is not None and level_code not in levels:
        errors.append(("UNKNOWN_LEVEL",
                       f"{prefix}: level '{raw_level}' maps to OC level code '{level_code}', which this society "
                       "does not have; create the level or fix level_value_map."))
        level_code = None
    values["level_code"] = level_code

    status: str | None = None
    if "status" in headers:
        raw_status = cell("status")
        if not raw_status:
            errors.append(("STATUS_MISSING", f"{prefix}: the membership status is empty."))
        else:
            if mapping.status_value_map:
                status = _lookup(mapping.status_value_map, raw_status)
            else:
                candidate = raw_status.strip().lower()
                status = candidate if candidate in {s.value for s in MembershipStatus} else None
            if status is None:
                errors.append(("STATUS_NOT_MAPPED",
                               f"{prefix}: status '{raw_status}' has no mapping; add it to status_value_map."))
        values["status"] = status

    parsed_dates: dict[str, date | None] = {}
    for name in ("starts_at", "expires_at"):
        if name not in headers:
            continue
        raw = cell(name)
        parsed: date | None = None
        if raw:
            parsed, problem = _parse_date(raw, mapping.date_formats)
            if problem == "DATE_AMBIGUOUS":
                errors.append(("DATE_AMBIGUOUS",
                               f"{prefix}: {name} '{raw}' reads as different dates under the listed formats "
                               f"({', '.join(mapping.date_formats)}); list exactly one format."))
            elif problem:
                errors.append(("DATE_INVALID",
                               f"{prefix}: {name} '{raw}' does not match the date format "
                               f"({', '.join(mapping.date_formats)})."))
        parsed_dates[name] = parsed
        values[name] = parsed.isoformat() if parsed else None

    starts, expires = parsed_dates.get("starts_at"), parsed_dates.get("expires_at")
    if starts and expires and expires < starts:
        errors.append(("DATES_INCONSISTENT", f"{prefix}: expiration date is before start date."))
    if status in (MembershipStatus.ACTIVE.value, MembershipStatus.GRACE.value) and not expires:
        if not any(code in ("DATE_INVALID", "DATE_AMBIGUOUS") for code, _ in errors):
            errors.append(("EXPIRY_REQUIRED_FOR_STATUS",
                           f"{prefix}: status '{status}' needs an expiration date."))
    if as_of is not None and expires:
        today = as_of.astimezone(timezone.utc).date()
        if status == MembershipStatus.ACTIVE.value and expires <= today:
            warnings.append("ACTIVE_BUT_EXPIRED: the source says active but the expiration date has passed; "
                            "the OC lifecycle will move it to grace/lapsed.")
        if status == MembershipStatus.LAPSED.value and expires > today:
            warnings.append("LAPSED_BUT_UNEXPIRED: the source says lapsed but the expiration date is in the future.")

    return CanonicalRow(row_number, source_id, values, errors, warnings)


def _utc_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).date().isoformat()


def oc_values(member: Mapping[str, Any]) -> dict[str, Any]:
    """The current OC record in the same canonical shape as :func:`canonicalize_row`."""
    address = None
    if member.get("mailing_line1"):
        address = {name: member.get(f"mailing_{name}") for name in ADDRESS_FIELDS}
    return {
        "display_name": member.get("display_name"),
        "first_name": member.get("first_name"),
        "last_name": member.get("last_name"),
        "email": member.get("primary_email"),
        "phone": member.get("primary_phone"),
        "address": address,
        "level_code": member.get("level_code"),
        "status": member.get("status"),
        "starts_at": _utc_date(member.get("starts_at")),
        "expires_at": _utc_date(member.get("expires_at")),
    }


def field_diff(incoming: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Field-level differences for every field the mapping supplies."""
    diff: dict[str, dict[str, Any]] = {}
    for name, value in incoming.items():
        if name == "source_record_id":
            continue
        if name == "status" and value is None:
            continue
        existing = current.get(name)
        if name == "address":
            mine = value or {}
            theirs = existing or {}
            for part in ADDRESS_FIELDS:
                if mine.get(part) != theirs.get(part):
                    diff[f"address.{part}"] = {"oc": theirs.get(part), "incoming": mine.get(part)}
            continue
        if value != existing:
            diff[name] = {"oc": existing, "incoming": value}
    return diff


def all_members(service: SocietyCRMService, organization_id: int) -> dict[int, dict[str, Any]]:
    repo = service._repo
    out: dict[int, dict[str, Any]] = {}
    offset = 0
    while True:
        page, total = repo.list_members(organization_id=organization_id, limit=500, offset=offset)
        for row in page:
            out[int(row["membership_id"])] = row
        offset += len(page)
        if not page or offset >= total:
            return out


def member_links(service: SocietyCRMService, organization_id: int, source_system: str) -> dict[str, dict[str, Any]]:
    return {
        link["source_record_id"]: link
        for link in service._repo.list_external_links(
            organization_id=organization_id, source_system=source_system, source_record_type=SOURCE_RECORD_TYPE
        )
    }


def normalize_source_system(value: str) -> str:
    system = (value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,39}", system):
        raise ValueError("INVALID_SOURCE_SYSTEM")
    return system


def _to_datetime(iso: str | None) -> datetime | None:
    if iso is None:
        return None
    parsed = date.fromisoformat(iso)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class _RowOutcome(Exception):
    def __init__(self, status: str, code: str, message: str) -> None:
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


def import_members(
    service: SocietyCRMService,
    principal: CRMPrincipal,
    organization_id: int,
    csv_text: str,
    mapping: ColumnMapping,
    *,
    dry_run: bool = True,
    source_system: str = "neon",
    import_id: str | None = None,
    as_of: datetime | None = None,
) -> ImportReport:
    service._require(organization_id, principal, SocietyCapability.MEMBER_IMPORT)
    repo = service._repo
    system = normalize_source_system(source_system)
    run_id = (import_id or uuid.uuid4().hex).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", run_id):
        raise ValueError("INVALID_IMPORT_ID")
    report = ImportReport(
        import_id=run_id,
        organization_id=organization_id,
        source_system=system,
        dry_run=dry_run,
        accepted=False,
        mapping_sha256=mapping.fingerprint(),
        csv_sha256=hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
    )
    parsed = parse_csv(csv_text, mapping)
    report.unknown_headers = parsed.unknown_headers
    report.total_rows = len(parsed.records)
    if parsed.fatal_errors:
        report.fatal_errors = parsed.fatal_errors
        return report
    report.accepted = True

    levels = {level["code"]: level for level in repo.list_membership_levels(
        organization_id=organization_id, include_inactive=True)}
    links = member_links(service, organization_id, system)
    members = all_members(service, organization_id)
    linked_constituents = {int(link["constituent_id"]): sid for sid, link in links.items()
                           if link.get("constituent_id") is not None}

    def audit(action: str, extra: dict[str, Any] | None = None) -> None:
        repo.record_audit_event(
            organization_id=organization_id, actor_subject=principal.subject, action=action,
            entity_type="import", entity_id=run_id,
            metadata={
                "source_system": system,
                "mapping_sha256": report.mapping_sha256,
                "csv_sha256": report.csv_sha256,
                "total_rows": report.total_rows,
                **(extra or {}),
            },
        )

    if not dry_run:
        audit("import.started")
    try:
        seen_ids: dict[str, int] = {}
        seen_emails: dict[str, int] = {}
        for row_number, cells, shape_ok in parsed.records:
            report.rows.append(
                _process_row(
                    service, principal, organization_id, system, mapping, levels, links, members,
                    linked_constituents, seen_ids, seen_emails, row_number, cells, shape_ok,
                    dry_run=dry_run, as_of=as_of,
                )
            )
    except BaseException:
        if not dry_run:
            audit("import.failed", {"rows_processed": len(report.rows), "counts": report.counts})
        raise
    if sum(report.counts.values()) != report.total_rows:  # rows must never disappear
        raise RuntimeError("IMPORT_ROW_ACCOUNTING_MISMATCH")
    if not dry_run:
        audit("import.completed", {"counts": report.counts})
    return report


def _process_row(
    service: SocietyCRMService,
    principal: CRMPrincipal,
    organization_id: int,
    system: str,
    mapping: ColumnMapping,
    levels: Mapping[str, Mapping[str, Any]],
    links: Mapping[str, Mapping[str, Any]],
    members: Mapping[int, Mapping[str, Any]],
    linked_constituents: Mapping[int, str],
    seen_ids: dict[str, int],
    seen_emails: dict[str, int],
    row_number: int,
    cells: dict[str, str],
    shape_ok: bool,
    *,
    dry_run: bool,
    as_of: datetime | None,
) -> RowResult:
    repo = service._repo
    row = canonicalize_row(row_number, cells, shape_ok, mapping, levels, as_of=as_of)
    result = RowResult(row_number=row_number, source_record_id=row.source_record_id, status="invalid",
                       warnings=list(row.warnings))

    if row.source_record_id and row.source_record_id in seen_ids:
        result.status = "duplicate_in_file"
        result.reason_codes = ["DUPLICATE_SOURCE_RECORD_ID_IN_FILE"]
        result.messages = [f"Row {row_number}: source id '{row.source_record_id}' already appeared in row "
                           f"{seen_ids[row.source_record_id]}; this row was not imported. Remove one of them."]
        return result
    if row.source_record_id:
        seen_ids[row.source_record_id] = row_number
    if not row.valid:
        result.reason_codes = [code for code, _ in row.errors]
        result.messages = [message for _, message in row.errors]
        return result

    email = row.values.get("email")
    if email and email in seen_emails:
        result.status = "duplicate_in_file"
        result.reason_codes = ["DUPLICATE_EMAIL_IN_FILE"]
        result.messages = [f"Row {row_number}: email is the same as row {seen_emails[email]}; this row was not "
                           "imported. Merge the two source records or give each its own email."]
        return result
    if email:
        seen_emails[email] = row_number

    sha = row.payload_sha256(system)
    result.source_payload_sha256 = sha
    link = links.get(row.source_record_id)
    if link is not None:
        result.constituent_id = link.get("constituent_id")
        result.membership_id = link.get("membership_id")
        member = members.get(int(link["membership_id"])) if link.get("membership_id") is not None else None
        if member is None:
            result.status = "conflict"
            result.reason_codes = ["LINK_TARGET_MISSING"]
            result.messages = [f"Row {row_number}: source id '{row.source_record_id}' is linked but the linked OC "
                               "membership was not found; resolve the link by hand."]
            return result
        diff = field_diff(row.values, oc_values(member))
        if not diff:
            result.status = "unchanged"
            return result
        result.status = "conflict"
        result.reason_codes = ["FIELD_CONFLICT"]
        result.diff = diff
        result.messages = [f"Row {row_number}: the OC record differs from the source in "
                           f"{', '.join(sorted(diff))}; nothing was overwritten. Decide which value is correct "
                           "and update Neon or OC."]
        return result

    if email:
        existing = repo.find_constituents_by_email(organization_id=organization_id, email=email)
        if existing:
            result.status = "possible_duplicate"
            other = sorted({linked_constituents[c] for c in existing if c in linked_constituents})
            if other:
                result.reason_codes = ["EMAIL_MATCHES_OTHER_SOURCE_RECORD"]
                result.messages = [f"Row {row_number}: email already belongs to OC person(s) linked to source id(s) "
                                   f"{', '.join(other)}; not created. Merge the duplicate source records first."]
            else:
                result.reason_codes = ["EMAIL_MATCHES_UNLINKED_CONSTITUENT"]
                result.messages = [f"Row {row_number}: email already belongs to OC person id(s) "
                                   f"{', '.join(str(c) for c in existing)} with no {system} link; not created. "
                                   "Confirm it is the same person and link or merge by hand."]
            result.constituent_id = existing[0]
            return result

    level = levels[row.values["level_code"]]
    if not level.get("is_active", True):
        result.reason_codes = ["LEVEL_INACTIVE"]
        result.messages = [f"Row {row_number}: OC level '{level['code']}' is inactive; reactivate it or map the "
                           "row to an active level."]
        return result

    result.status = "create"
    if dry_run:
        return result
    try:
        constituent_id, membership_id = _create_member(repo, principal, organization_id, system, row, sha)
    except _RowOutcome as outcome:
        result.status = outcome.status
        result.reason_codes = [outcome.code]
        result.messages = [f"Row {row_number}: {outcome.message}"]
        return result
    except (ValueError, LookupError) as exc:
        result.status = "invalid"
        result.reason_codes = [str(exc).split(":")[0] or "ROW_REJECTED"]
        result.messages = [f"Row {row_number}: the CRM rejected this row ({exc}); nothing from it was saved."]
        return result
    except (psycopg.errors.IntegrityError, psycopg.errors.DataError) as exc:
        result.status = "invalid"
        result.reason_codes = ["DATABASE_REJECTED_ROW"]
        result.messages = [f"Row {row_number}: the database rejected this row ({type(exc).__name__}); nothing from "
                           "it was saved."]
        return result
    result.constituent_id, result.membership_id = constituent_id, membership_id
    return result


def _create_member(repo, principal: CRMPrincipal, organization_id: int, system: str, row: CanonicalRow,
                   sha: str) -> tuple[int, int]:
    values = row.values
    actor = principal.subject
    source_id = row.source_record_id
    with repo.atomic(organization_id):
        # Re-check inside the unit: another import may have linked this id meanwhile.
        if repo.get_external_link(organization_id=organization_id, source_system=system,
                                  source_record_type=SOURCE_RECORD_TYPE, source_record_id=source_id):
            raise _RowOutcome("conflict", "CONCURRENTLY_LINKED",
                              "this source id was linked by another run while importing; re-run the import.")
        email = values.get("email")
        if email and repo.find_constituents_by_email(organization_id=organization_id, email=email):
            raise _RowOutcome("possible_duplicate", "EMAIL_MATCHES_UNLINKED_CONSTITUENT",
                              "the email was added to OC while importing; not created.")
        person = repo.create_person(organization_id=organization_id, display_name=values["display_name"],
                                    first_name=values.get("first_name"), last_name=values.get("last_name"),
                                    actor_subject=actor)
        constituent_id = int(person["id"])
        if email:
            repo.set_primary_email(organization_id=organization_id, constituent_id=constituent_id, email=email,
                                   actor_subject=actor)
        if values.get("phone"):
            repo.set_primary_phone(organization_id=organization_id, constituent_id=constituent_id,
                                   phone=values["phone"], actor_subject=actor)
        address = values.get("address")
        if address:
            repo.set_mailing_address(organization_id=organization_id, constituent_id=constituent_id,
                                     actor_subject=actor, **address)
        status = MembershipStatus(values.get("status") or MembershipStatus.PENDING.value)
        create_status = MembershipStatus.PENDING if status is MembershipStatus.CANCELLED else status
        membership = repo.create_membership(
            organization_id=organization_id, constituent_id=constituent_id, level_code=values["level_code"],
            actor_subject=actor, status=create_status, starts_at=_to_datetime(values.get("starts_at")),
            expires_at=_to_datetime(values.get("expires_at")), source_kind="import",
            source_ref=f"{system}:{source_id}"[:200],
        )
        membership_id = int(membership["id"])
        if status is MembershipStatus.CANCELLED:
            repo.update_membership_status(
                organization_id=organization_id, membership_id=membership_id, status=MembershipStatus.CANCELLED,
                actor_subject=actor, reason=f"import:{system}:{source_id}: source status cancelled",
            )
        repo.link_external_record(
            organization_id=organization_id, source_system=system, source_record_type=SOURCE_RECORD_TYPE,
            source_record_id=source_id, actor_subject=actor, constituent_id=constituent_id,
            membership_id=membership_id, source_payload_sha256=sha,
        )
    return constituent_id, membership_id


__all__ = [
    "CANONICAL_FIELDS",
    "ColumnMapping",
    "ImportMappingError",
    "ImportReport",
    "NEON_DEFAULT_MAPPING",
    "RowResult",
    "import_members",
]
