from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.routers.release_identity import release_identity


class ReleaseIdentityTests(unittest.TestCase):
    def test_missing_release_sha_fails_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            identity = release_identity()
        self.assertEqual(identity["contract"], "OCU-RELEASE-IDENTITY-001")
        self.assertFalse(identity["attested"])
        self.assertIsNone(identity["commit_sha"])

    def test_full_sha_is_attested(self) -> None:
        sha = "a" * 40
        with patch.dict(os.environ, {"OCU_RELEASE_SHA": sha}, clear=True):
            identity = release_identity()
        self.assertTrue(identity["attested"])
        self.assertEqual(identity["commit_sha"], sha)
        self.assertEqual(identity["source"], "OCU_RELEASE_SHA")

    def test_short_sha_is_not_attested(self) -> None:
        with patch.dict(os.environ, {"OCU_RELEASE_SHA": "abc1234"}, clear=True):
            identity = release_identity()
        self.assertFalse(identity["attested"])
        self.assertIsNone(identity["commit_sha"])

    def test_public_endpoint_exposes_only_non_secret_release_identity(self) -> None:
        sha = "b" * 40
        with patch.dict(os.environ, {"OCU_RELEASE_SHA": sha}, clear=True):
            response = TestClient(app).get("/api/release-identity")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["service"], "orchid-calyx-backend")
        self.assertEqual(payload["commit_sha"], sha)
        self.assertTrue(payload["attested"])
        self.assertNotIn("DATABASE_URL", payload)
        self.assertNotIn("CALYX_API_KEY", payload)


if __name__ == "__main__":
    unittest.main()
