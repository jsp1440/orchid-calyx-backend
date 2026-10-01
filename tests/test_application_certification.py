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
