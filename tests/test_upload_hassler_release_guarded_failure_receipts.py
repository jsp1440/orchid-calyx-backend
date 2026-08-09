from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

import scripts.upload_hassler_release_guarded as guarded


def _fixture_source(tmp_path: Path, monkeypatch) -> Path:
    payload = b"Taxon|Number|Name\nS|1|Example orchid\n"
    path = tmp_path / "fixture.csv"
    path.write_bytes(payload)
    monkeypatch.setattr(guarded, "EXPECTED_FILENAME", path.name)
    monkeypatch.setattr(guarded, "EXPECTED_SIZE_BYTES", len(payload))
    monkeypatch.setattr(guarded, "EXPECTED_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(guarded, "VERSION_LABEL", "fixture-version")
    monkeypatch.setattr(guarded, "ACQUIRED_AT", "2026-08-02")
    return path


def _release_report() -> dict:
    return {
        "release_id": guarded.EXPECTED_SHA256,
        "state": "inspected",
        "snapshot": {
            "sha256": guarded.EXPECTED_SHA256,
            "version_label": guarded.VERSION_LABEL,
            "filename": guarded.EXPECTED_FILENAME,
            "acquired_at": guarded.ACQUIRED_AT,
        },
        "automatic_promotion": False,
        "durable_storage": "postgresql",
    }


def test_successful_mutation_with_failed_readback_returns_failure_receipt(
    tmp_path: Path, monkeypatch
):
    path = _fixture_source(tmp_path, monkeypatch)
    release_gets = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal release_gets
        if request.url.path == "/api/mission-control/owner/session-token":
            return httpx.Response(200, json={"token": "owner-token"})
        release_path = f"/api/mission-control/taxonomy/releases/{guarded.EXPECTED_SHA256}"
        if request.url.path == release_path:
            release_gets += 1
            if release_gets == 1:
                return httpx.Response(404)
            return httpx.Response(503, json={"detail": "readback unavailable"})
        if request.url.path == "/api/mission-control/taxonomy/readiness":
            return httpx.Response(
                200,
                json={
                    "ready_for_upload": True,
                    "pipeline_state": "ready_for_release_upload",
                    "next_job": {"job": "upload_world_orchids_release"},
                },
            )
        if request.url.path == "/api/mission-control/taxonomy/releases/inspect":
            return httpx.Response(200, json=_release_report())
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.Client(
        base_url="https://calyx.invalid", transport=httpx.MockTransport(handler)
    )
    receipt = guarded.execute_upload(
        source_path=path,
        base_url="https://calyx.invalid",
        access_code="secret",
        client=client,
    )
    client.close()

    assert receipt["status"] == "MUTATED_VERIFICATION_FAILED"
    assert receipt["upload_invoked"] is True
    assert receipt["production_mutation"] is True
    assert receipt["mutation_state"] == "CONFIRMED"
    assert receipt["readback_verified"] is False
    assert receipt["artifact_hash"]
    assert "503" in receipt["error"]


def test_failed_upload_response_preserves_unknown_mutation_receipt(
    tmp_path: Path, monkeypatch
):
    path = _fixture_source(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/mission-control/owner/session-token":
            return httpx.Response(200, json={"token": "owner-token"})
        if request.url.path == (
            f"/api/mission-control/taxonomy/releases/{guarded.EXPECTED_SHA256}"
        ):
            return httpx.Response(404)
        if request.url.path == "/api/mission-control/taxonomy/readiness":
            return httpx.Response(
                200,
                json={
                    "ready_for_upload": True,
                    "pipeline_state": "ready_for_release_upload",
                    "next_job": {"job": "upload_world_orchids_release"},
                },
            )
        if request.url.path == "/api/mission-control/taxonomy/releases/inspect":
            return httpx.Response(503, json={"detail": "upstream timeout"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.Client(
        base_url="https://calyx.invalid", transport=httpx.MockTransport(handler)
    )
    receipt = guarded.execute_upload(
        source_path=path,
        base_url="https://calyx.invalid",
        access_code="secret",
        client=client,
    )
    client.close()

    assert receipt["status"] == "UPLOAD_RESULT_UNKNOWN"
    assert receipt["upload_invoked"] is True
    assert receipt["production_mutation"] is None
    assert receipt["mutation_state"] == "UNKNOWN"
    assert receipt["readback_verified"] is False
    assert receipt["artifact_hash"]
    assert "503" in receipt["error"]
