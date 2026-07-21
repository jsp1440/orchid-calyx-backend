from typing import Any

from .graph_models import PublicationExecutionRequest


class ControlledGraphPublicationService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def prepare(self, request: PublicationExecutionRequest) -> dict[str, Any]:
        return self.repository.prepare(request)

    def publish(self, request: PublicationExecutionRequest) -> dict[str, Any]:
        return self.repository.publish(request)

    def transaction(self, transaction_id: int) -> dict[str, Any] | None:
        return self.repository.transaction(transaction_id)

    def graph_version(self, graph_version_id: int) -> dict[str, Any] | None:
        return self.repository.graph_version(graph_version_id)
