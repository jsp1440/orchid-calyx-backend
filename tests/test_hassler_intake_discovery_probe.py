"""OC-COMPLETE-002 — read-only discovery probe emits lifecycle and exception receipt."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SHA = "e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f"
FILENAME = "WorldOrchids 26-08 (Aug 2 2026).csv"

READINESS = {
    "ready_for_upload": True,
    "pipeline_state": "ready_for_release_upload",
    "next_job": {"job": "upload_world_orchids_release"},
    "gates": [
        {"name": "owner_authentication", "status": "passed"},
        {"name": "smoke_fixture", "status": "blocked", "blocking_reason": "not run"},
    ],
}
MIGRATION = {"state": "migration_verified", "schema_complete": True}


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("CALYX_BACKEND_URL", "https://backend.invalid")
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "test-code")
    monkeypatch.setenv(
        "CALYX_HASSLER_DISCOVERY_REPORT", str(tmp_path / "discovery.json")
    )
    sys.modules.pop("discover_hassler_release_intake", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("discover_hassler_release_intake")


def _install_routes(monkeypatch, module, routes):
    """Replace the HTTP layer with a fixed route table; assert GET-only reads."""
    calls: list[tuple[str, str]] = []

    def fake_request(path, *, method="GET", payload=None, token=""):
        calls.append((method, path))
        if path == "/api/mission-control/owner/session-token":
            return 200, {"token": "session-token"}
        assert method == "GET", "discovery must never issue a non-GET read"
        if path not in routes:
            raise AssertionError(f"unexpected path: {path}")
        status, body = routes[path]
        if status >= 400:
            raise HTTPError(path, status, "error", {}, None)  # type: ignore[arg-type]
        return status, body

    monkeypatch.setattr(module, "_request", fake_request)
    return calls


@pytest.fixture
def absent_module(monkeypatch, tmp_path):
    module = _load(monkeypatch, tmp_path)
    calls = _install_routes(
        monkeypatch,
        module,
        {
            "/api/mission-control/taxonomy/migration-preflight": (200, MIGRATION),
            "/api/mission-control/taxonomy/readiness": (200, READINESS),
            "/api/mission-control/taxonomy/releases": (200, {"releases": []}),
            f"/api/mission-control/taxonomy/releases/{SHA}": (404, None),
            f"/api/mission-control/taxonomy/releases/{SHA}/staging": (404, None),
        },
    )
    return module, calls, tmp_path / "discovery.json"


def test_absent_release_emits_lifecycle_and_owner_exception_receipt(absent_module):
    module, calls, report_path = absent_module
    assert module.main() == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["schema_version"] == "1.2"
    assert report["upload_invoked"] is False
    assert report["staging_invoked"] is False
    assert report["lifecycle"]["lifecycle_state"] == "ABSENT"
    assert report["lifecycle"]["durably_uploaded"] is False

    receipt = report["owner_exception_receipt"]
    assert receipt["action_executed"] is False
    assert receipt["incorporation_assumed"] is False
    assert receipt["responsible_party"] == "repository owner"
    assert "upload_hassler_release_guarded.py" in receipt["next_executable_action"]
    assert receipt["prepared_action"]["confirmation_token_env"] == (
        "CALYX_HASSLER_UPLOAD_CONFIRMATION"
    )
    assert len(receipt["artifact_hash"]) == 64
    assert len(report["artifact_hash"]) == 64

    # Only the session token is a POST; every state read is a GET.
    assert [method for method, _ in calls].count("POST") == 1


def test_unreadable_release_list_does_not_claim_absence(monkeypatch, tmp_path):
    module = _load(monkeypatch, tmp_path)
    _install_routes(
        monkeypatch,
        module,
        {
            "/api/mission-control/taxonomy/migration-preflight": (200, MIGRATION),
            "/api/mission-control/taxonomy/readiness": (200, READINESS),
            "/api/mission-control/taxonomy/releases": (200, {}),
            f"/api/mission-control/taxonomy/releases/{SHA}": (503, None),
            f"/api/mission-control/taxonomy/releases/{SHA}/staging": (503, None),
        },
    )
    assert module.main() == 0
    report = json.loads((tmp_path / "discovery.json").read_text(encoding="utf-8"))
    # The release list itself returned 200 with no releases key: absent is correct,
    # but staging and readback are unavailable and must be recorded as such.
    assert report["lifecycle"]["lifecycle_state"] == "ABSENT"
    probes = {item["probe"] for item in report["lifecycle"]["unavailable_evidence"]}
    assert {"release_detail", "staging", "canonical_activation"} <= probes


def test_present_and_staged_release_is_reported_without_activation(
    monkeypatch, tmp_path
):
    module = _load(monkeypatch, tmp_path)
    entry = {
        "release_id": SHA,
        "state": "staged",
        "snapshot": {
            "filename": FILENAME,
            "sha256": SHA,
            "size_bytes": 11_529_836,
            "version_label": "26-08",
            "acquired_at": "2026-08-02",
            "row_count": 34_724,
        },
    }
    staging = {
        "checkpoint": {
            "next_row_index": 34_724,
            "staged_count": 34_724,
            "completed": True,
            "updated_at": "2026-08-22T00:00:00+00:00",
        },
        "counts": {"staged": 34_724, "open_review": 0},
        "change_report": {"summary": {"added_taxa": 65, "malformed_rows": 0}},
    }
    _install_routes(
        monkeypatch,
        module,
        {
            "/api/mission-control/taxonomy/migration-preflight": (200, MIGRATION),
            "/api/mission-control/taxonomy/readiness": (200, READINESS),
            "/api/mission-control/taxonomy/releases": (200, {"releases": [entry]}),
            f"/api/mission-control/taxonomy/releases/{SHA}": (200, entry),
            f"/api/mission-control/taxonomy/releases/{SHA}/staging": (200, staging),
        },
    )
    assert module.main() == 0
    report = json.loads((tmp_path / "discovery.json").read_text(encoding="utf-8"))

    assert report["real_release_present"] is True
    assert report["lifecycle"]["lifecycle_state"] == "STAGED_COMPLETE"
    assert report["lifecycle"]["identity"]["verified"] is True
    assert report["lifecycle"]["activation"]["exact_release_is_active"] is None
    assert report["status_block"]["active_vs_staged"] == "unavailable"
    assert report["status_block"]["staged_release_id"] == SHA
    assert "owner_exception_receipt" not in report
    assert report["downstream_relink_impact"]["drivers"]["added_taxa"] == 65
