from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

from app.university.durable_repository import DurableUniversityError
from app.university.session_discovery import (
    _decode_cursor,
    _encode_cursor,
    list_owned_session_summaries,
)


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return list(self.rows)


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


class UniversitySessionDiscoveryTests(unittest.TestCase):
    def test_cursor_round_trip_is_timezone_aware_and_stable(self) -> None:
        updated = datetime(2026, 8, 7, 19, 30, tzinfo=timezone.utc)
        session_id = UUID("11111111-1111-1111-1111-111111111111")
        cursor = _encode_cursor(updated, session_id)
        decoded = _decode_cursor(cursor)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded[0], updated)
        self.assertEqual(decoded[1], session_id)

    def test_invalid_cursor_fails_closed(self) -> None:
        with self.assertRaises(DurableUniversityError) as ctx:
            _decode_cursor("not-a-valid-cursor")
        self.assertEqual(ctx.exception.code, "INVALID_SESSION_CURSOR")

    def test_query_filters_by_actor_in_sql_and_returns_summary_only(self) -> None:
        actor = "supabase:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        rows = [
            {
                "session_id": UUID("11111111-1111-1111-1111-111111111111"),
                "laboratory_id": "OCU-LAB-FAILURE-TO-BLOOM-001",
                "chapter_id": "BITB-CHAPTER-ORCHID-FLOWERING-001",
                "status": "analyzing",
                "current_stage": "analyze",
                "revision": 8,
                "created_at": datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 8, 7, 19, 0, tzinfo=timezone.utc),
            },
            {
                "session_id": UUID("22222222-2222-2222-2222-222222222222"),
                "laboratory_id": "OCU-LAB-FAILURE-TO-BLOOM-001",
                "chapter_id": "BITB-CHAPTER-ORCHID-FLOWERING-001",
                "status": "observing",
                "current_stage": "observe",
                "revision": 2,
                "created_at": datetime(2026, 8, 7, 17, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 8, 7, 18, 30, tzinfo=timezone.utc),
            },
        ]
        fake_cursor = _FakeCursor(rows)
        with patch("app.university.session_discovery.durable_sessions_enabled", return_value=True), patch(
            "app.university.session_discovery._connect",
            return_value=_FakeConnection(fake_cursor),
        ):
            result = list_owned_session_summaries(actor=actor, limit=1)

        self.assertIn("learner_actor=%s", fake_cursor.query)
        self.assertEqual(fake_cursor.params[0], actor)
        self.assertEqual(fake_cursor.params[-1], 2)
        self.assertEqual(len(result["sessions"]), 1)
        self.assertTrue(result["has_more"])
        self.assertIsNotNone(result["next_cursor"])
        summary = result["sessions"][0]
        self.assertNotIn("actor", summary)
        self.assertNotIn("events", summary)
        self.assertNotIn("reviews", summary)

    def test_closed_durable_gate_prevents_database_access(self) -> None:
        with patch("app.university.session_discovery.durable_sessions_enabled", return_value=False), patch(
            "app.university.session_discovery._connect"
        ) as connect:
            with self.assertRaises(DurableUniversityError) as ctx:
                list_owned_session_summaries(
                    actor="supabase:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
                )
        self.assertEqual(ctx.exception.code, "DURABLE_UNIVERSITY_DISABLED")
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
