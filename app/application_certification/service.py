from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from urllib.parse import quote

import httpx

from .models import (
    CertificationGate,
    CertificationReport,
    CertificationTarget,
    GateStatus,
)

# Certification implementation issue: #1717
GITHUB_API = "https://api.github.com"
OC_PUBLIC_API = "https://orchid-continuum-public-api.onrender.com"
CALYX_API = "https://orchid-calyx-backend.onrender.com"

TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".html", ".css",
    ".yml", ".yaml", ".toml", ".env", ".txt",
}

EDITH_TARGET = CertificationTarget(
    application_id="edith-bramble-famous",
    application_name="Edith Bramble Chronicles / Famous.ai",
    source_repository="jsp1440/edith-bramble-famous-sync",
    source_ref="main",
    runtime_url="https://story-orchids-interactive.deploypad.app",
)


class ApplicationCertificationService:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=12.0,
            follow_redirects=True,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "orchid-continuum-calyx"},
        )

    def certify(self, target: CertificationTarget) -> CertificationReport:
        gates: list[CertificationGate] = []
        sha, paths, source_text = self._source_inventory(target, gates)
        self._source_contract_checks(paths, source_text, gates)
        self._backend_probes(gates)
        self._runtime_gate(target, gates)
        return self._report(target, sha, gates)

    def _source_inventory(
        self,
        target: CertificationTarget,
        gates: list[CertificationGate],
    ) -> tuple[str | None, list[str], str]:
        owner, repo = self._split_repo(target.source_repository)
        try:
            commit = self._get_json(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{target.source_ref}")
            sha = str(commit.get("sha") or "") or None
            if not sha:
                raise ValueError("commit SHA missing")
            tree = self._get_json(f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{sha}?recursive=1")
            entries = tree.get("tree") if isinstance(tree, dict) else None
            paths = [
                str(item.get("path"))
                for item in (entries or [])
                if isinstance(item, dict) and item.get("type") == "blob" and item.get("path")
            ]
            gates.append(CertificationGate(
                gate_id="source_exact_sha",
                status=GateStatus.PASS,
                evidence_type="source",
                observed_evidence=f"Resolved {target.source_repository}@{target.source_ref} to {sha}.",
            ))
            texts: list[str] = []
            inspected = 0
            for path in paths:
                if inspected >= 120:
                    break
                lower = path.lower()
                if not any(lower.endswith(sfx) for sfx in TEXT_SUFFIXES):
                    continue
                if any(part in lower for part in ("node_modules/", "dist/", "build/", ".min.js")):
                    continue
                raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}"
                try:
                    response = self.client.get(raw)
                    if response.status_code == 200:
                        texts.append(f"\n--- {path} ---\n{response.text[:100000]}")
                        inspected += 1
                except httpx.HTTPError:
                    continue
            source_text = "".join(texts)
            source_files = [p for p in paths if p.lower().endswith((".ts", ".tsx", ".js", ".jsx", ".py"))]
            if source_files:
                gates.append(CertificationGate(
                    gate_id="source_application_files",
                    status=GateStatus.PASS,
                    evidence_type="source",
                    observed_evidence=f"Found {len(source_files)} source files; inspected up to {inspected} text files.",
                ))
            else:
                archives = [p for p in paths if p.lower().endswith(".zip")]
                archive_paths: list[str] = []
                archive_text = ""
                if archives:
                    archive_paths, archive_text = self._inspect_zip_source(
                        owner, repo, sha, archives[0]
                    )
                archive_source_files = [
                    p for p in archive_paths
                    if p.lower().endswith((".ts", ".tsx", ".js", ".jsx", ".py"))
                ]
                if archive_source_files:
                    paths = archive_paths
                    source_text = archive_text
                    gates.append(CertificationGate(
                        gate_id="source_application_files",
                        status=GateStatus.PASS,
                        evidence_type="source",
                        observed_evidence=(
                            f"Audited packaged source from {archives[0]}: "
                            f"{len(archive_source_files)} source files found."
                        ),
                    ))
                else:
                    gates.append(CertificationGate(
                        gate_id="source_application_files",
                        status=GateStatus.PARTIAL if archives else GateStatus.FAIL,
                        evidence_type="source",
                        observed_evidence=(
                            "Repository contains a ZIP handoff, but no auditable application source "
                            "could be extracted from it."
                            if archives else
                            "Repository exposes no directly auditable application source files."
                        ),
                        blocker="Canonical source is not available to the certification target.",
                        smallest_next_action=(
                            "Export/sync the current Famous.ai source or provide a readable ZIP handoff."
                        ),
                    ))
            return sha, paths, source_text
        except (httpx.HTTPError, ValueError) as exc:
            gates.append(CertificationGate(
                gate_id="source_exact_sha",
                status=GateStatus.BLOCKED,
                evidence_type="source",
                observed_evidence="Could not resolve the configured GitHub source target.",
                blocker=f"{type(exc).__name__}: {exc}",
                smallest_next_action="Restore GitHub reachability or correct the source repository/ref.",
            ))
            return None, [], ""

    def _inspect_zip_source(
        self,
        owner: str,
        repo: str,
        sha: str,
        archive_path: str,
    ) -> tuple[list[str], str]:
        encoded_path = quote(archive_path, safe="/")
        raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{encoded_path}"
        try:
            response = self.client.get(raw)
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
                texts: list[str] = []
                inspected = 0
                for name in names:
                    if inspected >= 120:
                        break
                    lower = name.lower()
                    if not any(lower.endswith(sfx) for sfx in TEXT_SUFFIXES):
                        continue
                    if any(part in lower for part in ("node_modules/", "dist/", "build/", ".min.js")):
                        continue
                    try:
                        payload = archive.read(name)
                        decoded = payload.decode("utf-8")
                    except (KeyError, UnicodeDecodeError):
                        continue
                    texts.append(f"\n--- {name} ---\n{decoded[:100000]}")
                    inspected += 1
                return names, "".join(texts)
        except (httpx.HTTPError, zipfile.BadZipFile):
            return [], ""

    def _source_contract_checks(
        self, paths: list[str], source_text: str, gates: list[CertificationGate]
    ) -> None:
        lower = source_text.lower()
        if not source_text:
            for gate_id, label in (
                ("oc_source_wiring", "Orchid Continuum source wiring"),
                ("client_role_security", "client-side role security"),
                ("information_architecture", "information architecture"),
            ):
                gates.append(CertificationGate(
                    gate_id=gate_id,
                    status=GateStatus.UNVERIFIED,
                    evidence_type="source",
                    observed_evidence=f"{label} cannot be verified without the current application source tree.",
                    blocker="Current source tree unavailable to the certification target.",
                ))
            return

        oc_markers = (
            "orchid-continuum-public-api.onrender.com",
            "vite_orchid_continuum_api_base_url",
            "/api/platform/species/",
            "/api/platform/federation/resolve-species",
        )
        oc_hits = [marker for marker in oc_markers if marker in lower]
        pending_hits = [
            marker for marker in ("adapter = null", "status: 'pending'", 'status = "pending"', "continuum_base_url = null")
            if marker in lower
        ]
        status = GateStatus.PASS if len(oc_hits) >= 2 and not pending_hits else GateStatus.PARTIAL
        gates.append(CertificationGate(
            gate_id="oc_source_wiring",
            status=status,
            evidence_type="source",
            observed_evidence=f"OC wiring markers={oc_hits}; pending/null markers={pending_hits}.",
            blocker="Pending/null OC adapter markers remain." if pending_hits else None,
            smallest_next_action="Remove pending/null OC wiring and use canonical OC adapters." if pending_hits else None,
        ))

        privilege_patterns = [
            r"setrole\s*\(",
            r"role\s*:\s*['\"](?:editor|admin)['\"]",
            r"update\([^\n]{0,200}role",
        ]
        risky = [p for p in privilege_patterns if re.search(p, lower, re.IGNORECASE)]
        gates.append(CertificationGate(
            gate_id="client_role_security",
            status=GateStatus.FAIL if risky else GateStatus.PASS,
            evidence_type="source",
            observed_evidence=(
                f"Potential client privilege-elevation patterns detected: {risky}."
                if risky else
                "No configured client privilege-elevation pattern was detected in inspected source text."
            ),
            blocker="Client code appears capable of requesting or mutating privileged roles." if risky else None,
            smallest_next_action="Move privileged role assignment behind server-side owner/admin authorization." if risky else None,
        ))

        route_like = len(re.findall(r"(?:path|to|href)\s*=\s*['\"]/[^'\"]+", source_text, re.IGNORECASE))
        nav_terms = sum(lower.count(term) for term in (
            "chronicle", "greenhouse", "culture library", "featured genus", "species dossier",
            "science", "notebook", "journal", "grimoire", "potting bench", "plant doctor",
            "herbarium", "plates", "watch & listen", "coloring", "go deeper",
        ))
        ia_status = GateStatus.PARTIAL if route_like >= 12 or nav_terms >= 18 else GateStatus.PASS
        gates.append(CertificationGate(
            gate_id="information_architecture",
            status=ia_status,
            evidence_type="source",
            observed_evidence=f"Observed route-like links={route_like}; educational/navigation concept mentions={nav_terms}.",
            blocker="Large parallel navigation surface requires educational IA review." if ia_status == GateStatus.PARTIAL else None,
            smallest_next_action=(
                "Produce a canonical 3–5 destination navigation model and contextual cross-link map."
                if ia_status == GateStatus.PARTIAL else None
            ),
        ))

    def _backend_probes(self, gates: list[CertificationGate]) -> None:
        probes = (
            ("oc_species_search", f"{OC_PUBLIC_API}/api/species/search?q=Catasetum&limit=1"),
            ("oc_genus_media", f"{OC_PUBLIC_API}/images/genus/Catasetum?limit=1"),
            ("calyx_federation", f"{CALYX_API}/api/platform/federation/resolve-species?name=Catasetum%20macrocarpum"),
        )
        resolved_taxon: str | None = None
        for gate_id, url in probes:
            status, detail, data = self._probe(url)
            gates.append(CertificationGate(
                gate_id=gate_id,
                status=status,
                evidence_type="api",
                observed_evidence=detail,
                blocker=None if status == GateStatus.PASS else detail,
                smallest_next_action=None if status == GateStatus.PASS else "Repair endpoint availability/CORS/contract response and re-run certification.",
            ))
            if gate_id == "calyx_federation" and isinstance(data, dict):
                taxon = data.get("taxon_id")
                if taxon:
                    resolved_taxon = str(taxon)

        if resolved_taxon:
            for suffix, gate_id in (("dossier", "calyx_species_dossier"), ("atlas", "calyx_species_atlas")):
                url = f"{CALYX_API}/api/platform/species/{resolved_taxon}/{suffix}"
                status, detail, _ = self._probe(url)
                gates.append(CertificationGate(
                    gate_id=gate_id,
                    status=status,
                    evidence_type="api",
                    observed_evidence=detail,
                    blocker=None if status == GateStatus.PASS else detail,
                    smallest_next_action=None if status == GateStatus.PASS else f"Repair {suffix} endpoint and re-run certification.",
                ))
        else:
            for gate_id in ("calyx_species_dossier", "calyx_species_atlas"):
                gates.append(CertificationGate(
                    gate_id=gate_id,
                    status=GateStatus.BLOCKED,
                    evidence_type="api",
                    observed_evidence="Canonical taxon ID was not resolved, so the dependent endpoint was not guessed.",
                    blocker="Federation resolver did not provide a taxon_id.",
                    smallest_next_action="Restore federation resolution, then re-run dependent probes.",
                ))

    def _runtime_gate(self, target: CertificationTarget, gates: list[CertificationGate]) -> None:
        """Probe runtime reachability only; browser journey certification is a later gate."""
        runtime = target.runtime_url or target.preview_url
        if runtime is None:
            gates.append(CertificationGate(
                gate_id="live_runtime_journeys",
                status=GateStatus.UNVERIFIED,
                evidence_type="browser",
                observed_evidence="No Famous.ai preview/published URL is registered.",
                blocker="Live runtime target is missing.",
                smallest_next_action="Register the current Famous.ai preview or published URL; source/API audits continue independently.",
            ))
            return
        status, detail, _ = self._probe(str(runtime))
        gates.append(CertificationGate(
            gate_id="live_runtime_journeys",
            status=status if status in {GateStatus.PASS, GateStatus.BLOCKED} else GateStatus.FAIL,
            evidence_type="deployment",
            observed_evidence=detail,
            blocker=None if status == GateStatus.PASS else detail,
            smallest_next_action=None if status == GateStatus.PASS else "Repair live deployment reachability, then execute browser journey gates.",
        ))

    def _report(
        self,
        target: CertificationTarget,
        sha: str | None,
        gates: list[CertificationGate],
    ) -> CertificationReport:
        by_id = {g.gate_id: g for g in gates}
        source_status = self._aggregate(gates, evidence_types={"source", "test", "configuration"})
        runtime_status = by_id.get("live_runtime_journeys", CertificationGate(
            gate_id="missing", status=GateStatus.UNVERIFIED, evidence_type="browser", observed_evidence="missing"
        )).status
        security = by_id.get("client_role_security")
        security_status = security.status if security else GateStatus.UNVERIFIED
        media_status = self._aggregate([g for g in gates if g.gate_id in {"oc_genus_media", "oc_source_wiring"}])
        scientific_status = self._aggregate([g for g in gates if g.gate_id in {
            "oc_source_wiring", "oc_species_search", "calyx_federation", "calyx_species_dossier", "calyx_species_atlas"
        }])
        accessibility = GateStatus.UNVERIFIED
        blockers = [g.blocker for g in gates if g.blocker and g.status in {
            GateStatus.FAIL, GateStatus.BLOCKED, GateStatus.UNVERIFIED, GateStatus.PARTIAL
        }]
        required = [
            source_status, runtime_status, scientific_status, security_status, media_status, accessibility
        ]
        if any(s in {GateStatus.FAIL, GateStatus.BLOCKED} for s in required):
            publish_ready = "NO"
        elif any(s in {GateStatus.UNVERIFIED, GateStatus.PARTIAL} for s in required):
            publish_ready = "UNVERIFIED"
        else:
            publish_ready = "YES"
        return CertificationReport(
            application_id=target.application_id,
            application_name=target.application_name,
            source_repository=target.source_repository,
            source_ref=target.source_ref,
            source_sha=sha,
            runtime_url=str(target.runtime_url or target.preview_url) if (target.runtime_url or target.preview_url) else None,
            policy_version=target.policy_version,
            gates=gates,
            source_audit_status=source_status,
            runtime_audit_status=runtime_status,
            scientific_provenance_status=scientific_status,
            security_status=security_status,
            media_status=media_status,
            accessibility_status=accessibility,
            publish_ready=publish_ready,
            exact_blockers=[b for b in blockers if b],
        )

    @staticmethod
    def _aggregate(
        gates: list[CertificationGate], evidence_types: set[str] | None = None
    ) -> GateStatus:
        selected = [g for g in gates if evidence_types is None or g.evidence_type in evidence_types]
        statuses = [g.status for g in selected]
        if not statuses:
            return GateStatus.UNVERIFIED
        if GateStatus.FAIL in statuses:
            return GateStatus.FAIL
        if GateStatus.BLOCKED in statuses:
            return GateStatus.BLOCKED
        if GateStatus.UNVERIFIED in statuses:
            return GateStatus.UNVERIFIED
        if GateStatus.PARTIAL in statuses:
            return GateStatus.PARTIAL
        return GateStatus.PASS

    def _probe(self, url: str) -> tuple[GateStatus, str, Any | None]:
        try:
            response = self.client.get(url, headers={"Accept": "application/json"})
        except httpx.ProxyError as exc:
            # The certifying runner's own egress proxy refused the host: that
            # is evidence about the runner, not about the target.
            return GateStatus.BLOCKED, f"{url} runner egress refused: {type(exc).__name__}: {exc}", None
        except httpx.HTTPError as exc:
            return GateStatus.FAIL, f"{url} network error: {type(exc).__name__}: {exc}", None
        content_type = response.headers.get("content-type", "")
        data: Any | None = None
        if "json" in content_type.lower():
            try:
                data = response.json()
            except ValueError:
                data = None
        detail = f"{url} -> HTTP {response.status_code}; content-type={content_type or 'unknown'}"
        if 200 <= response.status_code < 300:
            return GateStatus.PASS, detail, data
        return GateStatus.FAIL, detail, data

    def _get_json(self, url: str) -> dict[str, Any]:
        response = self.client.get(url)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError("JSON object required")
        return data

    @staticmethod
    def _split_repo(repository: str) -> tuple[str, str]:
        parts = repository.strip("/").split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("source_repository must use owner/repo form")
        return parts[0], parts[1]
