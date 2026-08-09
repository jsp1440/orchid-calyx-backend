from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg

from scripts import apply_university_durable_migration as runner

READY_PREFLIGHT = {
    "ready_to_apply_migration": True,
    "migration_blockers": [],
    "database": {"configured": True, "reachable": True, "schema_valid": False, "missing_columns": {"lab_sessions": ["session_id"]}, "missing_constraint_fragments": []},
}
VALID_SCHEMA_PREFLIGHT = {**READY_PREFLIGHT, "database": {"configured": True, "reachable": True, "schema_valid": True, "missing_columns": {}, "missing_constraint_fragments": []}}


class GuardedMigrationRunnerContractTests(unittest.TestCase):
    def test_plan_is_non_mutating_and_redacts_credentials(self) -> None:
        database_url = "postgresql://secret-user:secret-pass@db.example.org:5432/orchid"
        with patch.object(runner, "preflight", return_value=READY_PREFLIGHT):
            result = runner.plan(release_evidence=Path("evidence.json"), database_url=database_url)
        self.assertTrue(result["migration_stage_preflight"]["ready"])
        self.assertTrue(result["would_apply"])
        self.assertFalse(result["mutations_performed"])
        self.assertEqual(result["database"]["hostname"], "db.example.org")
        self.assertEqual(result["database"]["database"], "orchid")
        self.assertEqual(result["database_confirmation_target"], "db.example.org:5432/orchid")
        self.assertNotIn("secret-user", str(result)); self.assertNotIn("secret-pass", str(result))
        self.assertRegex(result["migration"]["sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_keyword_conninfo_is_redacted_and_normalized(self) -> None:
        database_url = "host=db.example.org port=5432 dbname=orchid user=secret-user password=secret-pass sslmode=require"
        with patch.object(runner, "preflight", return_value=READY_PREFLIGHT):
            result = runner.plan(release_evidence=Path("evidence.json"), database_url=database_url)
        self.assertEqual(result["database"]["hostname"], "db.example.org"); self.assertEqual(result["database"]["port"], "5432"); self.assertEqual(result["database"]["database"], "orchid")
        self.assertEqual(result["database_confirmation_target"], "db.example.org:5432/orchid")
        self.assertNotIn("secret-user", str(result)); self.assertNotIn("secret-pass", str(result))

    def test_apply_requires_exact_digest_confirmation_before_connecting(self) -> None:
        database_url = "postgresql://db.example.org/orchid"
        with patch.object(runner, "preflight", return_value=READY_PREFLIGHT), patch.object(runner.psycopg, "connect") as connect:
            with self.assertRaisesRegex(runner.MigrationGuardError, "exact migration SHA-256 confirmation"):
                runner.apply_migration(release_evidence=Path("evidence.json"), database_url=database_url, confirm_migration_sha256="sha256:" + "0" * 64, confirm_database_target=runner.database_confirmation_target(database_url))
        connect.assert_not_called()

    def test_apply_rejects_file_change_between_snapshot_and_plan(self) -> None:
        database_url = "postgresql://db.example.org/orchid"; actual_digest = runner.migration_digest(); zero_digest = "sha256:" + "0" * 64; different_digest = zero_digest if actual_digest != zero_digest else "sha256:" + "1" * 64
        forged_plan = {"contract": "OCU-SCI-009N-MIGRATION-RUNNER-001", "mode": "dry_run", "migration": {"path": "migrations/ocu_sci_008_durable_sessions.sql", "sha256": different_digest}, "database": {"hostname": "db.example.org", "port": None, "database": "orchid"}, "database_confirmation_target": "db.example.org/orchid", "migration_stage_preflight": {"ready": True, "blockers": []}, "schema_already_valid": False, "would_apply": True, "requires_exact_migration_confirmation": different_digest, "requires_exact_database_confirmation": "db.example.org/orchid", "mutations_performed": False}
        with patch.object(runner, "plan", return_value=forged_plan), patch.object(runner.psycopg, "connect") as connect:
            with self.assertRaisesRegex(runner.MigrationGuardError, "migration file changed during guarded apply"):
                runner.apply_migration(release_evidence=Path("evidence.json"), database_url=database_url, confirm_migration_sha256=different_digest, confirm_database_target="db.example.org/orchid")
        connect.assert_not_called()

    def test_apply_requires_exact_database_target_before_connecting(self) -> None:
        database_url = "postgresql://db.example.org/orchid"
        with patch.object(runner, "preflight", return_value=READY_PREFLIGHT), patch.object(runner.psycopg, "connect") as connect:
            with self.assertRaisesRegex(runner.MigrationGuardError, "exact database target confirmation"):
                runner.apply_migration(release_evidence=Path("evidence.json"), database_url=database_url, confirm_migration_sha256=runner.migration_digest(), confirm_database_target="wrong.example.org/orchid")
        connect.assert_not_called()

    def test_blocked_preflight_never_connects(self) -> None:
        database_url = "postgresql://db.example.org/orchid"; blocked = {**READY_PREFLIGHT, "ready_to_apply_migration": False, "migration_blockers": ["release evidence artifact is invalid"]}
        with patch.object(runner, "preflight", return_value=blocked), patch.object(runner.psycopg, "connect") as connect:
            with self.assertRaisesRegex(runner.MigrationGuardError, "migration-stage preflight is blocked"):
                runner.apply_migration(release_evidence=Path("evidence.json"), database_url=database_url, confirm_migration_sha256=runner.migration_digest(), confirm_database_target=runner.database_confirmation_target(database_url))
        connect.assert_not_called()

    def test_already_valid_schema_is_idempotent_noop(self) -> None:
        database_url = "postgresql://db.example.org/orchid"
        with patch.object(runner, "preflight", return_value=VALID_SCHEMA_PREFLIGHT), patch.object(runner.psycopg, "connect") as connect:
            result = runner.apply_migration(release_evidence=Path("evidence.json"), database_url=database_url, confirm_migration_sha256=runner.migration_digest(), confirm_database_target=runner.database_confirmation_target(database_url))
        connect.assert_not_called(); self.assertEqual(result["result"], "already_valid_noop"); self.assertFalse(result["mutations_performed"])

    def test_apply_uses_bounded_connect_and_transaction_timeouts(self) -> None:
        database_url = "postgresql://db.example.org/orchid"; connect = MagicMock(); conn = connect.return_value.__enter__.return_value; cursor = conn.cursor.return_value.__enter__.return_value; conn.transaction.return_value.__enter__.return_value = MagicMock()
        with patch.object(runner, "preflight", return_value=READY_PREFLIGHT), patch.object(runner.psycopg, "connect", connect), patch.object(runner, "_schema_state_on_connection", return_value={"schema_valid": True, "missing_columns": {}, "missing_constraint_fragments": []}):
            result = runner.apply_migration(release_evidence=Path("evidence.json"), database_url=database_url, confirm_migration_sha256=runner.migration_digest(), confirm_database_target=runner.database_confirmation_target(database_url))
        self.assertEqual(result["result"], "applied_and_verified"); connect.assert_called_once_with(database_url, autocommit=True, connect_timeout=runner.CONNECT_TIMEOUT_SECONDS)
        cursor.execute.assert_any_call("SELECT set_config('lock_timeout', %s, true)", (f"{runner.LOCK_TIMEOUT_MS}ms",)); cursor.execute.assert_any_call("SELECT set_config('statement_timeout', %s, true)", (f"{runner.STATEMENT_TIMEOUT_MS}ms",))


@unittest.skipUnless(os.getenv("OCU_TEST_DATABASE_URL"), "OCU_TEST_DATABASE_URL is not configured")
class GuardedMigrationRunnerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database_url = os.environ["OCU_TEST_DATABASE_URL"]; cls.database_target = runner.database_confirmation_target(cls.database_url)
    def tearDown(self) -> None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS oc_university CASCADE"); conn.execute("DROP SCHEMA IF EXISTS ocu_rollback_probe CASCADE")
    def test_real_migration_applies_and_verifies_atomically(self) -> None:
        with patch.object(runner, "preflight", return_value=READY_PREFLIGHT):
            result = runner.apply_migration(release_evidence=Path("evidence.json"), database_url=self.database_url, confirm_migration_sha256=runner.migration_digest(), confirm_database_target=self.database_target)
        self.assertEqual(result["result"], "applied_and_verified"); self.assertTrue(result["post_apply_schema_valid"])
        with psycopg.connect(self.database_url) as conn: state = runner._schema_state_on_connection(conn)
        self.assertTrue(state["schema_valid"])
    def test_failed_post_apply_verification_rolls_back_transaction(self) -> None:
        bad_migration = runner.ROOT / "migrations" / "_ocu_sci_009n_bad_test.sql"
        try:
            bad_migration.write_text("CREATE SCHEMA ocu_rollback_probe; CREATE TABLE ocu_rollback_probe.partial(id integer);\n", encoding="utf-8")
            with patch.object(runner, "MIGRATION", bad_migration), patch.object(runner, "preflight", return_value=READY_PREFLIGHT):
                digest = runner.migration_digest()
                with self.assertRaisesRegex(runner.MigrationGuardError, "post-apply durable schema verification failed"):
                    runner.apply_migration(release_evidence=Path("evidence.json"), database_url=self.database_url, confirm_migration_sha256=digest, confirm_database_target=self.database_target)
        finally: bad_migration.unlink(missing_ok=True)
        with psycopg.connect(self.database_url) as conn:
            exists = conn.execute("SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name='ocu_rollback_probe')").fetchone()[0]
        self.assertFalse(exists)


if __name__ == "__main__": unittest.main()
