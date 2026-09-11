import pytest

from app.data_governance import (
    DataAccessContext,
    DataPolicy,
    DataPolicyDecision,
    DataSensitivity,
    DisclosureMode,
    ModelProcessingDenied,
    ProtectedValue,
    ProtectedValueKind,
    authorize_model_processing,
    guard_generated_text,
)


def test_model_processing_requires_every_policy_to_allow_provider():
    allowed = DataPolicy(
        policy_id="allowed",
        authority_org="partner-a",
        sensitivity=DataSensitivity.RESEARCH_RESTRICTED,
        required_capabilities=("partner.a.use",),
        allowed_purposes=("conservation_research",),
        allow_model_processing=True,
        approved_model_providers=("approved-provider",),
        default_disclosure=DisclosureMode.AGGREGATE_ONLY,
    )
    denied = DataPolicy(
        policy_id="denied",
        authority_org="partner-b",
        sensitivity=DataSensitivity.RESEARCH_RESTRICTED,
        required_capabilities=("partner.b.use",),
        allowed_purposes=("conservation_research",),
        allow_model_processing=False,
        default_disclosure=DisclosureMode.AGGREGATE_ONLY,
    )
    context = DataAccessContext(
        principal_id="researcher",
        authenticated=True,
        capabilities=("partner.a.use", "partner.b.use"),
        purpose="conservation_research",
        requests_model_processing=True,
        model_provider="approved-provider",
    )

    with pytest.raises(ModelProcessingDenied) as exc:
        authorize_model_processing((allowed, denied), context)
    assert "denied:MODEL_PROCESSING_PROHIBITED" in str(exc.value)


def test_model_processing_requires_declared_provider_and_policy():
    context = DataAccessContext(
        principal_id="researcher",
        authenticated=True,
        requests_model_processing=True,
        model_provider=None,
    )
    with pytest.raises(ModelProcessingDenied) as provider:
        authorize_model_processing((), context)
    assert str(provider.value) == "MODEL_PROVIDER_REQUIRED"


def test_output_guard_redacts_exact_locality_and_restricted_image_values():
    decision = DataPolicyDecision(
        allowed=True,
        disclosure=DisclosureMode.FULL,
        location_disclosure=DisclosureMode.GENERALIZED,
        image_disclosure=DisclosureMode.DENY,
        reason_codes=("POLICY_REQUIREMENTS_SATISFIED",),
        policy_id="policy-1",
        authority_org="partner",
        attribution_required=True,
    )
    guarded = guard_generated_text(
        "The exact site is Secret Meadow and the photograph is https://private.invalid/a.jpg.",
        decision,
        (
            ProtectedValue("exact-site", "Secret Meadow", ProtectedValueKind.LOCALITY),
            ProtectedValue(
                "restricted-image",
                "https://private.invalid/a.jpg",
                ProtectedValueKind.IMAGE,
            ),
        ),
    )
    assert "Secret Meadow" not in guarded.text
    assert "https://private.invalid/a.jpg" not in guarded.text
    assert guarded.redacted_labels == ("exact-site", "restricted-image")


def test_output_guard_allows_values_only_when_matching_disclosure_is_full():
    decision = DataPolicyDecision(
        allowed=True,
        disclosure=DisclosureMode.FULL,
        location_disclosure=DisclosureMode.FULL,
        image_disclosure=DisclosureMode.FULL,
        reason_codes=("POLICY_REQUIREMENTS_SATISFIED",),
        policy_id="policy-1",
        authority_org="partner",
        attribution_required=True,
    )
    text = "Site Secret Meadow has image https://private.invalid/a.jpg."
    guarded = guard_generated_text(
        text,
        decision,
        (
            ProtectedValue("exact-site", "Secret Meadow", ProtectedValueKind.LOCALITY),
            ProtectedValue(
                "restricted-image",
                "https://private.invalid/a.jpg",
                ProtectedValueKind.IMAGE,
            ),
        ),
    )
    assert guarded.text == text
    assert guarded.redacted_labels == ()
