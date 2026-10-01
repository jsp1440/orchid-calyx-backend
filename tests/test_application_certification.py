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


FULL_WIRING = (
    "const oc='https://orchid-continuum-public-api.onrender.com';"
    "const calyx='https://orchid-calyx-backend.onrender.com';"
    "get(oc+'/api/species/search');get(oc+'/images/genus/'+g);"
    "get(calyx+'/api/platform/federation/resolve-species');get(calyx+'/api/platform/species/'+t);"
)


def _live_handler(federation: dict, bundle_js: str):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.github.com" in url or "raw.githubusercontent.com" in url:
            return httpx.Response(404, request=request)
        if "/federation/resolve-species" in url:
            return _json(request, federation)
        if "/species/101/" in url or "/api/species/search" in url or "/images/genus/" in url:
            return _json(request, {"ok": True})
        if url.endswith("/assets/index-abc.js"):
            return httpx.Response(200, text=bundle_js, request=request)
        if "deploypad.app" in url:
            return httpx.Response(
                200,
                text="<html><script type='module' src='/assets/index-abc.js'></script>"
                "<script src='https://cdn.example.test/x.js'></script></html>",
                headers={"content-type": "text/html"},
                request=request,
            )
        return httpx.Response(404, request=request)

    return handler


def test_federation_http_200_without_resolution_is_a_failure_with_resolver_evidence():
    handler = _live_handler(
        {"status": "unresolved", "match_state": "none", "taxon_id": None,
         "explanation": "No canonical taxon matched."},
        "",
    )
    report = ApplicationCertificationService(httpx.Client(transport=httpx.MockTransport(handler))).certify(EDITH_TARGET)
    by_id = {g.gate_id: g for g in report.gates}
    assert by_id["calyx_federation"].status == GateStatus.FAIL
    assert "status='unresolved'" in by_id["calyx_federation"].observed_evidence
    assert "No canonical taxon matched." in by_id["calyx_federation"].observed_evidence
    assert by_id["calyx_species_dossier"].status == GateStatus.BLOCKED


def test_deployed_bundle_with_canonical_wiring_passes_runtime_oc_gate():
    handler = _live_handler(
        {"status": "resolved", "match_state": "accepted_name", "taxon_id": "101", "explanation": "ok"},
        FULL_WIRING,
    )
    report = ApplicationCertificationService(httpx.Client(transport=httpx.MockTransport(handler))).certify(EDITH_TARGET)
    gate = {g.gate_id: g for g in report.gates}["runtime_oc_wiring"]
    assert gate.status == GateStatus.PASS
    assert "index-abc.js" in gate.observed_evidence
    assert "cdn.example.test" not in gate.observed_evidence


def test_deployed_bundle_saying_integration_not_live_is_not_a_pass():
    handler = _live_handler(
        {"status": "resolved", "match_state": "accepted_name", "taxon_id": "101", "explanation": "ok"},
        "const a='orchid-continuum-public-api.onrender.com';"
        "const copy='The Orchid Continuum / Calyx integration is not live.'",
    )
    report = ApplicationCertificationService(httpx.Client(transport=httpx.MockTransport(handler))).certify(EDITH_TARGET)
    by_id = {g.gate_id: g for g in report.gates}
    assert by_id["runtime_oc_wiring"].status == GateStatus.PARTIAL
    assert report.runtime_audit_status == GateStatus.PARTIAL
    assert report.publish_ready != "YES"


def test_deployed_bundle_without_any_oc_wiring_fails():
    handler = _live_handler(
        {"status": "resolved", "match_state": "accepted_name", "taxon_id": "101", "explanation": "ok"},
        "const dataSource = staticDataSource;",
    )
    report = ApplicationCertificationService(httpx.Client(transport=httpx.MockTransport(handler))).certify(EDITH_TARGET)
    assert {g.gate_id: g for g in report.gates}["runtime_oc_wiring"].status == GateStatus.FAIL
    assert report.runtime_audit_status == GateStatus.FAIL


def test_source_inspection_reads_application_code_before_docs():
    from app.application_certification.service import _inspection_priority

    ordered = sorted(["README.md", "a.json", "src/lib/orchid-continuum.ts", "src/App.tsx"], key=_inspection_priority)
    assert ordered[:2] == ["src/App.tsx", "src/lib/orchid-continuum.ts"]


def _source_and_runtime_handler(source_ts: str, bundle_js: str):
    sha = "c" * 40
    live = _live_handler(
        {"status": "resolved", "match_state": "accepted_name", "taxon_id": "101", "explanation": "ok"},
        bundle_js,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/commits/main" in url:
            return _json(request, {"sha": sha})
        if f"/git/trees/{sha}" in url:
            return _json(request, {"tree": [{"path": "src/lib/orchid-continuum.ts", "type": "blob"}]})
        if "raw.githubusercontent.com" in url:
            return httpx.Response(200, text=source_ts, request=request)
        return live(request)

    return handler


def test_deployed_client_role_self_update_fails_runtime_security():
    bundle = (
        "fetch('https://orchid-continuum-public-api.onrender.com/api/species/search');"
        'await s.from("profiles").update({role:e,updated_at:new Date().toISOString()}).eq("id",u)'
    )
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_and_runtime_handler("const x=1;", bundle)))
    ).certify(EDITH_TARGET)
    gate = {g.gate_id: g for g in report.gates}["runtime_role_security"]
    assert gate.status == GateStatus.FAIL
    assert report.security_status == GateStatus.FAIL


def test_deployed_role_rpc_without_client_write_passes_runtime_security():
    bundle = (
        "fetch('https://orchid-continuum-public-api.onrender.com/api/species/search');"
        'await s.rpc("set_user_role",{target:u,new_role:e})'
    )
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_and_runtime_handler("const x=1;", bundle)))
    ).certify(EDITH_TARGET)
    assert {g.gate_id: g for g in report.gates}["runtime_role_security"].status == GateStatus.PASS


def test_stale_source_handoff_is_a_correspondence_failure():
    bundle = "fetch('https://orchid-continuum-public-api.onrender.com/api/species/search')"
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(
            _source_and_runtime_handler("export const ocConnection = { adapter: null };", bundle)
        ))
    ).certify(EDITH_TARGET)
    by_id = {g.gate_id: g for g in report.gates}
    assert by_id["source_runtime_correspondence"].status == GateStatus.FAIL
    assert report.source_audit_status == GateStatus.FAIL
    assert report.publish_ready == "NO"


def test_matching_source_and_runtime_correspond():
    source = (
        "const api='https://orchid-continuum-public-api.onrender.com';"
        "const r='/api/platform/federation/resolve-species';"
    )
    bundle = "fetch('https://orchid-continuum-public-api.onrender.com/api/species/search')"
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_and_runtime_handler(source, bundle)))
    ).certify(EDITH_TARGET)
    assert {g.gate_id: g for g in report.gates}["source_runtime_correspondence"].status == GateStatus.PASS


def test_unavailable_source_makes_no_correspondence_claim():
    handler = _live_handler(
        {"status": "resolved", "match_state": "accepted_name", "taxon_id": "101", "explanation": "ok"},
        "fetch('https://orchid-continuum-public-api.onrender.com/x')",
    )
    report = ApplicationCertificationService(httpx.Client(transport=httpx.MockTransport(handler))).certify(EDITH_TARGET)
    assert "source_runtime_correspondence" not in {g.gate_id for g in report.gates}


def test_domain_names_alone_are_not_canonical_runtime_wiring():
    handler = _live_handler(
        {"status": "resolved", "match_state": "accepted_name", "taxon_id": "101", "explanation": "ok"},
        "// orchid-continuum-public-api.onrender.com orchid-calyx-backend.onrender.com",
    )
    report = ApplicationCertificationService(httpx.Client(transport=httpx.MockTransport(handler))).certify(EDITH_TARGET)
    assert {g.gate_id: g for g in report.gates}["runtime_oc_wiring"].status == GateStatus.PARTIAL


def _source_handler(source_ts: str):
    sha = "d" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/commits/main" in url:
            return _json(request, {"sha": sha})
        if f"/git/trees/{sha}" in url:
            return _json(request, {"tree": [{"path": "src/contexts/AuthContext.tsx", "type": "blob"}]})
        if "raw.githubusercontent.com" in url:
            return httpx.Response(200, text=source_ts, request=request)
        return httpx.Response(404, request=request)

    return handler


def _role_gate(source_ts: str):
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_handler(source_ts)))
    ).certify(EDITH_TARGET)
    return {g.gate_id: g for g in report.gates}["client_role_security"]


def test_set_role_delegating_to_server_rpc_is_not_a_client_role_write():
    source = (
        "const setRole = useCallback(async (userId, role) => {"
        " const { error } = await supabase.rpc('set_user_role', { target: userId, new_role: role }); });"
        "\nonClick={async () => { await setRole(user.id, 'member'); }}"
    )
    assert _role_gate(source).status == GateStatus.PASS


def test_client_profile_role_update_is_a_role_write():
    source = (
        "const setRole = useCallback(async (role) => { await supabase.from('profiles')"
        "\n  .update({ role, updated_at: new Date().toISOString() }).eq('id', id); });"
    )
    assert _role_gate(source).status == GateStatus.FAIL


def test_signup_metadata_role_flag_is_a_role_write():
    source = "options: { data: { display_name: displayName, role: asEditor ? 'editor' : 'member' } }"
    assert _role_gate(source).status == GateStatus.FAIL


def test_ambiguous_taxonomy_is_blocked_with_candidate_provenance_and_no_selection():
    dossier_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/federation/resolve-species" in url:
            return _json(request, {
                "status": "ambiguous", "match_state": "none", "taxon_id": None,
                "candidates": [
                    {"taxon_id": "46599", "accepted_name": "Catasetum macrocarpum", "match_state": "accepted_name"},
                    {"taxon_id": "27265", "accepted_name": "Catasetum macrocarpum", "match_state": "accepted_name"},
                ],
                "explanation": "Multiple canonical taxa match the supplied identifier; human selection is required.",
            })
        if "/dossier" in url:
            dossier_calls.append(url)
            taxon = url.split("/species/")[1].split("/")[0]
            return _json(request, {
                "taxon_id": taxon,
                "identity": {"full_scientific_name": f"Catasetum macrocarpum Author{taxon}",
                             "authorship": f"Author{taxon}", "taxonomic_status": "accepted", "rank": "species"},
                "provenance": [{"source_name": f"Source{taxon}"}],
            })
        if "/atlas" in url:
            raise AssertionError("atlas must not be probed for an unselected candidate")
        return httpx.Response(404, request=request)

    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(handler))
    ).certify(EDITH_TARGET.model_copy(update={"runtime_url": None}))
    by_id = {g.gate_id: g for g in report.gates}
    federation = by_id["calyx_federation"]
    assert federation.status == GateStatus.BLOCKED
    for taxon in ("46599", "27265"):
        assert taxon in federation.blocker
        assert f"Author{taxon}" in federation.observed_evidence
        assert f"Source{taxon}" in federation.observed_evidence
    assert len(dossier_calls) == 2
    assert by_id["calyx_species_dossier"].status == GateStatus.BLOCKED
    assert by_id["calyx_species_atlas"].status == GateStatus.BLOCKED
    assert report.publish_ready == "NO"


_LITERALS = [f"Chapter {i}: the greenhouse lesson about observing roots and light carefully" for i in range(30)]


def _fingerprint_report(bundle_literals: list[str]):
    source = "\n".join(f"const s{i} = '{lit}';" for i, lit in enumerate(_LITERALS))
    bundle = (
        "fetch('https://orchid-continuum-public-api.onrender.com/api/species/search');"
        + ";".join(f'x("{lit}")' for lit in bundle_literals)
    )
    return ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_and_runtime_handler(source, bundle)))
    ).certify(EDITH_TARGET)


def test_identical_content_fingerprints_as_the_deployed_build():
    gate = {g.gate_id: g for g in _fingerprint_report(_LITERALS).gates}["source_runtime_fingerprint"]
    assert gate.status == GateStatus.PASS
    assert "30/30" in gate.observed_evidence
    assert "sha256=" in gate.observed_evidence
    assert "index-abc.js" in gate.observed_evidence


def test_diverged_content_is_not_certified_as_equivalent():
    report = _fingerprint_report(_LITERALS[:20])
    gate = {g.gate_id: g for g in report.gates}["source_runtime_fingerprint"]
    assert gate.status == GateStatus.FAIL
    assert "20/30" in gate.observed_evidence
    assert report.publish_ready == "NO"


def test_unavailable_runtime_makes_no_fingerprint_claim():
    source = "\n".join(f"const s{i} = '{lit}';" for i, lit in enumerate(_LITERALS))
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_handler(source)))
    ).certify(EDITH_TARGET)
    assert "source_runtime_fingerprint" not in {g.gate_id for g in report.gates}


def test_fingerprint_reads_minifier_unicode_escapes():
    literal = "Edith’s greenhouse — an observation-first lesson about roots and light"
    literals = [literal] + _LITERALS[:25]
    source = "\n".join(f"const s{i} = \"{lit}\";" for i, lit in enumerate(literals))
    escaped = literal.encode("ascii", "backslashreplace").decode("ascii")
    bundle = "fetch('https://orchid-continuum-public-api.onrender.com/x');" + ";".join(
        f'x("{lit}")' for lit in [escaped] + _LITERALS[:25]
    )
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_and_runtime_handler(source, bundle)))
    ).certify(EDITH_TARGET)
    gate = {g.gate_id: g for g in report.gates}["source_runtime_fingerprint"]
    assert gate.status == GateStatus.PASS, gate.observed_evidence
