from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.university.learner_auth import _stable_actor, verify_supabase_access_token


class UniversityLearnerAuthTests(unittest.TestCase):
    def test_stable_actor_uses_uuid_only(self) -> None:
        actor = _stable_actor("11111111-1111-1111-1111-111111111111")
        self.assertEqual(actor, "supabase:11111111-1111-1111-1111-111111111111")

    def test_invalid_subject_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _stable_actor("not-a-uuid")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail["code"], "INVALID_LEARNER_IDENTITY")

    def test_verified_user_returns_no_email_or_token(self) -> None:
        response = Mock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "learner@example.org",
            "user_metadata": {"display_name": "Learner"},
        }
        env = {
            "OCU_SUPABASE_URL": "https://project.supabase.co",
            "OCU_SUPABASE_ANON_KEY": "anon-key",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "app.university.learner_auth.requests.get", return_value=response
        ) as request:
            identity = verify_supabase_access_token("secret-access-token")
        self.assertEqual(
            identity,
            {
                "actor": "supabase:11111111-1111-1111-1111-111111111111",
                "subject": "supabase:11111111-1111-1111-1111-111111111111",
                "auth_type": "university_learner",
            },
        )
        self.assertNotIn("email", identity)
        self.assertNotIn("token", identity)
        headers = request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer secret-access-token")
        self.assertEqual(headers["apikey"], "anon-key")

    def test_expired_or_invalid_token_fails_closed(self) -> None:
        response = Mock(status_code=401, ok=False)
        env = {
            "OCU_SUPABASE_URL": "https://project.supabase.co",
            "OCU_SUPABASE_ANON_KEY": "anon-key",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "app.university.learner_auth.requests.get", return_value=response
        ):
            with self.assertRaises(HTTPException) as ctx:
                verify_supabase_access_token("expired")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail["code"], "INVALID_LEARNER_TOKEN")

    def test_missing_verifier_configuration_fails_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                verify_supabase_access_token("token")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail["code"], "LEARNER_AUTH_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
