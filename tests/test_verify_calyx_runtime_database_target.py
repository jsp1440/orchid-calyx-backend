from __future__ import annotations

import pytest

from scripts.verify_calyx_runtime_database_target import _identity, verify_targets


def test_same_database_identity_matches_with_different_credentials():
    result = verify_targets(
        "postgresql://app_user:secret@db.example.net:5432/orchid",
        "postgresql://migration_user:other@db.example.net/orchid",
    )
    assert result["database_target_match"] is True
    assert result["database_mutation_attempted"] is False
    assert result["production_database_mutation_attempted"] is False
    assert result["runtime_database_fingerprint"] == result["migration_database_fingerprint"]


def test_different_host_fails_identity_match():
    result = verify_targets(
        "postgresql://app@runtime.example.net/orchid",
        "postgresql://migration@migration.example.net/orchid",
    )
    assert result["database_target_match"] is False
    assert result["runtime_database_fingerprint"] != result["migration_database_fingerprint"]


def test_different_database_fails_identity_match():
    result = verify_targets(
        "postgresql://app@db.example.net/orchid_runtime",
        "postgresql://migration@db.example.net/orchid_migrations",
    )
    assert result["database_target_match"] is False


def test_default_postgres_port_is_canonicalized():
    assert _identity("postgresql://app@db.example.net/orchid") == (
        "db.example.net",
        5432,
        "orchid",
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("sqlite:///calyx.db", "POSTGRESQL_DATABASE_URL_REQUIRED"),
        ("postgresql:///orchid", "DATABASE_HOST_REQUIRED"),
        ("postgresql://db.example.net/", "DATABASE_NAME_REQUIRED"),
    ],
)
def test_invalid_targets_fail_closed(value: str, expected: str):
    with pytest.raises(ValueError, match=expected):
        _identity(value)
