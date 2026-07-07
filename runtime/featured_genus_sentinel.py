from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen


REQUIREMENTS_FILE = Path(__file__).with_name("requirements") / "featured_genus_media_policy.json"
DEFAULT_CALYX_PUBLIC_URL = "https://orchid-calyx-backend.onrender.com"


@dataclass(frozen=True)
class SentinelFinding:
    code: str
    severity: str
    message: str
    evidence: dict[str, Any]


class FeaturedGenusSentinel:
    """Read-only command gate for Featured Genus media changes.

    The sentinel turns prior audit findings into executable release conditions.
    It does not auto-fix, merge, or deploy. A failed audit blocks promotion and
    records the evidence Calyx must obtain before proposing a repair.
    """

    def load_policy(self) -> dict[str, Any]:
        with REQUIREMENTS_FILE.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @property
    def calyx_public_url(self) -> str:
        return os.environ.get("CALYX_PUBLIC_URL", DEFAULT_CALYX_PUBLIC_URL).rstrip("/")

    def _fetch_live_media(self, genus: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        url = f"{self.calyx_public_url}/api/media/genus/{quote(genus)}?limit=12"
        try:
            with urlopen(url, timeout=20) as response:  # nosec B310: fixed HTTPS origin or deployment env override
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                return None, {"url": url, "error": "non_object_json"}
            return payload, None
        except HTTPError as exc:
            return None, {"url": url, "error": "http_error", "status_code": exc.code}
        except URLError as exc:
            return None, {"url": url, "error": "network_error", "reason": str(exc.reason)}
        except (TimeoutError, json.JSONDecodeError) as exc:
            return None, {"url": url, "error": type(exc).__name__, "reason": str(exc)}

    def _audit_live_endpoint(self, policy: dict[str, Any]) -> tuple[list[SentinelFinding], dict[str, Any]]:
        findings: list[SentinelFinding] = []
        results: dict[str, Any] = {}
        for genus in policy["acceptance_genera"]:
            payload, error = self._fetch_live_media(genus)
            if error:
                results[genus] = {"status": "unreachable", "error": error}
                findings.append(
                    SentinelFinding(
                        code="MEDIA_ENDPOINT_UNREACHABLE",
                        severity="blocker",
                        message=f"Calyx could not obtain a live Featured Genus response for {genus}.",
                        evidence={"genus": genus, **error},
                    )
                )
                continue

            status = payload.get("status")
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            result = {
                "status": status,
                "returned_count": len(items),
                "scientific_names": [item.get("scientific_name") for item in items if isinstance(item, dict)],
                "image_urls": [item.get("image_url") for item in items if isinstance(item, dict)],
            }
            results[genus] = result

            if status not in {"ok", "no_approved_media", "invalid_genus"}:
                findings.append(
                    SentinelFinding(
                        code="MEDIA_ENDPOINT_INVALID_STATUS",
                        severity="blocker",
                        message=f"Calyx returned unsupported status for {genus}.",
                        evidence={"genus": genus, "status": status},
                    )
                )
                continue

            if status == "ok":
                urls = [url for url in result["image_urls"] if isinstance(url, str) and url]
                names = [name for name in result["scientific_names"] if isinstance(name, str) and name]
                if len(urls) != len(set(urls)):
                    findings.append(
                        SentinelFinding(
                            code="DUPLICATE_MEDIA_URL",
                            severity="blocker",
                            message=f"Featured Genus response repeats a media URL for {genus}.",
                            evidence={"genus": genus, "urls": urls},
                        )
                    )
                if len(names) != len(set(names)):
                    findings.append(
                        SentinelFinding(
                            code="DUPLICATE_SPECIES_IN_GALLERY",
                            severity="blocker",
                            message=f"Featured Genus response repeats a species in the gallery for {genus}.",
                            evidence={"genus": genus, "scientific_names": names},
                        )
                    )
                for item in items:
                    if not isinstance(item, dict):
                        findings.append(
                            SentinelFinding(
                                code="MALFORMED_MEDIA_ITEM",
                                severity="blocker",
                                message=f"Featured Genus response contains a malformed item for {genus}.",
                                evidence={"genus": genus, "item": item},
                            )
                        )
                        continue
                    missing = [field for field in ("scientific_name", "image_url", "source_name", "media_kind") if not item.get(field)]
                    if missing:
                        findings.append(
                            SentinelFinding(
                                code="MISSING_MEDIA_PROVENANCE",
                                severity="blocker",
                                message=f"Featured Genus media lacks required provenance fields for {genus}.",
                                evidence={"genus": genus, "media_id": item.get("media_id"), "missing": missing},
                            )
                        )
                    if item.get("media_kind") != "photograph":
                        findings.append(
                            SentinelFinding(
                                code="NON_PHOTOGRAPH_MEDIA_KIND",
                                severity="blocker",
                                message=f"Featured Genus media is not classified as a photograph for {genus}.",
                                evidence={"genus": genus, "media_id": item.get("media_id"), "media_kind": item.get("media_kind")},
                            )
                        )
        return findings, results

    def audit(self) -> dict[str, Any]:
        policy = self.load_policy()
        requirements = policy["requirements"]
        endpoint_findings, endpoint_results = self._audit_live_endpoint(policy)
        findings = [
            SentinelFinding(
                code="BUILD208_SOURCE_CONTRACT_UNVERIFIED",
                severity="blocker",
                message=(
                    "The approved Featured Genus data contract has not been verified "
                    "against BUILD-208 before this release decision."
                ),
                evidence={
                    "audit_build": "BUILD-208",
                    "documented_legacy_view": "api.v_frontend_orchid_images",
                    "documented_legacy_source": "public.images",
                    "documented_v2_sql_generated": True,
                    "documented_v2_sql_executable": False,
                    "required": "Inspect the current view definition, endpoint parser, and selected rows before recommending a replacement data path.",
                },
            ),
            SentinelFinding(
                code="LIVE_BROWSER_RENDER_PROBE_MISSING",
                severity="blocker",
                message=(
                    "No browser-render evidence has been attached to this audit, so Calyx "
                    "cannot prove that the deployed homepage visibly renders the endpoint response."
                ),
                evidence={
                    "required_checks": [
                        "hero image visibly loads",
                        "gallery image visibly loads",
                        "no illustration or plate",
                        "no duplicate URL or duplicate cluster",
                        "frontend response equals endpoint response",
                    ],
                    "configured": False,
                },
            ),
            SentinelFinding(
                code="PROMOTION_GATE_ACTIVE",
                severity="info",
                message=(
                    "Calyx must not recommend merge or deployment for Featured Genus "
                    "media while a blocker remains open."
                ),
                evidence={"policy": requirements["promotion_policy"]},
            ),
            *endpoint_findings,
        ]
        blockers = [finding for finding in findings if finding.severity == "blocker"]
        return {
            "audit": "featured_genus_media",
            "status": "blocked" if blockers else "passed",
            "promotion_allowed": not blockers,
            "policy_version": policy["policy_version"],
            "acceptance_genera": policy["acceptance_genera"],
            "requirements": requirements,
            "live_endpoint_results": endpoint_results,
            "findings": [finding.__dict__ for finding in findings],
            "next_command": "Collect source-contract evidence and browser-render evidence, then re-run audit_featured_genus_media.",
        }
