import os
from pathlib import Path

import scripts.calyx_matrix_durability_run as launcher


def test_launcher_scopes_custom_registry_root_for_copy_and_readiness(monkeypatch, tmp_path: Path):
    source_root = tmp_path / "registries"
    captured = {}

    def fake_execute_deployment(*, apply=False, source_root=None):
        captured["apply"] = apply
        captured["source_root"] = source_root
        captured["env_root"] = os.environ.get("CALYX_MATRIX_REGISTRY_DIR")
        return {"mode": "apply", "blockers": []}

    monkeypatch.setattr(launcher, "execute_deployment", fake_execute_deployment)
    monkeypatch.setenv("CALYX_MATRIX_REGISTRY_DIR", "/previous/root")

    result = launcher.run(apply=True, source_root=source_root)

    assert result["blockers"] == []
    assert captured == {
        "apply": True,
        "source_root": source_root,
        "env_root": str(source_root),
    }
    assert os.environ["CALYX_MATRIX_REGISTRY_DIR"] == "/previous/root"


def test_launcher_removes_temporary_root_when_none_existed(monkeypatch, tmp_path: Path):
    source_root = tmp_path / "registries"
    seen = {}

    def fake_execute_deployment(*, apply=False, source_root=None):
        seen["during"] = os.environ.get("CALYX_MATRIX_REGISTRY_DIR")
        return {"mode": "dry_run", "blockers": []}

    monkeypatch.setattr(launcher, "execute_deployment", fake_execute_deployment)
    monkeypatch.delenv("CALYX_MATRIX_REGISTRY_DIR", raising=False)

    launcher.run(source_root=source_root)

    assert seen["during"] == str(source_root)
    assert "CALYX_MATRIX_REGISTRY_DIR" not in os.environ


def test_launcher_without_custom_root_does_not_mutate_registry_environment(monkeypatch):
    captured = {}

    def fake_execute_deployment(*, apply=False, source_root=None):
        captured["env_root"] = os.environ.get("CALYX_MATRIX_REGISTRY_DIR")
        captured["source_root"] = source_root
        return {"mode": "dry_run", "blockers": []}

    monkeypatch.setattr(launcher, "execute_deployment", fake_execute_deployment)
    monkeypatch.setenv("CALYX_MATRIX_REGISTRY_DIR", "/configured/root")

    launcher.run()

    assert captured == {"env_root": "/configured/root", "source_root": None}
    assert os.environ["CALYX_MATRIX_REGISTRY_DIR"] == "/configured/root"


def test_launcher_bootstraps_repository_root_for_direct_execution():
    assert str(launcher.ROOT) in launcher.sys.path
