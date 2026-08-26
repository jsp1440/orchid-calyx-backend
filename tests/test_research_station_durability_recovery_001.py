"""Research Station durability (CALYX-RECOVERY-001 defects B and C).

Authoritative project state lived only as JSON under
CALYX_RESEARCH_STATION_DIR, defaulting to /tmp/calyx/research-station. On any
container that recycles /tmp — which is what /tmp is for — a project, its
questions, its claims and its evidence were gone at the next restart, and
nothing reported that they had been lost.

The restart in these tests is modelled the way it actually happens: a new
service instance, a brand-new empty workspace directory, and the same record
store. If the database is not authoritative, the project is simply not there.
"""

from __future__ import annotations

import pytest

from runtime.research_station import ResearchStationService
from runtime.research_station_store import (
    DURABLE_KINDS,
    MemoryProjectRecordStore,
    persistence_mode,
)

OWNER = "owner@example.test"
PROJECT = {
    "project_id": "RSR-GH-LAELIA01",
    "title": "Laelia anceps ecology",
    "objective": "Assemble governed evidence for Laelia anceps",
    "created_at": "2026-08-26T12:00:00+00:00",
}


def _service(tmp_path, store, name="run-1"):
    workspace = tmp_path / name
    workspace.mkdir(parents=True, exist_ok=True)
    return ResearchStationService(workspace, record_store=store)


# ----------------------------------------------------- defect C: stale import


def test_research_station_no_longer_imports_the_absent_literature_module():
    """The lazy import raised ModuleNotFoundError on every access.

    Binding the retrieval path the repository already ships is the repair; a
    second literature platform would have been a worse one.
    """
    service = ResearchStationService()

    assert service.literature.__name__ == "app.calyx_conversation.external_literature"
    assert hasattr(service.literature, "extract_taxa")


def test_a_supplied_literature_service_still_wins():
    sentinel = object()
    assert ResearchStationService(literature=sentinel).literature is sentinel


# -------------------------------------------------- defect B: restart survival


def test_a_project_survives_a_restart_with_a_cold_workspace(tmp_path):
    store = MemoryProjectRecordStore()
    created = _service(tmp_path, store, "run-1").create_project(OWNER, PROJECT)
    assert created["created"] is True

    # Restart: new service, new empty workspace, same database.
    restarted = _service(tmp_path, store, "run-2").create_project(OWNER, PROJECT)

    assert restarted["created"] is False, "the project was recreated, not recovered"
    assert restarted["project"] == created["project"]


def test_without_durable_storage_a_restart_silently_forks_the_project(tmp_path):
    """The defect itself, pinned so it cannot return unnoticed.

    Two stores stand in for a workspace whose /tmp was recycled. The project
    comes back reported as newly created — one research history quietly
    becoming two.
    """
    first = _service(tmp_path, MemoryProjectRecordStore(), "run-1")
    second = _service(tmp_path, MemoryProjectRecordStore(), "run-2")

    assert first.create_project(OWNER, PROJECT)["created"] is True
    assert second.create_project(OWNER, PROJECT)["created"] is True


def test_questions_and_claims_survive_a_restart(tmp_path):
    store = MemoryProjectRecordStore()
    service = _service(tmp_path, store, "run-1")
    service.create_project(OWNER, PROJECT)
    question = service.add_question(
        OWNER,
        PROJECT["project_id"],
        {"text": "Which pollinators are recorded for Laelia anceps?"},
    )
    assert question["created"] is True

    restarted = _service(tmp_path, store, "run-2")
    restarted.create_project(OWNER, PROJECT)
    replayed = restarted.add_question(
        OWNER,
        PROJECT["project_id"],
        {"text": "Which pollinators are recorded for Laelia anceps?"},
    )

    assert replayed["created"] is False
    assert replayed["question"] == question["question"]


def test_the_recovered_record_repopulates_the_workspace_cache(tmp_path):
    """The filesystem stays a cache, and a cold one is refilled from the store."""
    store = MemoryProjectRecordStore()
    _service(tmp_path, store, "run-1").create_project(OWNER, PROJECT)

    second_workspace = tmp_path / "run-2"
    restarted = _service(tmp_path, store, "run-2")
    restarted.create_project(OWNER, PROJECT)

    cached = (
        second_workspace
        / "owners"
        / ResearchStationService._owner_key(OWNER)
        / "projects"
        / PROJECT["project_id"]
        / "project.json"
    )
    assert cached.exists()


def test_a_conflicting_record_is_still_refused_after_recovery(tmp_path):
    """Durability must not weaken immutability."""
    store = MemoryProjectRecordStore()
    _service(tmp_path, store, "run-1").create_project(OWNER, PROJECT)

    restarted = _service(tmp_path, store, "run-2")
    with pytest.raises(ValueError, match="IMMUTABLE_CONFLICT"):
        restarted.create_project(OWNER, {**PROJECT, "objective": "something else"})


# --------------------------------------------------------------- the contract


def test_persistence_mode_is_reported_rather_than_assumed():
    assert persistence_mode({"DATABASE_URL": "postgres://x"}) == "durable_database"
    assert persistence_mode({}) == "in_process_memory"


def test_every_record_kind_the_recovery_requires_is_marked_durable():
    """The kinds #1187 names as needing to survive a restart."""
    for kind in (
        "project",
        "question",
        "protocol",
        "dataset",
        "attachment",
        "claim",
        "evidence",
        "notebook",
        "artifact",
    ):
        assert kind in DURABLE_KINDS


def test_the_project_id_can_carry_the_build051_request_identity(tmp_path):
    """A request and its research workspace share one key."""
    store = MemoryProjectRecordStore()
    service = _service(tmp_path, store, "run-1")
    service.create_project(OWNER, PROJECT)

    owner_key = ResearchStationService._owner_key(OWNER)
    stored = store.get(
        owner_key=owner_key,
        project_id="RSR-GH-LAELIA01",
        kind="project",
        record_id="RSR-GH-LAELIA01",
    )
    assert stored is not None
    assert stored["project_id"] == "RSR-GH-LAELIA01"


# ------------------------------------------------- degradation must be visible


def test_constructing_a_station_opens_no_database_connection(monkeypatch):
    """Building the store eagerly made every construction attempt a connect.

    A service that only ever touches its workspace then failed outright on a
    machine whose DATABASE_URL points somewhere unreachable — which is what
    happened to 52 existing tests when this was written the other way.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://127.0.0.1:1/nothing")
    calls: list[int] = []

    import runtime.research_station_store as store_module

    def _explode(*args, **kwargs):
        calls.append(1)
        raise AssertionError("constructed a database store during __init__")

    monkeypatch.setattr(store_module, "build_record_store", _explode)
    monkeypatch.setattr(
        "runtime.research_station.build_record_store", _explode, raising=False
    )

    ResearchStationService()  # must not raise

    assert calls == []


def test_a_durable_write_failure_degrades_the_cache_rather_than_the_operation(tmp_path):
    """The workspace write already succeeded. Losing it too helps nobody."""

    class _Unreachable:
        def put(self, **kwargs):
            raise ConnectionError("database unreachable")

        def get(self, **kwargs):
            raise ConnectionError("database unreachable")

        def list(self, **kwargs):
            raise ConnectionError("database unreachable")

    service = _service(tmp_path, _Unreachable(), "run-1")
    created = service.create_project(OWNER, PROJECT)

    assert created["created"] is True


def test_a_durable_write_failure_is_reported_not_swallowed(tmp_path):
    """Degrading quietly would leave a caller believing in durability it lost.

    That is the failure this whole change exists to prevent, so it must not
    reappear as the change's own error path.
    """

    class _Unreachable:
        def put(self, **kwargs):
            raise ConnectionError("database unreachable")

        def get(self, **kwargs):
            return None

        def list(self, **kwargs):
            return []

    service = _service(tmp_path, _Unreachable(), "run-1")
    assert service.durability_degraded is None

    service.create_project(OWNER, PROJECT)

    assert service.durability_degraded is not None
    assert "ConnectionError" in service.durability_degraded
