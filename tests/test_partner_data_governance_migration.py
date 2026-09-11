from __future__ import annotations

from pathlib import Path

MIGRATION = Path("migrations/111_partner_data_governance_registry.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_governance_migration_creates_isolated_schema_and_revokes_public_access():
    sql = _sql()
    assert "CREATE SCHEMA IF NOT EXISTS oc_security" in sql
    assert "REVOKE ALL ON SCHEMA oc_security FROM PUBLIC" in sql
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA oc_security FROM PUBLIC" in sql
    assert "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA oc_security FROM PUBLIC" in sql


def test_registry_contains_partner_agreement_policy_project_and_audit_objects():
    sql = _sql()
    required_objects = (
        "oc_security.partner_organizations",
        "oc_security.partner_agreements",
        "oc_security.dataset_policies",
        "oc_security.research_projects",
        "oc_security.project_memberships",
        "oc_security.principal_entitlements",
        "oc_security.record_policy_bindings",
        "oc_security.access_audit_events",
        "oc_security.policy_change_events",
    )
    for object_name in required_objects:
        assert f"CREATE TABLE IF NOT EXISTS {object_name}" in sql


def test_database_policy_vocabulary_matches_application_security_vocabulary():
    sql = _sql()
    for sensitivity in (
        "PUBLIC",
        "ATTRIBUTED",
        "RESEARCH_RESTRICTED",
        "SENSITIVE_CONSERVATION",
        "SEALED_PARTNER",
    ):
        assert f"'{sensitivity}'" in sql
    for disclosure in (
        "FULL",
        "GENERALIZED",
        "AGGREGATE_ONLY",
        "EXISTENCE_ONLY",
        "DENY",
    ):
        assert f"'{disclosure}'" in sql


def test_record_policy_and_audit_surfaces_force_rls_without_permissive_policy():
    sql = _sql()
    for table in (
        "oc_security.record_policy_bindings",
        "oc_security.access_audit_events",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY" not in sql


def test_migration_does_not_mutate_existing_scientific_domain_tables():
    sql = _sql().upper()
    assert "DROP TABLE" not in sql
    assert "DROP SCHEMA" not in sql
    assert "TRUNCATE " not in sql
    assert "DELETE FROM" not in sql
    assert "UPDATE OC_" not in sql
    assert "ALTER TABLE OC_OCCURRENCES" not in sql
    assert "ALTER TABLE OCCURRENCE_PIPELINE" not in sql


def test_policy_registry_separates_model_export_and_media_location_permissions():
    sql = _sql()
    for field in (
        "allow_export boolean",
        "allow_model_processing boolean",
        "approved_model_providers text[]",
        "default_disclosure text",
        "location_disclosure text",
        "image_disclosure text",
    ):
        assert field in sql
