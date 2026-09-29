"""Journey 10 — community observations and moderation decisions are durable records.

The in-memory dict the MVP shipped with lost every submission and every
moderation decision on restart, so the Intake Review page could never be
production-tested. These tests pin the record-store contract instead.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.community_observation import service as observation_service
from app.community_observation.models import (
    CommunityObservation,
    ModerationState,
    ObservationEpistemicLabel,
)
from app.community_observation.routes import router
from app.community_observation.service import (
    KIND_OBSERVATION,
    OWNER_KEY,
    PROJECT_ID,
    CommunityObservationRepository,
    ObservationNotFound,
)
from app.security import verify_owner_or_api_key
from runtime.research_station_store import PostgresProjectRecordStore

MODERATOR = {"actor": "owner:jeff", "auth_type": "owner_session"}
PAYLOAD = {
    "taxon_name_verbatim": "Dracula vampira",
    "location_verbatim": "a cloud-forest ridge; exact site withheld by observer",
    "observation_date": str(date(2026, 8, 2)),
    "epistemic_label": "PROBABLE",
    "notes": "Two plants in flower.",
    "evidence_media_ids": [],
}


@pytest.fixture(autouse=True)
def reset_store():
    observation_service.configure_store(None)
    yield
    observation_service.configure_store(None)


def moderator_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: dict(MODERATOR)
    return app


class FakePostgresCursor:
    """Emulates just enough of psycopg for the record store's three statements."""

    def __init__(self, rows: dict[tuple[str, str, str, str], dict[str, Any]]) -> None:
        self.rows = rows
        self._result: list[dict[str, Any]] = []
        self.statements: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        compact = " ".join(sql.split())
        self.statements.append(compact)
        assert "%s" in sql and "'" not in compact.replace("''", ""), "record store must stay parameterised"
        if compact.startswith("INSERT INTO oc_admin.research_station_records"):
            owner, project, kind, record_id, payload = params
            self.rows[(owner, project, kind, record_id)] = dict(payload.obj)
            self._result = []
        elif "WHERE owner_key = %s AND project_id = %s AND kind = %s AND record_id = %s" in compact:
            found = self.rows.get(tuple(params))
            self._result = [{"payload": found}] if found is not None else []
        elif "WHERE owner_key = %s AND project_id = %s AND kind = %s ORDER BY record_id ASC" in compact:
            owner, project, kind = params
            keys = sorted(k for k in self.rows if k[:3] == (owner, project, kind))
            self._result = [{"payload": self.rows[k]} for k in keys]
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {compact}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


def postgres_store(rows: dict) -> PostgresProjectRecordStore:
    cursor = FakePostgresCursor(rows)
    return PostgresProjectRecordStore(lambda work: work(cursor))


# -- repository ---------------------------------------------------------------------------


def test_repository_round_trips_the_full_record_through_the_store():
    store = observation_service.memory_store()
    repo = CommunityObservationRepository(store)
    obs = CommunityObservation(
        submitter_auth_subject="subject-1",
        taxon_name_verbatim="Dracula vampira",
        location_verbatim="withheld",
        observation_date=date(2026, 8, 2),
        epistemic_label=ObservationEpistemicLabel.PROBABLE,
    )
    repo.save(obs)
    stored = store.get(owner_key=OWNER_KEY, project_id=PROJECT_ID, kind=KIND_OBSERVATION, record_id=str(obs.id))
    assert stored is not None and stored["taxon_name_verbatim"] == "Dracula vampira"
    assert repo.get(obs.id) == obs
    with pytest.raises(ObservationNotFound):
        repo.get(uuid.uuid4())


def test_moderation_records_actor_and_time_and_is_what_a_fresh_repository_reads_back():
    store = observation_service.memory_store()
    first = CommunityObservationRepository(store)
    obs = first.save(
        CommunityObservation(
            submitter_auth_subject="subject-1",
            taxon_name_verbatim="Dracula vampira",
            location_verbatim="withheld",
            observation_date=date(2026, 8, 2),
            epistemic_label=ObservationEpistemicLabel.POSSIBLE,
        )
    )
    first.moderate(obs.id, new_state=ModerationState.APPROVED, reason="clear photo", moderated_by="owner:jeff")

    second = CommunityObservationRepository(store)  # a restarted process over the same store
    reloaded = second.get(obs.id)
    assert reloaded.moderation_state is ModerationState.APPROVED
    assert reloaded.moderation_reason == "clear photo"
    assert reloaded.moderated_by == "owner:jeff"
    assert reloaded.moderated_at is not None and reloaded.moderated_at.tzinfo is not None
    assert reloaded.epistemic_label is ObservationEpistemicLabel.POSSIBLE  # moderation never edits the observation


def test_list_is_newest_first_and_filters_by_state():
    repo = CommunityObservationRepository(observation_service.memory_store())
    ids = []
    for day in (1, 2, 3):
        obs = repo.save(
            CommunityObservation(
                submitter_auth_subject="s",
                taxon_name_verbatim="x",
                location_verbatim="y",
                observation_date=date(2026, 8, day),
                epistemic_label=ObservationEpistemicLabel.UNCERTAIN,
            )
        )
        ids.append(obs.id)
    repo.moderate(ids[1], new_state=ModerationState.REJECTED, reason=None, moderated_by=None)
    listed = repo.list()
    assert [o.id for o in listed] == list(reversed(ids))
    assert [o.id for o in repo.list(moderation_state=ModerationState.REJECTED)] == [ids[1]]
    assert len(repo.list(moderation_state=ModerationState.SUBMITTED)) == 2


def test_repository_works_over_the_postgres_record_store_with_parameterised_sql():
    rows: dict = {}
    repo = CommunityObservationRepository(postgres_store(rows))
    obs = repo.save(
        CommunityObservation(
            submitter_auth_subject="s",
            taxon_name_verbatim="Dracula vampira",
            location_verbatim="withheld",
            observation_date=date(2026, 8, 2),
            epistemic_label=ObservationEpistemicLabel.PROBABLE,
        )
    )
    assert (OWNER_KEY, PROJECT_ID, KIND_OBSERVATION, str(obs.id)) in rows
    repo.moderate(obs.id, new_state=ModerationState.QUARANTINED, reason="needs a second look", moderated_by="owner:jeff")
    again = CommunityObservationRepository(postgres_store(rows)).get(obs.id)
    assert again.moderation_state is ModerationState.QUARANTINED
    assert again.moderated_by == "owner:jeff"
    assert [o.id for o in CommunityObservationRepository(postgres_store(rows)).list()] == [obs.id]


def test_without_a_database_the_store_returns_nothing_rather_than_inventing_records():
    repo = CommunityObservationRepository(PostgresProjectRecordStore(lambda work: work(None)))
    assert repo.list() == []
    with pytest.raises(ObservationNotFound):
        repo.get(uuid.uuid4())


# -- routes -------------------------------------------------------------------------------


def test_a_decision_made_in_one_process_is_visible_to_the_next_process():
    shared = observation_service.memory_store()
    observation_service.configure_store(shared)
    first = TestClient(moderator_app())
    obs_id = first.post("/api/community/observations", json=PAYLOAD).json()["id"]
    resp = first.patch(
        f"/api/community/observations/{obs_id}/moderate",
        json={"observation_id": obs_id, "new_state": "APPROVED", "reason": "verified by photo"},
    )
    assert resp.status_code == 200, resp.text

    observation_service.configure_store(shared)  # the next process boots over the same durable store
    second = TestClient(moderator_app())
    body = second.get(f"/api/community/observations/{obs_id}").json()
    assert body["moderation_state"] == "APPROVED"
    assert body["moderation_reason"] == "verified by photo"
    assert body["moderated_by"] == "owner:jeff"
    approved = second.get("/api/community/observations", params={"moderation_state": "APPROVED"}).json()
    assert [item["id"] for item in approved["items"]] == [obs_id]


def test_routes_no_longer_keep_a_module_level_dict():
    from app.community_observation import routes

    assert not hasattr(routes, "_store")
    assert observation_service.get_store() is observation_service.get_store()  # built once, then reused


def test_anonymous_list_still_exposes_only_id_state_and_time(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    observation_service.configure_store(observation_service.memory_store())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.post("/api/community/observations", json=PAYLOAD)
    listed = client.get("/api/community/observations").json()
    assert set(listed["items"][0]) == {"id", "moderation_state", "created_at"}
    assert "withheld" not in listed.__repr__()
