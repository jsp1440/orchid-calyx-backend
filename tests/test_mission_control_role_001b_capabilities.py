import pytest

from app.mission_control_access import (
    AccessDenied,
    AccessPrincipal,
    Capability,
    CapabilityService,
    MissionControlRole,
)


def test_public_view_is_available_without_authentication():
    service = CapabilityService()
    principal = AccessPrincipal(principal_id="anonymous", authenticated=False)
    decision = service.evaluate(principal, Capability.VIEW_PUBLIC.value)
    assert decision.allowed is True
    assert decision.reason_code == "PUBLIC_CAPABILITY"


def test_unauthenticated_principal_cannot_access_operational_data():
    service = CapabilityService()
    principal = AccessPrincipal(
        principal_id="anonymous",
        roles=(MissionControlRole.ADMINISTRATOR,),
        authenticated=False,
    )
    decision = service.evaluate(principal, Capability.VIEW_OPERATIONS.value)
    assert decision.allowed is False
    assert decision.reason_code == "AUTHENTICATION_REQUIRED"


def test_volunteer_requires_recorded_qualification_for_scientific_review():
    service = CapabilityService()
    unqualified = AccessPrincipal(
        principal_id="volunteer-1",
        roles=(MissionControlRole.VOLUNTEER,),
    )
    assert Capability.REVIEW_SCIENCE.value not in service.effective_capabilities(unqualified)

    qualified = AccessPrincipal(
        principal_id="volunteer-2",
        roles=(MissionControlRole.VOLUNTEER,),
        qualifications=("qualified.science-reviewer",),
    )
    assert Capability.REVIEW_SCIENCE.value in service.effective_capabilities(qualified)


def test_expert_capability_requires_expert_qualification():
    service = CapabilityService()
    principal = AccessPrincipal(
        principal_id="expert-1",
        roles=(MissionControlRole.EXPERT,),
        qualifications=("qualified.expert-reviewer",),
    )
    service.require(principal, Capability.REVIEW_EXPERT.value)
    with pytest.raises(AccessDenied):
        service.require(principal, Capability.REVIEW_PUBLISH.value)


def test_administrator_cannot_silently_approve_science():
    service = CapabilityService()
    principal = AccessPrincipal(
        principal_id="admin-1",
        roles=(MissionControlRole.ADMINISTRATOR,),
    )
    effective = service.effective_capabilities(principal)
    assert Capability.VIEW_OPERATIONS.value in effective
    assert Capability.MANAGE_ASSIGNMENTS.value in effective
    assert Capability.REVIEW_SCIENCE.value not in effective
    assert Capability.REVIEW_EXPERT.value not in effective
    assert Capability.REVIEW_PUBLISH.value not in effective


def test_public_direct_scientific_capability_is_not_trusted_without_qualification():
    service = CapabilityService()
    principal = AccessPrincipal(
        principal_id="user-1",
        roles=(MissionControlRole.PUBLIC,),
        direct_capabilities=(Capability.REVIEW_PUBLISH.value,),
    )
    assert Capability.REVIEW_PUBLISH.value not in service.effective_capabilities(principal)


def test_allowed_actions_are_calculated_from_capabilities():
    service = CapabilityService()
    principal = AccessPrincipal(
        principal_id="expert-1",
        roles=(MissionControlRole.EXPERT,),
        qualifications=("qualified.expert-reviewer",),
    )
    actions = service.allowed_actions(
        principal,
        {
            "view": Capability.VIEW_PUBLIC.value,
            "inspect-evidence": Capability.VIEW_RESTRICTED_EVIDENCE.value,
            "expert-review": Capability.REVIEW_EXPERT.value,
            "publish": Capability.REVIEW_PUBLISH.value,
            "manage-assignments": Capability.MANAGE_ASSIGNMENTS.value,
        },
    )
    assert actions == ("expert-review", "inspect-evidence", "view")


def test_access_decision_has_auditable_reason():
    service = CapabilityService()
    principal = AccessPrincipal(principal_id="user-1")
    decision = service.evaluate(principal, Capability.VIEW_AUDIT.value)
    payload = service.audit_payload(decision)
    assert payload["allowed"] is False
    assert payload["reason_code"] == "CAPABILITY_REQUIRED"
    assert payload["principal_id"] == "user-1"
