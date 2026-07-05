"""BUILD-032 Frontend Workbench.

Deterministic planning engine for turning frontend audits into reviewable repair
work items. This module does not write to GitHub directly. It organizes the
Orchid Continuum frontend repair process around the founding philosophy added
in BUILD-031: cultivate understanding by revealing relationships.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class FrontendRepairTask:
    """A reviewable frontend repair task."""

    task_id: str
    title: str
    priority: int
    status: str
    mode: str
    rationale: str
    target_files: list[str]
    acceptance_criteria: list[str]
    philosophy_alignment: list[str]


class FrontendWorkbench:
    """Create a prioritized repair queue for the Orchid Continuum frontend."""

    build = "BUILD-032"

    def queue_from_audit(self, audit: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a deterministic homepage/frontend repair queue.

        Args:
            audit: Optional BUILD-028 frontend audit payload. When provided,
                target files from the audit are used to refine the queue.
        """
        audit = audit or {}
        inventory = audit.get("inventory") or {}
        priority_files = inventory.get("priority_files") or []

        def files_matching(*terms: str) -> list[str]:
            matches = [path for path in priority_files if any(term.lower() in path.lower() for term in terms)]
            return matches[:12]

        tasks = [
            FrontendRepairTask(
                task_id="FE-WB-001",
                title="Restore Genus of the Day image experience",
                priority=100,
                status="ready_for_patch_plan",
                mode="human_review_required",
                rationale="The homepage cannot create wonder if the living orchid images are missing, static, or replaced by placeholders.",
                target_files=files_matching("DailyGenusFeature", "genusData", "imageQuality", "FallbackImage"),
                acceptance_criteria=[
                    "Hero image renders from a trusted live image source.",
                    "Gallery hides cards without usable images instead of showing IMAGE PENDING.",
                    "Rotation behavior is visible or explicitly disabled with a reason.",
                    "Photographer/source credit remains visible when available.",
                ],
                philosophy_alignment=["Beauty", "Relationships", "Stewardship"],
            ),
            FrontendRepairTask(
                task_id="FE-WB-002",
                title="Make Discovery Trails visible and connected",
                priority=96,
                status="ready_for_patch_plan",
                mode="human_review_required",
                rationale="Discovery Trails express the adaptive visitor journey: Story, Habitat, Relationships, and Conservation.",
                target_files=files_matching("DailyGenusFeature", "AppLayout", "Home", "Discovery"),
                acceptance_criteria=[
                    "Discovery Trails are visible on the live homepage without excessive scrolling.",
                    "Each trail links or points to a meaningful next action.",
                    "The section reinforces that visitors choose how to enter the Continuum.",
                ],
                philosophy_alignment=["Ways of Learning", "Personal Journey", "Community"],
            ),
            FrontendRepairTask(
                task_id="FE-WB-003",
                title="Unify the homepage narrative into one canonical flow",
                priority=94,
                status="ready_for_patch_plan",
                mode="human_review_required",
                rationale="Screenshots show multiple generations of homepage content mixed together. Build 032 should organize the homepage as one coherent journey.",
                target_files=files_matching("AppLayout", "Home", "DailyGenusFeature", "Continuum", "Atlas", "Knowledge"),
                acceptance_criteria=[
                    "No duplicate legacy marketing sections remain in the primary homepage flow.",
                    "Homepage order moves from wonder to discovery to understanding to stewardship.",
                    "Each major section answers what it is, why it matters, how it connects, and where to go next.",
                ],
                philosophy_alignment=["Integrative Science", "Emergence", "Design Principles"],
            ),
            FrontendRepairTask(
                task_id="FE-WB-004",
                title="Audit live backend and image URL configuration",
                priority=92,
                status="ready_for_patch_plan",
                mode="human_review_required",
                rationale="Broken homepage images often trace to stale API base URLs, rejected trusted image URLs, or placeholder fallback logic.",
                target_files=files_matching("backendConfig", "ocBackend", "imageQuality", "publicImageSource", "genusData"),
                acceptance_criteria=[
                    "Production backend URL is resolved deterministically.",
                    "Trusted backend image URLs are not rejected by frontend quality filters.",
                    "External placeholder states are distinguishable from real missing data.",
                ],
                philosophy_alignment=["Provenance", "Evidence", "Living Graph"],
            ),
            FrontendRepairTask(
                task_id="FE-WB-005",
                title="Connect homepage modules to the Knowledge Layers model",
                priority=88,
                status="ready_for_patch_plan",
                mode="human_review_required",
                rationale="The homepage should make the Continuum visible as Beauty, Identity, Ecology, Geography, Literature, History, Culture, Conservation, Media, Education, Personal Journey, Ways of Learning, and Ways of Thinking.",
                target_files=files_matching("Knowledge", "Atlas", "University", "Relationship", "Habitat"),
                acceptance_criteria=[
                    "Homepage sections map to Knowledge Layers without overwhelming the visitor.",
                    "Literature, media/videos, history, ethnobotany, economics, and education are represented as future-ready layers.",
                    "Missing data is shown as a knowledge gap rather than a broken card.",
                ],
                philosophy_alignment=["Knowledge Layers", "Integrative Science", "Ways of Thinking"],
            ),
        ]

        ordered = sorted(tasks, key=lambda item: item.priority, reverse=True)
        return {
            "build": self.build,
            "status": "frontend_workbench_ready",
            "mode": "planning_only_no_writes",
            "source_audit_status": audit.get("status"),
            "source_repo": audit.get("repo"),
            "source_branch": audit.get("branch"),
            "queue_summary": {
                "total": len(ordered),
                "highest_priority": ordered[0].priority if ordered else None,
                "recommended_next_task": ordered[0].task_id if ordered else None,
            },
            "frontend_repair_queue": [asdict(task) for task in ordered],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
