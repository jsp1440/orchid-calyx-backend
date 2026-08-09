from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

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
            "source_encoding": "utf-8",
            "row_count": 1,
        },
        "automatic_promotion": False,
        "durable_storage": "postgresql",
    }


def test_validate_source_fails_closed_on_checksum_drift(tmp_path: Path, monkeypatch):
    path = _fixture_source(tmp_path, monkeypatch)
    monkeypatch.setattr(guarded, "EXPECTED_SHA256", "0" * 64)

    with pytest.raises(ValueError, match="unexpected source sha256"):
        guarded.validate_source(path)


def test_release_report_rejects_automatic_promotion(tmp_path: Path, monkeypatch):
    _fixture_source(tmp_path, monkeypatch)
    report = _release_report()
    report["automatic_promotion"] = True

    with pytest.raises(RuntimeError, match="automatic promotion"):
        guarded._assert_release_report(report)


def test_execute_upload_verifies_readback_and_never_stages(tmp_path: Path, monkeypatch):
    path = _fixture_source(tmp_path, monkeypatch)
    seen: list[tuple[str, str]] = []
    release_gets = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal release_gets
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/mission-control/owner/session-token":
            return httpx.Response(200, json={"token": "owner-token"})
        release_path = (
            f"/api/mission-control/taxonomy/releases/{guarded.EXPECTED_SHA256}"
        )
        if request.url.path == release_path:
            release_gets += 1
            if release_gets == 1:
                return httpx.Response(
                    404, json={"detail": "taxonomy release not found"}
                )
            return httpx.Response(200, json=_release_report())
        if request.url.path == "/api/mission-control/taxonomy/readiness":
            readiness_calls = sum(
                1
                for method, route in seen
                if method == "GET" and route.endswith("/readiness")
            )
            if readiness_calls == 1:
                return httpx.Response(
                    200,
                    json={
                        "ready_for_upload": True,
                        "pipeline_state": "ready_for_release_upload",
                        "next_job": {"job": "upload_world_orchids_release"},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "ready_for_upload": True,
                    "pipeline_state": "release_inspected_staging_smoke_required",
                    "next_job": {"job": "verify_taxonomy_staging_smoke"},
                },
            )
        if request.url.path == "/api/mission-control/taxonomy/releases/inspect":
            assert request.method == "POST"
            assert b"fixture-version" in request.content
            assert b"Example orchid" in request.content
            return httpx.Response(200, json=_release_report())
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.Client(
        base_url="https://calyx.invalid",
        transport=httpx.MockTransport(handler),
    )
    receipt = guarded.execute_upload(
        source_path=path,
        base_url="https://calyx.invalid",
        access_code="secret",
        client=client,
    )
    client.close()

    assert receipt["status"] == "passed"
    assert receipt["upload_invoked"] is True
    assert receipt["production_mutation"] is True
    assert receipt["readback_verified"] is True
    assert receipt["staging_invoked"] is False
    assert receipt["taxonomy_activation_authorized"] is False
    assert receipt["knowledge_graph_mutation_authorized"] is False
    assert receipt["post_upload_pipeline_state"] == (
        "release_inspected_staging_smoke_required"
    )
    assert release_gets == 2
    assert all(not route.endswith("/stage") for _, route in seen)


def test_execute_upload_is_noop_when_exact_durable_release_already_exists(
    tmp_path: Path, monkeypatch
):
    path = _fixture_source(tmp_path, monkeypatch)
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/mission-control/owner/session-token":
            return httpx.Response(200, json={"token": "owner-token"})
        if request.url.path == (
            f"/api/mission-control/taxonomy/releases/{guarded.EXPECTED_SHA256}"
        ):
            return httpx.Response(200, json=_release_report())
        if request.url.path == "/api/mission-control/taxonomy/readiness":
            return httpx.Response(
                200,
                json={
                    "ready_for_upload": True,
                    "pipeline_state": "release_inspected_ready_for_bounded_staging",
                    "next_job": {"job": "stage_next_taxonomy_batch"},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.Client(
        base_url="https://calyx.invalid",
        transport=httpx.MockTransport(handler),
    )
    receipt = guarded.execute_upload(
        source_path=path,
        base_url="https://calyx.invalid",
        access_code="secret",
        client=client,
    )
    client.close()

    assert receipt["status"] == "NO_OP_ALREADY_PRESENT"
    assert receipt["upload_invoked"] is False
    assert receipt["production_mutation"] is False
    assert receipt["readback_verified"] is True
    assert receipt["next_job"]["job"] == "stage_next_taxonomy_batch"
    assert not any(route.endswith("/inspect") for _, route in seen)


def test_execute_upload_rejects_mismatched_existing_release_without_post(
    tmp_path: Path, monkeypatch
):
    path = _fixture_source(tmp_path, monkeypatch)
    seen: list[tuple[str, str]] = []
    mismatched = _release_report()
    mismatched["snapshot"] = {**mismatched["snapshot"], "version_label": "wrong"}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/mission-control/owner/session-token":
            return httpx.Response(200, json={"token": "owner-token"})
        if request.url.path == (
            f"/api/mission-control/taxonomy/releases/{guarded.EXPECTED_SHA256}"
        ):
            return httpx.Response(200, json=mismatched)
        raise AssertionError("mismatched immutable release must fail before upload")

    client = httpx.Client(
        base_url="https://calyx.invalid",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="release identity mismatch"):
        guarded.execute_upload(
            source_path=path,
            base_url="https://calyx.invalid",
            access_code="secret",
            client=client,
        )
    client.close()
    assert not any(route.endswith("/inspect") for _, route in seen)


def test_execute_upload_refuses_when_mission_control_is_not_ready(
    tmp_path: Path, monkeypatch
):
    path = _fixture_source(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/mission-control/owner/session-token":
            return httpx.Response(200, json={"token": "owner-token"})
        if request.url.path == (
            f"/api/mission-control/taxonomy/releases/{guarded.EXPECTED_SHA256}"
        ):
            return httpx.Response(404, json={"detail": "taxonomy release not found"})
        if request.url.path == "/api/mission-control/taxonomy/readiness":
            return httpx.Response(
                200,
                json={
                    "ready_for_upload": False,
                    "next_job": {"job": "resolve_taxonomy_intake_gates"},
                },
            )
        raise AssertionError("upload must not be attempted when readiness is blocked")

    client = httpx.Client(
        base_url="https://calyx.invalid",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="ready_for_upload=true"):
        guarded.execute_upload(
            source_path=path,
            base_url="https://calyx.invalid",
            access_code="secret",
            client=client,
        )
    client.close()
