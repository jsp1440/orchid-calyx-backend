from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.university.release import release_readiness


class UniversityReleaseReadinessTests(unittest.TestCase):
    def test_disabled_configuration_is_not_read_only_ready(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = release_readiness()
        self.assertFalse(result["university_enabled"])
        self.assertFalse(result["read_only_ready"])
        self.assertFalse(result["session_writes_enabled"])

    def test_safe_read_only_configuration_is_ready(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OCU_UNIVERSITY_ENABLED": "true",
                "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "false",
            },
            clear=True,
        ):
            result = release_readiness()
        self.assertTrue(result["read_only_ready"])
        self.assertFalse(result["session_writes_enabled"])
        self.assertFalse(result["publication_enabled"])
        self.assertFalse(result["candidate_knowledge_writes_enabled"])
        self.assertFalse(result["calyx_model_calls_enabled"])
        self.assertTrue(result["human_review_required"])

    def test_write_enabled_configuration_is_not_read_only_ready(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OCU_UNIVERSITY_ENABLED": "true",
                "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
            },
            clear=True,
        ):
            result = release_readiness()
        self.assertFalse(result["read_only_ready"])
        self.assertTrue(result["session_writes_enabled"])


if __name__ == "__main__":
    unittest.main()
