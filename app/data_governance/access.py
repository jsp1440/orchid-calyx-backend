from __future__ import annotations

from app.mission_control_access import AccessPrincipal, CapabilityService

from .models import DataAccessContext


def access_context_from_principal(
    principal: AccessPrincipal,
    *,
    purpose: str | None = None,
    project_id: str | None = None,
    requests_export: bool = False,
    requests_model_processing: bool = False,
    model_provider: str | None = None,
    capability_service: CapabilityService | None = None,
) -> DataAccessContext:
    """Build the record-policy context from the canonical server-side principal.

    Direct partner/dataset entitlements remain ordinary capability strings on the
    principal, which permits narrowly scoped capabilities such as
    `partner.naocc.dataset.pollinators.use` without granting them to a broad role.
    """

    service = capability_service or CapabilityService()
    return DataAccessContext(
        principal_id=principal.principal_id,
        authenticated=principal.authenticated,
        capabilities=service.effective_capabilities(principal),
        purpose=purpose,
        project_id=project_id,
        model_provider=model_provider,
        requests_export=requests_export,
        requests_model_processing=requests_model_processing,
    )
