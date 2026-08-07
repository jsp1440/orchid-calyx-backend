from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.university.reviewer_workspace import (
    list_reviewable_session_summaries,
    reviewer_context,
    reviewer_session_detail,
)
from app.university.service import UniversityServiceError


class _FakeCursor:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self.executions.append((query, params))

    def fetchall(self):
        return list(self.result_sets.pop(0))

    def fetchone(self):
        rows = self.result_sets.pop(0)
        return rows[0] if rows else None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


def _admin(*, qualifications=()) -> AccessPrincipal:
    return AccessPrincipal(
        principal_id="owner",
        roles=(MissionControlRole.ADMINISTRATOR,),
        qualifications=tuple(qualifications),
        authenticated=True,
    )


class UniversityReviewerWorkspaceTests(unittest.TestCase):
    def test_administrator_without_scientific_qualification_has_no_review_authority(self) -> None:
        context = reviewer_context(_admin())
        self.assertFalse(context["science_review_allowed"])
        self.assertFalse(context["expert_review_allowed"])
        self.assertEqual(context["qualifications"], [])

    def test_science_qualification_enables_only_science_review(self) -> None:
        context = reviewer_context(_admin(qualifications=("qualified.science-reviewer",)))
        self.assertTrue(context["science_review_allowed"])
        self.assertFalse(context["expert_review_allowed"])

    def test_unqualified_reviewer_is_rejected_before_database_access(self) -> None:
        with patch("app.university.reviewer_workspace._connect") as connect:
            with self.assertRaises(UniversityServiceError) as ctx:
                list_reviewable_session_summaries(principal=_admin())
        self.assertEqual(ctx.exception.code, "REVIEWER_QUALIFICATION_REQUIRED")
        connect.assert_not_called()

    def test_review_queue_contains_only_reviewable_summary_fields(self) -> None:
        now = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)
        rows = [
            {
                "session_id": UUID("11111111-1111-1111-1111-111111111111"),
                "laboratory_id": "OCU-LAB-FAILURE-TO-BLOOM-001",
                "chapter_id": "BITB-CHAPTER-ORCHID-FLOWERING-001",
                "status": "submitted",
                "current_stage": "contribute",
                "revision": 9,
                "created_at": now,
                "updated_at": now,
            }
        ]
        cursor = _FakeCursor([rows])
        with patch("app.university.reviewer_workspace.durable_sessions_enabled", return_value=True), patch(
            "app.university.reviewer_workspace._connect",
            return_value=_FakeConnection(cursor),
        ):
            page = list_reviewable_session_summaries(
                principal=_admin(qualifications=("qualified.science-reviewer",))
            )
        sql, _ = cursor.executions[0]
        self.assertIn("status IN ('submitted','under_review')", sql)
        summary = page["sessions"][0]
        self.assertNotIn("learner_actor", summary)
        self.assertNotIn("events", summary)
        self.assertNotIn("reviews", summary)

    def test_reviewer_detail_preserves_science_but_removes_actor_identifiers(self) -> None:
        now = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)
        session = {
            "session_id": UUID("11111111-1111-1111-1111-111111111111"),
            "laboratory_id": "OCU-LAB-FAILURE-TO-BLOOM-001",
            "chapter_id": "BITB-CHAPTER-ORCHID-FLOWERING-001",
            "status": "submitted",
            "current_stage": "contribute",
            "revision": 9,
            "created_at": now,
            "updated_at": now,
        }
        events = [
            {
                "event_id": UUID("22222222-2222-2222-2222-222222222222"),
                "event_type": "conclusion_drafted",
                "stage": "communicate",
                "payload": {"text": "Bounded conclusion", "authorship": "learner"},
                "session_revision": 7,
                "created_at": now,
            }
        ]
        reviews = [
            {
                "decision": "changes_requested",
                "notes": "Clarify uncertainty.",
                "reviewed_revision": 6,
                "reviewer_capability": "review.science",
                "created_at": now,
            }
        ]
        cursor = _FakeCursor([[session], events, reviews])
        with patch("app.university.reviewer_workspace.durable_sessions_enabled", return_value=True), patch(
            "app.university.reviewer_workspace._connect",
            return_value=_FakeConnection(cursor),
        ):
            detail = reviewer_session_detail(
                principal=_admin(qualifications=("qualified.science-reviewer",)),
                session_id=str(session["session_id"]),
            )
        self.assertEqual(detail["events"][0]["payload"]["text"], "Bounded conclusion")
        self.assertEqual(detail["review_history"][0]["notes"], "Clarify uncertainty.")
        self.assertNotIn("learner_actor", detail)
        self.assertNotIn("actor", detail["events"][0])
        self.assertNotIn("reviewer_actor", detail["review_history"][0])
        self.assertEqual(
            detail["privacy"],
            {
                "learner_actor_exposed": False,
                "event_actor_exposed": False,
                "reviewer_actor_exposed": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
