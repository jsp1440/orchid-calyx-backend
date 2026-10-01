from __future__ import annotations

import hashlib
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

SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".py")
INSPECTION_CAP = 400
_CODE_LIKE = re.compile(r"[{}()<>=;|&\[\]]|\b(?:const|return|classname|function)\b")
# Correspondence threshold: share of the audited source's distinctive string
# literals that must appear verbatim in the deployed bundle.
CORRESPONDENCE_MIN_MATCH = 0.98


def _inspection_priority(path: str) -> tuple[int, str]:
    """Application code first, so the inspection cap never starves it for docs/JSON."""
    return (0 if path.lower().endswith(SOURCE_SUFFIXES) else 1, path)


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
        self._source_identity: str | None = None
        self._source_strings_text = ""
        self._runtime_identity: str | None = None
        self._runtime_text = ""
        sha, paths, source_text = self._source_inventory(target, gates)
        self._source_contract_checks(paths, source_text, gates)
        self._backend_probes(gates)
        self._runtime_gate(target, gates)
        self._correspondence_gate(gates)
        self._fingerprint_gate(gates)
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
            for path in sorted(paths, key=_inspection_priority):
                if inspected >= INSPECTION_CAP:
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
            self._source_identity = f"{target.source_repository}@{sha} (repository tree)"
            self._source_strings_text = source_text
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
                    self._source_strings_text = archive_text
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
            self._source_identity = (
                f"{owner}/{repo}@{sha}:{archive_path} "
                f"sha256={hashlib.sha256(response.content).hexdigest()}"
            )
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
                texts: list[str] = []
                inspected = 0
                for name in sorted(names, key=_inspection_priority):
                    if inspected >= INSPECTION_CAP:
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

        # A function NAME is not a write: setRole() that delegates to an
        # admin-checked server RPC is the repair, not the defect.
        privilege_patterns = [
            r"\.update\(\s*\{\s*role\b",
            r"role\s*:\s*[\w$.]+\s*\?\s*['\"]editor['\"]",
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
        ambiguous: list[str] = []
        for gate_id, url in probes:
            status, detail, data = self._probe(url)
            if gate_id == "calyx_federation" and status == GateStatus.PASS:
                status, detail = self._federation_verdict(detail, data)
            if gate_id == "calyx_federation" and isinstance(data, dict) and data.get("status") == "ambiguous":
                ambiguous = [
                    str(c["taxon_id"]) for c in (data.get("candidates") or [])
                    if isinstance(c, dict) and c.get("taxon_id")
                ][:5]
                provenance = [self._candidate_provenance(t) for t in ambiguous]
                gates.append(CertificationGate(
                    gate_id=gate_id,
                    status=GateStatus.BLOCKED,
                    evidence_type="api",
                    observed_evidence=f"{detail}; candidate provenance={provenance}",
                    blocker=(
                        "Canonical taxonomy is ambiguous for the probe name; candidates "
                        f"{ambiguous} require authoritative human taxonomic selection."
                    ),
                    smallest_next_action=(
                        "A taxonomy reviewer selects/merges the canonical record among "
                        f"{ambiguous} through the governed taxonomy path, then re-run certification."
                    ),
                ))
                continue
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
                    observed_evidence=(
                        "Canonical taxon ID was not resolved, so the dependent endpoint was not guessed"
                        + (f"; ambiguous candidates {ambiguous} were probed for provenance only." if ambiguous else ".")
                    ),
                    blocker="Federation resolver did not provide a taxon_id.",
                    smallest_next_action="Restore federation resolution, then re-run dependent probes.",
                ))

    def _candidate_provenance(self, taxon_id: str) -> dict[str, Any]:
        """Evidence for a human reviewer. Never selects a candidate."""
        url = f"{CALYX_API}/api/platform/species/{quote(taxon_id, safe='')}/dossier"
        _status, detail, data = self._probe(url)
        record: dict[str, Any] = {"taxon_id": taxon_id, "dossier_http": detail.split(" -> ")[-1]}
        if isinstance(data, dict):
            identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
            record.update({
                "full_scientific_name": identity.get("full_scientific_name") or data.get("full_scientific_name"),
                "authorship": identity.get("authorship"),
                "taxonomic_status": identity.get("taxonomic_status"),
                "rank": identity.get("rank"),
                "provenance_sources": sorted({
                    str(r.get("source_name")) for r in (data.get("provenance") or [])
                    if isinstance(r, dict) and r.get("source_name")
                })[:5],
            })
        return record

    @staticmethod
    def _federation_verdict(detail: str, data: Any | None) -> tuple[GateStatus, str]:
        """HTTP 200 is reachability, not resolution: read the resolver's own verdict."""
        if not isinstance(data, dict):
            return GateStatus.FAIL, f"{detail}; body is not a FederationResolveResult object"
        verdict = (
            f"{detail}; status={data.get('status')!r} match_state={data.get('match_state')!r} "
            f"taxon_id={data.get('taxon_id')!r} candidates={[(c.get('taxon_id'), c.get('accepted_name')) for c in (data.get('candidates') or []) if isinstance(c, dict)]} "
            f"explanation={str(data.get('explanation') or '')[:300]!r}"
        )
        if data.get("status") == "resolved" and data.get("taxon_id"):
            return GateStatus.PASS, verdict
        return GateStatus.FAIL, verdict

    def _runtime_bundle_gate(self, runtime: str, gates: list[CertificationGate]) -> None:
        """Static inspection of the deployed bundle: what the live app actually ships.

        Read-only text inspection of same-origin HTML/JS. Nothing is executed.
        """
        try:
            page = self.client.get(runtime, headers={"Accept": "text/html"})
        except httpx.ProxyError as exc:
            gates.append(CertificationGate(
                gate_id="runtime_oc_wiring",
                status=GateStatus.BLOCKED,
                evidence_type="deployment",
                observed_evidence=f"{runtime} runner egress refused: {type(exc).__name__}: {exc}",
                blocker="Certifying runner cannot reach the runtime.",
                smallest_next_action="Run certification from a runner with egress to the runtime host.",
            ))
            return
        except httpx.HTTPError as exc:
            gates.append(CertificationGate(
                gate_id="runtime_oc_wiring",
                status=GateStatus.FAIL,
                evidence_type="deployment",
                observed_evidence=f"{runtime} network error: {type(exc).__name__}: {exc}",
                blocker="Runtime HTML could not be fetched.",
                smallest_next_action="Repair live deployment reachability, then re-run certification.",
            ))
            return
        html = page.text if page.status_code == 200 else ""
        base = httpx.URL(str(page.url))
        scripts: list[str] = []
        for src in re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, re.IGNORECASE):
            url = base.join(src)
            if url.host == base.host and str(url) not in scripts:
                scripts.append(str(url))
        bundle = [html]
        fetched: list[str] = []
        for url in scripts[:8]:
            try:
                response = self.client.get(url)
            except httpx.HTTPError:
                continue
            if response.status_code == 200:
                bundle.append(response.text[:8_000_000])
                fetched.append(url.rsplit("/", 1)[-1])
        text = "\n".join(bundle).lower()
        self._runtime_text = text
        self._runtime_identity = ", ".join(
            f"{name} sha256={hashlib.sha256(body.encode('utf-8')).hexdigest()}"
            for name, body in zip(fetched, bundle[1:], strict=True)
        ) or None
        if fetched:
            self._role_security_runtime_gate(text, fetched, gates)
        markers = {
            "oc_public_api_host": "orchid-continuum-public-api.onrender.com",
            "calyx_api_host": "orchid-calyx-backend.onrender.com",
            "species_search_path": "/api/species/search",
            "genus_images_path": "/images/genus/",
            "federation_resolve_path": "/api/platform/federation/resolve-species",
            "species_platform_path": "/api/platform/species/",
        }
        present = sorted(k for k, v in markers.items() if v in text)
        not_live = [
            phrase for phrase in (
                "integration is not live",
                "intentionally not connected",
            ) if phrase in text
        ]
        if not fetched:
            status = GateStatus.UNVERIFIED
        elif set(present) == set(markers) and not not_live:
            # Every canonical host and path: a bare domain string is not wiring.
            status = GateStatus.PASS
        elif present:
            status = GateStatus.PARTIAL
        else:
            status = GateStatus.FAIL
        gates.append(CertificationGate(
            gate_id="runtime_oc_wiring",
            status=status,
            evidence_type="deployment",
            observed_evidence=(
                f"Inspected deployed HTML (HTTP {page.status_code}) and {len(fetched)} same-origin "
                f"script(s) {fetched}; OC/Calyx markers present={present}; "
                f"'not live' statements={not_live}."
            ),
            blocker=None if status == GateStatus.PASS else (
                "Deployed bundle could not be inspected." if status == GateStatus.UNVERIFIED else
                "Deployed application does not ship canonical OC/Calyx endpoint wiring, "
                "or still tells readers the integration is not live."
            ),
            smallest_next_action=None if status == GateStatus.PASS else (
                "Wire the deployed app to the canonical OC public API / Calyx endpoints, remove "
                "'not live' copy, redeploy, then re-run certification."
            ),
        ))

    @staticmethod
    def _role_security_runtime_gate(
        text: str, fetched: list[str], gates: list[CertificationGate]
    ) -> None:
        """Does the deployed client mutate its own role, or delegate to a guarded RPC?"""
        compact = re.sub(r"\s+", "", text)
        self_update = bool(re.search(r"\.update\(\{role:", compact))
        signup_role = bool(re.search(r"role:[\w$.]+\?[\"'`]editor[\"'`]", compact))
        server_rpc = "set_user_role" in compact
        risky = [name for name, hit in (
            ("client .update({role:...})", self_update),
            ("signup metadata role:<flag>?'editor'", signup_role),
        ) if hit]
        if risky:
            status = GateStatus.FAIL
        elif server_rpc:
            status = GateStatus.PASS
        else:
            status = GateStatus.UNVERIFIED
        gates.append(CertificationGate(
            gate_id="runtime_role_security",
            status=status,
            evidence_type="deployment",
            observed_evidence=(
                f"Deployed script(s) {fetched}: client role-mutation patterns={risky}; "
                f"server-side set_user_role RPC referenced={server_rpc}. Static inspection only; "
                "database RLS enforcement is not exercised by this gate."
            ),
            blocker=None if status == GateStatus.PASS else (
                "Deployed client can request or write a privileged role." if risky else
                "Deployed bundle shows neither a client role write nor a server-side role RPC."
            ),
            smallest_next_action=None if status == GateStatus.PASS else (
                "Route role changes through an admin-checked server RPC and ignore client-supplied "
                "signup roles, redeploy, then re-run certification."
            ),
        ))

    def _fingerprint_gate(self, gates: list[CertificationGate]) -> None:
        """Exact evidence that the audited source IS the deployed build, or is not."""
        if not self._runtime_identity or not self._source_strings_text:
            return
        literals = {
            " ".join(m.split()).lower()
            for m in re.findall(r"[\"']([^\"'\\\n`]{40,400})[\"']", self._source_strings_text)
            if not re.search(r"https?://|\.(?:png|jpe?g|svg|webp)\b", m)
        }
        # Prose only: code spans and utility-class strings are rewritten by the
        # minifier, so they measure the build tool, not the build's identity.
        literals = sorted(
            lit for lit in literals
            if not _CODE_LIKE.search(lit) and len(re.findall(r"[a-z]{2,}", lit)) >= 6
        )
        if len(literals) < 20:
            gates.append(CertificationGate(
                gate_id="source_runtime_fingerprint",
                status=GateStatus.UNVERIFIED,
                evidence_type="configuration",
                observed_evidence=f"Only {len(literals)} distinctive source literals; too few to fingerprint.",
                blocker="Insufficient source content to prove or disprove build identity.",
            ))
            return
        # Minifiers may escape non-ASCII and quotes; compare decoded text.
        decoded = re.sub(
            r"\\u\{?([0-9a-f]{4,5})\}?", lambda m: chr(int(m.group(1), 16)), self._runtime_text
        ).replace("\\'", "'").replace('\\"', '"')
        runtime = " ".join(decoded.split())
        missing = [lit for lit in literals if lit not in runtime]
        share = 1 - len(missing) / len(literals)
        status = GateStatus.PASS if share >= CORRESPONDENCE_MIN_MATCH else GateStatus.FAIL
        gates.append(CertificationGate(
            gate_id="source_runtime_fingerprint",
            status=status,
            evidence_type="configuration",
            observed_evidence=(
                f"Audited source: {self._source_identity}. Deployed: {self._runtime_identity}. "
                f"{len(literals) - len(missing)}/{len(literals)} distinctive source string literals "
                f"({share:.1%}) appear verbatim in the deployed bundle; examples absent from the "
                f"deployed bundle: {[m[:90] for m in missing[:3]]}."
            ),
            blocker=None if status == GateStatus.PASS else (
                "The deployed bundle is not a build of the audited source; equivalence is not proven."
            ),
            smallest_next_action=None if status == GateStatus.PASS else (
                "Commit the exact source of the deployed Famous build to the registered source "
                "repository, then re-run certification."
            ),
        ))

    @staticmethod
    def _correspondence_gate(gates: list[CertificationGate]) -> None:
        """A source audit only certifies the runtime if they are the same application."""
        by_id = {g.gate_id: g for g in gates}
        source = by_id.get("oc_source_wiring")
        runtime = by_id.get("runtime_oc_wiring")
        if source is None or runtime is None or GateStatus.UNVERIFIED in {source.status, runtime.status}:
            return
        source_wired = "OC wiring markers=[]" not in source.observed_evidence
        runtime_wired = "oc_public_api_host" in runtime.observed_evidence or (
            "calyx_api_host" in runtime.observed_evidence
        )
        if runtime_wired and not source_wired:
            gates.append(CertificationGate(
                gate_id="source_runtime_correspondence",
                status=GateStatus.FAIL,
                evidence_type="configuration",
                observed_evidence=(
                    "The deployed bundle ships canonical OC/Calyx endpoint wiring that the audited "
                    "source does not contain, so the audited source is not the deployed application."
                ),
                blocker="Source handoff is stale relative to the deployed Famous runtime.",
                smallest_next_action=(
                    "Export the current Famous.ai project source into the registered source "
                    "repository, then re-run certification."
                ),
            ))
        else:
            gates.append(CertificationGate(
                gate_id="source_runtime_correspondence",
                status=GateStatus.PASS if source_wired == runtime_wired else GateStatus.PARTIAL,
                evidence_type="configuration",
                observed_evidence=(
                    f"Source OC wiring present={source_wired}; deployed OC wiring present={runtime_wired}."
                ),
                blocker=None if source_wired == runtime_wired else
                "Audited source and deployed bundle disagree about OC wiring.",
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
        if status == GateStatus.PASS:
            self._runtime_bundle_gate(str(runtime), gates)

    def _report(
        self,
        target: CertificationTarget,
        sha: str | None,
        gates: list[CertificationGate],
    ) -> CertificationReport:
        by_id = {g.gate_id: g for g in gates}
        source_status = self._aggregate(gates, evidence_types={"source", "test", "configuration"})
        runtime_gates = [g for g in gates if g.gate_id in {"live_runtime_journeys", "runtime_oc_wiring"}]
        runtime_status = self._aggregate(runtime_gates) if "live_runtime_journeys" in by_id else GateStatus.UNVERIFIED
        security_gates = [g for g in gates if g.gate_id in {"client_role_security", "runtime_role_security"}]
        security_status = self._aggregate(security_gates) if security_gates else GateStatus.UNVERIFIED
        media_status = self._aggregate([g for g in gates if g.gate_id in {"oc_genus_media", "oc_source_wiring"}])
        scientific_status = self._aggregate([g for g in gates if g.gate_id in {
            "oc_source_wiring", "oc_species_search", "calyx_federation", "calyx_species_dossier", "calyx_species_atlas",
            "runtime_oc_wiring",
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
