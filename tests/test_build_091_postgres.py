from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from app.implementation_planning.postgres_repository import (
    PostgresImplementationPlanningRepository,
)
from app.implementation_planning.service import ImplementationSpecificationService
from tests.test_build_091_implementation_specification import source_bundle

DATABASE_URL = os.getenv("BUILD_091_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="BUILD_091_DATABASE_URL not set")


def test_postgres_migration_persistence_idempotency_and_immutability():
    migration = Path("migrations/091_my_conservatory_implementation_specification.sql").read_text(encoding="utf-8")
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(migration)
        connection.execute(migration)

    repository = PostgresImplementationPlanningRepository(DATABASE_URL)
    service = ImplementationSpecificationService(repository)
    first = service.generate_my_conservatory(source_bundle(), "build-091-postgres")
    second = service.generate_my_conservatory(source_bundle(), "build-091-postgres")

    assert first.specification_id == second.specification_id
    restored = repository.get(first.specification_id)
    assert restored is not None
    assert len(restored.pages) == 12
    assert len(restored.components) >= 39
    assert len(restored.data_contracts) == 24
    assert len(repository.history(first.logical_key)) == 1
    assert len(repository.audits(first.specification_id)) == 1

    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            connection.execute(
                "UPDATE implementation_planning.specification_sets SET lifecycle_state='APPROVED' WHERE specification_id=%s",
                (first.specification_id,),
            )
        connection.rollback()
