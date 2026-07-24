from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.concepts.dependencies import get_concept_service
from app.concepts.models import CONCEPT_URI_PREFIX, ConceptStatus, ReviewState
from app.concepts.routers import router
from app.concepts.services import ConceptRegistryService, OntologyTermConceptAdapter
from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key


class MemoryConceptRepository:
    def __init__(self) -> None:
        self.schemes: dict[UUID, dict] = {}
        self.releases: dict[UUID, dict] = {}
        self.concepts: dict[UUID, dict] = {}
        self.ontology_terms = {77: {"id": 77, "preferred_label": "Labellum"}}
        self.ontology_mappings: dict[int, UUID] = {}
        self.audit: list[str] = []

    @staticmethod
    def _timestamps(row: dict) -> dict:
        now = datetime.now(UTC)
        return {**row, "created_at": now, "revised_at": now}

    def create_scheme(self, data):
        if data["scheme_id"] in self.schemes:
            raise ValueError("SCHEME_IDENTIFIER_REUSE")
        if any(
            row["scheme_key"] == data["scheme_key"] for row in self.schemes.values()
        ):
            raise ValueError("DUPLICATE_SCHEME_KEY")
        row = self._timestamps(dict(data))
        self.schemes[row["scheme_id"]] = row
        return deepcopy(row)

    def get_scheme(self, scheme_id):
        return deepcopy(self.schemes.get(scheme_id))

    def create_release(self, data):
        if data["release_id"] in self.releases:
            raise ValueError("RELEASE_IDENTIFIER_REUSE")
        if any(
            row["scheme_id"] == data["scheme_id"] and row["version"] == data["version"]
            for row in self.releases.values()
        ):
            raise ValueError("DUPLICATE_SCHEME_RELEASE_VERSION")
        row = self._timestamps(dict(data))
        self.releases[row["release_id"]] = row
        return deepcopy(row)

    def get_release(self, release_id):
        return deepcopy(self.releases.get(release_id))

    def create_concept(self, data):
        concept_id = data["concept_id"]
        if concept_id in self.concepts:
            raise ValueError("CONCEPT_IDENTIFIER_REUSE")
        if any(
            row["concept_uri"] == data["concept_uri"] for row in self.concepts.values()
        ):
            raise ValueError("CONCEPT_URI_REUSE")
        row = self._timestamps({**dict(data), "superseded_by_id": None})
        self.concepts[concept_id] = row
        self.audit.append("CONCEPT_CREATED")
        return deepcopy(row)

    def get_concept(self, identifier):
        return deepcopy(self.concepts.get(identifier))

    def transition_concept(
        self,
        concept_id,
        status,
        review_state,
        superseded_by_id,
        actor,
    ):
        row = self.concepts.get(concept_id)
        if row is None:
            return None
        identity = (row["concept_id"], row["concept_uri"], row["created_at"])
        row.update(
            status=status,
            review_state=review_state,
            superseded_by_id=superseded_by_id,
            revised_at=datetime.now(UTC),
        )
        assert identity == (row["concept_id"], row["concept_uri"], row["created_at"])
        self.audit.append(f"CONCEPT_{status}")
        return deepcopy(row)

    def adapt_ontology_term(self, term_id, concept_data, actor):
        if term_id not in self.ontology_terms:
            raise LookupError("ONTOLOGY_TERM_NOT_FOUND")
        if term_id in self.ontology_mappings:
            return deepcopy(self.concepts[self.ontology_mappings[term_id]])
        row = self.create_concept(concept_data)
        self.ontology_mappings[term_id] = row["concept_id"]
        self.audit.append("ONTOLOGY_TERM_ADAPTED")
        return row


@pytest.fixture
def repository():
    return MemoryConceptRepository()


@pytest.fixture
def registry(repository):
    return ConceptRegistryService(repository)


@pytest.fixture
def scheme(registry):
    return registry.create_scheme(
        scheme_key="orchid-core",
        name="Orchid Core Concepts",
        authority="Orchid Continuum",
        steward="semantic-board",
    )


def test_uri_generation_is_opaque_canonical_and_immutable(registry, scheme):
    concept = registry.create_concept(
        scheme_id=scheme["scheme_id"],
        steward="curator",
    )
    assert concept["concept_uri"] == f"{CONCEPT_URI_PREFIX}{concept['concept_id']}"
    assert UUID(concept["concept_uri"].removeprefix(CONCEPT_URI_PREFIX))
    assert "orchid-core" not in concept["concept_uri"]
    activated = registry.transition(
        concept["concept_id"],
        ConceptStatus.ACTIVE,
        actor="reviewer",
    )
    assert activated["concept_id"] == concept["concept_id"]
    assert activated["concept_uri"] == concept["concept_uri"]
    assert activated["created_at"] == concept["created_at"]


def test_identifier_cannot_be_reused(registry, scheme):
    concept = registry.create_concept(
        scheme_id=scheme["scheme_id"],
        steward="curator",
    )
    with pytest.raises(ValueError, match="IDENTIFIER_REUSE"):
        registry.create_concept(
            scheme_id=scheme["scheme_id"],
            steward="another-curator",
            concept_id=concept["concept_id"],
        )


def test_lifecycle_transitions_are_forward_only(registry, scheme):
    concept = registry.create_concept(
        scheme_id=scheme["scheme_id"],
        steward="curator",
        review_state=ReviewState.IN_REVIEW,
    )
    active = registry.transition(
        concept["concept_id"],
        ConceptStatus.ACTIVE,
        actor="reviewer",
    )
    assert active["status"] == "ACTIVE"
    assert active["review_state"] == "APPROVED"
    deprecated = registry.transition(
        concept["concept_id"],
        ConceptStatus.DEPRECATED,
        actor="steward",
    )
    assert deprecated["status"] == "DEPRECATED"
    with pytest.raises(ValueError, match="INVALID_CONCEPT_STATUS_TRANSITION"):
        registry.transition(
            concept["concept_id"],
            ConceptStatus.ACTIVE,
            actor="steward",
        )


def test_supersession_requires_active_replacement_in_same_scheme(registry, scheme):
    original = registry.create_concept(
        scheme_id=scheme["scheme_id"],
        steward="curator",
    )
    registry.transition(original["concept_id"], ConceptStatus.ACTIVE, actor="reviewer")
    replacement = registry.create_concept(
        scheme_id=scheme["scheme_id"],
        steward="curator",
    )
    registry.transition(
        replacement["concept_id"],
        ConceptStatus.ACTIVE,
        actor="reviewer",
    )
    superseded = registry.transition(
        original["concept_id"],
        ConceptStatus.SUPERSEDED,
        actor="steward",
        superseded_by_id=replacement["concept_id"],
    )
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_id"] == replacement["concept_id"]
    with pytest.raises(ValueError, match="INVALID_CONCEPT_STATUS_TRANSITION"):
        registry.transition(
            original["concept_id"],
            ConceptStatus.DEPRECATED,
            actor="steward",
        )


def test_concept_scheme_and_release_metadata(registry, scheme):
    release = registry.create_release(
        scheme_id=scheme["scheme_id"],
        version="2026.1",
        metadata={"source": "curated", "issue": 124},
    )
    concept = registry.create_concept(
        scheme_id=scheme["scheme_id"],
        release_id=release["release_id"],
        steward="curator",
    )
    assert concept["scheme_id"] == scheme["scheme_id"]
    assert concept["release_id"] == release["release_id"]
    assert release["version"] == "2026.1"
    assert release["metadata"]["issue"] == 124


def test_release_from_another_scheme_is_rejected(registry, scheme):
    other = registry.create_scheme(
        scheme_key="other",
        name="Other",
        authority="Other Authority",
        steward="other-steward",
    )
    release = registry.create_release(scheme_id=other["scheme_id"], version="1")
    with pytest.raises(ValueError, match="RELEASE_SCHEME_MISMATCH"):
        registry.create_concept(
            scheme_id=scheme["scheme_id"],
            release_id=release["release_id"],
            steward="curator",
        )


def test_ontology_adapter_is_idempotent_and_does_not_mutate_legacy_term(
    repository,
    registry,
    scheme,
):
    original = deepcopy(repository.ontology_terms[77])
    adapter = OntologyTermConceptAdapter(repository)
    first = adapter.adapt(
        ontology_term_id=77,
        scheme_id=scheme["scheme_id"],
        steward="curator",
        actor="migration-operator",
    )
    second = adapter.adapt(
        ontology_term_id=77,
        scheme_id=scheme["scheme_id"],
        steward="curator",
        actor="migration-operator",
    )
    assert first["concept_id"] == second["concept_id"]
    assert repository.ontology_terms[77] == original
    assert len(repository.concepts) == 1


def test_api_requires_authentication():
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/api/concepts/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 401


def test_api_retrieves_by_uuid_and_full_uri(repository, registry, scheme):
    concept = registry.create_concept(
        scheme_id=scheme["scheme_id"],
        steward="curator",
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "owner"}
    app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    app.dependency_overrides[get_concept_service] = lambda: registry
    client = TestClient(app)
    assert client.get(f"/api/concepts/{concept['concept_id']}").status_code == 200
    encoded_uri = quote(concept["concept_uri"], safe="")
    response = client.get(f"/api/concepts/{encoded_uri}")
    assert response.status_code == 200
    assert response.json()["concept_uri"] == concept["concept_uri"]
    assert client.get("/api/concepts/not-a-concept").status_code == 422


def test_migration_is_additive_immutable_and_preserves_ontology():
    sql = Path("migrations/102a_core_concept_registry.sql").read_text(encoding="utf-8")
    lowered = sql.lower()
    assert "create schema if not exists oc_concepts" in lowered
    assert lowered.count("create table if not exists") == 5
    assert "https://id.orchidcontinuum.org/concept/" in sql
    assert "concept_identity_immutable" in lowered
    assert "concept_lifecycle_valid" in lowered
    assert "before update or delete" in lowered
    assert "ontology_term_concepts" in lowered
    assert "drop table" not in lowered
    assert "truncate" not in lowered
    assert "delete from" not in lowered
    assert "alter table oc_ontology" not in lowered
    assert "update oc_ontology" not in lowered


def test_existing_ontology_routes_remain_mounted_and_unmodified():
    from app.ontology.routers import router as ontology_router

    paths = {route.path for route in ontology_router.routes}
    assert "/api/ontology/registries" in paths
    assert "/api/ontology/terms/{term_id}" in paths
    assert "/api/ontology/resolutions/candidate/{candidate_id}" in paths
