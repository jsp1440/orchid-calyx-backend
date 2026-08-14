from scripts.verify_calyx_runtime_migration_database_target import (
    TargetObservation,
    compare_targets,
)


def _target(**overrides):
    values = {
        "source": "fixture",
        "host": "db.example",
        "port": 5432,
        "database": "orchids",
        "current_user": "calyx",
        "database_oid": "16384",
        "server_version_num": "170010",
        "server_address": "10.0.0.10",
        "server_port": 5432,
        "system_identifier": "7777777777777777777",
        "species_relation_oid": "22000",
        "research_station_projects_oid": None,
        "transaction_read_only": "on",
    }
    values.update(overrides)
    return TargetObservation(**values)


def test_exact_config_identity_is_accepted():
    result = compare_targets(_target(source="runtime"), _target(source="migration"))
    assert result["same_target"] is True
    assert result["config_identity_match"] is True
    assert result["system_identifier_mismatch"] is False
    assert result["same_cluster_database_oid_mismatch"] is False
    assert result["blockers"] == []


def test_same_cluster_database_allows_different_connection_endpoint():
    runtime = _target(host="runtime-pool.example", server_address="10.0.0.10")
    migration = _target(host="migration-direct.example", server_address="10.0.0.11")
    result = compare_targets(runtime, migration)
    assert result["same_target"] is True
    assert result["config_identity_match"] is False
    assert result["cluster_database_identity_match"] is True


def test_exact_config_identity_rejects_observed_cluster_identifier_mismatch():
    runtime = _target(source="runtime")
    migration = _target(source="migration", system_identifier="8888888888888888888")
    result = compare_targets(runtime, migration)
    assert result["config_identity_match"] is True
    assert result["system_identifier_mismatch"] is True
    assert result["same_target"] is False
    assert "POSTGRES_CLUSTER_SYSTEM_IDENTIFIER_MISMATCH" in result["blockers"]
    assert "RUNTIME_MIGRATION_DATABASE_TARGET_NOT_PROVEN_EQUAL" in result["blockers"]


def test_same_cluster_same_database_name_rejects_database_oid_mismatch():
    runtime = _target(source="runtime")
    migration = _target(source="migration", database_oid="16385")
    result = compare_targets(runtime, migration)
    assert result["config_identity_match"] is True
    assert result["same_cluster_database_oid_mismatch"] is True
    assert result["same_target"] is False
    assert "POSTGRES_DATABASE_OID_MISMATCH" in result["blockers"]


def test_different_database_fails_closed():
    result = compare_targets(_target(), _target(database="other", database_oid="16385"))
    assert result["same_target"] is False
    assert "RUNTIME_MIGRATION_DATABASE_TARGET_NOT_PROVEN_EQUAL" in result["blockers"]


def test_unprovable_cross_host_target_fails_closed_without_cluster_identifier():
    result = compare_targets(
        _target(host="runtime.example", system_identifier=None),
        _target(host="migration.example", system_identifier=None),
    )
    assert result["same_target"] is False


def test_relation_identity_mismatch_fails_closed():
    result = compare_targets(
        _target(),
        _target(species_relation_oid="22001"),
    )
    assert result["same_target"] is False
    assert result["sentinel_relation_mismatch_indexes"] == [0]
    assert "CANONICAL_SENTINEL_RELATION_IDENTITY_MISMATCH" in result["blockers"]
