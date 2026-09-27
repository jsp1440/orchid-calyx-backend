"""OC-CRM-BACKUP-RESTORE-001: real pg_dump/pg_restore proof for the society CRM.

Re-runnable against a persistent database: every run seeds two new organizations
with uuid-suffixed slugs/subjects, and every scratch restore database is uniquely
named and dropped.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.constituent_platform.crm_migrations import CRM_MIGRATIONS
from app.constituent_platform.backup_verification import (
    DEFAULT_SCHEMAS,
    SCRATCH_PREFIX,
    compare_fingerprints,
    drop_scratch_database,
    find_pg_binary,
    redact_dsn,
    run_backup_restore_drill,
    snapshot_fingerprint,
)
from app.constituent_platform.tenant_db import dsn_connection_factory, tenant_transaction

pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = CRM_MIGRATIONS
SEEDED_TABLES = (
    "oc_constituent.organizations",
    "oc_constituent.membership_levels",
    "oc_constituent.constituents",
    "oc_constituent.email_addresses",
    "oc_constituent.phone_numbers",
    "oc_constituent.postal_addresses",
    "oc_constituent.entitlements",
    "oc_constituent.memberships",
    "oc_constituent.organization_staff_roles",
    "oc_constituent.identity_links",
    "oc_constituent.organization_identity_bindings",
    "oc_constituent.communication_preferences",
    "oc_constituent.suppressions",
    "oc_constituent.membership_renewals",
    "oc_constituent.membership_household_members",
    "oc_constituent.external_record_links",
    "oc_constituent.crm_audit_events",
    "oc_communications.intents",
    "oc_communications.audience_snapshots",
    "oc_communications.audience_members",
    "oc_communications.approval_events",
    "oc_constituent.payments",
    "oc_constituent.payment_events",
    "oc_constituent.refunds",
    "oc_constituent.donations",
    "oc_constituent.donation_receipt_counters",
    "oc_constituent.member_portal_invites",
)


def _required_here() -> bool:
    if os.environ.get("OC_REQUIRE_POSTGRES", "").strip() in {"1", "true", "yes"}:
        return True
    return os.environ.get("CI", "").strip().lower() == "true"


@pytest.fixture(scope="module")
def binaries() -> tuple[str, str]:
    pg_dump = find_pg_binary("pg_dump", "PG_DUMP_BIN")
    pg_restore = find_pg_binary("pg_restore", "PG_RESTORE_BIN")
    if not pg_dump or not pg_restore:
        reason = "pg_dump/pg_restore client binaries not found (set PG_DUMP_BIN/PG_RESTORE_BIN)"
        if _required_here():
            pytest.fail(reason, pytrace=False)
        pytest.skip(reason)
    return pg_dump, pg_restore


@pytest.fixture(scope="module")
def dsn() -> str:
    return os.environ["DATABASE_URL"]


def _insert(cur: psycopg.Cursor, table: str, **cols: Any) -> int:
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    cur.execute(f"INSERT INTO {table} ({names}) VALUES ({marks}) RETURNING id", tuple(cols.values()))
    return cur.fetchone()[0]


@pytest.fixture(scope="module")
def seeded(dsn: str) -> dict[str, Any]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for _ in range(2):  # twice: migrations must be idempotent
            for path in MIGRATIONS:
                conn.execute((ROOT / path).read_text(encoding="utf-8"))

    s = uuid.uuid4().hex[:12]
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    year = timedelta(days=365)
    shared_email = f"pat.grower+{s}@example.org"  # same address in both societies
    ids: dict[str, Any] = {"suffix": s}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        a = _insert(cur, "oc_constituent.organizations", slug=f"drill-a-{s}", display_name="Orchid Society (Drill)")
        b = _insert(cur, "oc_constituent.organizations", slug=f"drill-b-{s}", display_name="Orchid Society (Drill)")
        ids.update(org_a=a, org_b=b)
        for org in (a, b):
            _insert(cur, "oc_constituent.membership_levels", organization_id=org, code="individual",
                    display_name="Individual", dues_amount_cents=3500, benefits=json.dumps({"newsletter": True}))
            _insert(cur, "oc_constituent.membership_levels", organization_id=org, code="household",
                    display_name="Household", dues_amount_cents=5000, household_max_members=4, grace_days=45)

        def person(org: int, first: str, last: str) -> int:
            return _insert(cur, "oc_constituent.constituents", kind="person", display_name=f"{first} {last}",
                           first_name=first, last_name=last, owner_organization_id=org)

        pat_a, sam_a, kim_a, lee_a, robin_a = (person(a, n, "Grower") for n in ("Pat", "Sam", "Kim", "Lee", "Robin"))
        pat_b, sam_b = person(b, "Pat", "Grower"), person(b, "Sam", "Grower")
        ids.update(pat_a=pat_a, pat_b=pat_b)

        _insert(cur, "oc_constituent.email_addresses", constituent_id=pat_a, organization_id=a,
                normalized_email=shared_email, is_primary=True, verification_state="verified", verified_at=now)
        _insert(cur, "oc_constituent.email_addresses", constituent_id=pat_b, organization_id=b,
                normalized_email=shared_email, is_primary=True)
        _insert(cur, "oc_constituent.email_addresses", constituent_id=sam_a, organization_id=a,
                normalized_email=f"sam+{s}@example.org")
        _insert(cur, "oc_constituent.phone_numbers", constituent_id=pat_a, organization_id=a,
                normalized_phone="+15555550100", is_primary=True)
        _insert(cur, "oc_constituent.phone_numbers", constituent_id=pat_b, organization_id=b,
                normalized_phone="+15555550100", label="home")
        for org, who in ((a, pat_a), (b, pat_b)):
            _insert(cur, "oc_constituent.postal_addresses", constituent_id=who, organization_id=org,
                    line1="1 Synthetic Way", locality="Testville", postal_code="00000", country_code="US",
                    is_primary=True)
        _insert(cur, "oc_constituent.entitlements", constituent_id=pat_a, organization_id=a,
                entitlement_code="journal_access", source_kind="membership", limits=json.dumps({"seats": 1}))

        def membership(org: int, who: int, level: str, status: str, **extra: Any) -> int:
            return _insert(cur, "oc_constituent.memberships", organization_id=org, constituent_id=who,
                           level_code=level, status=status, starts_at=now - year, expires_at=now,
                           status_changed_at=now, **extra)

        m_pat_a = membership(a, pat_a, "household", "active", last_renewed_at=now)
        m_sam_a = membership(a, sam_a, "individual", "grace")
        membership(a, kim_a, "individual", "cancelled", cancelled_at=now, cancellation_reason="moved away")
        m_lee_a = membership(a, lee_a, "individual", "pending", source_kind="import", source_ref="row-17")
        m_pat_b = membership(b, pat_b, "individual", "lapsed")
        m_sam_b = membership(b, sam_b, "individual", "active")
        ids.update(tamper_membership=m_lee_a, memberships_b={m_pat_b, m_sam_b})
        cur.execute("SELECT id FROM oc_constituent.memberships WHERE organization_id = %s", (a,))
        ids["memberships_a"] = {row[0] for row in cur.fetchall()}

        _insert(cur, "oc_constituent.organization_staff_roles", organization_id=a, constituent_id=sam_a,
                role_code="admin", granted_by_subject="platform:operator")
        _insert(cur, "oc_constituent.organization_staff_roles", organization_id=a, constituent_id=pat_a,
                role_code="viewer", granted_by_subject="platform:operator", status="revoked", revoked_at=now)
        _insert(cur, "oc_constituent.organization_staff_roles", organization_id=b, constituent_id=pat_b,
                role_code="treasurer", granted_by_subject="platform:operator")

        subject_a, subject_b = f"supabase:{uuid.uuid4()}", f"supabase:{uuid.uuid4()}"
        _insert(cur, "oc_constituent.identity_links", constituent_id=pat_a, auth_subject=subject_a)
        _insert(cur, "oc_constituent.identity_links", constituent_id=pat_b, auth_subject=subject_b)
        _insert(cur, "oc_constituent.organization_identity_bindings", organization_id=a, constituent_id=pat_a,
                auth_subject=subject_a, verification_method="verified_email_match", bound_by_subject="platform:operator")
        _insert(cur, "oc_constituent.organization_identity_bindings", organization_id=b, constituent_id=pat_b,
                auth_subject=subject_b, verification_method="admin_attested", bound_by_subject=subject_b)
        _insert(cur, "oc_constituent.organization_identity_bindings", organization_id=a, constituent_id=sam_a,
                auth_subject=f"supabase:{uuid.uuid4()}", verification_method="admin_attested",
                bound_by_subject="platform:operator", status="revoked", revoked_at=now,
                revoked_by_subject="platform:operator")

        first = _insert(cur, "oc_constituent.communication_preferences", organization_id=a, constituent_id=pat_a,
                        purpose="marketing", state="subscribed", source_kind="signup_form")
        ids["tamper_preference"] = _insert(
            cur, "oc_constituent.communication_preferences", organization_id=a, constituent_id=pat_a,
            purpose="marketing", state="unsubscribed", source_kind="unsubscribe_link", evidence_ref="msg-1",
            supersedes_id=first)
        _insert(cur, "oc_constituent.communication_preferences", organization_id=b, constituent_id=pat_b,
                purpose="membership_relationship", state="subscribed", source_kind="admin")

        _insert(cur, "oc_constituent.suppressions", organization_id=a, constituent_id=pat_a,
                normalized_email=shared_email, kind="hard_bounce", reason="550 mailbox unavailable",
                source_kind="provider_webhook")
        _insert(cur, "oc_constituent.suppressions", organization_id=b, normalized_email=shared_email,
                kind="unsubscribe", source_kind="list_unsubscribe")
        _insert(cur, "oc_constituent.suppressions", organization_id=a, constituent_id=sam_a,
                kind="admin_block", source_kind="admin", lifted_at=now)

        _insert(cur, "oc_constituent.membership_renewals", organization_id=a, membership_id=m_pat_a,
                renewal_key=f"renew-{s}-1", level_code="household", term_months=12, previous_status="grace",
                previous_expires_at=now - year, new_starts_at=now - year, new_expires_at=now,
                source_kind="offline_payment", source_ref="check-1042", actor_subject="staff:treasurer")
        _insert(cur, "oc_constituent.membership_renewals", organization_id=b, membership_id=m_sam_b,
                renewal_key=f"renew-{s}-1", level_code="individual", term_months=12, previous_status="active",
                new_starts_at=now - year, new_expires_at=now, source_kind="admin", actor_subject="staff:admin")
        # Money: a partially refunded check, a cash payment in the other tenant, and a receipted donation.
        pay_a = _insert(cur, "oc_constituent.payments", organization_id=a, constituent_id=pat_a,
                        membership_id=m_pat_a, purpose="membership_dues", amount_cents=4500, currency="USD",
                        method="check", check_number="1042", status="partially_refunded",
                        refunded_amount_cents=500, received_at=now, recorded_by_subject="staff:treasurer",
                        idempotency_key=f"check-{s}-1042")
        _insert(cur, "oc_constituent.payment_events", organization_id=a, payment_id=pay_a, to_status="succeeded",
                reason="recorded", amount_cents=4500, actor_subject="staff:treasurer")
        _insert(cur, "oc_constituent.payment_events", organization_id=a, payment_id=pay_a, from_status="succeeded",
                to_status="partially_refunded", reason="duplicate dues", amount_cents=500,
                actor_subject="staff:treasurer")
        _insert(cur, "oc_constituent.refunds", organization_id=a, payment_id=pay_a, amount_cents=500,
                reason="duplicate dues", idempotency_key=f"refund-{s}-1", recorded_by_subject="staff:treasurer")
        _insert(cur, "oc_constituent.payments", organization_id=b, constituent_id=pat_b, purpose="other",
                amount_cents=1200, currency="USD", method="cash", status="succeeded", received_at=now,
                recorded_by_subject="staff:treasurer", idempotency_key=f"cash-{s}-1")
        gift = _insert(cur, "oc_constituent.payments", organization_id=a, constituent_id=pat_a, purpose="donation",
                       amount_cents=10000, currency="USD", method="check", check_number="1043", status="succeeded",
                       received_at=now, recorded_by_subject="staff:treasurer", idempotency_key=f"gift-{s}-1")
        cur.execute(
            "INSERT INTO oc_constituent.donation_receipt_counters (organization_id, last_receipt_number) "
            "VALUES (%s, 1) ON CONFLICT (organization_id) DO UPDATE SET last_receipt_number = "
            "oc_constituent.donation_receipt_counters.last_receipt_number + 1 RETURNING last_receipt_number",
            (a,),
        )
        receipt_number = cur.fetchone()[0]
        _insert(cur, "oc_constituent.donations", organization_id=a, constituent_id=pat_a, payment_id=gift,
                amount_cents=10000, currency="USD", designation="greenhouse-fund", tax_deductible_cents=10000,
                receipt_number=receipt_number, receipt_issued_at=now)
        _insert(cur, "oc_constituent.member_portal_invites", organization_id=a, constituent_id=pat_a,
                code_sha256=hashlib.sha256(f"invite-{s}".encode()).hexdigest(), created_by_subject="staff:admin",
                expires_at=now + year)
        _insert(cur, "oc_constituent.membership_household_members", organization_id=a, membership_id=m_pat_a,
                constituent_id=robin_a, relationship="partner")
        _insert(cur, "oc_constituent.external_record_links", organization_id=a, constituent_id=pat_a,
                membership_id=m_pat_a, source_system="legacy_csv", source_record_type="member",
                source_record_id=f"csv-{s}-1", source_payload_sha256="a" * 64)
        _insert(cur, "oc_constituent.external_record_links", organization_id=b, constituent_id=pat_b,
                source_system="neon_import", source_record_type="person", source_record_id=f"neon-{s}-1")

        ids["audit_a"] = _insert(cur, "oc_constituent.crm_audit_events", organization_id=a,
                                 actor_subject="staff:admin", action="membership.created", entity_type="membership",
                                 entity_id=str(m_pat_a), after_state=json.dumps({"status": "active"}))
        _insert(cur, "oc_constituent.crm_audit_events", organization_id=a, actor_subject="staff:admin",
                action="membership.status_changed", entity_type="membership", entity_id=str(m_sam_a),
                before_state=json.dumps({"status": "active"}), after_state=json.dumps({"status": "grace"}),
                metadata=json.dumps({"reason": "dues overdue"}))
        _insert(cur, "oc_constituent.crm_audit_events", organization_id=b, actor_subject="staff:admin",
                action="membership.created", entity_type="membership", entity_id=str(m_pat_b))

        intent = _insert(cur, "oc_communications.intents", organization_id=a, purpose="membership_relationship",
                         initiating_module="crm", initiating_principal="staff:communications", subject="Renewal",
                         required_auth_class="staff")
        snapshot = _insert(cur, "oc_communications.audience_snapshots", intent_id=intent)
        _insert(cur, "oc_communications.audience_members", snapshot_id=snapshot, constituent_id=pat_a,
                normalized_email=shared_email, allowed=False, decision_reason="hard_bounce")
        cur.execute("UPDATE oc_communications.audience_snapshots SET audience_sha256 = %s, frozen_at = %s "
                    "WHERE id = %s", ("b" * 64, now, snapshot))
        _insert(cur, "oc_communications.approval_events", intent_id=intent, action="approved",
                principal="staff:admin", auth_class="staff", audience_sha256="b" * 64)
        conn.commit()
    return ids


@pytest.fixture()
def kept_scratch(dsn: str):
    names: list[str] = []
    yield names
    for name in names:
        drop_scratch_database(dsn, name)


def _drill(dsn: str, binaries: tuple[str, str], seeded: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return run_backup_restore_drill(
        dsn, dsn, DEFAULT_SCHEMAS, binaries[0], binaries[1],
        isolation_organization_ids=[seeded["org_a"], seeded["org_b"]], **kwargs,
    )


def _scratch_dsn(dsn: str, name: str) -> str:
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    params["dbname"] = name
    return psycopg.conninfo.make_conninfo(**params)


def _scratch_exists(dsn: str, name: str) -> bool:
    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)", (name,)).fetchone()[0]


def test_restored_database_preserves_all_crm_state(dsn, binaries, seeded, kept_scratch) -> None:
    report = _drill(dsn, binaries, seeded, keep=True)
    kept_scratch.append(report["scratch_database"])
    json.dumps(report)  # JSON-serializable

    assert report["discrepancies"] == []
    assert report["pass"] is True
    assert report["isolation_verified_between_tenants"] is True
    assert report["checks"]["roles"]["missing_roles"] == []
    assert "oc_crm_runtime" in report["checks"]["roles"]["roles_referenced_by_policies"]
    assert report["checks"]["roles"]["policies_bound_to_runtime_role"] >= 17
    assert report["checks"]["isolation"]["failures"] == []
    guards = report["checks"]["append_only_guards"]["tables"]
    assert "CRM_AUDIT_IMMUTABLE" in guards["oc_constituent.crm_audit_events"]
    assert "CRM_AUDIT_IMMUTABLE" in guards["oc_constituent.membership_renewals"]
    assert report["dump_bytes"] > 0
    for step in ("pg_dump_seconds", "pg_restore_seconds", "fingerprint_source_seconds"):
        assert step in report["timings"]
    for table in SEEDED_TABLES:
        entry = report["tables"][table]
        assert entry["source_rows"] >= 1, table
        assert entry["match"] is True, table
        assert entry["source_rows"] == entry["restored_rows"], table
        assert entry["source_sha256"] == entry["restored_sha256"], table
    password = psycopg.conninfo.conninfo_to_dict(dsn).get("password")
    if password:
        blob = json.dumps(report)
        assert f"password={password}" not in blob and f":{password}@" not in blob

    scratch = _scratch_dsn(dsn, report["scratch_database"])
    with psycopg.connect(scratch) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="CRM_AUDIT_IMMUTABLE"):
            conn.execute("UPDATE oc_constituent.crm_audit_events SET action = 'tampered' WHERE id = %s",
                         (seeded["audit_a"],))
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="CRM_AUDIT_IMMUTABLE"):
            conn.execute("DELETE FROM oc_constituent.crm_audit_events WHERE id = %s", (seeded["audit_a"],))
        conn.rollback()

    connect = dsn_connection_factory(scratch)
    with tenant_transaction(seeded["org_a"], connect=connect) as cur:
        cur.execute("SELECT id FROM oc_constituent.memberships")
        assert {row["id"] for row in cur.fetchall()} == seeded["memberships_a"]
        cur.execute("SELECT DISTINCT organization_id FROM oc_constituent.email_addresses")
        assert [row["organization_id"] for row in cur.fetchall()] == [seeded["org_a"]]
        cur.execute("SELECT id FROM oc_constituent.constituents WHERE id = %s", (seeded["pat_b"],))
        assert cur.fetchall() == []  # same name/email, other tenant: invisible
    with tenant_transaction(seeded["org_b"], connect=connect) as cur:
        cur.execute("SELECT id FROM oc_constituent.memberships")
        assert {row["id"] for row in cur.fetchall()} == seeded["memberships_b"]
        cur.execute("SELECT id FROM oc_constituent.organizations")
        assert [row["id"] for row in cur.fetchall()] == [seeded["org_b"]]


def test_tampered_rows_are_reported_exactly(dsn, binaries, seeded) -> None:
    membership_id, preference_id = seeded["tamper_membership"], seeded["tamper_preference"]

    def tamper(conn: psycopg.Connection) -> None:
        with conn.transaction():
            conn.execute("SET LOCAL session_replication_role = replica")
            conn.execute("DELETE FROM oc_constituent.memberships WHERE id = %s", (membership_id,))
            conn.execute("UPDATE oc_constituent.communication_preferences SET state = 'subscribed' WHERE id = %s",
                         (preference_id,))

    report = _drill(dsn, binaries, seeded, after_restore_hook=tamper)
    assert report["pass"] is False
    assert report["scratch_database_dropped"] is True
    assert not _scratch_exists(dsn, report["scratch_database"])

    errors = {d["object"]: d for d in report["discrepancies"] if d["severity"] == "error"}
    assert set(errors) == {"oc_constituent.memberships", "oc_constituent.communication_preferences"}

    members = report["tables"]["oc_constituent.memberships"]
    assert members["restored_rows"] == members["source_rows"] - 1
    expected = (f"table oc_constituent.memberships: {members['source_rows']} rows in backup source, "
                f"{members['source_rows'] - 1} after restore")
    assert errors["oc_constituent.memberships"]["message"].startswith(expected)
    assert f"missing after restore: id={membership_id}" in errors["oc_constituent.memberships"]["message"]
    assert errors["oc_constituent.memberships"]["details"]["rows"]["missing_after_restore"] == [f"id={membership_id}"]

    prefs = errors["oc_constituent.communication_preferences"]
    assert prefs["category"] == "row_content"
    assert "row contents differ after restore" in prefs["message"]
    assert prefs["details"]["rows"]["changed_after_restore"] == [f"id={preference_id}"]
    assert prefs["details"]["rows"]["missing_after_restore"] == []


def test_tampered_safety_structure_is_reported(dsn, binaries, seeded) -> None:
    def tamper(conn: psycopg.Connection) -> None:
        conn.execute("ALTER TABLE oc_constituent.email_addresses DISABLE ROW LEVEL SECURITY")
        conn.execute("ALTER TABLE oc_constituent.crm_audit_events DISABLE TRIGGER trg_reject_crm_audit_update")
        conn.execute("DROP POLICY oc_crm_tenant_isolation ON oc_constituent.memberships")
        conn.execute("SELECT setval('oc_constituent.memberships_id_seq', 1)")

    report = _drill(dsn, binaries, seeded, after_restore_hook=tamper)
    assert report["pass"] is False
    messages = [d["message"] for d in report["discrepancies"]]
    assert ("table oc_constituent.email_addresses: row-level security is ENABLED in backup source but DISABLED "
            "after restore -- tenant isolation is lost for this table") in messages
    assert any(m.startswith("table oc_constituent.crm_audit_events: trigger trg_reject_crm_audit_update is "
                            "DISABLED after restore") for m in messages)
    assert ("table oc_constituent.memberships: policy oc_crm_tenant_isolation is missing after restore") in messages
    assert any(m.startswith("sequence oc_constituent.memberships_id_seq: next value is") and "would be reissued" in m
               for m in messages)
    assert any("would collide with restored ids" in m for m in messages)

    isolation = report["checks"]["isolation"]
    assert isolation["status"] == "fail"
    assert any("oc_constituent.email_addresses" in f and "NO tenant set" in f for f in isolation["failures"])
    assert any("oc_constituent.email_addresses" in f and "cross-tenant leak" in f for f in isolation["failures"])
    guards = report["checks"]["append_only_guards"]
    assert guards["status"] == "fail"
    assert guards["tables"]["oc_constituent.crm_audit_events"] == "fail_update_accepted"


def test_fingerprint_is_stable_and_detects_change(dsn, seeded) -> None:
    with psycopg.connect(dsn) as conn:
        first = snapshot_fingerprint(conn, DEFAULT_SCHEMAS)
        second = snapshot_fingerprint(conn, DEFAULT_SCHEMAS)
    assert compare_fingerprints(first, second) == []
    assert set(SEEDED_TABLES) <= set(first["tables"])
    altered = json.loads(json.dumps(second))
    altered["tables"]["oc_constituent.suppressions"]["row_count"] -= 1
    del altered["tables"]["oc_constituent.crm_audit_events"]
    messages = [d["message"] for d in compare_fingerprints(first, altered)]
    rows = first["tables"]["oc_constituent.suppressions"]["row_count"]
    assert f"table oc_constituent.suppressions: {rows} rows in backup source, {rows - 1} after restore" in messages
    assert any(m.startswith("table oc_constituent.crm_audit_events: missing after restore") for m in messages)


def test_cli_writes_report_and_exits_zero_on_pass(dsn, binaries, seeded, tmp_path, capsys) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("oc_crm_drill_cli", ROOT / "scripts/oc_crm_backup_restore_drill.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    output = tmp_path / "report.json"
    code = cli.main(["--source-dsn", dsn, "--admin-dsn", dsn, "--output", str(output),
                     "--schemas", "oc_constituent,oc_communications,oc_drill_absent_probe",
                     "--pg-dump-bin", binaries[0], "--pg-restore-bin", binaries[1]])
    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["pass"] is True
    assert report["scratch_database"].startswith(SCRATCH_PREFIX)
    assert report["schemas"] == ["oc_constituent", "oc_communications"]
    assert report["schemas_absent"] == ["oc_drill_absent_probe"]
    assert any("oc_drill_absent_probe" in w for w in report["warnings"])
    assert not _scratch_exists(dsn, report["scratch_database"])
    assert "PASS" in capsys.readouterr().out


def test_redaction_never_exposes_passwords() -> None:
    redacted = redact_dsn("postgresql://crm:s3cr3t-pw@db.example.org:5432/crm")
    assert "s3cr3t-pw" not in redacted and "password=***" in redacted
    with pytest.raises(ValueError, match="refusing to drop"):
        drop_scratch_database("postgresql://ignored@localhost/x", "production_db")


def test_new_tables_are_discovered_without_code_changes(dsn, binaries, seeded) -> None:
    """A table the harness has never heard of (e.g. a future donations ledger) is covered."""
    schema = f"oc_drill_future_{seeded['suffix']}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
        try:
            conn.execute(
                f"CREATE TABLE {schema}.donations (id BIGSERIAL PRIMARY KEY, organization_id BIGINT NOT NULL "
                f"REFERENCES oc_constituent.organizations(id), amount_cents BIGINT NOT NULL, "
                f"received_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            conn.execute(f"INSERT INTO {schema}.donations (organization_id, amount_cents) VALUES (%s, 2500), (%s, 100)",
                         (seeded["org_a"], seeded["org_b"]))

            def tamper(scratch: psycopg.Connection) -> None:
                scratch.execute(f"UPDATE {schema}.donations SET amount_cents = 2600 WHERE amount_cents = 2500")

            report = run_backup_restore_drill(
                dsn, dsn, [*DEFAULT_SCHEMAS, schema], binaries[0], binaries[1],
                isolation_organization_ids=[seeded["org_a"], seeded["org_b"]], after_restore_hook=tamper,
            )
            entry = report["tables"][f"{schema}.donations"]
            assert entry["source_rows"] == entry["restored_rows"] == 2
            assert entry["match"] is False
            assert f"{schema}.donations_id_seq" in report["sequences"]
            assert [d["object"] for d in report["discrepancies"]] == [f"{schema}.donations"]
            assert report["pass"] is False
        finally:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")
