from __future__ import annotations

from .models import Capability, MissionControlRole


ROLE_CAPABILITIES: dict[MissionControlRole, frozenset[str]] = {
    MissionControlRole.PUBLIC: frozenset({Capability.VIEW_PUBLIC.value}),
    MissionControlRole.VOLUNTEER: frozenset(
        {
            Capability.VIEW_PUBLIC.value,
            Capability.REVIEW_SCIENCE.value,
        }
    ),
    MissionControlRole.EXPERT: frozenset(
        {
            Capability.VIEW_PUBLIC.value,
            Capability.VIEW_RESTRICTED_EVIDENCE.value,
            Capability.REVIEW_SCIENCE.value,
            Capability.REVIEW_EXPERT.value,
        }
    ),
    MissionControlRole.ADMINISTRATOR: frozenset(
        {
            Capability.VIEW_PUBLIC.value,
            Capability.VIEW_OPERATIONS.value,
            Capability.MANAGE_ASSIGNMENTS.value,
            Capability.EXPORT_EXTERNAL.value,
            Capability.IMPORT_EXTERNAL.value,
            Capability.VIEW_AUDIT.value,
        }
    ),
}


SCIENTIFIC_APPROVAL_CAPABILITIES = frozenset(
    {
        Capability.REVIEW_SCIENCE.value,
        Capability.REVIEW_EXPERT.value,
        Capability.REVIEW_PUBLISH.value,
    }
)


QUALIFICATION_CAPABILITIES: dict[str, frozenset[str]] = {
    "qualified.science-reviewer": frozenset({Capability.REVIEW_SCIENCE.value}),
    "qualified.expert-reviewer": frozenset({Capability.REVIEW_EXPERT.value}),
    "qualified.publication-reviewer": frozenset({Capability.REVIEW_PUBLISH.value}),
    "qualified.external-workforce-manager": frozenset(
        {
            Capability.EXPORT_EXTERNAL.value,
            Capability.IMPORT_EXTERNAL.value,
        }
    ),
}
