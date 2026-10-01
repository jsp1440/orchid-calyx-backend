import io
import zipfile

import httpx

from app.application_certification.models import GateStatus
from app.application_certification.service import (
    EDITH_TARGET,
    ApplicationCertificationService,
)


def _json(request: httpx.Request, payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=request)


def test_edith_certification_records_source_sha_and_keeps_runtime_unverified():
    sha = "a" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/commits/main" in url:
            return _json(request, {"sha": sha})
        if f"/git/trees/{sha}" in url:
            return _json(
                request,
                {
                    "tree": [
                        {"path": "src/lib/orchid-continuum.ts", "type": "blob"},
                        {"path": "src/pages/SpeciesDossier.tsx", "type": "blob"},
                    ]
                },
            )
        if "raw.githubusercontent.com" in url and "orchid-continuum.ts" in url:
            return httpx.Response(
                200,
                text=(
                    "const api='https://orchid-continuum-public-api.onrender.com'; "
                    "const dossier='/api/platform/species/'; "
                    "const resolve='/api/platform/federation/resolve-species';"
                ),
                request=request,
            )
        if "raw.githubusercontent.com" in url:
            return httpx.Response(200, text="<a href='/species/x'>Species</a>", request=request)
        if "/api/species/search" in url:
            return _json(request, {"results": [{"taxonomy_id": "101", "canonical_name": "Catasetum macrocarpum"}]})
        if "/images/genus/Catasetum" in url:
            return _json(request, {"images": [{"scientific_name": "Catasetum macrocarpum", "image_url": "https://example.test/a.jpg"}]})
        if "/federation/resolve-species" in url:
            return _json(request, {"status": "resolved", "taxon_id": "101"})
        if "/species/101/dossier" in url:
            return _json(request, {"taxon_id": "101", "accepted_name": "Catasetum macrocarpum"})
        if "/species/101/atlas" in url:
            return _json(request, {"taxon_id": "101", "layers": []})
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = ApplicationCertificationService(client).certify(
        EDITH_TARGET.model_copy(update={"runtime_url": None})
    )

    assert report.source_sha == sha
    assert report.runtime_audit_status == GateStatus.UNVERIFIED
    assert report.publish_ready == "UNVERIFIED"
    gates = {gate.gate_id: gate for gate in report.gates}
    assert gates["source_exact_sha"].status == GateStatus.PASS
    assert gates["oc_source_wiring"].status == GateStatus.PASS
    assert gates["oc_species_search"].status == GateStatus.PASS
    assert gates["oc_genus_media"].status == GateStatus.PASS
    assert gates["calyx_federation"].status == GateStatus.PASS
    assert gates["calyx_species_dossier"].status == GateStatus.PASS
    assert gates["calyx_species_atlas"].status == GateStatus.PASS


def test_client_role_elevation_is_a_release_failure():
    sha = "b" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/commits/main" in url:
            return _json(request, {"sha": sha})
        if f"/git/trees/{sha}" in url:
            return _json(request, {"tree": [{"path": "src/auth.ts", "type": "blob"}]})
        if "raw.githubusercontent.com" in url:
            return httpx.Response(200, text="export const setRole=(role)=>update({role});", request=request)
        if "/federation/resolve-species" in url:
            return _json(request, {"status": "unresolved"})
        return _json(request, {})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = ApplicationCertificationService(client).certify(EDITH_TARGET)
    gates = {gate.gate_id: gate for gate in report.gates}

    assert gates["client_role_security"].status == GateStatus.FAIL
    assert report.security_status == GateStatus.FAIL
    assert report.publish_ready == "NO"


def test_zip_handoff_source_is_auditable():
    sha = "c" * 40
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "src/lib/orchid-continuum.ts",
            (
                "const api='https://orchid-continuum-public-api.onrender.com'; "
                "const dossier='/api/platform/species/'; "
                "const resolve='/api/platform/federation/resolve-species';"
            ),
        )
        archive.writestr("src/App.tsx", "<a href='/science'>Science</a>")
    zip_bytes = payload.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/commits/main" in url:
            return _json(request, {"sha": sha})
        if f"/git/trees/{sha}" in url:
            return _json(
                request,
                {"tree": [{"path": "handoff.zip", "type": "blob"}]},
            )
        if "raw.githubusercontent.com" in url and url.endswith("handoff.zip"):
            return httpx.Response(
                200,
                content=zip_bytes,
                headers={"content-type": "application/zip"},
                request=request,
            )
        if "/api/species/search" in url:
            return _json(request, {})
        if "/images/genus/Catasetum" in url:
            return _json(request, {})
        if "/federation/resolve-species" in url:
            return _json(request, {"status": "unresolved"})
        return _json(request, {})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = ApplicationCertificationService(client).certify(
        EDITH_TARGET.model_copy(update={"runtime_url": None})
    )
    gates = {gate.gate_id: gate for gate in report.gates}

    assert gates["source_application_files"].status == GateStatus.PASS
    assert "packaged source" in gates["source_application_files"].observed_evidence
    assert gates["oc_source_wiring"].status == GateStatus.PASS


def test_runner_proxy_refusal_is_blocked_not_a_target_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("403 Forbidden", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = ApplicationCertificationService(client).certify(EDITH_TARGET)
    by_id = {g.gate_id: g for g in report.gates}

    for gate_id in ("oc_species_search", "oc_genus_media", "calyx_federation", "live_runtime_journeys"):
        assert by_id[gate_id].status == GateStatus.BLOCKED
        assert "runner egress refused" in by_id[gate_id].observed_evidence
    assert report.publish_ready == "NO"


def test_runtime_connect_error_remains_a_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if "deploypad.app" in str(request.url):
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = ApplicationCertificationService(client).certify(EDITH_TARGET)
    runtime = {g.gate_id: g for g in report.gates}["live_runtime_journeys"]
    assert runtime.status == GateStatus.FAIL


def test_certification_run_record_binds_run_repo_sha_and_gate_lists():
    import importlib.util
    from datetime import datetime, timezone
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_edith_bramble_certification.py"
    spec = importlib.util.spec_from_file_location("run_edith_cert", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("403 Forbidden", request=request)

    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(handler))
    ).certify(EDITH_TARGET)
    record = module.build_record(
        report.model_dump(mode="json"), "run-1", "b" * 40, datetime(2026, 10, 1, tzinfo=timezone.utc)
    )
    assert record["certification_run_id"] == "run-1"
    assert record["calyx_repository_sha"] == "b" * 40
    assert record["runtime_tested"] == "https://story-orchids-interactive.deploypad.app/"
    assert "live_runtime_journeys" in record["blocked_gates"]
    assert record["passed_gates"] == []
    assert record["publish_ready"] == "NO"
    summary = module.render_summary(record)
    assert all(line.count("\n") == 0 for line in summary.splitlines())
    assert "| live_runtime_journeys | BLOCKED |" in summary
