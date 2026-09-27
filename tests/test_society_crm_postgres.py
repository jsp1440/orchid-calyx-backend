"""Society CRM: tenant isolation, authorization, and membership lifecycle against PostgreSQL.

Every test creates its own synthetic organizations (unique slugs), so the suite is
re-runnable against a persistent database and never depends on table emptiness.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.constituent_platform.crm_migrations import CRM_MIGRATIONS
from app.constituent_platform.authorization import (
    SocietyAccessDenied,
    SocietyCapability,
    SocietyRole,
    capabilities_for_roles,
    require_capability,
)
from app.constituent_platform.domain import MembershipStatus
from app.constituent_platform.postgres_repository import PostgresSocietyCRMRepository
from app.constituent_platform.society_service import (
    CRMPrincipal,
    NotFound,
    PlatformOperatorRequired,
    SocietyCRMService,
)
from app.constituent_platform.tenant_db import platform_transaction, tenant_transaction

pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)

MIGRATIONS = CRM_MIGRATIONS
T0 = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
OPERATOR = CRMPrincipal("owner:platform-operator", platform_operator=True)


def _apply_migrations(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in MIGRATIONS:
            sql = Path(path).read_text(encoding="utf-8")
            conn.execute(sql)
        # Idempotency: the CRM migrations re-apply cleanly.
        for path in MIGRATIONS[1:]:
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


def _subject() -> str:
    return f"supabase:{uuid.uuid4()}"


def _org(crm: SocietyCRMService, label: str = "Orchid Society") -> dict:
    # Deliberately overlapping display names across tenants.
    return crm.create_organization(OPERATOR, slug=f"t-{uuid.uuid4().hex[:12]}", display_name=label)


def _admin(crm: SocietyCRMService, org_id: int, name: str = "Pat Admin") -> CRMPrincipal:
    subject = _subject()
    crm.bootstrap_admin(OPERATOR, org_id, display_name=name, auth_subject=subject)
    return CRMPrincipal(subject)


def _society(crm: SocietyCRMService, label: str = "Orchid Society", *, grace_days: int = 30,
             entitlements: list[str] | None = None) -> tuple[int, CRMPrincipal]:
    org = _org(crm, label)
    admin = _admin(crm, org["id"])
    crm.create_level(admin, org["id"], code="individual", display_name="Individual",
                     dues_amount_cents=3000, term_months=12, grace_days=grace_days,
                     benefits={"entitlements": entitlements or []})
    crm.create_level(admin, org["id"], code="family", display_name="Family",
                     dues_amount_cents=4500, term_months=12, grace_days=grace_days, household_max_members=3)
    return org["id"], admin


def _staff(crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, org_id: int, admin: CRMPrincipal,
           role: SocietyRole | None, name: str = "Staff Person") -> tuple[CRMPrincipal, int]:
    """A verified person bound in org_id, optionally holding one staff role."""
    subject = _subject()
    person = repo.create_person(organization_id=org_id, display_name=name, actor_subject=admin.subject)
    crm.bind_identity(admin, org_id, constituent_id=person["id"], auth_subject=subject)
    if role is not None:
        crm.grant_role(admin, org_id, constituent_id=person["id"], role=role)
    return CRMPrincipal(subject), int(person["id"])


def _active_member(crm: SocietyCRMService, org_id: int, admin: CRMPrincipal, name: str, email: str,
                   level: str = "individual", as_of: datetime = T0) -> dict:
    member = crm.create_member(admin, org_id, display_name=name, email=email, level_code=level)
    crm.renew(admin, org_id, member["membership_id"], renewal_key=f"join-{uuid.uuid4()}", as_of=as_of)
    return crm.get_member(admin, org_id, member["membership_id"])


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_two_societies_with_overlapping_people_are_fully_isolated(crm: SocietyCRMService) -> None:
    org_a, admin_a = _society(crm, "Five Cities Orchid Society")
    org_b, admin_b = _society(crm, "Five Cities Orchid Society")

    member_a = _active_member(crm, org_a, admin_a, "Same Person", "same@example.org")
    member_b = _active_member(crm, org_b, admin_b, "Same Person", "same@example.org")
    assert member_a["constituent_id"] != member_b["constituent_id"]  # tenant-owned records

    # Society A cannot read Society B's member through its own tenant.
    with pytest.raises(NotFound):
        crm.get_member(admin_a, org_a, member_b["membership_id"])
    # Society A's admin has no authority in Society B at all.
    with pytest.raises(SocietyAccessDenied):
        crm.get_member(admin_a, org_b, member_b["membership_id"])
    with pytest.raises(SocietyAccessDenied):
        crm.list_members(admin_a, org_b)

    # Search in A never returns B, even for the shared email and name.
    rows, total = crm.list_members(admin_a, org_a, search="same@example.org")
    assert total == 1 and [r["membership_id"] for r in rows] == [member_a["membership_id"]]
    rows, total = crm.list_members(admin_a, org_a, search="Same Person")
    assert [r["membership_id"] for r in rows] == [member_a["membership_id"]]

    # Society A cannot update Society B's member through its own tenant id.
    with pytest.raises(NotFound):
        crm.update_profile(admin_a, org_a, member_b["membership_id"], {"display_name": "Hijacked"})
    with pytest.raises(NotFound):
        crm.change_status(admin_a, org_a, member_b["membership_id"], MembershipStatus.CANCELLED, reason="x")
    with pytest.raises(SocietyAccessDenied):
        crm.change_email(admin_a, org_b, member_b["membership_id"], "attacker@example.org")

    # Editing A's copy of the person never changes B's copy.
    crm.update_profile(admin_a, org_a, member_a["membership_id"], {"display_name": "Renamed In A"})
    assert crm.get_member(admin_b, org_b, member_b["membership_id"])["display_name"] == "Same Person"

    # Audit trails are tenant-scoped.
    with pytest.raises(SocietyAccessDenied):
        crm.audit_events(admin_a, org_b)
    audit_a = crm.audit_events(admin_a, org_a)
    assert audit_a and all(event["organization_id"] == org_a for event in audit_a)
    assert not any(event["entity_id"] == str(member_b["membership_id"]) and event["entity_type"] == "membership"
                   for event in audit_a)


def test_society_cannot_assign_itself_a_role_in_another_society(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, dsn: str
) -> None:
    org_a, admin_a = _society(crm)
    org_b, _admin_b = _society(crm)
    _, person_a = _staff(crm, repo, org_a, admin_a, None, "A Person")

    # Through the service: no role.admin in B.
    with pytest.raises(SocietyAccessDenied):
        crm.grant_role(admin_a, org_b, constituent_id=person_a, role=SocietyRole.ADMIN)
    # Through the repository: A's person does not exist in B's tenant.
    with pytest.raises(LookupError):
        repo.grant_staff_role(organization_id=org_b, constituent_id=person_a, role=SocietyRole.ADMIN,
                              granted_by_subject=admin_a.subject)
    # Through raw SQL as the table owner: the composite tenant FK refuses it.
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO oc_constituent.organization_staff_roles "
                "(organization_id, constituent_id, role_code, granted_by_subject) VALUES (%s, %s, 'admin', 'x:y')",
                (org_b, person_a),
            )
    # And A's person cannot be bound into B.
    with pytest.raises(LookupError):
        repo.bind_identity(organization_id=org_b, constituent_id=person_a, auth_subject=admin_a.subject,
                           verification_method="admin_attested", actor_subject=admin_a.subject)


def test_row_level_security_hides_other_tenants_without_any_filter(crm: SocietyCRMService, dsn: str) -> None:
    org_a, admin_a = _society(crm)
    org_b, admin_b = _society(crm)
    _active_member(crm, org_a, admin_a, "Alpha", "alpha@example.org")
    _active_member(crm, org_b, admin_b, "Beta", "beta@example.org")

    connect = lambda: psycopg.connect(dsn, row_factory=dict_row)  # noqa: E731
    tables = ("memberships", "email_addresses", "crm_audit_events", "organization_staff_roles",
              "membership_levels", "membership_renewals", "organization_identity_bindings")
    with tenant_transaction(org_a, connect=connect) as cur:
        for table in tables:
            cur.execute(f"SELECT DISTINCT organization_id FROM oc_constituent.{table}")  # no WHERE
            assert {row["organization_id"] for row in cur.fetchall()} == {org_a}, table
        cur.execute("SELECT DISTINCT owner_organization_id FROM oc_constituent.constituents")
        assert {row["owner_organization_id"] for row in cur.fetchall()} == {org_a}
        cur.execute("SELECT id FROM oc_constituent.organizations")
        assert [row["id"] for row in cur.fetchall()] == [org_a]

    # Writing a row for another tenant is refused by the policy's WITH CHECK.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_transaction(org_a, connect=connect) as cur:
            cur.execute(
                "INSERT INTO oc_constituent.constituents (kind, display_name, owner_organization_id) "
                "VALUES ('person', 'Smuggled', %s)",
                (org_b,),
            )

    # The runtime role with no tenant set sees nothing (default deny).
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE oc_crm_runtime")
        cur.execute("SELECT count(*) AS n FROM oc_constituent.memberships")
        assert cur.fetchone()["n"] == 0


def test_pooled_connection_never_carries_tenant_context_between_requests(crm: SocietyCRMService, dsn: str) -> None:
    org_a, admin_a = _society(crm)
    org_b, admin_b = _society(crm)
    _active_member(crm, org_a, admin_a, "Alpha", "alpha@example.org")
    _active_member(crm, org_b, admin_b, "Beta", "beta@example.org")

    pooled = psycopg.connect(dsn, row_factory=dict_row)  # one long-lived connection, reused
    try:
        with pooled.cursor() as cur:
            cur.execute("SELECT current_user AS u")
            login_user = cur.fetchone()["u"]
        pooled.commit()

        def unused() -> psycopg.Connection:
            raise AssertionError("must reuse the pooled connection")

        with tenant_transaction(org_a, connect=unused, connection=pooled) as cur:
            cur.execute("SELECT DISTINCT organization_id FROM oc_constituent.memberships")
            assert {r["organization_id"] for r in cur.fetchall()} == {org_a}

        # Next "request" on the same connection, a different tenant: no A rows leak in.
        with tenant_transaction(org_b, connect=unused, connection=pooled) as cur:
            cur.execute("SELECT DISTINCT organization_id FROM oc_constituent.memberships")
            assert {r["organization_id"] for r in cur.fetchall()} == {org_b}

        # A failed request rolls back and leaves nothing behind either.
        with pytest.raises(RuntimeError):
            with tenant_transaction(org_a, connect=unused, connection=pooled):
                raise RuntimeError("request failed")

        with platform_transaction(connect=unused, connection=pooled) as cur:
            cur.execute("SELECT current_user AS u, current_setting('oc.crm_organization_id', true) AS t")
            row = cur.fetchone()
            assert row["u"] == login_user
            assert row["t"] in (None, "")
    finally:
        pooled.close()


def test_runtime_role_is_least_privilege_and_confined_to_crm_schemas(dsn: str) -> None:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        grants = conn.execute(
            """
            SELECT table_schema, table_name, privilege_type
            FROM information_schema.role_table_grants
            WHERE grantee = 'oc_crm_runtime'
            """
        ).fetchall()
        role = conn.execute(
            "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = 'oc_crm_runtime'"
        ).fetchone()
    assert grants
    # No private Conservatory/OASIS/Calyx/research/security schema is reachable.
    assert {g["table_schema"] for g in grants} <= {"oc_constituent", "oc_communications"}
    assert not any(g["privilege_type"] in {"DELETE", "TRUNCATE"} for g in grants)
    audit_privs = {g["privilege_type"] for g in grants if g["table_name"] == "crm_audit_events"}
    assert audit_privs == {"SELECT", "INSERT"}
    assert role == {"rolsuper": False, "rolbypassrls": False, "rolcanlogin": False}


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_being_a_member_does_not_make_someone_an_administrator(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository
) -> None:
    org, admin = _society(crm)
    member = _active_member(crm, org, admin, "Ordinary Member", "member@example.org")
    subject = _subject()
    crm.bind_identity(admin, org, constituent_id=member["constituent_id"], auth_subject=subject)
    me = CRMPrincipal(subject)

    assert crm.my_access(org, me)["capabilities"] == []
    with pytest.raises(SocietyAccessDenied):
        crm.list_members(me, org)
    # Self-promotion is refused, and leaves no role behind.
    with pytest.raises(SocietyAccessDenied):
        crm.grant_role(me, org, constituent_id=member["constituent_id"], role=SocietyRole.ADMIN)
    assert repo.staff_roles_for_subject(organization_id=org, auth_subject=subject) == frozenset()


def test_treasurer_and_membership_editor_permissions_are_limited(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository
) -> None:
    org, admin = _society(crm)
    member = _active_member(crm, org, admin, "Some Member", "some@example.org")
    treasurer, _ = _staff(crm, repo, org, admin, SocietyRole.TREASURER, "Terry Treasurer")
    editor, _ = _staff(crm, repo, org, admin, SocietyRole.MEMBERSHIP_EDITOR, "Eddie Editor")

    treasurer_caps = crm.capabilities(org, treasurer)
    assert {SocietyCapability.PAYMENT_WRITE, SocietyCapability.DONATION_WRITE, SocietyCapability.ROSTER_READ} <= treasurer_caps
    for forbidden in (SocietyCapability.MEMBER_WRITE, SocietyCapability.MEMBERSHIP_WRITE, SocietyCapability.ROLE_ADMIN,
                      SocietyCapability.SETTINGS_WRITE, SocietyCapability.MEMBER_IMPORT,
                      SocietyCapability.ORGANIZATION_EXPORT):
        assert forbidden not in treasurer_caps
    crm.get_member(treasurer, org, member["membership_id"])  # may read roster
    with pytest.raises(SocietyAccessDenied):
        crm.update_profile(treasurer, org, member["membership_id"], {"display_name": "Nope"})
    with pytest.raises(SocietyAccessDenied):
        crm.change_status(treasurer, org, member["membership_id"], MembershipStatus.CANCELLED, reason="x")
    with pytest.raises(SocietyAccessDenied):
        crm.create_level(treasurer, org, code="patron", display_name="Patron")

    editor_caps = crm.capabilities(org, editor)
    for forbidden in (SocietyCapability.PAYMENT_READ, SocietyCapability.PAYMENT_WRITE, SocietyCapability.DONATION_READ,
                      SocietyCapability.DONATION_WRITE, SocietyCapability.ROLE_ADMIN,
                      SocietyCapability.ORGANIZATION_EXPORT, SocietyCapability.SETTINGS_WRITE):
        assert forbidden not in editor_caps
    crm.update_profile(editor, org, member["membership_id"], {"first_name": "Some"})
    with pytest.raises(SocietyAccessDenied):
        crm.grant_role(editor, org, constituent_id=member["constituent_id"], role=SocietyRole.TREASURER)

    viewer_caps = capabilities_for_roles({SocietyRole.VIEWER})
    assert SocietyCapability.PAYMENT_READ not in viewer_caps and SocietyCapability.AUDIT_READ not in viewer_caps
    assert capabilities_for_roles({SocietyRole.ADMIN}) == frozenset(SocietyCapability)
    with pytest.raises(PermissionError, match="SOCIETY_CAPABILITY_REQUIRED:role.admin"):
        require_capability({SocietyRole.TREASURER}, SocietyCapability.ROLE_ADMIN)


def test_role_revocation_removes_authority_immediately(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository
) -> None:
    org, admin = _society(crm)
    second_admin, second_id = _staff(crm, repo, org, admin, SocietyRole.ADMIN, "Second Admin")
    assert crm.list_members(second_admin, org)[1] == 0

    crm.revoke_role(admin, org, constituent_id=second_id, role=SocietyRole.ADMIN)
    with pytest.raises(SocietyAccessDenied):
        crm.list_members(second_admin, org)

    actions = [e["action"] for e in crm.audit_events(admin, org)]
    assert "staff_role.granted" in actions and "staff_role.revoked" in actions

    # The last active admin cannot be revoked (organization lock-out protection).
    admin_constituent = repo.bound_constituent_id(organization_id=org, auth_subject=admin.subject)
    with pytest.raises(ValueError, match="LAST_ADMIN_REQUIRED"):
        crm.revoke_role(admin, org, constituent_id=admin_constituent, role=SocietyRole.ADMIN)


def test_identity_subject_cannot_be_silently_reassigned(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, dsn: str
) -> None:
    org, admin = _society(crm)
    first = repo.create_person(organization_id=org, display_name="First Identity", actor_subject=admin.subject)
    second = repo.create_person(organization_id=org, display_name="Second Identity", actor_subject=admin.subject)
    subject = _subject()
    binding = crm.bind_identity(admin, org, constituent_id=first["id"], auth_subject=subject)

    with pytest.raises(ValueError, match="AUTH_SUBJECT_ALREADY_BOUND"):
        crm.bind_identity(admin, org, constituent_id=second["id"], auth_subject=subject)
    # Idempotent retry for the same person is safe.
    assert crm.bind_identity(admin, org, constituent_id=first["id"], auth_subject=subject)["id"] == binding["id"]
    # Even the table owner cannot re-point a binding row.
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="IDENTITY_BINDING_IMMUTABLE"):
            conn.execute(
                "UPDATE oc_constituent.organization_identity_bindings SET constituent_id = %s WHERE id = %s",
                (second["id"], binding["id"]),
            )

    # Rebinding is an explicit, audited revoke followed by a new binding.
    crm.revoke_identity(admin, org, auth_subject=subject)
    crm.bind_identity(admin, org, constituent_id=second["id"], auth_subject=subject)
    actions = [e["action"] for e in crm.audit_events(admin, org)]
    assert actions.count("identity_binding.created") >= 3 and "identity_binding.revoked" in actions

    # Platform-level identity links keep their original guarantee too.
    repo.link_identity(constituent_id=first["id"], auth_subject=subject)
    with pytest.raises(ValueError, match="AUTH_SUBJECT_ALREADY_LINKED"):
        repo.link_identity(constituent_id=second["id"], auth_subject=subject)


def test_role_without_identity_binding_grants_nothing(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository
) -> None:
    org, admin = _society(crm)
    person = repo.create_person(organization_id=org, display_name="Unbound Officer", actor_subject=admin.subject)
    crm.grant_role(admin, org, constituent_id=person["id"], role=SocietyRole.ADMIN)
    assert crm.roles(org, CRMPrincipal(_subject())) == frozenset()


def test_platform_operator_bootstraps_but_gets_no_implicit_society_data_access(crm: SocietyCRMService) -> None:
    org, admin = _society(crm)
    _active_member(crm, org, admin, "Private Member", "private@example.org")
    with pytest.raises(SocietyAccessDenied):
        crm.list_members(OPERATOR, org)
    with pytest.raises(SocietyAccessDenied):
        crm.audit_events(OPERATOR, org)
    with pytest.raises(PlatformOperatorRequired):
        crm.create_organization(admin, slug=f"t-{uuid.uuid4().hex[:12]}", display_name="Rogue")
    with pytest.raises(PlatformOperatorRequired):
        crm.bootstrap_admin(admin, org, display_name="Rogue", auth_subject=_subject())


# ---------------------------------------------------------------------------
# Membership lifecycle
# ---------------------------------------------------------------------------


def test_full_membership_lifecycle(crm: SocietyCRMService) -> None:
    org, admin = _society(crm, grace_days=30, entitlements=["society.member_portal"])
    member = crm.create_member(admin, org, display_name="Life Cycle", email="cycle@example.org",
                               level_code="individual")
    mid = member["membership_id"]
    assert member["status"] == "pending"

    # pending -> active cannot skip the renewal ledger.
    with pytest.raises(ValueError, match="MEMBERSHIP_RENEWAL_REQUIRED"):
        crm.change_status(admin, org, mid, MembershipStatus.ACTIVE)
    # pending -> grace is not a lifecycle edge.
    with pytest.raises(ValueError, match="INVALID_MEMBERSHIP_TRANSITION"):
        crm.change_status(admin, org, mid, MembershipStatus.GRACE)

    joined = crm.renew(admin, org, mid, renewal_key="fcos-2026-join", as_of=T0)
    assert joined["applied"] is True
    assert joined["member"]["status"] == "active"
    assert joined["member"]["expires_at"] == datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc)

    # Retrying the same renewal is a no-op: renewed exactly once.
    again = crm.renew(admin, org, mid, renewal_key="fcos-2026-join", as_of=T0 + timedelta(days=3))
    assert again["applied"] is False
    assert crm.get_member(admin, org, mid)["expires_at"] == joined["member"]["expires_at"]

    expiry = joined["member"]["expires_at"]
    assert crm.run_lifecycle(admin, org, as_of=expiry - timedelta(days=1)) == []
    # active -> grace at expiry
    assert crm.run_lifecycle(admin, org, as_of=expiry + timedelta(days=1)) == [
        {"membership_id": mid, "from": "active", "to": "grace"}
    ]
    assert crm.get_member(admin, org, mid)["status"] == "grace"
    # re-running the job changes nothing
    assert crm.run_lifecycle(admin, org, as_of=expiry + timedelta(days=2)) == []
    # grace -> lapsed after the grace period
    assert crm.run_lifecycle(admin, org, as_of=expiry + timedelta(days=31)) == [
        {"membership_id": mid, "from": "grace", "to": "lapsed"}
    ]
    entitlements = crm._repo.list_entitlements(organization_id=org, constituent_id=member["constituent_id"])
    assert [(e["entitlement_code"], e["status"]) for e in entitlements] == [("society.member_portal", "expired")]

    # lapsed -> active after renewal: a new term from the renewal date.
    restore_at = expiry + timedelta(days=60)
    restored = crm.renew(admin, org, mid, renewal_key="fcos-2027-restore", as_of=restore_at)
    assert restored["member"]["status"] == "active"
    assert restored["member"]["expires_at"] == datetime(2028, 3, 16, 12, 0, tzinfo=timezone.utc)
    entitlements = crm._repo.list_entitlements(organization_id=org, constituent_id=member["constituent_id"])
    assert [(e["entitlement_code"], e["status"]) for e in entitlements] == [("society.member_portal", "active")]

    # Early renewal extends from the existing expiry; no paid time is lost.
    early = crm.renew(admin, org, mid, renewal_key="fcos-2028-early", as_of=restore_at + timedelta(days=30))
    assert early["member"]["expires_at"] == datetime(2029, 3, 16, 12, 0, tzinfo=timezone.utc)

    # Cancellation requires a reason and revokes the society entitlement.
    with pytest.raises(ValueError, match="MEMBERSHIP_TRANSITION_REASON_REQUIRED"):
        crm.change_status(admin, org, mid, MembershipStatus.CANCELLED)
    cancelled = crm.change_status(admin, org, mid, MembershipStatus.CANCELLED, reason="Member request",
                                  as_of=restore_at + timedelta(days=31))
    assert cancelled["status"] == "cancelled" and cancelled["cancelled_at"] is not None
    entitlements = crm._repo.list_entitlements(organization_id=org, constituent_id=member["constituent_id"])
    assert entitlements[0]["status"] == "cancelled"
    # Reinstating a cancelled membership that still has paid time requires a reason.
    with pytest.raises(ValueError, match="MEMBERSHIP_TRANSITION_REASON_REQUIRED"):
        crm.change_status(admin, org, mid, MembershipStatus.ACTIVE, as_of=restore_at + timedelta(days=32))
    reinstated = crm.change_status(admin, org, mid, MembershipStatus.ACTIVE, reason="Cancelled in error",
                                   as_of=restore_at + timedelta(days=32))
    assert reinstated["status"] == "active" and reinstated["cancelled_at"] is None

    history = crm.member_history(admin, org, mid)
    assert [r["renewal_key"] for r in history["renewals"]] == ["fcos-2026-join", "fcos-2027-restore", "fcos-2028-early"]
    actions = [e["action"] for e in history["audit"]]
    assert actions.count("membership.renewed") == 3
    assert actions.count("membership.lifecycle_transition") == 2
    assert "membership.status_changed" in actions


def test_renewal_key_cannot_be_reused_for_another_membership(crm: SocietyCRMService) -> None:
    org, admin = _society(crm)
    one = _active_member(crm, org, admin, "One", "one@example.org")
    two = crm.create_member(admin, org, display_name="Two", email="two@example.org", level_code="individual")
    crm.renew(admin, org, one["membership_id"], renewal_key="check-1001", as_of=T0)
    with pytest.raises(ValueError, match="RENEWAL_KEY_CONFLICT"):
        crm.renew(admin, org, two["membership_id"], renewal_key="check-1001", as_of=T0)
    assert crm.get_member(admin, org, two["membership_id"])["status"] == "pending"


def test_level_change_household_and_profile_edits_are_audited(crm: SocietyCRMService) -> None:
    org, admin = _society(crm)
    member = _active_member(crm, org, admin, "Hou Sehold", "house@example.org")
    mid = member["membership_id"]

    with pytest.raises(ValueError, match="HOUSEHOLD_CAPACITY_EXCEEDED"):
        crm.add_household_member(admin, org, mid, display_name="Partner", relationship="partner")
    with pytest.raises(ValueError, match="UNKNOWN_MEMBERSHIP_LEVEL"):
        crm.change_level(admin, org, mid, "platinum")

    crm.change_level(admin, org, mid, "family", reason="Added partner")
    crm.add_household_member(admin, org, mid, display_name="Partner", relationship="partner")
    detail = crm.add_household_member(admin, org, mid, display_name="Child", relationship="child")
    assert [h["display_name"] for h in detail["household_members"]] == ["Partner", "Child"]
    with pytest.raises(ValueError, match="HOUSEHOLD_CAPACITY_EXCEEDED"):
        crm.add_household_member(admin, org, mid, display_name="Too Many")
    # Downgrading below the household size is refused rather than orphaning people.
    with pytest.raises(ValueError, match="HOUSEHOLD_CAPACITY_EXCEEDED"):
        crm.change_level(admin, org, mid, "individual")

    crm.change_email(admin, org, mid, "new.house@example.org")
    crm.change_phone(admin, org, mid, "+1 (805) 555-0100")
    updated = crm.change_address(admin, org, mid, line1="1 Orchid Way", locality="San Luis Obispo",
                                 administrative_area="CA", postal_code="93401", country_code="us")
    assert updated["primary_email"] == "new.house@example.org"
    assert updated["primary_phone"] == "+18055550100"
    assert updated["mailing_line1"] == "1 Orchid Way" and updated["mailing_country_code"] == "US"
    assert updated["level_code"] == "family"

    actions = [e["action"] for e in crm.member_history(admin, org, mid)["audit"]]
    for expected in ("membership.level_changed", "household_member.added", "email.primary_changed",
                     "phone.primary_changed", "address.mailing_changed"):
        assert expected in actions, expected
    level_event = next(e for e in crm.member_history(admin, org, mid)["audit"]
                       if e["action"] == "membership.level_changed")
    assert level_event["before_state"]["level_code"] == "individual"
    assert level_event["after_state"]["level_code"] == "family"
    assert level_event["actor_subject"] == admin.subject


def test_roster_filters_and_duplicate_detection_stay_within_tenant(crm: SocietyCRMService) -> None:
    org_a, admin_a = _society(crm)
    org_b, admin_b = _society(crm)
    active = _active_member(crm, org_a, admin_a, "Ann Active", "ann@example.org")
    pending = crm.create_member(admin_a, org_a, display_name="Pete Pending", email="pete@example.org",
                                level_code="family")
    _active_member(crm, org_b, admin_b, "Ann Active", "ann@example.org")

    rows, total = crm.list_members(admin_a, org_a, status=MembershipStatus.ACTIVE)
    assert total == 1 and rows[0]["membership_id"] == active["membership_id"]
    rows, total = crm.list_members(admin_a, org_a, level_code="family")
    assert [r["membership_id"] for r in rows] == [pending["membership_id"]]
    rows, total = crm.list_members(admin_a, org_a, search="pete")
    assert total == 1
    rows, total = crm.list_members(admin_a, org_a, search="%")  # LIKE wildcards are literal
    assert total == 0

    with pytest.raises(ValueError, match="DUPLICATE_MEMBER_EMAIL"):
        crm.create_member(admin_a, org_a, display_name="Ann Again", email="ANN@example.org", level_code="individual")
    # The same email in another tenant is not a duplicate here.
    assert crm.duplicate_candidates(admin_b, org_b) == []
    crm.create_member(admin_a, org_a, display_name="Ann Active", email="ann.two@example.org", level_code="individual")
    assert [c["match_kind"] for c in crm.duplicate_candidates(admin_a, org_a)] == ["name"]


def test_failed_member_creation_leaves_no_partial_rows(crm: SocietyCRMService, dsn: str) -> None:
    org, admin = _society(crm)

    def people() -> int:
        with psycopg.connect(dsn) as conn:
            return conn.execute(
                "SELECT count(*) FROM oc_constituent.constituents WHERE owner_organization_id = %s", (org,)
            ).fetchone()[0]

    before = people()
    with pytest.raises(ValueError, match="UNKNOWN_MEMBERSHIP_LEVEL"):
        crm.create_member(admin, org, display_name="Orphan", email="orphan@example.org", level_code="nonexistent")
    assert people() == before


def test_society_levels_cannot_grant_private_platform_entitlements(crm: SocietyCRMService) -> None:
    org, admin = _society(crm)
    for code in ("oasis.private_collection", "conservatory.full", "calyx.research", "society"):
        with pytest.raises(ValueError, match="FORBIDDEN_SOCIETY_ENTITLEMENT"):
            crm.create_level(admin, org, code=f"lvl-{uuid.uuid4().hex[:6]}", display_name="Bad",
                             benefits={"entitlements": [code]})


def test_crm_audit_events_are_immutable(crm: SocietyCRMService, dsn: str) -> None:
    org, admin = _society(crm)
    member = _active_member(crm, org, admin, "Audit Member", "audit@example.org")
    event_id = crm.audit_events(admin, org)[0]["id"]

    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="CRM_AUDIT_IMMUTABLE"):
            conn.execute("UPDATE oc_constituent.crm_audit_events SET action='tampered' WHERE id=%s", (event_id,))
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="CRM_AUDIT_IMMUTABLE"):
            conn.execute("DELETE FROM oc_constituent.crm_audit_events WHERE id=%s", (event_id,))
        conn.rollback()
        renewal_id = conn.execute(
            "SELECT id FROM oc_constituent.membership_renewals WHERE membership_id = %s", (member["membership_id"],)
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("DELETE FROM oc_constituent.membership_renewals WHERE id=%s", (renewal_id,))
        conn.rollback()

    assert crm.get_member(admin, org, member["membership_id"]) is not None
