import io
import zipfile
from urllib.parse import quote

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
    assert report.runtime_audit_status not in {GateStatus.PASS}
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


def test_fingerprint_ignores_code_fragments_the_minifier_rewrites():
    code_spans = [
        f" && data{i} && !data{i}.found && <p className=" for i in range(40)
    ]
    source = "\n".join(f"const s{i} = '{lit}';" for i, lit in enumerate(_LITERALS)) + "\n" + "\n".join(
        f'x = "{span}"' for span in code_spans
    )
    bundle = "fetch('https://orchid-continuum-public-api.onrender.com/x');" + ";".join(
        f'x("{lit}")' for lit in _LITERALS
    )
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_and_runtime_handler(source, bundle)))
    ).certify(EDITH_TARGET)
    gate = {g.gate_id: g for g in report.gates}["source_runtime_fingerprint"]
    assert gate.status == GateStatus.PASS, gate.observed_evidence
    assert "30/30" in gate.observed_evidence


_LIVE_PROSE = [f"Chronicle {i}: Edith asks what the reader actually sees on the roots today" for i in range(30)]
_OLD_PROSE = [f"Draft {i}: an earlier chapter that the greenhouse story later rewrote entirely" for i in range(30)]


def _zip(files: dict[str, str]) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return payload.getvalue()


def _export(prose: list[str], *, wired: bool, rpc: bool, routes: list[str]) -> bytes:
    lines = [f"const p{i} = '{lit}';" for i, lit in enumerate(prose)]
    if wired:
        lines.append("const a='https://orchid-continuum-public-api.onrender.com';")
        lines.append("const b='https://orchid-calyx-backend.onrender.com';")
        lines.append("get('/api/species/search');get('/images/genus/');")
        lines.append("get('/api/platform/federation/resolve-species');get('/api/platform/species/');")
    lines.append(
        "supabase.rpc('set_user_role', { target: u, new_role: r });" if rpc
        else "supabase.from('profiles').update({ role, updated_at: now }).eq('id', u);"
    )
    lines.extend(f"<Route path=\"{r}\" element={{<X/>}} />" for r in routes)
    return _zip({"src/App.tsx": "\n".join(lines)})


def _multi_archive_handler(archives: dict[str, bytes], bundle: str | None):
    sha = "e" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/commits/main" in url:
            return _json(request, {"sha": sha})
        if f"/git/trees/{sha}" in url:
            return _json(request, {"tree": [{"path": n, "type": "blob"} for n in archives]
                                   + [{"path": "README.md", "type": "blob"}]})
        if "raw.githubusercontent.com" in url:
            for name, data in archives.items():
                if url.endswith(quote(name, safe="/")):
                    return httpx.Response(200, content=data, request=request)
            return httpx.Response(200, text="Authoritative export: story 5.zip", request=request)
        if "/federation/resolve-species" in url:
            return _json(request, {"status": "resolved", "match_state": "accepted_name",
                                   "taxon_id": "101", "explanation": "ok"})
        if "/api/" in url or "/images/" in url:
            return _json(request, {"ok": True})
        if bundle is None and "deploypad.app" in url:
            return httpx.Response(503, request=request)
        if url.endswith("/assets/index-abc.js"):
            return httpx.Response(200, text=bundle, request=request)
        if "deploypad.app" in url:
            return httpx.Response(
                200, text="<html><script type='module' src='/assets/index-abc.js'></script></html>",
                headers={"content-type": "text/html"}, request=request,
            )
        return httpx.Response(404, request=request)

    return handler


def _live_bundle(prose: list[str], routes: list[str]) -> str:
    return (
        FULL_WIRING
        + ";".join(f'x("{lit}")' for lit in prose)
        + ';s.rpc("set_user_role",{target:u,new_role:r});'
        + "".join(f'{{path:"{r}",element:X}},' for r in routes)
    )


ROUTES = ["/chronicle-i", "/chronicle-ii", "/featured-genus", "/species/:taxon"]


def _certify(archives: dict[str, bytes], bundle: str | None):
    return ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_multi_archive_handler(archives, bundle)))
    ).certify(EDITH_TARGET)


def test_source_under_test_is_the_archive_that_matches_the_live_build_not_the_first():
    report = _certify(
        {
            "story 5.zip": _export(_OLD_PROSE, wired=False, rpc=False, routes=ROUTES[:2]),
            "story 9.zip": _export(_LIVE_PROSE, wired=True, rpc=True, routes=ROUTES),
        },
        _live_bundle(_LIVE_PROSE, ROUTES),
    )
    by_id = {g.gate_id: g for g in report.gates}
    selection = by_id["source_candidate_selection"]
    assert selection.status == GateStatus.PASS, selection.observed_evidence
    assert "Source-under-test: story 9.zip" in selection.observed_evidence
    assert "historical provenance only: ['story 5.zip']" in selection.observed_evidence
    assert "routes 4/4" in selection.observed_evidence
    assert by_id["source_runtime_fingerprint"].status == GateStatus.PASS
    assert by_id["client_role_security"].status == GateStatus.PASS
    assert by_id["source_runtime_correspondence"].status == GateStatus.PASS


def test_newer_archive_that_does_not_match_the_live_build_is_not_selected_as_verified():
    report = _certify(
        {
            "story 5.zip": _export(_OLD_PROSE, wired=False, rpc=False, routes=ROUTES),
            "story 9.zip": _export(_OLD_PROSE[:15] + _LIVE_PROSE[:15], wired=True, rpc=True, routes=ROUTES),
        },
        _live_bundle(_LIVE_PROSE, ROUTES),
    )
    selection = {g.gate_id: g for g in report.gates}["source_candidate_selection"]
    assert selection.status == GateStatus.FAIL
    assert "0 candidate(s) verified" in selection.blocker
    assert report.publish_ready == "NO"


def test_matching_prose_with_a_divergent_role_model_is_not_verified():
    report = _certify(
        {"story 9.zip": _export(_LIVE_PROSE, wired=True, rpc=False, routes=ROUTES)},
        _live_bundle(_LIVE_PROSE, ROUTES),
    )
    selection = {g.gate_id: g for g in report.gates}["source_candidate_selection"]
    assert selection.status == GateStatus.FAIL
    assert "role_rpc_agree=False" in selection.observed_evidence


def test_no_live_bundle_means_no_source_is_tied_to_the_runtime():
    report = _certify(
        {"story 9.zip": _export(_LIVE_PROSE, wired=True, rpc=True, routes=ROUTES)},
        None,
    )
    selection = {g.gate_id: g for g in report.gates}["source_candidate_selection"]
    assert selection.status == GateStatus.BLOCKED
    assert report.publish_ready == "NO"


def test_matching_prose_with_a_divergent_route_set_is_not_verified():
    report = _certify(
        {"story 9.zip": _export(_LIVE_PROSE, wired=True, rpc=True, routes=ROUTES + ["/grimoire", "/kitchen"])},
        _live_bundle(_LIVE_PROSE, ROUTES),
    )
    selection = {g.gate_id: g for g in report.gates}["source_candidate_selection"]
    assert selection.status == GateStatus.FAIL
    assert "routes 4/6" in selection.observed_evidence


def _oc_wiring_gate(source_ts: str):
    report = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_source_handler(source_ts)))
    ).certify(EDITH_TARGET)
    return {g.gate_id: g for g in report.gates}["oc_source_wiring"]


_WIRED_SOURCE = (
    "const a='https://orchid-continuum-public-api.onrender.com';"
    "const r='/api/platform/federation/resolve-species';const d='/api/platform/species/';\n"
)


def test_pending_type_union_is_not_a_pending_connection():
    source = _WIRED_SOURCE + (
        "export const ocConnection: { status: 'pending' | 'live'; adapter: OrchidContinuumAdapter | null } = {\n"
        "  status: 'live',\n  adapter: liveAdapter,\n};"
    )
    assert _oc_wiring_gate(source).status == GateStatus.PASS


def test_pending_null_assignment_is_still_detected():
    source = _WIRED_SOURCE + "export const ocConnection = {\n  status: 'pending',\n  adapter: null,\n};"
    gate = _oc_wiring_gate(source)
    assert gate.status == GateStatus.PARTIAL
    assert "adapter assigned null" in gate.observed_evidence
    assert "status assigned 'pending'" in gate.observed_evidence


def test_required_external_gates_are_unverified_until_executed():
    report = _certify(
        {"story 9.zip": _export(_LIVE_PROSE, wired=True, rpc=True, routes=ROUTES)},
        _live_bundle(_LIVE_PROSE, ROUTES),
    )
    by_id = {g.gate_id: g for g in report.gates}
    for gate_id in ("app_lockfile_sync", "app_build", "app_lint", "app_typecheck",
                    "compiled_asset_correspondence", "journey_suite", "accessibility_suite"):
        assert by_id[gate_id].status == GateStatus.UNVERIFIED
    assert report.accessibility_status == GateStatus.UNVERIFIED
    assert report.publish_ready != "YES"
    assert report.source_under_test == "story 9.zip"


def _all_green_evidence() -> list:
    from app.application_certification.models import CertificationGate

    ids = ["app_lockfile_sync", "app_build", "app_lint", "app_typecheck", "compiled_asset_correspondence",
           "journey_homepage", "accessibility_homepage_desktop"]
    return [CertificationGate(gate_id=i, status=GateStatus.PASS,
                              evidence_type="browser" if i.startswith(("journey_", "accessibility_")) else "test",
                              observed_evidence=f"{i} executed") for i in ids]


def test_finalize_replaces_placeholders_and_recomputes_without_inventing():
    service = ApplicationCertificationService(
        httpx.Client(transport=httpx.MockTransport(_multi_archive_handler(
            {"story 9.zip": _export(_LIVE_PROSE, wired=True, rpc=True, routes=ROUTES)},
            _live_bundle(_LIVE_PROSE, ROUTES),
        )))
    )
    report = service.certify(EDITH_TARGET)
    final = ApplicationCertificationService(httpx.Client()).finalize(report, _all_green_evidence())
    by_id = {g.gate_id: g for g in final.gates}
    assert "journey_suite" not in by_id and "accessibility_suite" not in by_id
    assert by_id["app_build"].observed_evidence == "app_build executed"
    assert final.accessibility_status == GateStatus.PASS
    assert final.source_under_test == "story 9.zip"
    # YES iff every aggregate is PASS: evidence cannot lift a gate it did not cover.
    aggregates = [final.source_audit_status, final.runtime_audit_status, final.scientific_provenance_status,
                  final.security_status, final.media_status, final.accessibility_status]
    assert (final.publish_ready == "YES") == all(a == GateStatus.PASS for a in aggregates)


def test_finalize_with_a_failing_journey_cannot_be_publish_ready():
    from app.application_certification.models import CertificationGate

    report = _certify(
        {"story 9.zip": _export(_LIVE_PROSE, wired=True, rpc=True, routes=ROUTES)},
        _live_bundle(_LIVE_PROSE, ROUTES),
    )
    evidence = _all_green_evidence() + [CertificationGate(
        gate_id="journey_chronicle_ii_chapters", status=GateStatus.FAIL, evidence_type="browser",
        observed_evidence="4 of 5 chapters rendered")]
    final = ApplicationCertificationService(httpx.Client()).finalize(report, evidence)
    assert final.runtime_audit_status == GateStatus.FAIL
    assert final.publish_ready == "NO"


def test_finalize_cli_merges_evidence_files_and_keeps_the_run_identity(tmp_path):
    import importlib.util
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_edith_bramble_certification.py"
    spec = importlib.util.spec_from_file_location("run_edith_cert_finalize", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = _certify(
        {"story 9.zip": _export(_LIVE_PROSE, wired=True, rpc=True, routes=ROUTES)},
        _live_bundle(_LIVE_PROSE, ROUTES),
    )
    record_path = tmp_path / "run.json"
    record_path.write_text(json.dumps(module.build_record(
        report.model_dump(mode="json"), "run-9", "f" * 40, datetime(2026, 10, 1, tzinfo=timezone.utc)
    )))
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "app-checks.json").write_text(json.dumps([
        {"gate_id": "app_build", "status": "FAIL", "evidence_type": "test",
         "observed_evidence": "vite build exited 1"},
    ]))

    assert module.main(["--finalize", str(record_path), "--evidence-dir", str(evidence)]) == 0
    merged = json.loads(record_path.read_text())
    assert merged["certification_run_id"] == "run-9"
    assert merged["calyx_repository_sha"] == "f" * 40
    assert merged["evidence_files"] == ["app-checks.json"]
    assert "app_build" in merged["failed_gates"]
    assert merged["report"]["source_under_test"] == "story 9.zip"
    assert merged["publish_ready"] == "NO"


def _diverged_report():
    # Static selection fails on prose (tree-shaken content), every other signal agrees.
    return _certify(
        {"story 9.zip": _export(_LIVE_PROSE + _OLD_PROSE, wired=True, rpc=True, routes=ROUTES)},
        _live_bundle(_LIVE_PROSE, ROUTES),
    )


def _compiled(status: str, evidence: str):
    from app.application_certification.models import CertificationGate

    return CertificationGate(gate_id="compiled_asset_correspondence", status=status,
                             evidence_type="deployment", observed_evidence=evidence)


def test_byte_identical_build_supersedes_static_prose_heuristics():
    report = _diverged_report()
    before = {g.gate_id: g for g in report.gates}
    assert before["source_candidate_selection"].status == GateStatus.FAIL
    final = ApplicationCertificationService(httpx.Client()).finalize(report, [_compiled(
        "PASS", "Live scripts {...}; identical sha256: ['964a97']. Prose literals: ...")])
    by_id = {g.gate_id: g for g in final.gates}
    for gate_id in ("source_candidate_selection", "source_runtime_fingerprint"):
        assert by_id[gate_id].status == GateStatus.PASS
        assert "SUPERSEDED" in by_id[gate_id].observed_evidence
        # The original static evidence is preserved verbatim, not replaced.
        assert by_id[gate_id].observed_evidence.startswith(before[gate_id].observed_evidence)


def test_prose_only_compiled_match_does_not_supersede():
    final = ApplicationCertificationService(httpx.Client()).finalize(_diverged_report(), [_compiled(
        "PASS", "identical sha256: none. Prose literals: live covered 99.5%, built covered 99.4%")])
    assert {g.gate_id: g for g in final.gates}["source_candidate_selection"].status == GateStatus.FAIL


def test_failed_compiled_correspondence_does_not_supersede():
    final = ApplicationCertificationService(httpx.Client()).finalize(_diverged_report(), [_compiled(
        "FAIL", "identical sha256: ['abc'] but other scripts differ")])
    assert {g.gate_id: g for g in final.gates}["source_candidate_selection"].status == GateStatus.FAIL
