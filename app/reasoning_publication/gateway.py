from __future__ import annotations

import os
from typing import Any, Protocol

from app.knowledge_publication.graph_models import PublicationExecutionRequest
from app.knowledge_publication.graph_postgres_repository import (
    PostgresControlledGraphRepository,
)
from app.knowledge_publication.graph_service import ControlledGraphPublicationService
from app.knowledge_publication.models import CandidateRequest, PublicationPathway
from app.knowledge_publication.postgres_repository import PostgresPublicationRegistry
from app.knowledge_publication.service import KnowledgePublicationService


class CanonicalPublicationGate(Protocol):
    def publish(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class PublicationGateError(RuntimeError):
    pass


class ExistingKnowledgeGraphPublicationGate:
    """Adapter into BUILD-088B/088C; this class contains no graph SQL."""

    def __init__(self, database_url: str) -> None:
        self.registry = KnowledgePublicationService(
            PostgresPublicationRegistry(database_url)
        )
        self.graph = ControlledGraphPublicationService(
            PostgresControlledGraphRepository(database_url)
        )

    @classmethod
    def from_environment(cls) -> ExistingKnowledgeGraphPublicationGate:
        return cls(os.getenv("DATABASE_URL", ""))

    def publish(self, artifact: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._publish(artifact)
        except PublicationGateError:
            raise
        except Exception as exc:
            raise PublicationGateError(str(exc)) from exc

    def _publish(self, artifact: dict[str, Any]) -> dict[str, Any]:
        candidate = self.registry.submit(
            CandidateRequest(
                assertion_id=artifact["canonical_assertion_id"],
                assertion_version=artifact["canonical_assertion_version"],
                policy_id=artifact["policy_id"],
                policy_version=artifact["policy_version"],
                requested_pathway=PublicationPathway.HUMAN,
                idempotency_key=artifact["artifact_hash"],
                actor=artifact["submitting_actor"],
                correlation_id=artifact["publication_artifact_id"],
            )
        )
        statement = (
            candidate.get("trusted_snapshot", {})
            .get("assertion", {})
            .get("normalized_statement", {})
        )
        expected = (
            artifact["subject_canonical_key"],
            artifact["predicate"],
            artifact.get("object_canonical_key")
            or artifact.get("canonical_literal_value"),
        )
        actual = (
            statement.get("subject"),
            statement.get("predicate"),
            statement.get("object"),
        )
        if tuple(str(value).casefold() for value in actual) != tuple(
            str(value).casefold() for value in expected
        ):
            raise PublicationGateError("LEDGER_ASSERTION_BINDING_MISMATCH")
        decision = self.registry.evaluate(
            candidate["publication_id"], authority_identity=artifact["submitting_actor"]
        )
        if decision["outcome"] != "AUTHORIZED":
            raise ValueError(f"KNOWLEDGE_GRAPH_GATE_{decision['outcome']}")
        graph = self.graph.publish(
            PublicationExecutionRequest(
                publication_id=candidate["publication_id"],
                publication_version=candidate["publication_version"],
                service_identity=artifact["submitting_actor"],
                correlation_id=artifact["publication_artifact_id"],
            )
        )
        return {
            "publication_id": candidate["publication_id"],
            "authorization_decision_id": decision["decision_id"],
            "graph": graph,
        }
