from typing import Any

from .models import CandidateRequest, PublicationPolicy
from .repositories import PublicationRegistry


class KnowledgePublicationService:
    """Narrow internal facade; it exposes no graph operation or state assignment."""

    def __init__(self, registry: PublicationRegistry) -> None:
        self.registry = registry

    def register_policy(
        self, policy: PublicationPolicy, *, actor: str
    ) -> dict[str, Any]:
        return self.registry.create_policy(policy, actor)

    def activate_policy(self, policy_id: str, version: int, *, actor: str) -> None:
        self.registry.activate_policy(policy_id, version, actor)

    def submit(self, request: CandidateRequest) -> dict[str, Any]:
        return self.registry.create_candidate(request)

    def evaluate(
        self, publication_id: int, *, authority_identity: str
    ) -> dict[str, Any]:
        return self.registry.authorize(publication_id, authority_identity)

    def get(self, publication_id: int) -> dict[str, Any] | None:
        return self.registry.candidate(publication_id)

    def history(self, publication_id: int) -> list[dict[str, Any]]:
        return self.registry.audit_history("PUBLICATION_CANDIDATE", publication_id)
