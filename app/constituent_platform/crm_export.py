"""Roster CSV export and full organization export for the society CRM.

``export_roster_csv`` (``roster.export``) -- one row per membership, for mailing,
reconciliation and spreadsheets. Cells beginning with ``=``, ``+``, ``-``, ``@``, tab
or carriage return are prefixed with a single quote so a spreadsheet never evaluates
them as formulas (CSV/formula injection). This means a phone stored as ``+1805...``
appears as ``'+1805...`` in the CSV.

``export_organization`` (``organization.export``, admin only) -- a complete,
versioned JSON document with every tenant-owned row of every CRM table for one
organization, read in one REPEATABLE READ transaction under the tenant's RLS
context (so it cannot include another tenant's rows). It is the "leave Orchid
Continuum" artifact: nothing a society owns in the CRM is withheld from it. It
contains personal data and must be handled as such.

The document carries ``schema_version``, ``exported_at``, ``row_counts`` and
``body_sha256`` -- the sha256 of the canonical JSON of the document without that
field (``json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)``);
:func:`verify_organization_export` recomputes it.

Both exports write an audit event (``export.roster`` / ``export.organization``) with
row counts only, after the data has been read. The organization export's own audit
event is therefore not inside the export it describes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .authorization import SocietyCapability
from .crm_import import all_members
from .domain import MembershipStatus
from .society_service import CRMPrincipal, SocietyCRMService

EXPORT_FORMAT = "orchid-continuum.society-crm.organization-export"
EXPORT_SCHEMA_VERSION = 1

ROSTER_COLUMNS = (
    "membership_id",
    "display_name",
    "first_name",
    "last_name",
    "email",
    "phone",
    "mailing_line1",
    "mailing_line2",
    "mailing_locality",
    "mailing_administrative_area",
    "mailing_postal_code",
    "mailing_country_code",
    "level_code",
    "status",
    "starts_at",
    "expires_at",
    "neon_source_record_id",
)

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> str:
    """Render one cell, neutralizing spreadsheet formula injection."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        text = value.astimezone(timezone.utc).date().isoformat()
    else:
        text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def export_roster_csv(
    service: SocietyCRMService,
    principal: CRMPrincipal,
    organization_id: int,
    *,
    status: MembershipStatus | None = None,
    source_system: str = "neon",
) -> str:
    service._require(organization_id, principal, SocietyCapability.ROSTER_EXPORT)
    repo = service._repo
    members = all_members(service, organization_id)
    source_ids = {
        int(link["membership_id"]): link["source_record_id"]
        for link in repo.list_external_links(
            organization_id=organization_id, source_system=source_system, source_record_type="member"
        )
        if link.get("membership_id") is not None
    }
    rows = [m for m in members.values() if status is None or m["status"] == status.value]
    rows.sort(key=lambda m: ((m["display_name"] or "").lower(), m["membership_id"]))
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(ROSTER_COLUMNS)
    for m in rows:
        writer.writerow([
            csv_safe(v) for v in (
                m["membership_id"], m["display_name"], m["first_name"], m["last_name"], m["primary_email"],
                m["primary_phone"], m["mailing_line1"], m["mailing_line2"], m["mailing_locality"],
                m["mailing_administrative_area"], m["mailing_postal_code"], m["mailing_country_code"],
                m["level_code"], m["status"], m["starts_at"], m["expires_at"],
                source_ids.get(int(m["membership_id"])),
            )
        ])
    repo.record_audit_event(
        organization_id=organization_id, actor_subject=principal.subject, action="export.roster",
        entity_type="export", entity_id="roster",
        metadata={"row_count": len(rows), "status_filter": status.value if status else None},
    )
    return buffer.getvalue()


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    return value


def _canonical_sha256(body: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def verify_organization_export(document: dict[str, Any]) -> bool:
    body = {k: v for k, v in document.items() if k != "body_sha256"}
    return document.get("body_sha256") == _canonical_sha256(body)


def export_organization(
    service: SocietyCRMService, principal: CRMPrincipal, organization_id: int
) -> dict[str, Any]:
    service._require(organization_id, principal, SocietyCapability.ORGANIZATION_EXPORT)
    repo = service._repo
    tables = {key: [_json_value(row) for row in rows]
              for key, rows in repo.snapshot_tenant_tables(organization_id=organization_id).items()}
    body: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "schema_version": EXPORT_SCHEMA_VERSION,
        "organization_id": organization_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_by": principal.subject,
        "tables": tables,
        "row_counts": {key: len(rows) for key, rows in tables.items()},
        "excluded": {
            "oc_communications.audience_snapshots/audience_members/approval_events":
                "not organization-scoped in the current schema; not readable by the CRM runtime role",
            "oc_constituent.identity_links": "platform-global account links, not tenant-owned",
        },
    }
    document = {**body, "body_sha256": _canonical_sha256(body)}
    repo.record_audit_event(
        organization_id=organization_id, actor_subject=principal.subject, action="export.organization",
        entity_type="export", entity_id="organization",
        metadata={"schema_version": EXPORT_SCHEMA_VERSION, "row_counts": body["row_counts"],
                  "body_sha256": document["body_sha256"]},
    )
    return document


__all__ = [
    "EXPORT_SCHEMA_VERSION",
    "ROSTER_COLUMNS",
    "csv_safe",
    "export_organization",
    "export_roster_csv",
    "verify_organization_export",
]
