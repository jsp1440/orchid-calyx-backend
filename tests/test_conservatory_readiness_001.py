from pathlib import Path

import pytest

import runtime.conservatory_readiness as readiness
from runtime.conservatory_readiness import (
    build_conservatory_readiness,
    create_restart_probe,
    verify_restart_probe,
)


def test_readiness_fails_closed_on_temporary_unverified_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("CALYX_CONSERVATORY_STORAGE_PERSISTENT", raising=False)

    report = build_conservatory_readiness(tmp_path)
    gates = {gate["name"]: gate["passed"] for gate in report["gates"]}

    assert report["ready_for_collection_entry"] is False
    assert gates["storage_directory"] is True
    assert gates["non_ephemeral_path"] is False
    assert gates["persistent_volume_declared"] is False
    assert gates["restart_survival"] is False


def test_probe_cannot_verify_before_restart(tmp_path: Path):
    probe = create_restart_probe(tmp_path)

    with pytest.raises(ValueError, match="restart has not occurred"):
        verify_restart_probe(tmp_path, probe["token"])


def test_probe_certifies_after_boot_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    probe = create_restart_probe(tmp_path)
    monkeypatch.setattr(readiness, "_BOOT_ID", "different-process-boot")

    result = verify_restart_probe(tmp_path, probe["token"])

    assert result["verified"] is True
    assert result["token"] == probe["token"]


def test_readiness_passes_after_persistent_restart_certification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    persistent_root = tmp_path / "mounted-conservatory"
    persistent_root.mkdir()
    probe = create_restart_probe(persistent_root)
    monkeypatch.setattr(readiness, "_BOOT_ID", "different-process-boot")
    verify_restart_probe(persistent_root, probe["token"])
    monkeypatch.setenv("CALYX_CONSERVATORY_STORAGE_PERSISTENT", "true")
    monkeypatch.setattr(readiness, "_is_non_ephemeral", lambda root: True)

    report = build_conservatory_readiness(persistent_root)

    assert report["ready_for_collection_entry"] is True
    assert all(gate["passed"] for gate in report["gates"])
