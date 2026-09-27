"""Member portal linking/self-service, admin diagnostics, and the lifecycle job (PostgreSQL)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from app.constituent_platform.crm_migrations import CRM_MIGRATIONS
from app.constituent_platform.authorization import SocietyAccessDenied, SocietyRole
from app.constituent_platform.crm_diagnostics import (
    organization_diagnostics,
    platform_diagnostics,
    run_lifecycle_job,
)
from app.constituent_platform.member_portal import MemberPortalService
from app.constituent_platform.postgres_repository import PostgresSocietyCRMRepository
from app.constituent_platform.society_service import CRMPrincipal, NotFound, SocietyCRMService

pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)

MIGRATIONS = CRM_MIGRATIONS
OPERATOR = CRMPrincipal("owner:platform-operator", platform_operator=True)
T0 = datetime(2026, 3, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ["DATABASE_URL"]
    with psycopg.connect(value, autocommit=True) as conn:
        for path in MIGRATIONS:
            conn.execute(Path(path).read_text(encoding="utf-8"))
        conn.execute(Path(MIGRATIONS[-1]).read_text(encoding="utf-8"))  # idempotent
    return value


@pytest.fixture()
def repo(dsn: str) -> PostgresSocietyCRMRepository:
    return PostgresSocietyCRMRepository(dsn)


@pytest.fixture()
def crm(repo: PostgresSocietyCRMRepository) -> SocietyCRMService:
    return SocietyCRMService(repo)


@pytest.fixture()
def portal(repo: PostgresSocietyCRMRepository, crm: SocietyCRMService) -> MemberPortalService:
    return MemberPortalService(repo, crm)


def _society(crm: SocietyCRMService) -> tuple[int, CRMPrincipal]:
    org = crm.create_organization(OPERATOR, slug=f"t-{uuid.uuid4().hex[:12]}", display_name="Orchid Society")
    subject = f"supabase:{uuid.uuid4()}"
    crm.bootstrap_admin(OPERATOR, org["id"], display_name="Pat Admin", auth_subject=subject)
    admin = CRMPrincipal(subject)
    crm.create_level(admin, org["id"], code="individual", display_name="Individual", dues_amount_cents=3000,
                     grace_days=30)
    return org["id"], admin


def _member(crm: SocietyCRMService, org: int, admin: CRMPrincipal, name: str, email: str,
            *, as_of: datetime = T0) -> dict:
    member = crm.create_member(admin, org, display_name=name, email=email, level_code="individual")
    crm.renew(admin, org, member["membership_id"], renewal_key=f"k-{uuid.uuid4()}", as_of=as_of)
    return crm.get_member(admin, org, member["membership_id"])


def test_member_links_login_with_single_use_invite_and_sees_only_own_record(
    crm: SocietyCRMService, portal: MemberPortalService
) -> None:
    org, admin = _society(crm)
    mine = _member(crm, org, admin, "Mia Member", "mia@example.org")
    _member(crm, org, admin, "Other Person", "other@example.org")
    me = CRMPrincipal(f"supabase:{uuid.uuid4()}")

    with pytest.raises(NotFound, match="PORTAL_NOT_LINKED"):
        portal.my_membership(me, org)
    invite = portal.issue_invite(admin, org, mine["membership_id"])
    view = portal.redeem_invite(me, org, invite["code"])
    assert view["membership_id"] == mine["membership_id"]
    assert view["status"] == "active" and view["expires_at"] == datetime(2027, 3, 1, tzinfo=timezone.utc)
    assert view["can_renew"] is True and len(view["renewals"]) == 1
    assert "constituent_id" not in view and "audit" not in view

    # Single use: the same code cannot link a second login.
    intruder = CRMPrincipal(f"supabase:{uuid.uuid4()}")
    with pytest.raises(ValueError, match="INVITE_INVALID_OR_EXPIRED"):
        portal.redeem_invite(intruder, org, invite["code"])
    with pytest.raises(ValueError, match="INVITE_INVALID_OR_EXPIRED"):
        portal.redeem_invite(intruder, org, "not-a-real-code-at-all")

    # Linking a portal login grants no staff capability.
    assert crm.my_access(org, me)["capabilities"] == []
    with pytest.raises(SocietyAccessDenied):
        crm.list_members(me, org)

    # Permitted self-service edits are audited under the member's own subject.
    portal.update_my_profile(me, org, {"first_name": "Mia"})
    portal.update_my_phone(me, org, "805-555-0199")
    updated = portal.update_my_address(me, org, line1="9 Bloom St", country_code="US", postal_code="93401")
    assert updated["primary_phone"] == "8055550199" and updated["mailing_line1"] == "9 Bloom St"
    for field in ("primary_email", "status", "level_code", "expires_at"):
        with pytest.raises(ValueError, match="MEMBER_FIELD_NOT_EDITABLE"):
            portal.update_my_profile(me, org, {field: "x"})
    actors = {e["actor_subject"] for e in crm.audit_events(admin, org) if e["action"] in
              ("person.updated", "phone.primary_changed", "address.mailing_changed")}
    assert actors == {me.subject}


def test_expired_invite_and_cross_society_portal_isolation(
    crm: SocietyCRMService, portal: MemberPortalService
) -> None:
    org_a, admin_a = _society(crm)
    org_b, admin_b = _society(crm)
    member_a = _member(crm, org_a, admin_a, "Shared Name", "shared@example.org")
    _member(crm, org_b, admin_b, "Shared Name", "shared@example.org")
    me = CRMPrincipal(f"supabase:{uuid.uuid4()}")

    expired = portal.issue_invite(admin_a, org_a, member_a["membership_id"], ttl_days=1, as_of=T0)
    with pytest.raises(ValueError, match="INVITE_INVALID_OR_EXPIRED"):
        portal.redeem_invite(me, org_a, expired["code"], as_of=T0 + timedelta(days=2))
    # A fresh code replaces older open codes.
    first = portal.issue_invite(admin_a, org_a, member_a["membership_id"])
    second = portal.issue_invite(admin_a, org_a, member_a["membership_id"])
    with pytest.raises(ValueError, match="INVITE_INVALID_OR_EXPIRED"):
        portal.redeem_invite(me, org_a, first["code"])
    # Society A's code does not work in Society B.
    with pytest.raises(ValueError, match="INVITE_INVALID_OR_EXPIRED"):
        portal.redeem_invite(me, org_b, second["code"])
    portal.redeem_invite(me, org_a, second["code"])
    assert portal.my_membership(me, org_a)["membership_id"] == member_a["membership_id"]
    with pytest.raises(NotFound, match="PORTAL_NOT_LINKED"):
        portal.my_membership(me, org_b)
    # Society B cannot issue codes for Society A's member.
    with pytest.raises(NotFound):
        portal.issue_invite(admin_b, org_b, member_a["membership_id"])


def test_invite_for_a_staff_record_requires_role_admin(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, portal: MemberPortalService
) -> None:
    org, admin = _society(crm)
    editor_subject = f"supabase:{uuid.uuid4()}"
    editor_person = repo.create_person(organization_id=org, display_name="Eddie Editor", actor_subject=admin.subject)
    crm.bind_identity(admin, org, constituent_id=editor_person["id"], auth_subject=editor_subject)
    crm.grant_role(admin, org, constituent_id=editor_person["id"], role=SocietyRole.MEMBERSHIP_EDITOR)
    editor = CRMPrincipal(editor_subject)

    treasurer_member = _member(crm, org, admin, "Terry Treasurer", "terry@example.org")
    crm.grant_role(admin, org, constituent_id=treasurer_member["constituent_id"], role=SocietyRole.TREASURER)
    plain = _member(crm, org, admin, "Plain Member", "plain@example.org")

    assert portal.issue_invite(editor, org, plain["membership_id"])["code"]
    # The editor must not be able to hand a login treasurer authority.
    with pytest.raises(SocietyAccessDenied, match="role.admin"):
        portal.issue_invite(editor, org, treasurer_member["membership_id"])
    assert portal.issue_invite(admin, org, treasurer_member["membership_id"])["code"]


def test_diagnostics_explain_problems_and_respect_authorization(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository
) -> None:
    org, admin = _society(crm)
    _member(crm, org, admin, "Late Renewer", "late@example.org", as_of=T0)
    crm.create_member(admin, org, display_name="Late Renewer", email="late2@example.org", level_code="individual")

    checks = {c["check"]: c for c in organization_diagnostics(crm, admin, org, as_of=T0 + timedelta(days=400))}
    assert checks["membership_lifecycle"]["status"] == "warning" and checks["membership_lifecycle"]["count"] == 1
    assert "lifecycle job" in checks["membership_lifecycle"]["action"]
    assert checks["duplicates"]["status"] == "warning"
    assert all(c["message"] and "@" not in c["message"] for c in checks.values())

    with pytest.raises(SocietyAccessDenied):
        organization_diagnostics(crm, CRMPrincipal(f"supabase:{uuid.uuid4()}"), org)
    with pytest.raises(PermissionError):
        platform_diagnostics(repo, admin)

    platform = {c["check"]: c for c in platform_diagnostics(repo, OPERATOR)}
    assert platform["database"]["status"] == "ok"
    assert platform["schema"]["status"] == "ok"
    assert platform["row_level_security"]["status"] == "ok", platform["row_level_security"]
    assert platform["runtime_role"]["status"] == "ok"


def test_lifecycle_job_is_idempotent_and_recorded(crm: SocietyCRMService, repo: PostgresSocietyCRMRepository) -> None:
    org, admin = _society(crm)
    member = _member(crm, org, admin, "Expiring", "expiring@example.org", as_of=T0)
    later = T0 + timedelta(days=370)

    first = run_lifecycle_job(repo, as_of=later)
    assert first["succeeded"] and first["transitions"] >= 1
    assert crm.get_member(admin, org, member["membership_id"])["status"] == "grace"
    run_lifecycle_job(repo, as_of=later)
    assert crm.get_member(admin, org, member["membership_id"])["status"] == "grace"
    assert [e["action"] for e in crm.audit_events(admin, org)].count("membership.lifecycle_transition") == 1

    runs = repo.latest_job_runs(job_name="membership_lifecycle", limit=1)
    assert runs[0]["status"] == "succeeded" and runs[0]["summary"]["societies"] >= 1
    checks = {c["check"]: c for c in organization_diagnostics(crm, admin, org, as_of=later)}
    assert checks["lifecycle_job"]["status"] == "ok"
