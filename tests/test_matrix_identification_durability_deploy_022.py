from pathlib import Path

from scripts import calyx_matrix_durability_deploy as deploy


def test_dry_run_never_applies_migrations_or_changes_activation_flags(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CALYX_MATRIX_REGISTRY_DURABLE_ENABLED", raising=False)
    monkeypatch.delenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", raising=False)
    monkeypatch.setattr(deploy, "matrix_durability_readiness", lambda: {"ok": True})

    result = deploy.execute_deployment(apply=False)

    assert result["mode"] == "dry_run"
    assert result["database_url_configured"] is False
    assert "change Render/service environment variables" in result["apply_would_not_perform"]
    assert "CALYX_MATRIX_REGISTRY_DURABLE_ENABLED" not in __import__("os").environ
    assert "CALYX_MATRIX_SESSION_DURABLE_ENABLED" not in __import__("os").environ


def test_apply_fails_closed_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(deploy, "matrix_durability_readiness", lambda: {"components": {}})

    result = deploy.execute_deployment(apply=True)

    assert result["applied"] is False
    assert result["blockers"] == ["DATABASE_URL_NOT_CONFIGURED"]


def test_successful_apply_requires_registry_copy_and_both_component_preflights(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.delenv("CALYX_MATRIX_REGISTRY_DURABLE_ENABLED", raising=False)
    monkeypatch.delenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", raising=False)
    monkeypatch.setattr(
        deploy,
        "migration_inventory",
        lambda: [
            {"migration": 612, "path": "612.sql", "exists": True, "bytes": 1},
            {"migration": 613, "path": "613.sql", "exists": True, "bytes": 1},
        ],
    )
    monkeypatch.setattr(
        deploy,
        "apply_migrations",
        lambda dsn: [
            {"migration": 612, "applied": True},
            {"migration": 613, "applied": True},
        ],
    )
    monkeypatch.setattr(deploy, "FileMatrixRegistryStore", lambda root: object())
    monkeypatch.setattr(deploy, "PostgresMatrixRegistryStore", lambda dsn: object())
    monkeypatch.setattr(
        deploy,
        "execute_registry_migration",
        lambda **kwargs: {"applied": True, "blockers": [], "verification": {"data_copy_ready": True}},
    )
    monkeypatch.setattr(
        deploy,
        "matrix_durability_readiness",
        lambda: {
            "components": {
                "registry": {"preflight": {"activation_ready": True}},
                "session": {"preflight": {"activation_ready": True}},
            }
        },
    )

    result = deploy.execute_deployment(apply=True, source_root=Path(tmp_path))

    assert result["applied"] is True
    assert result["activation_ready_after_apply"] is True
    assert result["activation_flags_changed"] is False
    assert result["activation_order"] == [
        "CALYX_MATRIX_REGISTRY_DURABLE_ENABLED",
        "CALYX_MATRIX_SESSION_DURABLE_ENABLED",
    ]
    assert "CALYX_MATRIX_REGISTRY_DURABLE_ENABLED" not in __import__("os").environ
    assert "CALYX_MATRIX_SESSION_DURABLE_ENABLED" not in __import__("os").environ


def test_failed_registry_copy_blocks_activation_readiness(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.setattr(
        deploy,
        "migration_inventory",
        lambda: [
            {"migration": 612, "path": "612.sql", "exists": True, "bytes": 1},
            {"migration": 613, "path": "613.sql", "exists": True, "bytes": 1},
        ],
    )
    monkeypatch.setattr(deploy, "apply_migrations", lambda dsn: [{"migration": 612}, {"migration": 613}])
    monkeypatch.setattr(deploy, "FileMatrixRegistryStore", lambda root: object())
    monkeypatch.setattr(deploy, "PostgresMatrixRegistryStore", lambda dsn: object())
    monkeypatch.setattr(
        deploy,
        "execute_registry_migration",
        lambda **kwargs: {"applied": False, "blockers": ["MATRIX_REGISTRY_SOURCE_CHECKSUM_INVALID"]},
    )

    result = deploy.execute_deployment(apply=True, source_root=Path(tmp_path))

    assert result["applied"] is False
    assert result["activation_flags_changed"] is False
    assert result["blockers"] == ["MATRIX_REGISTRY_SOURCE_CHECKSUM_INVALID"]
