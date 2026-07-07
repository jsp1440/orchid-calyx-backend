from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from sqlalchemy import text

from app.database import get_engine


REQUIREMENTS_FILE = Path(__file__).with_name("requirements") / "featured_genus_media_policy.json"
DEFAULT_CALYX_PUBLIC_URL = "https://orchid-calyx-backend.onrender.com"
CURRENT_ENDPOINT_SOURCE = "public.orchid_images"
BUILD_208_LEGACY_VIEW = "api.v_frontend_orchid_images"
BUILD_208_LEGACY_SOURCE = "public.images"


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

    def _audit_source_contract(self) -> tuple[list[SentinelFinding], dict[str, Any]]:
        """Read the live database metadata needed to enforce BUILD-208.

        This deliberately inspects metadata and small counts only. It does not
        alter views, media records, or taxonomy.
        """
        findings: list[SentinelFinding] = []
        evidence: dict[str, Any] = {
            "build_208_legacy_view": BUILD_208_LEGACY_VIEW,
            "build_208_legacy_source": BUILD_208_LEGACY_SOURCE,
            "current_endpoint_source": CURRENT_ENDPOINT_SOURCE,
        }
        try:
            with get_engine().connect() as conn:
                view_row = conn.execute(
                    text(
                        """
                        SELECT view_definition
                        FROM information_schema.views
                        WHERE table_schema = 'api'
                          AND table_name = 'v_frontend_orchid_images'
                        """
                    )
                ).mappings().first()
                v2_row = conn.execute(
                    text(
                        """
                        SELECT view_definition
                        FROM information_schema.views
                        WHERE table_schema = 'api'
                          AND table_name = 'v_frontend_orchid_images_v2'
                        """
                    )
                ).mappings().first()
                image_counts = conn.execute(
                    text(
                        """
                        SELECT
                          to_regclass('public.images') IS NOT NULL AS legacy_images_exists,
                          to_regclass('public.orchid_images') IS NOT NULL AS current_images_exists
                        """
                    )
                ).mappings().one()
            evidence.update(
                {
                    "legacy_view_exists": bool(view_row),
                    "legacy_view_definition": (view_row or {}).get("view_definition"),
                    "v2_view_exists": bool(v2_row),
                    "v2_view_definition": (v2_row or {}).get("view_definition"),
                    "legacy_images_exists": bool(image_counts["legacy_images_exists"]),
                    "current_images_exists": bool(image_counts["current_images_exists"]),
                }
            )
        except Exception as exc:
            findings.append(
                SentinelFinding(
                    code="BUILD208_SOURCE_CONTRACT_AUDIT_ERROR",
                    severity="blocker",
                    message="Calyx could not inspect the live database source contract required by BUILD-208.",
                    evidence={**evidence, "error_type": type(exc).__name__, "error": str(exc)},
                )
            )
            return findings, evidence

        if not evidence["legacy_view_exists"]:
            findings.append(
                SentinelFinding(
                    code="BUILD208_LEGACY_VIEW_MISSING",
                    severity="blocker",
                    message="The BUILD-208 legacy frontend view is absent, so its contract cannot be compared safely.",
                    evidence=evidence,
                )
            )
        if CURRENT_ENDPOINT_SOURCE != BUILD_208_LEGACY_SOURCE:
            findings.append(
                SentinelFinding(
                    code="ACTIVE_ENDPOINT_BYPASSES_BUILD208_SOURCE",
                    severity="blocker",
                    message=(
                        "The active Calyx Featured Genus endpoint reads a different raw source than the "
                        "BUILD-208-audited frontend contract. A replacement requires an explicit reviewed mapping."
                    ),
                    evidence=evidence,
                )
            )
        if evidence["v2_view_exists"]:
            findings.append(
                SentinelFinding(
                    code="UNREVIEWED_V2_VIEW_PRESENT",
                    severity="blocker",
                    message="A v2 frontend view exists but has not yet been accepted as the approved replacement contract.",
                    evidence=evidence,
                )
            )
        return findings, evidence

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
        source_findings, source_contract = self._audit_source_contract()
        endpoint_findings, endpoint_results = self._audit_live_endpoint(policy)
        findings = [
            SentinelFinding(
                code="LIVE_BROWSER_RENDER_PROBE_PENDING",
                severity="blocker",
                message=(
                    "Calyx requires the companion GitHub browser workflow artifact before it can "
                    "prove that the deployed homepage visibly renders the endpoint response."
                ),
                evidence={
                    "workflow": "Featured Genus Render Sentinel",
                    "required_checks": [
                        "hero image visibly loads",
                        "gallery image visibly loads",
                        "no illustration or plate",
                        "no duplicate URL or duplicate cluster",
                        "frontend response equals endpoint response",
                    ],
                },
            ),
            SentinelFinding(
                code="PROMOTION_GATE_ACTIVE",
                severity="info",
                message=(
                    "Calyx must not recommend merge or deployment for Featured Genus media "
                    "while a blocker remains open."
                ),
                evidence={"policy": requirements["promotion_policy"]},
            ),
            *source_findings,
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
            "source_contract": source_contract,
            "live_endpoint_results": endpoint_results,
            "findings": [finding.__dict__ for finding in findings],
            "next_command": "Resolve every blocker and attach the latest browser workflow artifact before requesting a Featured Genus promotion decision.",
        }
