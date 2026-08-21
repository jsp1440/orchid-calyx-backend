from app.data_governance import access_context_from_principal
from app.mission_control_access import AccessPrincipal, MissionControlRole


def test_administrator_role_does_not_gain_arbitrary_partner_entitlement():
    principal = AccessPrincipal(
        principal_id="admin-1",
        roles=(MissionControlRole.ADMINISTRATOR,),
    )
    context = access_context_from_principal(
        principal,
        purpose="conservation_research",
        project_id="project-1",
    )
    assert "partner.naocc.dataset.pollinators.use" not in context.capabilities


def test_dataset_specific_entitlement_can_be_granted_directly_without_role_widening():
    principal = AccessPrincipal(
        principal_id="researcher-1",
        roles=(MissionControlRole.EXPERT,),
        direct_capabilities=("partner.naocc.dataset.pollinators.use",),
    )
    context = access_context_from_principal(
        principal,
        purpose="conservation_research",
        project_id="project-1",
    )
    assert "partner.naocc.dataset.pollinators.use" in context.capabilities
    assert context.project_id == "project-1"
    assert context.purpose == "conservation_research"


def test_model_and_export_requests_are_explicit_context_attributes():
    principal = AccessPrincipal(principal_id="researcher-1")
    context = access_context_from_principal(
        principal,
        purpose="conservation_research",
        project_id="project-1",
        requests_export=True,
        requests_model_processing=True,
        model_provider="institution-approved-provider",
    )
    assert context.requests_export is True
    assert context.requests_model_processing is True
    assert context.model_provider == "institution-approved-provider"
