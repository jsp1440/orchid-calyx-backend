import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ark.oc_ark import Ark, load_config, sha256


class ArkTests(unittest.TestCase):
    def test_sha256(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.bin"
            path.write_bytes(b"orchid-continuum")
            self.assertEqual(sha256(path), hashlib.sha256(b"orchid-continuum").hexdigest())

    def test_load_config(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps({"repositories": []}), encoding="utf-8")
            self.assertEqual(load_config(path)["repositories"], [])

    def test_inventory_reports_targets_without_exposing_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            config = {"local_root": td, "repositories": [{"name": "r", "url": "https://example.invalid/r.git"}]}
            env = {
                "DATABASE_URL": "postgresql://secret-user:secret-pass@example.invalid/db",
                "AZURE_STORAGE_ACCOUNT": "arkaccount",
                "AZURE_STORAGE_CONTAINER": "oc-ark",
                "ARK_OFFLINE_ROOT": "/offline",
            }
            with patch.dict(os.environ, env, clear=False):
                result = Ark(config).inventory()
            self.assertTrue(result["database_configured"])
            self.assertTrue(result["azure_configured"])
            self.assertTrue(result["offline_target_configured"])
            serialized = json.dumps(result)
            self.assertNotIn("secret-pass", serialized)
            self.assertNotIn("DATABASE_URL", serialized)


if __name__ == "__main__":
    unittest.main()
