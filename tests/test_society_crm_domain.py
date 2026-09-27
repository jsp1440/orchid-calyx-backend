"""Pure lifecycle and policy rules for the society CRM (no database)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.constituent_platform.domain import (
    MembershipStatus,
    add_months,
    lifecycle_status_at,
    renewal_term,
    validate_membership_transition,
    validate_society_entitlement_code,
)

UTC = timezone.utc


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert add_months(datetime(2028, 1, 31, tzinfo=UTC), 1) == datetime(2028, 2, 29, tzinfo=UTC)
    assert add_months(datetime(2026, 11, 15, tzinfo=UTC), 14) == datetime(2028, 1, 15, tzinfo=UTC)
    with pytest.raises(ValueError):
        add_months(datetime(2026, 1, 1, tzinfo=UTC), 0)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (MembershipStatus.PENDING, MembershipStatus.GRACE),
        (MembershipStatus.PENDING, MembershipStatus.LAPSED),
        (MembershipStatus.LAPSED, MembershipStatus.GRACE),
        (MembershipStatus.CANCELLED, MembershipStatus.GRACE),
        (MembershipStatus.CANCELLED, MembershipStatus.LAPSED),
    ],
)
def test_invalid_membership_transitions_fail_closed(current: MembershipStatus, target: MembershipStatus) -> None:
    with pytest.raises(ValueError, match="INVALID_MEMBERSHIP_TRANSITION"):
        validate_membership_transition(current, target, reason="because")


def test_cancellation_and_reinstatement_require_reason() -> None:
    with pytest.raises(ValueError, match="REASON_REQUIRED"):
        validate_membership_transition(MembershipStatus.ACTIVE, MembershipStatus.CANCELLED, reason="  ")
    with pytest.raises(ValueError, match="REASON_REQUIRED"):
        validate_membership_transition(MembershipStatus.CANCELLED, MembershipStatus.ACTIVE)
    validate_membership_transition(MembershipStatus.CANCELLED, MembershipStatus.ACTIVE, reason="error")
    validate_membership_transition(MembershipStatus.GRACE, MembershipStatus.LAPSED)


def test_lifecycle_status_follows_expiry_and_grace() -> None:
    expiry = datetime(2027, 1, 15, tzinfo=UTC)
    active = MembershipStatus.ACTIVE
    assert lifecycle_status_at(active, expiry, 30, expiry - timedelta(seconds=1)) is active
    assert lifecycle_status_at(active, expiry, 30, expiry) is MembershipStatus.GRACE
    assert lifecycle_status_at(active, expiry, 30, expiry + timedelta(days=30)) is MembershipStatus.LAPSED
    assert lifecycle_status_at(active, expiry, 0, expiry) is MembershipStatus.LAPSED
    for frozen in (MembershipStatus.PENDING, MembershipStatus.LAPSED, MembershipStatus.CANCELLED):
        assert lifecycle_status_at(frozen, expiry, 30, expiry + timedelta(days=400)) is frozen
    assert lifecycle_status_at(active, None, 30, expiry) is active


def test_renewal_term_base() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    expiry = datetime(2026, 9, 1, tzinfo=UTC)
    assert renewal_term(MembershipStatus.ACTIVE, expiry, 12, now) == (expiry, datetime(2027, 9, 1, tzinfo=UTC))
    late = datetime(2026, 9, 20, tzinfo=UTC)
    assert renewal_term(MembershipStatus.GRACE, expiry, 12, late)[1] == datetime(2027, 9, 1, tzinfo=UTC)
    assert renewal_term(MembershipStatus.LAPSED, expiry, 12, late) == (late, datetime(2027, 9, 20, tzinfo=UTC))
    assert renewal_term(MembershipStatus.PENDING, None, 6, now) == (now, datetime(2026, 12, 1, tzinfo=UTC))


@pytest.mark.parametrize("code", ["oasis.private", "calyx.research", "society", "society.", "Society.X Y", "research"])
def test_society_entitlements_cannot_reach_private_platform_data(code: str) -> None:
    with pytest.raises(ValueError, match="FORBIDDEN_SOCIETY_ENTITLEMENT"):
        validate_society_entitlement_code(code)
    assert validate_society_entitlement_code(" Society.Member_Portal ") == "society.member_portal"


def test_ci_workflow_applies_exactly_the_canonical_migration_chain() -> None:
    from pathlib import Path

    import yaml

    from app.constituent_platform.crm_migrations import CRM_MIGRATIONS, REPO_ROOT

    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/oc-society-crm-p0-validation.yml").read_text(encoding="utf-8")
    )
    listed = tuple(workflow["jobs"]["validate"]["env"]["CRM_MIGRATIONS"].split())
    assert listed == CRM_MIGRATIONS
    for path in CRM_MIGRATIONS:
        assert Path(REPO_ROOT / path).is_file(), path
