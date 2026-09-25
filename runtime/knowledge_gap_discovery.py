"""BUILD-016 knowledge gap discovery.

Two gap sources, never mixed silently:

* **evidence coverage** (``runtime/evidence_coverage_gaps.py``): counts from the
  persisted knowledge graph of which dossier evidence domains each taxon lacks.
  When an engine is given a KG source it uses only this; if the KG cannot be
  read it fails closed to the stored record, marked stale with the reason, and
  never falls back to the keyword method as if that were fresh.
* **keyword match** (legacy): discovery-memory module and capability names that
  contain a keyword. Used only by an engine built without a KG source, and
  always labelled with :data:`DISCOVERY_METHOD`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .discovery_memory import DiscoveryMemoryStore
from .evidence_coverage_gaps import (
    EVIDENCE_COVERAGE_METHOD,
    EvidenceCoverageGapSource,
    EvidenceCoverageUnavailable,
    research_mission,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
GAP_DIR = REPO_ROOT / "runtime" / "knowledge_gaps"
LATEST_PATH = GAP_DIR / "latest.json"

#: A knowledge-gap record older than this is stale by contract. Every consumer
#: reads the ``freshness`` block rather than inferring age from ``generated_at``.
MAX_RECORD_AGE_DAYS = 30
#: What the domain-coverage numbers in this record actually are. They count
#: discovery-memory module and capability *names* that contain a keyword. They
#: are not an inventory of ``app/`` and not a count of database tables, so a
#: domain can show "0 matched" while the application plainly implements it.
DISCOVERY_METHOD = (
    "keyword match over discovery-memory module and capability names; "
    "not an inventory of app/ modules or database tables"
)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def freshness_block(
    generated_at: str,
    *,
    now: datetime | None = None,
    max_age_days: int = MAX_RECORD_AGE_DAYS,
    stale_reason: str | None = None,
    method: str = DISCOVERY_METHOD,
) -> dict[str, Any]:
    """The freshness contract for a record generated at ``generated_at``.

    ``stale`` is true when the record is older than ``max_age_days`` or when the
    caller supplies a reason of its own (for example, the snapshot it was
    generated from was already stale). ``reason`` is never invented: it names
    the age, the caller's reason, or both.
    """
    now = now or datetime.now(timezone.utc)
    generated = _parse_timestamp(generated_at)
    age_days = (now - generated).days if generated else None
    reasons: list[str] = []
    if age_days is None:
        reasons.append("generated_at is not an ISO timestamp")
    elif age_days > max_age_days:
        reasons.append(f"record is {age_days} days old, older than {max_age_days} days")
    if stale_reason:
        reasons.append(stale_reason)
    return {
        "generated_at": generated_at,
        "assessed_at": now.isoformat(),
        "max_record_age_days": max_age_days,
        "age_days": age_days,
        "stale": bool(reasons),
        "reason": "; ".join(reasons) if reasons else None,
        "method": method,
    }


def assess_freshness(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Return ``payload`` with its ``freshness`` block re-assessed at read time.

    A record that was fresh when written and is old now is reported stale now;
    a reason the record already carries is kept. The stored file is not
    rewritten: reading never changes what was generated.
    """
    existing = payload.get("freshness") if isinstance(payload.get("freshness"), dict) else {}
    kept_reason = existing.get("reason") if existing.get("stale") else None
    assessed = dict(payload)
    assessed["freshness"] = freshness_block(
        str(payload.get("generated_at") or ""),
        now=now,
        max_age_days=int(existing.get("max_record_age_days") or MAX_RECORD_AGE_DAYS),
        stale_reason=kept_reason,
        method=str(existing.get("method") or DISCOVERY_METHOD),
    )
    return assessed


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

    def __init__(
        self,
        output_dir: Path | None = None,
        memory_store: DiscoveryMemoryStore | None = None,
        kg_source: EvidenceCoverageGapSource | None = None,
    ) -> None:
        self.output_dir = output_dir or GAP_DIR
        self.latest_path = self.output_dir / "latest.json"
        self.memory_store = memory_store or DiscoveryMemoryStore()
        self.kg_source = kg_source
        self._kg_payload: dict[str, Any] | None = None
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def discover(self, write_cache: bool = True, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        if self.kg_source is not None:
            return self._discover_from_kg(write_cache=write_cache, now=now)
        snapshot = self.memory_store.latest()
        modules = snapshot.get("modules", [])
        capabilities = snapshot.get("capabilities", [])
        recommendations = snapshot.get("recommendations", [])
        domain_coverage = self._domain_coverage(modules, capabilities)
        gaps = self._gaps_from_coverage(domain_coverage, recommendations)
        ranked = sorted(gaps, key=lambda item: item.severity_score, reverse=True)
        generated_at = now.isoformat()
        snapshot_generated_at = snapshot.get("generated_at")
        snapshot_age = _parse_timestamp(snapshot_generated_at)
        snapshot_reason = None
        if snapshot_age is not None and (now - snapshot_age).days > MAX_RECORD_AGE_DAYS:
            snapshot_reason = (
                f"generated from discovery snapshot {snapshot.get('snapshot_id')} "
                f"captured {snapshot_generated_at}, {(now - snapshot_age).days} days old"
            )
        payload = {
            "build": "BUILD-016",
            "status": "knowledge_gaps_discovered",
            "generated_at": generated_at,
            "freshness": freshness_block(generated_at, now=now, stale_reason=snapshot_reason),
            "source_snapshot_id": snapshot.get("snapshot_id"),
            "source_snapshot_generated_at": snapshot_generated_at,
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

    def _discover_from_kg(self, *, write_cache: bool, now: datetime) -> dict[str, Any]:
        try:
            kg = self.kg_source.collect(now=now)  # type: ignore[union-attr]
        except EvidenceCoverageUnavailable as exc:
            return self._fail_closed(str(exc), now=now)
        generated_at = kg["generated_at"]
        payload = {
            "build": "BUILD-016",
            "status": "knowledge_gaps_discovered",
            "gap_source": "evidence_coverage_kg",
            "generated_at": generated_at,
            "freshness": freshness_block(generated_at, now=now, method=EVIDENCE_COVERAGE_METHOD),
            "source_id": kg["source_id"],
            "summary": kg["summary"],
            "domain_coverage": kg["domain_coverage"],
            "evidence_sources": kg["evidence_sources"],
            "gaps": kg["gaps"],
            "top_actions": kg["top_actions"],
        }
        if write_cache:
            self.latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def _fail_closed(self, reason: str, *, now: datetime) -> dict[str, Any]:
        """Serve the stored record, marked stale; never regenerate it by keyword."""
        if self.latest_path.exists():
            payload = assess_freshness(json.loads(self.latest_path.read_text(encoding="utf-8")), now=now)
        else:
            payload = {
                "build": "BUILD-016",
                "status": "knowledge_gaps_unavailable",
                "generated_at": None,
                "freshness": freshness_block("", now=now),
                "summary": {},
                "domain_coverage": {},
                "gaps": [],
                "top_actions": [],
            }
        freshness = dict(payload.get("freshness") or {})
        note = (
            f"evidence-coverage KG source unavailable ({reason}); serving the stored record "
            "unchanged, not regenerated by keyword match"
        )
        freshness["stale"] = True
        freshness["reason"] = "; ".join(r for r in (freshness.get("reason"), note) if r)
        payload["freshness"] = freshness
        payload["gap_source"] = "stored_record_fail_closed"
        return payload

    def latest(self, *, now: datetime | None = None) -> dict[str, Any]:
        """The stored record with its freshness assessed now, never rewritten.

        With a KG source, the live evidence-coverage record (or the fail-closed
        stored record) is returned instead, computed once per engine.
        """
        if self.kg_source is not None:
            if self._kg_payload is None:
                self._kg_payload = self.discover(write_cache=False, now=now)
            return self._kg_payload
        if self.latest_path.exists():
            payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
        else:
            payload = self.discover(write_cache=True, now=now)
        return assess_freshness(payload, now=now)

    def gaps(self) -> dict[str, Any]:
        payload = self.latest()
        return {
            "build": "BUILD-016",
            "count": len(payload.get("gaps", [])),
            "gaps": payload.get("gaps", []),
            "freshness": payload.get("freshness"),
        }

    def domains(self) -> dict[str, Any]:
        payload = self.latest()
        return {
            "build": "BUILD-016",
            "count": len(payload.get("domain_coverage", {})),
            "domains": payload.get("domain_coverage", {}),
            "freshness": payload.get("freshness"),
        }

    def priorities(self) -> dict[str, Any]:
        payload = self.latest()
        gaps = payload.get("gaps", [])
        grouped: dict[str, list[dict[str, Any]]] = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
        for gap in gaps:
            grouped.setdefault(gap.get("priority", "LOW"), []).append(gap)
        return {"build": "BUILD-016", "priorities": grouped, "freshness": payload.get("freshness")}

    def research_queue(self, limit: int = 10) -> dict[str, Any]:
        payload = self.latest()
        gaps = payload.get("gaps", [])[:limit]
        queue = [
            {
                "queue_rank": index + 1,
                "gap_id": gap["gap_id"],
                "domain": gap["domain"],
                "task": gap["proposed_action"],
                "priority": gap["priority"],
                # Only evidence-coverage gaps carry KG counts, so only they are missions.
                "mission": research_mission(gap)
                if gap.get("source") == "evidence_coverage_kg"
                else None,
            }
            for index, gap in enumerate(gaps)
        ]
        return {
            "build": "BUILD-016",
            "gap_source": payload.get("gap_source"),
            "queue_depth": len(queue),
            "queue": queue,
            "freshness": payload.get("freshness"),
        }

    def dashboard(self) -> dict[str, Any]:
        payload = self.latest()
        return {
            "build": "BUILD-016",
            "status": payload.get("status"),
            "freshness": payload.get("freshness"),
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
                    evidence=[
                        f"Matched runtime items: {len(info.get('matched_items', []))}",
                        f"Method: {DISCOVERY_METHOD}",
                    ],
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
