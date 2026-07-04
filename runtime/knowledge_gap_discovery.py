"""BUILD-016 knowledge gap discovery.

This module turns runtime discovery memory into actionable Orchid Continuum
knowledge-gap signals. It is intentionally safe and file-backed: it can run on
Render without DATABASE_URL, while using live discovery snapshots when they are
available.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .discovery_memory import DiscoveryMemoryStore


REPO_ROOT = Path(__file__).resolve().parents[1]
GAP_DIR = REPO_ROOT / "runtime" / "knowledge_gaps"
LATEST_PATH = GAP_DIR / "latest.json"


DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "Taxonomy": ["taxonomy", "taxon", "species", "genus", "synonym", "name"],
    "Images": ["image", "media", "photo", "vision"],
    "Occurrences": ["occurrence", "atlas", "gbif", "inat", "location", "geo"],
    "Pollination": ["pollination", "pollinator", "interaction", "ecology"],
    "Mycorrhiza": ["mycorrhiza", "fungal", "fungus"],
    "Conservation": ["conservation", "iucn", "threat", "habitat", "climate"],
    "Literature": ["literature", "citation", "reference", "paper", "doc"],
    "Traits": ["trait", "morphology", "phenology", "flower", "life"],
    "Governance": ["governance", "review", "audit", "provenance", "claim"],
}


@dataclass
class KnowledgeGap:
    gap_id: str
    domain: str
    title: str
    priority: str
    severity_score: int
    evidence: list[str] = field(default_factory=list)
    proposed_action: str = ""
    source: str = "BUILD-016"


class KnowledgeGapDiscoveryEngine:
    """Derive knowledge-gap candidates from discovery memory and runtime modules."""

    def __init__(self, output_dir: Path | None = None, memory_store: DiscoveryMemoryStore | None = None) -> None:
        self.output_dir = output_dir or GAP_DIR
        self.latest_path = self.output_dir / "latest.json"
        self.memory_store = memory_store or DiscoveryMemoryStore()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def discover(self, write_cache: bool = True) -> dict[str, Any]:
        snapshot = self.memory_store.latest()
        modules = snapshot.get("modules", [])
        capabilities = snapshot.get("capabilities", [])
        recommendations = snapshot.get("recommendations", [])
        domain_coverage = self._domain_coverage(modules, capabilities)
        gaps = self._gaps_from_coverage(domain_coverage, recommendations)
        ranked = sorted(gaps, key=lambda item: item.severity_score, reverse=True)
        payload = {
            "build": "BUILD-016",
            "status": "knowledge_gaps_discovered",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_snapshot_id": snapshot.get("snapshot_id"),
            "summary": {
                "domains": len(domain_coverage),
                "gaps": len(ranked),
                "critical": sum(1 for gap in ranked if gap.priority == "CRITICAL"),
                "high": sum(1 for gap in ranked if gap.priority == "HIGH"),
                "source_modules": len(modules),
                "source_capabilities": len(capabilities),
            },
            "domain_coverage": domain_coverage,
            "gaps": [asdict(item) for item in ranked],
            "top_actions": [item.proposed_action for item in ranked[:5]],
        }
        if write_cache:
            self.latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def latest(self) -> dict[str, Any]:
        if self.latest_path.exists():
            return json.loads(self.latest_path.read_text(encoding="utf-8"))
        return self.discover(write_cache=True)

    def gaps(self) -> dict[str, Any]:
        payload = self.latest()
        return {"build": "BUILD-016", "count": len(payload.get("gaps", [])), "gaps": payload.get("gaps", [])}

    def domains(self) -> dict[str, Any]:
        payload = self.latest()
        return {"build": "BUILD-016", "count": len(payload.get("domain_coverage", {})), "domains": payload.get("domain_coverage", {})}

    def priorities(self) -> dict[str, Any]:
        gaps = self.latest().get("gaps", [])
        grouped: dict[str, list[dict[str, Any]]] = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
        for gap in gaps:
            grouped.setdefault(gap.get("priority", "LOW"), []).append(gap)
        return {"build": "BUILD-016", "priorities": grouped}

    def research_queue(self, limit: int = 10) -> dict[str, Any]:
        gaps = self.latest().get("gaps", [])[:limit]
        queue = [
            {
                "queue_rank": index + 1,
                "gap_id": gap["gap_id"],
                "domain": gap["domain"],
                "task": gap["proposed_action"],
                "priority": gap["priority"],
            }
            for index, gap in enumerate(gaps)
        ]
        return {"build": "BUILD-016", "queue_depth": len(queue), "queue": queue}

    def dashboard(self) -> dict[str, Any]:
        payload = self.latest()
        return {
            "build": "BUILD-016",
            "status": payload.get("status"),
            "summary": payload.get("summary", {}),
            "top_gaps": payload.get("gaps", [])[:5],
            "top_actions": payload.get("top_actions", []),
        }

    def _domain_coverage(self, modules: list[dict[str, Any]], capabilities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        text_by_domain: dict[str, list[str]] = {domain: [] for domain in DOMAIN_KEYWORDS}
        module_names = [str(item.get("name", "")) for item in modules]
        capability_names = [str(item.get("name", "")) for item in capabilities]
        haystacks = module_names + capability_names
        for domain, keywords in DOMAIN_KEYWORDS.items():
            matches = []
            for text in haystacks:
                lowered = text.lower()
                if any(keyword in lowered for keyword in keywords):
                    matches.append(text)
            text_by_domain[domain] = sorted(set(matches))
        return {
            domain: {
                "matched_items": matches,
                "coverage_score": min(100, len(matches) * 20),
                "status": "covered" if len(matches) >= 3 else "thin" if matches else "gap",
                "keywords": DOMAIN_KEYWORDS[domain],
            }
            for domain, matches in text_by_domain.items()
        }

    def _gaps_from_coverage(self, coverage: dict[str, dict[str, Any]], recommendations: list[dict[str, Any]]) -> list[KnowledgeGap]:
        gaps: list[KnowledgeGap] = []
        for domain, info in coverage.items():
            status = info["status"]
            score = info["coverage_score"]
            if status == "covered":
                continue
            severity = 100 - score
            priority = "CRITICAL" if severity >= 90 else "HIGH" if severity >= 70 else "MEDIUM"
            gaps.append(
                KnowledgeGap(
                    gap_id=f"KG-{domain.upper().replace(' ', '-')}-001",
                    domain=domain,
                    title=f"{domain} coverage is {status}",
                    priority=priority,
                    severity_score=severity,
                    evidence=[f"Matched runtime items: {len(info.get('matched_items', []))}"],
                    proposed_action=f"Add or connect {domain.lower()} data sources, validators, and review-ready outputs.",
                )
            )
        if recommendations:
            gaps.append(
                KnowledgeGap(
                    gap_id="KG-RUNTIME-RECOMMENDATIONS-001",
                    domain="Governance",
                    title="Runtime recommendations need triage",
                    priority="HIGH",
                    severity_score=75,
                    evidence=[f"{len(recommendations)} active runtime recommendation(s) found."],
                    proposed_action="Convert runtime recommendations into ranked implementation tasks.",
                )
            )
        return gaps
