from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


REQUIREMENTS_FILE = Path(__file__).with_name("requirements") / "featured_genus_media_policy.json"


@dataclass(frozen=True)
class SentinelFinding:
    code: str
    severity: str
    message: str
    evidence: dict[str, Any]


class FeaturedGenusSentinel:
    """Read-only command gate for Featured Genus media changes.

    The sentinel turns prior audit findings into executable release conditions.
    It does not auto-fix or auto-deploy. A failed audit blocks promotion and
    records the missing evidence Calyx must obtain before proposing a repair.
    """

    def load_policy(self) -> dict[str, Any]:
        with REQUIREMENTS_FILE.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def audit(self) -> dict[str, Any]:
        policy = self.load_policy()
        requirements = policy["requirements"]
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
                    "documented_v2_executed": False,
                    "required": "Inspect actual current view definition, endpoint parser, and selected rows before recommending a repair.",
                },
            ),
            SentinelFinding(
                code="LIVE_BROWSER_RENDER_PROBE_MISSING",
                severity="blocker",
                message=(
                    "The Calyx runtime has no configured browser-render probe, so it "
                    "cannot prove that the deployed homepage visibly renders the same "
                    "media returned by its endpoint."
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
        ]
        return {
            "audit": "featured_genus_media",
            "status": "blocked",
            "promotion_allowed": False,
            "policy_version": policy["policy_version"],
            "acceptance_genera": policy["acceptance_genera"],
            "requirements": requirements,
            "findings": [finding.__dict__ for finding in findings],
            "next_command": "Collect source-contract evidence and browser-render evidence, then re-run audit_featured_genus_media.",
        }
