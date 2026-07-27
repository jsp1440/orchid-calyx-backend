from pathlib import Path

from app.review_tasks.postgres_repository import PostgresReviewTaskRepository, _decode, _json


class FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.description = [(key,) for key in row] if isinstance(row, dict) else []
        self.calls = []
        self.closed = False

    def execute(self, query, params=()):
        self.calls.append((query, params))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_migration_defines_governed_review_schema():
    sql = Path("migrations/mission_control_role_001d.sql").read_text()
    assert "CREATE SCHEMA IF NOT EXISTS oc_review" in sql
    assert "CREATE TABLE IF NOT EXISTS oc_review.access_principal" in sql
    assert "CREATE TABLE IF NOT EXISTS oc_review.review_task" in sql
    assert "CREATE TABLE IF NOT EXISTS oc_review.review_decision" in sql
    assert "CREATE TABLE IF NOT EXISTS oc_review.review_event" in sql
    assert "ON DELETE RESTRICT" in sql
    assert "review_task_queue_idx" in sql


def test_json_serialization_is_deterministic_and_round_trips():
    encoded = _json({"b": [2, 1], "a": True})
    assert encoded == '{"a":true,"b":[2,1]}'
    assert _decode(encoded) == {"a": True, "b": [2, 1]}


def test_task_get_uses_parameterized_query_and_closes_transaction():
    row = {"task_id": "task-1", "metadata": '{"policy":"v1"}'}
    cursor = FakeCursor(row)
    connection = FakeConnection(cursor)
    repository = PostgresReviewTaskRepository(lambda: connection)

    stored = repository.get("task-1")

    assert stored == {"task_id": "task-1", "metadata": {"policy": "v1"}}
    query, params = cursor.calls[0]
    assert "%s" in query
    assert params == ("task-1",)
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    assert cursor.closed is True


def test_task_save_is_idempotent_upsert():
    row = {"task_id": "task-1", "candidate_ids": '["candidate-1"]', "metadata": "{}"}
    cursor = FakeCursor(row)
    connection = FakeConnection(cursor)
    repository = PostgresReviewTaskRepository(lambda: connection)
    task = {
        "task_id": "task-1",
        "orchestration_id": "orch-1",
        "review_type": "HUMAN_REVIEW_REQUIRED",
        "risk_class": "2",
        "routing_outcome": "HUMAN_REVIEW_REQUIRED",
        "required_capability": "review.science",
        "candidate_ids": ["candidate-1"],
        "aggregate_version_ids": [],
        "priority": 60,
        "scientific_impact_score": 0.6,
        "consensus_required": 1,
        "batch_key": None,
        "display_policy": "internal",
        "embargoed": False,
        "metadata": {},
        "state": "OPEN",
        "assigned_to": None,
        "reservation_expires_at": None,
        "authoritative_decision": None,
        "created_at": "2026-07-27T00:00:00+00:00",
        "updated_at": "2026-07-27T00:00:00+00:00",
    }

    stored = repository.save(task)

    assert stored["candidate_ids"] == ["candidate-1"]
    assert "ON CONFLICT (task_id) DO UPDATE" in cursor.calls[0][0]
    assert connection.committed is True
