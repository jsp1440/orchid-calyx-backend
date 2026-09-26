from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from app.constituent_platform.domain import MembershipStatus
from app.constituent_platform.postgres_repository import PostgresSocietyCRMRepository

pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)


def _apply_migrations(dsn: str) -> None:
    foundation = Path("migrations/20260823_oc_constituent_communications_foundation.sql").read_text(encoding="utf-8")
    crm = Path("migrations/20260926_society_crm_p0_core.sql").read_text(encoding="utf-8")
    with psycopg.connect(dsn) as conn:
        conn.execute(foundation)
        conn.execute(crm)
        conn.execute(crm)


def test_society_memberships_are_organization_scoped_and_audited() -> None:
    dsn = os.environ["DATABASE_URL"]
    _apply_migrations(dsn)
    repo = PostgresSocietyCRMRepository(dsn)

    org_a = repo.create_organization(slug="crm-test-a", display_name="CRM Test Society A")
    org_b = repo.create_organization(slug="crm-test-b", display_name="CRM Test Society B")
    repo.create_membership_level(
        organization_id=org_a["id"],
        code="individual",
        display_name="Individual",
        dues_amount_cents=3000,
    )
    repo.create_membership_level(
        organization_id=org_b["id"],
        code="individual",
        display_name="Individual",
        dues_amount_cents=2500,
    )

    person = repo.create_person(display_name="Same Person", first_name="Same", last_name="Person")
    repo.add_email(
        organization_id=org_a["id"],
        constituent_id=person["id"],
        email="same@example.com",
    )
    repo.add_email(
        organization_id=org_b["id"],
        constituent_id=person["id"],
        email="same@example.com",
    )

    member_a = repo.create_membership(
        organization_id=org_a["id"],
        constituent_id=person["id"],
        level_code="individual",
        status=MembershipStatus.ACTIVE,
        actor_subject="test:admin-a",
    )
    member_b = repo.create_membership(
        organization_id=org_b["id"],
        constituent_id=person["id"],
        level_code="individual",
        status=MembershipStatus.ACTIVE,
        actor_subject="test:admin-b",
    )

    assert repo.get_member(organization_id=org_a["id"], membership_id=member_a["id"]) is not None
    assert repo.get_member(organization_id=org_b["id"], membership_id=member_b["id"]) is not None

    # Cross-tenant lookup must fail closed even when the membership id exists.
    assert repo.get_member(organization_id=org_a["id"], membership_id=member_b["id"]) is None
    assert repo.get_member(organization_id=org_b["id"], membership_id=member_a["id"]) is None

    rows_a = repo.list_members(organization_id=org_a["id"])
    rows_b = repo.list_members(organization_id=org_b["id"])
    assert [row["membership_id"] for row in rows_a] == [member_a["id"]]
    assert [row["membership_id"] for row in rows_b] == [member_b["id"]]

    changed = repo.update_membership_status(
        organization_id=org_a["id"],
        membership_id=member_a["id"],
        status=MembershipStatus.GRACE,
        actor_subject="test:admin-a",
    )
    assert changed and changed["status"] == "grace"
    assert (
        repo.update_membership_status(
            organization_id=org_b["id"],
            membership_id=member_a["id"],
            status=MembershipStatus.CANCELLED,
            actor_subject="test:admin-b",
        )
        is None
    )

    events_a = repo.list_audit_events(organization_id=org_a["id"])
    events_b = repo.list_audit_events(organization_id=org_b["id"])
    assert [event["action"] for event in events_a] == [
        "membership.created",
        "membership.status_changed",
    ]
    assert [event["action"] for event in events_b] == ["membership.created"]


def test_membership_level_must_belong_to_same_organization() -> None:
    dsn = os.environ["DATABASE_URL"]
    _apply_migrations(dsn)
    repo = PostgresSocietyCRMRepository(dsn)

    org_a = repo.create_organization(slug="crm-level-a", display_name="CRM Level A")
    org_b = repo.create_organization(slug="crm-level-b", display_name="CRM Level B")
    repo.create_membership_level(
        organization_id=org_a["id"],
        code="student",
        display_name="Student",
        dues_amount_cents=1500,
    )
    person = repo.create_person(display_name="Test Student")

    with pytest.raises(ValueError, match="UNKNOWN_MEMBERSHIP_LEVEL"):
        repo.create_membership(
            organization_id=org_b["id"],
            constituent_id=person["id"],
            level_code="student",
            actor_subject="test:admin-b",
        )


def test_crm_audit_events_are_immutable() -> None:
    dsn = os.environ["DATABASE_URL"]
    _apply_migrations(dsn)
    repo = PostgresSocietyCRMRepository(dsn)

    org = repo.create_organization(slug="crm-audit", display_name="CRM Audit")
    repo.create_membership_level(
        organization_id=org["id"],
        code="individual",
        display_name="Individual",
    )
    person = repo.create_person(display_name="Audit Member")
    member = repo.create_membership(
        organization_id=org["id"],
        constituent_id=person["id"],
        level_code="individual",
        actor_subject="test:admin",
    )
    event_id = repo.list_audit_events(organization_id=org["id"])[0]["id"]

    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="CRM_AUDIT_IMMUTABLE"):
            conn.execute(
                "UPDATE oc_constituent.crm_audit_events SET action='tampered' WHERE id=%s",
                (event_id,),
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="CRM_AUDIT_IMMUTABLE"):
            conn.execute(
                "DELETE FROM oc_constituent.crm_audit_events WHERE id=%s",
                (event_id,),
            )
        conn.rollback()

    # Membership itself remains readable after audit tamper attempts.
    assert repo.get_member(organization_id=org["id"], membership_id=member["id"]) is not None
