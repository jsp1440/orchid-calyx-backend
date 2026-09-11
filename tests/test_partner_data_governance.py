from app.data_governance import (
    DataAccessContext,
    DataPolicy,
    DataPolicyEngine,
    DataSensitivity,
    DisclosureMode,
)


def test_public_data_is_available_but_respects_locality_and_image_policy():
    policy = DataPolicy(
        policy_id="public-1",
        authority_org="example",
        sensitivity=DataSensitivity.PUBLIC,
        default_disclosure=DisclosureMode.FULL,
        location_disclosure=DisclosureMode.GENERALIZED,
        image_disclosure=DisclosureMode.FULL,
    )
    decision = DataPolicyEngine().evaluate(
        policy,
        DataAccessContext(principal_id="anonymous", authenticated=False),
    )
    assert decision.allowed is True
    assert decision.disclosure == DisclosureMode.FULL
    assert decision.location_disclosure == DisclosureMode.GENERALIZED


def test_public_view_permission_does_not_imply_bulk_export_permission():
    policy = DataPolicy(
        policy_id="public-no-export",
        authority_org="partner",
        sensitivity=DataSensitivity.PUBLIC,
        default_disclosure=DisclosureMode.FULL,
        allow_export=False,
    )
    decision = DataPolicyEngine().evaluate(
        policy,
        DataAccessContext(
            principal_id="anonymous",
            authenticated=False,
            requests_export=True,
        ),
    )
    assert decision.allowed is False
    assert decision.reason_codes == ("EXPORT_PROHIBITED",)


def test_public_view_permission_does_not_imply_external_model_permission():
    policy = DataPolicy(
        policy_id="public-no-model",
        authority_org="partner",
        sensitivity=DataSensitivity.PUBLIC,
        default_disclosure=DisclosureMode.FULL,
        allow_model_processing=False,
    )
    decision = DataPolicyEngine().evaluate(
        policy,
        DataAccessContext(
            principal_id="anonymous",
            authenticated=False,
            requests_model_processing=True,
            model_provider="some-provider",
        ),
    )
    assert decision.allowed is False
    assert decision.reason_codes == ("MODEL_PROCESSING_PROHIBITED",)


def test_restricted_data_denies_unauthenticated_access():
    policy = DataPolicy(
        policy_id="restricted-1",
        authority_org="partner",
        sensitivity=DataSensitivity.RESEARCH_RESTRICTED,
        required_capabilities=("review.evidence.restricted",),
        allowed_purposes=("conservation_research",),
        default_disclosure=DisclosureMode.FULL,
    )
    decision = DataPolicyEngine().evaluate(
        policy,
        DataAccessContext(principal_id="anonymous", authenticated=False),
    )
    assert decision.allowed is False
    assert decision.disclosure == DisclosureMode.DENY
    assert decision.reason_codes == ("AUTHENTICATION_REQUIRED",)


def test_sensitive_data_requires_capability_and_allowed_purpose():
    policy = DataPolicy(
        policy_id="sensitive-1",
        authority_org="partner",
        sensitivity=DataSensitivity.SENSITIVE_CONSERVATION,
        required_capabilities=("conservation.data.sensitive.analyze",),
        allowed_purposes=("conservation_research",),
        default_disclosure=DisclosureMode.AGGREGATE_ONLY,
        location_disclosure=DisclosureMode.EXISTENCE_ONLY,
        image_disclosure=DisclosureMode.DENY,
    )
    decision = DataPolicyEngine().evaluate(
        policy,
        DataAccessContext(
            principal_id="researcher-1",
            authenticated=True,
            capabilities=("conservation.data.sensitive.analyze",),
            purpose="conservation_research",
        ),
    )
    assert decision.allowed is True
    assert decision.disclosure == DisclosureMode.AGGREGATE_ONLY
    assert decision.location_disclosure == DisclosureMode.EXISTENCE_ONLY
    assert decision.image_disclosure == DisclosureMode.DENY


def test_sensitive_data_does_not_inherit_admin_privilege():
    policy = DataPolicy(
        policy_id="sealed-1",
        authority_org="partner",
        sensitivity=DataSensitivity.SEALED_PARTNER,
        required_capabilities=("partner.sealed.dataset.use",),
        allowed_purposes=("approved_partner_project",),
        default_disclosure=DisclosureMode.AGGREGATE_ONLY,
    )
    decision = DataPolicyEngine().evaluate(
        policy,
        DataAccessContext(
            principal_id="administrator",
            authenticated=True,
            capabilities=("governance.audit.view", "review.external.export"),
            purpose="approved_partner_project",
        ),
    )
    assert decision.allowed is False
    assert decision.reason_codes == ("CAPABILITY_REQUIRED",)


def test_model_processing_requires_explicit_permission_and_provider_allowlist():
    policy = DataPolicy(
        policy_id="model-1",
        authority_org="partner",
        sensitivity=DataSensitivity.RESEARCH_RESTRICTED,
        required_capabilities=("review.evidence.restricted",),
        allowed_purposes=("conservation_research",),
        allow_model_processing=True,
        approved_model_providers=("institution-approved-provider",),
        default_disclosure=DisclosureMode.AGGREGATE_ONLY,
    )
    denied = DataPolicyEngine().evaluate(
        policy,
        DataAccessContext(
            principal_id="researcher-1",
            authenticated=True,
            capabilities=("review.evidence.restricted",),
            purpose="conservation_research",
            requests_model_processing=True,
            model_provider="unapproved-provider",
        ),
    )
    assert denied.allowed is False
    assert denied.reason_codes == ("MODEL_PROVIDER_NOT_APPROVED",)

    allowed = DataPolicyEngine().evaluate(
        policy,
        DataAccessContext(
            principal_id="researcher-1",
            authenticated=True,
            capabilities=("review.evidence.restricted",),
            purpose="conservation_research",
            requests_model_processing=True,
            model_provider="institution-approved-provider",
        ),
    )
    assert allowed.allowed is True
    assert "MODEL_PROCESSING_ALLOWED" in allowed.reason_codes
