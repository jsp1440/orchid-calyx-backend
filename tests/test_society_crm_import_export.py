"""Society CRM: Neon CSV import, reconciliation, roster export and organization export.

Runs against real PostgreSQL. Every test creates its own synthetic organizations
(unique slugs) and uuid-based emails, so the module is re-runnable against a
persistent database and never depends on table emptiness.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest

from app.constituent_platform.authorization import SocietyAccessDenied, SocietyRole
from app.constituent_platform.crm_export import (
    ROSTER_COLUMNS,
    csv_safe,
    export_organization,
    export_roster_csv,
    verify_organization_export,
)
from app.constituent_platform.crm_import import NEON_DEFAULT_MAPPING, ColumnMapping, import_members
from app.constituent_platform.crm_reconcile import reconcile
from app.constituent_platform.domain import MembershipStatus
from app.constituent_platform.postgres_repository import PostgresSocietyCRMRepository
from app.constituent_platform.society_service import CRMPrincipal, SocietyCRMService

pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)

MIGRATIONS = (
    "migrations/20260823_oc_constituent_communications_foundation.sql",
    "migrations/20260926_society_crm_p0_core.sql",
    "migrations/20260927_society_crm_p1_tenant_isolation.sql",
)
OPERATOR = CRMPrincipal("owner:platform-operator", platform_operator=True)

HEADERS = list(NEON_DEFAULT_MAPPING.columns) + ["Neon Internal Notes"]
MAPPING = dataclasses.replace(
    NEON_DEFAULT_MAPPING, level_value_map={"Individual": "individual", "Family": "family"}
)

ALL_TABLES = (
    ("oc_constituent", "organizations"),
    ("oc_constituent", "constituents"),
    ("oc_constituent", "identity_links"),
    ("oc_constituent", "email_addresses"),
    ("oc_constituent", "phone_numbers"),
    ("oc_constituent", "postal_addresses"),
    ("oc_constituent", "memberships"),
    ("oc_constituent", "entitlements"),
    ("oc_constituent", "communication_preferences"),
    ("oc_constituent", "suppressions"),
    ("oc_constituent", "membership_levels"),
    ("oc_constituent", "organization_staff_roles"),
    ("oc_constituent", "external_record_links"),
    ("oc_constituent", "crm_audit_events"),
    ("oc_constituent", "organization_identity_bindings"),
    ("oc_constituent", "membership_renewals"),
    ("oc_constituent", "membership_household_members"),
    ("oc_communications", "intents"),
)


def _apply_migrations(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in MIGRATIONS:
            conn.execute(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ["DATABASE_URL"]
    _apply_migrations(value)
    return value


@pytest.fixture()
def repo(dsn: str) -> PostgresSocietyCRMRepository:
    return PostgresSocietyCRMRepository(dsn)


@pytest.fixture()
def crm(repo: PostgresSocietyCRMRepository) -> SocietyCRMService:
    return SocietyCRMService(repo)


# ---------------------------------------------------------------------------
# Helpers (local to this module by design)
# ---------------------------------------------------------------------------


def _subject() -> str:
    return f"supabase:{uuid.uuid4()}"


def _society(crm: SocietyCRMService, label: str = "Orchid Society") -> tuple[int, CRMPrincipal]:
    org = crm.create_organization(OPERATOR, slug=f"imp-{uuid.uuid4().hex[:12]}", display_name=label)
    subject = _subject()
    crm.bootstrap_admin(OPERATOR, org["id"], display_name="Pat Admin", auth_subject=subject)
    admin = CRMPrincipal(subject)
    crm.create_level(admin, org["id"], code="individual", display_name="Individual", dues_amount_cents=3000)
    crm.create_level(admin, org["id"], code="family", display_name="Family", dues_amount_cents=4500,
                     household_max_members=3)
    return int(org["id"]), admin


def _staff(crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, org_id: int, admin: CRMPrincipal,
           role: SocietyRole | None) -> CRMPrincipal:
    subject = _subject()
    person = repo.create_person(organization_id=org_id, display_name="Staff Person", actor_subject=admin.subject)
    crm.bind_identity(admin, org_id, constituent_id=person["id"], auth_subject=subject)
    if role is not None:
        crm.grant_role(admin, org_id, constituent_id=person["id"], role=role)
    return CRMPrincipal(subject)


def _email(tag: str = "m") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.org"


def _row(source_id: str, first: str, last: str, email: str, *, level: str = "Individual", status: str = "Active",
         start: str = "01/15/2026", expires: str = "01/15/2027", phone: str = "(805) 555-0101",
         line1: str = "1 Orchid Way", city: str = "San Luis Obispo", state: str = "CA", postal: str = "93401",
         country: str = "United States") -> dict[str, str]:
    return {
        "Account ID": source_id, "First Name": first, "Last Name": last, "Email 1": email, "Phone 1": phone,
        "Address Line 1": line1, "Address Line 2": "", "City": city, "State/Province": state,
        "Zip/Postal Code": postal, "Country": country, "Membership Level": level, "Membership Status": status,
        "Start Date": start, "Expiration Date": expires, "Neon Internal Notes": "ignored",
    }


def _csv(rows: list[dict[str, str]], headers: list[str] | None = None) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers or HEADERS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def _three_rows() -> list[dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    return [
        _row(f"N{tag}1", "Ada", "Orchid", _email("ada")),
        _row(f"N{tag}2", "Ben", "Cattleya", _email("ben"), level="Family", status="Grace",
             start="02/01/2025", expires="02/01/2026"),
        _row(f"N{tag}3", "Cy", "Dendrobium", _email("cy"), status="Pending", start="", expires=""),
    ]


def _table_counts(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn) as conn:
        return {
            f"{schema}.{table}": conn.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]
            for schema, table in ALL_TABLES
        }


def _org_audit_actions(dsn: str, org_id: int) -> list[str]:
    with psycopg.connect(dsn) as conn:
        return [r[0] for r in conn.execute(
            "SELECT action FROM oc_constituent.crm_audit_events WHERE organization_id = %s ORDER BY id", (org_id,)
        ).fetchall()]


def _assert_counts_add_up(report) -> None:
    assert report.accepted
    assert report.total_rows == sum(report.counts.values())
    assert len(report.rows) == report.total_rows


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def test_dry_run_is_default_and_performs_zero_writes(crm, dsn) -> None:
    org_id, admin = _society(crm)
    text = _csv(_three_rows())
    before = _table_counts(dsn)
    report = import_members(crm, admin, org_id, text, MAPPING)
    after = _table_counts(dsn)
    assert report.dry_run is True
    assert before == after  # no rows in any CRM table, not even an audit event
    assert report.counts["create"] == 3
    assert report.unknown_headers == ["Neon Internal Notes"]
    _assert_counts_add_up(report)
    json.dumps(report.to_dict())  # JSON-serializable


def test_first_import_creates_and_identical_repeat_is_unchanged_with_no_writes(crm, repo, dsn) -> None:
    org_id, admin = _society(crm)
    rows = _three_rows()
    text = _csv(rows)

    first = import_members(crm, admin, org_id, text, MAPPING, dry_run=False)
    _assert_counts_add_up(first)
    assert first.counts["create"] == 3, first.to_dict()
    by_id = {r.source_record_id: r for r in first.rows}

    ada = crm.get_member(admin, org_id, by_id[rows[0]["Account ID"]].membership_id)
    assert ada["display_name"] == "Ada Orchid"
    assert ada["primary_email"] == rows[0]["Email 1"]
    assert ada["primary_phone"] == "8055550101"
    assert ada["mailing_country_code"] == "US" and ada["mailing_locality"] == "San Luis Obispo"
    assert ada["status"] == "active" and ada["source_kind"] == "import"
    assert ada["expires_at"].date().isoformat() == "2027-01-15"
    ben = crm.get_member(admin, org_id, by_id[rows[1]["Account ID"]].membership_id)
    assert ben["status"] == "grace" and ben["level_code"] == "family"
    cy = crm.get_member(admin, org_id, by_id[rows[2]["Account ID"]].membership_id)
    assert cy["status"] == "pending" and cy["expires_at"] is None
    # Imported state is not presented as an OC-applied renewal.
    assert repo.list_renewals(organization_id=org_id, membership_id=ada["membership_id"]) == []
    link = repo.get_external_link(organization_id=org_id, source_system="neon", source_record_type="member",
                                  source_record_id=rows[0]["Account ID"])
    assert link["constituent_id"] == ada["constituent_id"] and link["membership_id"] == ada["membership_id"]
    assert len(link["source_payload_sha256"]) == 64

    before = _table_counts(dsn)
    audit_before = _org_audit_actions(dsn, org_id)
    second = import_members(crm, admin, org_id, text, MAPPING, dry_run=False)
    after = _table_counts(dsn)
    _assert_counts_add_up(second)
    assert second.counts["unchanged"] == 3, second.to_dict()
    assert {k: v for k, v in before.items() if k != "oc_constituent.crm_audit_events"} == \
        {k: v for k, v in after.items() if k != "oc_constituent.crm_audit_events"}
    assert after["oc_constituent.crm_audit_events"] == before["oc_constituent.crm_audit_events"] + 2
    assert _org_audit_actions(dsn, org_id)[len(audit_before):] == ["import.started", "import.completed"]


def test_import_audit_events_carry_counts_but_no_row_content(crm, dsn) -> None:
    org_id, admin = _society(crm)
    rows = _three_rows()
    report = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False, import_id="fcos-pilot-1")
    with psycopg.connect(dsn) as conn:
        events = conn.execute(
            "SELECT action, entity_id, metadata FROM oc_constituent.crm_audit_events "
            "WHERE organization_id = %s AND entity_type = 'import' ORDER BY id", (org_id,)
        ).fetchall()
    assert [(a, e) for a, e, _ in events] == [("import.started", "fcos-pilot-1"),
                                              ("import.completed", "fcos-pilot-1")]
    completed = events[1][2]
    assert completed["counts"] == report.counts
    blob = json.dumps([m for _, _, m in events])
    for row in rows:
        assert row["Email 1"] not in blob and row["Last Name"] not in blob


def test_conflicts_are_reported_with_field_diff_and_never_overwritten(crm, dsn) -> None:
    org_id, admin = _society(crm)
    rows = _three_rows()
    first = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    ada_id = next(r.membership_id for r in first.rows if r.source_record_id == rows[0]["Account ID"])
    ben_id = next(r.membership_id for r in first.rows if r.source_record_id == rows[1]["Account ID"])

    # OC-side edit after import.
    edited_email = _email("ada-new")
    crm.change_email(admin, org_id, ada_id, edited_email)
    # Source-side change in the CSV.
    rows[1]["Membership Level"] = "Individual"

    before = _table_counts(dsn)
    report = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    after = _table_counts(dsn)
    _assert_counts_add_up(report)
    assert report.counts == {"create": 0, "unchanged": 1, "conflict": 2, "possible_duplicate": 0,
                             "invalid": 0, "duplicate_in_file": 0}
    by_id = {r.source_record_id: r for r in report.rows}
    ada = by_id[rows[0]["Account ID"]]
    assert ada.reason_codes == ["FIELD_CONFLICT"]
    assert ada.diff == {"email": {"oc": edited_email, "incoming": rows[0]["Email 1"]}}
    assert by_id[rows[1]["Account ID"]].diff == {"level_code": {"oc": "family", "incoming": "individual"}}
    # Nothing overwritten; only the started/completed audit pair was written.
    assert crm.get_member(admin, org_id, ada_id)["primary_email"] == edited_email
    assert crm.get_member(admin, org_id, ben_id)["level_code"] == "family"
    assert after["oc_constituent.crm_audit_events"] == before["oc_constituent.crm_audit_events"] + 2
    assert {k: v for k, v in before.items() if k != "oc_constituent.crm_audit_events"} == \
        {k: v for k, v in after.items() if k != "oc_constituent.crm_audit_events"}


def test_invalid_rows_are_reported_with_row_numbers_and_counts_add_up(crm) -> None:
    org_id, admin = _society(crm)
    tag = uuid.uuid4().hex[:8]
    rows = [
        _row(f"V{tag}1", "Good", "Row", _email()),                             # row 2
        _row(f"V{tag}2", "Bad", "Email", "not-an-email"),                      # row 3
        _row("", "Missing", "Id", _email()),                                   # row 4
        _row(f"V{tag}4", "Gold", "Level", _email(), level="Gold"),             # row 5
        _row(f"V{tag}5", "Bad", "Date", _email(), expires="2027-13-45"),       # row 6
        _row(f"V{tag}6", "Odd", "Status", _email(), status="Honorary"),        # row 7
        _row(f"V{tag}7", "No", "Expiry", _email(), expires=""),                # row 8 (active needs expiry)
        _row(f"V{tag}8", "Bad", "Phone", _email(), phone="12"),                # row 9
    ]
    report = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    _assert_counts_add_up(report)
    assert report.counts["create"] == 1 and report.counts["invalid"] == 7
    by_row = {r.row_number: r for r in report.rows}
    assert by_row[2].status == "create"
    assert by_row[3].reason_codes == ["EMAIL_INVALID"]
    assert by_row[4].reason_codes == ["SOURCE_RECORD_ID_MISSING"]
    assert by_row[5].reason_codes == ["LEVEL_NOT_MAPPED"]
    assert by_row[5].messages == ["Row 5: level 'Gold' has no mapping; add it to level_value_map or create the "
                                  "level."]
    assert by_row[6].reason_codes == ["DATE_INVALID"] and by_row[6].messages[0].startswith("Row 6:")
    assert by_row[7].reason_codes == ["STATUS_NOT_MAPPED"]
    assert by_row[8].reason_codes == ["EXPIRY_REQUIRED_FOR_STATUS"]
    assert by_row[9].reason_codes == ["PHONE_INVALID"]
    members, total = crm.list_members(admin, org_id)
    assert total == 1  # invalid rows wrote nothing


def test_ambiguous_dates_are_errors_never_guesses(crm) -> None:
    org_id, admin = _society(crm)
    mapping = dataclasses.replace(MAPPING, date_formats=("%m/%d/%Y", "%d/%m/%Y"))
    tag = uuid.uuid4().hex[:8]
    rows = [
        _row(f"D{tag}1", "Amb", "Iguous", _email(), start="03/04/2026", expires="03/04/2027"),
        _row(f"D{tag}2", "Un", "Ambiguous", _email(), start="01/31/2026", expires="01/31/2027"),
    ]
    report = import_members(crm, admin, org_id, _csv(rows), mapping)
    _assert_counts_add_up(report)
    assert report.rows[0].status == "invalid" and "DATE_AMBIGUOUS" in report.rows[0].reason_codes
    assert report.rows[1].status == "create"


def test_within_file_duplicates_and_existing_email_possible_duplicate(crm, repo, dsn) -> None:
    org_id, admin = _society(crm)
    existing_email = _email("existing")
    crm.create_member(admin, org_id, display_name="Already Here", email=existing_email, level_code="individual")
    tag = uuid.uuid4().hex[:8]
    shared = _email("shared")
    rows = [
        _row(f"W{tag}1", "First", "Copy", shared),                 # row 2 create
        _row(f"W{tag}1", "Second", "Copy", _email()),              # row 3 duplicate source id
        _row(f"W{tag}3", "Same", "Email", shared.upper()),         # row 4 duplicate email (normalized)
        _row(f"W{tag}4", "Maybe", "Duplicate", existing_email),    # row 5 possible duplicate
    ]
    before = _table_counts(dsn)["oc_constituent.constituents"]
    report = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    _assert_counts_add_up(report)
    statuses = [(r.row_number, r.status, r.reason_codes) for r in report.rows]
    assert statuses == [
        (2, "create", []),
        (3, "duplicate_in_file", ["DUPLICATE_SOURCE_RECORD_ID_IN_FILE"]),
        (4, "duplicate_in_file", ["DUPLICATE_EMAIL_IN_FILE"]),
        (5, "possible_duplicate", ["EMAIL_MATCHES_UNLINKED_CONSTITUENT"]),
    ]
    assert "row 2" in report.rows[1].messages[0]
    assert _table_counts(dsn)["oc_constituent.constituents"] == before + 1
    assert len(repo.find_constituents_by_email(organization_id=org_id, email=existing_email)) == 1


def test_mapping_problems_reject_the_whole_import_before_any_write(crm, dsn) -> None:
    org_id, admin = _society(crm)
    text = _csv(_three_rows())
    no_id = ColumnMapping(columns={k: v for k, v in MAPPING.columns.items() if v != "source_record_id"},
                          level_value_map=MAPPING.level_value_map, status_value_map=MAPPING.status_value_map,
                          country_value_map=MAPPING.country_value_map, date_formats=MAPPING.date_formats)
    wrong_header = dataclasses.replace(MAPPING, columns={**MAPPING.columns, "Member Since": "starts_at"})
    before = _table_counts(dsn)
    for mapping, code in ((no_id, "SOURCE_RECORD_ID_UNMAPPED"), (wrong_header, "CANONICAL_FIELD_MAPPED_TWICE")):
        report = import_members(crm, admin, org_id, text, mapping, dry_run=False)
        assert report.accepted is False and report.rows == []
        assert code in [e["code"] for e in report.fatal_errors]
    missing_header = dataclasses.replace(MAPPING, columns={**MAPPING.columns, "Household ID": "display_name"})
    report = import_members(crm, admin, org_id, text, missing_header, dry_run=False)
    assert "MAPPED_HEADER_MISSING" in [e["code"] for e in report.fatal_errors]
    assert _table_counts(dsn) == before


def test_cancelled_and_lapsed_source_statuses(crm, repo) -> None:
    org_id, admin = _society(crm)
    tag = uuid.uuid4().hex[:8]
    rows = [
        _row(f"S{tag}1", "Can", "Celled", _email(), status="Cancelled", start="01/01/2024", expires="01/01/2025"),
        _row(f"S{tag}2", "Lap", "Sed", _email(), status="Lapsed", start="01/01/2024", expires="01/01/2025"),
    ]
    report = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    assert report.counts["create"] == 2, report.to_dict()
    cancelled = crm.get_member(admin, org_id, report.rows[0].membership_id)
    lapsed = crm.get_member(admin, org_id, report.rows[1].membership_id)
    assert cancelled["status"] == "cancelled" and cancelled["expires_at"].date().isoformat() == "2025-01-01"
    assert lapsed["status"] == "lapsed"
    again = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    assert again.counts["unchanged"] == 2, again.to_dict()


def test_import_requires_member_import_capability(crm, repo) -> None:
    org_id, admin = _society(crm)
    text = _csv(_three_rows())
    for role in (SocietyRole.VIEWER, SocietyRole.TREASURER, None):
        principal = _staff(crm, repo, org_id, admin, role)
        with pytest.raises(SocietyAccessDenied):
            import_members(crm, principal, org_id, text, MAPPING)
        with pytest.raises(SocietyAccessDenied):
            reconcile(crm, principal, org_id, text, MAPPING)
    editor = _staff(crm, repo, org_id, admin, SocietyRole.MEMBERSHIP_EDITOR)
    assert import_members(crm, editor, org_id, text, MAPPING, dry_run=False).counts["create"] == 3
    other_org, _ = _society(crm)
    with pytest.raises(SocietyAccessDenied):
        import_members(crm, admin, other_org, text, MAPPING)


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_reconciliation_identifies_missing_extra_changed_and_is_clean_after_matching_import(crm, dsn) -> None:
    org_id, admin = _society(crm)
    rows = _three_rows()
    text = _csv(rows)

    before_import = reconcile(crm, admin, org_id, text, MAPPING)
    assert before_import.clean is False
    assert sorted(m["source_record_id"] for m in before_import.missing_in_oc) == \
        sorted(r["Account ID"] for r in rows)

    import_members(crm, admin, org_id, text, MAPPING, dry_run=False)
    after_import = reconcile(crm, admin, org_id, text, MAPPING)
    assert after_import.clean is True, after_import.to_dict()
    assert after_import.matched == 3

    # Drift: an OC-only member, a record removed from Neon, a changed record, a new Neon record.
    oc_only = crm.create_member(admin, org_id, display_name="OC Only", email=_email("oconly"),
                                level_code="individual")
    changed_rows = [dict(r) for r in rows[:2]]
    changed_rows[0]["Membership Status"] = "Lapsed"
    changed_rows[0]["Expiration Date"] = "01/15/2026"
    new_row = _row(f"NEW{uuid.uuid4().hex[:8]}", "New", "Neon", _email("new"))
    drift = reconcile(crm, admin, org_id, _csv(changed_rows + [new_row]), MAPPING)
    assert drift.clean is False
    assert [m["source_record_id"] for m in drift.missing_in_oc] == [new_row["Account ID"]]
    assert len(drift.changed) == 1
    assert drift.changed[0]["source_record_id"] == rows[0]["Account ID"]
    assert drift.changed[0]["diff"] == {
        "status": {"oc": "active", "incoming": "lapsed"},
        "expires_at": {"oc": "2027-01-15", "incoming": "2026-01-15"},
    }
    extras = {(e["reason_codes"][0], e["source_record_id"], e["membership_id"]) for e in drift.extra_in_oc}
    removed_link_membership = next(m for m in drift.to_dict()["extra_in_oc"]
                                   if m["reason_codes"] == ["LINKED_ID_ABSENT_FROM_SNAPSHOT"])["membership_id"]
    assert extras == {
        ("NOT_LINKED", None, oc_only["membership_id"]),
        ("LINKED_ID_ABSENT_FROM_SNAPSHOT", rows[2]["Account ID"], removed_link_membership),
    }
    assert drift.matched == 1
    json.dumps(drift.to_dict())
    actions = _org_audit_actions(dsn, org_id)
    assert actions.count("reconciliation.run") == 3
    # Reconciliation never changed OC.
    assert crm.get_member(admin, org_id, removed_link_membership)["status"] == "pending"


# ---------------------------------------------------------------------------
# Roster export
# ---------------------------------------------------------------------------


def _parse_roster(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_roster_export_roles_and_contents(crm, repo, dsn) -> None:
    org_id, admin = _society(crm)
    rows = _three_rows()
    import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    editor = _staff(crm, repo, org_id, admin, SocietyRole.MEMBERSHIP_EDITOR)
    treasurer = _staff(crm, repo, org_id, admin, SocietyRole.TREASURER)
    viewer = _staff(crm, repo, org_id, admin, SocietyRole.VIEWER)
    nobody = _staff(crm, repo, org_id, admin, None)

    for principal in (editor, treasurer):
        text = export_roster_csv(crm, principal, org_id)
        parsed = _parse_roster(text)
        assert tuple(parsed[0].keys()) == ROSTER_COLUMNS
        assert len(parsed) == 3
        ada = next(r for r in parsed if r["display_name"] == "Ada Orchid")
        assert ada["neon_source_record_id"] == rows[0]["Account ID"]
        assert ada["email"] == rows[0]["Email 1"] and ada["expires_at"] == "2027-01-15"
        assert ada["mailing_postal_code"] == "93401" and ada["status"] == "active"
    active_only = _parse_roster(export_roster_csv(crm, editor, org_id, status=MembershipStatus.ACTIVE))
    assert [r["display_name"] for r in active_only] == ["Ada Orchid"]
    for principal in (viewer, nobody):
        with pytest.raises(SocietyAccessDenied):
            export_roster_csv(crm, principal, org_id)
    other_org, _ = _society(crm)
    with pytest.raises(SocietyAccessDenied):
        export_roster_csv(crm, editor, other_org)
    with psycopg.connect(dsn) as conn:
        events = conn.execute(
            "SELECT metadata FROM oc_constituent.crm_audit_events WHERE organization_id = %s "
            "AND action = 'export.roster' ORDER BY id", (org_id,)
        ).fetchall()
    assert [e[0]["row_count"] for e in events] == [3, 3, 1]
    assert rows[0]["Email 1"] not in json.dumps([e[0] for e in events])


def test_roster_export_neutralizes_csv_injection(crm) -> None:
    org_id, admin = _society(crm)
    tag = uuid.uuid4().hex[:8]
    rows = [
        _row(f"X{tag}1", "=HYPERLINK(\"http://evil\")", "Payload", _email(), line1="@SUM(A1:A9)"),
        _row(f"X{tag}2", "-2+3", "Minus", _email(), city="+cmd|' /C calc'!A0"),
    ]
    report = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    assert report.counts["create"] == 2, report.to_dict()
    parsed = _parse_roster(export_roster_csv(crm, admin, org_id))
    cells = [value for row in parsed for value in row.values()]
    assert not any(cell.startswith(("=", "+", "-", "@")) for cell in cells)
    assert "'=HYPERLINK(\"http://evil\") Payload" in cells
    assert "'@SUM(A1:A9)" in cells and "'-2+3" in cells and "'+cmd|' /C calc'!A0" in cells
    assert csv_safe("=1+1") == "'=1+1" and csv_safe("\t=x") == "'\t=x" and csv_safe("plain") == "plain"
    assert csv_safe(None) == ""


# ---------------------------------------------------------------------------
# Organization export
# ---------------------------------------------------------------------------


def test_organization_export_is_complete_tenant_only_and_admin_only(crm, repo, dsn) -> None:
    org_a, admin_a = _society(crm, "Five Cities Orchid Society")
    org_b, admin_b = _society(crm, "Five Cities Orchid Society")
    shared = _email("shared")
    b_only = _email("b-only")
    tag = uuid.uuid4().hex[:8]
    import_members(crm, admin_a, org_a, _csv([_row(f"A{tag}", "Same", "Person", shared, level="Family")]), MAPPING,
                   dry_run=False)
    import_members(crm, admin_b, org_b, _csv([_row(f"B{tag}1", "Same", "Person", shared),
                                              _row(f"B{tag}2", "Only", "InB", b_only)]), MAPPING, dry_run=False)
    member_a = crm.list_members(admin_a, org_a)[0][0]
    crm.add_household_member(admin_a, org_a, member_a["membership_id"], display_name="Household Kid")

    treasurer = _staff(crm, repo, org_a, admin_a, SocietyRole.TREASURER)
    editor = _staff(crm, repo, org_a, admin_a, SocietyRole.MEMBERSHIP_EDITOR)
    for principal in (treasurer, editor):
        with pytest.raises(SocietyAccessDenied):
            export_organization(crm, principal, org_a)
    with pytest.raises(SocietyAccessDenied):
        export_organization(crm, admin_a, org_b)

    doc = export_organization(crm, admin_a, org_a)
    assert doc["schema_version"] == 1 and doc["organization_id"] == org_a
    assert verify_organization_export(doc)
    tampered = json.loads(json.dumps(doc))
    tampered["tables"]["constituents"][0]["display_name"] = "Changed"
    assert not verify_organization_export(tampered)

    # Completeness: every tenant-owned table's row count equals what PostgreSQL holds for A.
    tenant_columns = {key: (table, column) for key, table, column in repo.TENANT_EXPORT_TABLES}
    with psycopg.connect(dsn) as conn:
        for key, (table, column) in tenant_columns.items():
            expected = conn.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (org_a,)).fetchone()[0]
            if key == "crm_audit_events":
                expected -= 1  # the export's own export.organization event is written after the snapshot
            assert doc["row_counts"][key] == expected == len(doc["tables"][key]), key
        b_constituents = {r[0] for r in conn.execute(
            "SELECT id FROM oc_constituent.constituents WHERE owner_organization_id = %s", (org_b,)).fetchall()}
    for key in ("organizations", "membership_levels", "constituents", "email_addresses", "memberships",
                "membership_household_members", "organization_staff_roles", "organization_identity_bindings",
                "external_record_links", "crm_audit_events"):
        assert doc["row_counts"][key] >= 1, key

    # Isolation: nothing of B, although both societies hold the identical email.
    for key, rows in doc["tables"].items():
        column = tenant_columns[key][1]
        assert all(row[column] == org_a for row in rows), key
    assert not b_constituents & {row["id"] for row in doc["tables"]["constituents"]}
    body = json.dumps(doc)
    assert b_only not in body
    shared_rows = [r for r in doc["tables"]["email_addresses"] if r["normalized_email"] == shared]
    assert len(shared_rows) == 1 and shared_rows[0]["organization_id"] == org_a

    with psycopg.connect(dsn) as conn:
        event = conn.execute(
            "SELECT metadata FROM oc_constituent.crm_audit_events WHERE organization_id = %s "
            "AND action = 'export.organization' ORDER BY id DESC LIMIT 1", (org_a,)
        ).fetchone()
    assert event[0]["row_counts"] == doc["row_counts"] and event[0]["body_sha256"] == doc["body_sha256"]
    assert shared not in json.dumps(event[0])


def test_a_row_failing_mid_write_rolls_back_alone_and_is_reported(crm, repo, dsn, monkeypatch) -> None:
    org_id, admin = _society(crm)
    rows = _three_rows()
    failing_id = rows[1]["Account ID"]
    original = repo.link_external_record

    def flaky_link(**kwargs):
        if kwargs["source_record_id"] == failing_id:
            raise ValueError("SIMULATED_LINK_FAILURE")
        return original(**kwargs)

    monkeypatch.setattr(repo, "link_external_record", flaky_link)
    before = _table_counts(dsn)
    report = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    after = _table_counts(dsn)
    _assert_counts_add_up(report)
    assert [r.status for r in report.rows] == ["create", "invalid", "create"]
    assert report.rows[1].reason_codes == ["SIMULATED_LINK_FAILURE"]
    assert report.rows[1].messages[0].startswith("Row 3:")
    # Person, email, phone, address and membership of the failed row were rolled back with it.
    assert after["oc_constituent.constituents"] == before["oc_constituent.constituents"] + 2
    assert after["oc_constituent.memberships"] == before["oc_constituent.memberships"] + 2
    assert after["oc_constituent.external_record_links"] == before["oc_constituent.external_record_links"] + 2
    assert repo.find_constituents_by_email(organization_id=org_id, email=rows[1]["Email 1"]) == []
    monkeypatch.undo()
    retry = import_members(crm, admin, org_id, _csv(rows), MAPPING, dry_run=False)
    assert [r.status for r in retry.rows] == ["unchanged", "create", "unchanged"]
