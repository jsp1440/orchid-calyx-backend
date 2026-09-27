"""Neon-vs-Orchid Continuum reconciliation report (read-only).

During the FCOS shadow pilot Neon remains the system of record. ``reconcile`` compares
a fresh Neon export with the OC tenant and reports:

* ``missing_in_oc`` -- valid snapshot rows with no ``(source_system, "member", id)`` link;
* ``extra_in_oc`` -- OC memberships in this organization with no link to this source
  system (``NOT_LINKED``), and links whose source id is absent from the snapshot
  (``LINKED_ID_ABSENT_FROM_SNAPSHOT``);
* ``changed`` -- linked rows whose mapped fields differ (status, level, dates, email,
  name, phone, address), with a field-level diff;
* ``invalid`` / ``duplicate_in_file`` -- snapshot rows that cannot be reconciled;
* ``matched`` -- linked rows with no differences.

``clean`` is true only when missing, extra, changed, invalid and duplicate_in_file are
all empty and the mapping was accepted. (Invalid snapshot rows are Neon data OC
cannot account for, so a report with any of them is not clean.)

Nothing is written except one ``reconciliation.run`` audit event carrying counts and
hashes, never row content. Requires ``member.import``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .authorization import SocietyCapability
from .crm_import import (
    ColumnMapping,
    normalize_source_system,
    all_members,
    canonicalize_row,
    field_diff,
    member_links,
    oc_values,
    parse_csv,
)
from .society_service import CRMPrincipal, SocietyCRMService


@dataclass
class ReconciliationReport:
    organization_id: int
    source_system: str
    accepted: bool
    mapping_sha256: str
    csv_sha256: str
    snapshot_rows: int = 0
    fatal_errors: list[dict[str, str]] = field(default_factory=list)
    unknown_headers: list[str] = field(default_factory=list)
    matched: int = 0
    missing_in_oc: list[dict[str, Any]] = field(default_factory=list)
    extra_in_oc: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[dict[str, Any]] = field(default_factory=list)
    duplicate_in_file: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.accepted and not (
            self.missing_in_oc or self.extra_in_oc or self.changed or self.invalid or self.duplicate_in_file
        )

    @property
    def counts(self) -> dict[str, int]:
        return {
            "snapshot_rows": self.snapshot_rows,
            "matched": self.matched,
            "missing_in_oc": len(self.missing_in_oc),
            "extra_in_oc": len(self.extra_in_oc),
            "changed": len(self.changed),
            "invalid": len(self.invalid),
            "duplicate_in_file": len(self.duplicate_in_file),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "source_system": self.source_system,
            "accepted": self.accepted,
            "clean": self.clean,
            "mapping_sha256": self.mapping_sha256,
            "csv_sha256": self.csv_sha256,
            "counts": self.counts,
            "fatal_errors": list(self.fatal_errors),
            "unknown_headers": list(self.unknown_headers),
            "missing_in_oc": list(self.missing_in_oc),
            "extra_in_oc": list(self.extra_in_oc),
            "changed": list(self.changed),
            "invalid": list(self.invalid),
            "duplicate_in_file": list(self.duplicate_in_file),
        }


def reconcile(
    service: SocietyCRMService,
    principal: CRMPrincipal,
    organization_id: int,
    neon_csv_text: str,
    mapping: ColumnMapping,
    source_system: str = "neon",
) -> ReconciliationReport:
    service._require(organization_id, principal, SocietyCapability.MEMBER_IMPORT)
    repo = service._repo
    system = normalize_source_system(source_system)
    report = ReconciliationReport(
        organization_id=organization_id,
        source_system=system,
        accepted=False,
        mapping_sha256=mapping.fingerprint(),
        csv_sha256=hashlib.sha256(neon_csv_text.encode("utf-8")).hexdigest(),
    )
    parsed = parse_csv(neon_csv_text, mapping)
    report.unknown_headers = parsed.unknown_headers
    report.snapshot_rows = len(parsed.records)
    if parsed.fatal_errors:
        report.fatal_errors = parsed.fatal_errors
    else:
        report.accepted = True
        _compare(service, organization_id, system, mapping, parsed, report)
    repo.record_audit_event(
        organization_id=organization_id, actor_subject=principal.subject, action="reconciliation.run",
        entity_type="reconciliation", entity_id=system,
        metadata={
            "source_system": system,
            "accepted": report.accepted,
            "clean": report.clean,
            "counts": report.counts,
            "mapping_sha256": report.mapping_sha256,
            "csv_sha256": report.csv_sha256,
        },
    )
    return report


def _compare(service, organization_id, system, mapping, parsed, report) -> None:
    repo = service._repo
    levels = {level["code"]: level for level in repo.list_membership_levels(
        organization_id=organization_id, include_inactive=True)}
    links = member_links(service, organization_id, system)
    members = all_members(service, organization_id)

    snapshot_ids: set[str] = set()
    seen: dict[str, int] = {}
    for row_number, cells, shape_ok in parsed.records:
        row = canonicalize_row(row_number, cells, shape_ok, mapping, levels)
        sid = row.source_record_id
        if sid:
            snapshot_ids.add(sid)
        if sid and sid in seen:
            report.duplicate_in_file.append({
                "row_number": row_number, "source_record_id": sid, "first_row_number": seen[sid],
                "message": f"Row {row_number}: source id '{sid}' already appeared in row {seen[sid]}.",
            })
            continue
        if sid:
            seen[sid] = row_number
        if not row.valid:
            report.invalid.append({
                "row_number": row_number, "source_record_id": sid,
                "reason_codes": [code for code, _ in row.errors],
                "messages": [message for _, message in row.errors],
            })
            continue
        link = links.get(sid)
        if link is None:
            email = row.values.get("email")
            matches = repo.find_constituents_by_email(organization_id=organization_id, email=email) if email else []
            report.missing_in_oc.append({
                "row_number": row_number, "source_record_id": sid,
                "email_matches_oc_constituent_ids": matches,
                "message": f"Row {row_number}: source id '{sid}' is not in OC"
                           + (" (its email matches an existing OC person; check for a duplicate)." if matches
                              else "; run the import to add it."),
            })
            continue
        member = members.get(int(link["membership_id"])) if link.get("membership_id") is not None else None
        if member is None:
            report.changed.append({
                "row_number": row_number, "source_record_id": sid, "membership_id": link.get("membership_id"),
                "reason_codes": ["LINK_TARGET_MISSING"], "diff": {},
                "message": f"Row {row_number}: source id '{sid}' is linked but its OC membership was not found.",
            })
            continue
        diff = field_diff(row.values, oc_values(member))
        if diff:
            report.changed.append({
                "row_number": row_number, "source_record_id": sid, "membership_id": member["membership_id"],
                "reason_codes": ["FIELD_CHANGED"], "diff": diff,
                "message": f"Row {row_number}: differs in {', '.join(sorted(diff))}.",
            })
        else:
            report.matched += 1

    linked_memberships = {int(link["membership_id"]) for link in links.values() if link.get("membership_id")}
    for membership_id, member in sorted(members.items()):
        if membership_id not in linked_memberships:
            report.extra_in_oc.append({
                "membership_id": membership_id, "constituent_id": member["constituent_id"],
                "source_record_id": None, "reason_codes": ["NOT_LINKED"],
                "message": f"OC membership {membership_id} has no {system} record; add it to {system} or "
                           "confirm it is intentionally OC-only.",
            })
    for sid, link in sorted(links.items()):
        if sid not in snapshot_ids:
            report.extra_in_oc.append({
                "membership_id": link.get("membership_id"), "constituent_id": link.get("constituent_id"),
                "source_record_id": sid, "reason_codes": ["LINKED_ID_ABSENT_FROM_SNAPSHOT"],
                "message": f"OC is linked to {system} id '{sid}', which is not in this export; check whether it "
                           f"was deleted or merged in {system}.",
            })


__all__ = ["ReconciliationReport", "reconcile"]
