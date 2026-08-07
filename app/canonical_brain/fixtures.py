from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .models import BrainObject, BrainRelationship
from .registry import CanonicalBrainRegistry


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _object(object_id: str, object_type: str, title: str, summary: str, aliases: list[str], tags: list[str]) -> BrainObject:
    return BrainObject(
        object_id=object_id,
        object_type=object_type,
        title=title,
        summary=summary,
        aliases=aliases,
        tags=tags,
        lifecycle="approved",
        source_uri=f"brain://fixtures/{object_id}",
        content_checksum=_checksum(f"{object_id}:{title}:{summary}"),
        created_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
    )


def build_canonical_brain_fixture() -> CanonicalBrainRegistry:
    registry = CanonicalBrainRegistry()
    records = [
        _object("intent:preserve-biodiversity", "intent", "Preserve orchid biodiversity", "Protect orchid diversity through evidence, conservation intelligence, and accessible knowledge.", ["Conservation mission"], ["mission", "conservation"]),
        _object("intent:accelerate-discovery", "intent", "Accelerate scientific discovery", "Connect evidence, tools, and reproducible workflows for orchid research.", ["Research mission"], ["mission", "research"]),
        _object("intent:educate-public", "intent", "Educate and empower people", "Make orchid knowledge understandable, visual, reusable, and available to learners, growers, and conservation partners.", ["Education mission"], ["mission", "education", "outreach"]),
        _object("intent:support-living-collections", "intent", "Support living collections", "Improve stewardship, cultivation, documentation, and scientific value of living orchid collections.", ["Collections mission"], ["mission", "collections", "cultivation"]),
        _object("intent:enable-governed-autonomy", "intent", "Enable governed autonomous operation", "Allow Calyx to plan, build, validate, document, and report work while preserving human approval and scientific safeguards.", ["Autonomy mission"], ["mission", "autonomy", "governance"]),
        _object("architecture:brain", "architecture", "Canonical Brain", "Institutional memory for architecture, decisions, intent, dependencies, validation, and reproducibility.", ["Project Brain", "Calyx Brain"], ["brain", "governance", "search"]),
        _object("architecture:mission-control", "architecture", "Mission Control", "Operational command surface for engineers, builds, approvals, blockers, and system health.", ["Control Plane"], ["operations", "orchestration"]),
        _object("architecture:knowledge-explorer", "architecture", "Knowledge Explorer", "Integrated glossary, scientific figures, photographs, learning paths, and evidence-linked concept exploration.", ["Illustrated Glossary", "Lexicon Engine", "FigureLabs"], ["glossary", "FigureLabs", "education"]),
        _object("architecture:atlas", "architecture", "Planetary Intelligence Atlas", "Earth systems, biodiversity, conservation, temporal intelligence, and deterministic thematic cartography.", ["Atlas", "Earth Systems Atlas"], ["maps", "earth science", "cartography"]),
        _object("architecture:research-station", "architecture", "Research Station", "Reproducible scientific workspaces and evidence-preserving analysis workflows.", ["Orchid Research Station"], ["research", "evidence"]),
        _object("architecture:conservatory", "architecture", "Conservatory", "Living-collection intelligence, QR records, cultivation history, and specimen dossiers.", ["Oasis", "Collection Manager"], ["collection", "QR"]),
        _object("architecture:matrix", "architecture", "Matrix Identification", "Explainable character-based comparison and identification with missing-data accounting.", ["Matrix"], ["identification", "characters"]),
        _object("architecture:ai-vision", "architecture", "AI.Vision", "Governed visual observations, annotations, and image-to-character proposals.", ["Vision Lab"], ["images", "annotation"]),
        _object("architecture:publishing", "architecture", "Scientific Publishing Platform", "Evidence-backed reports, articles, grants, presentations, and educational outputs.", ["Publishing Engine"], ["reports", "publication"]),
        _object("decision:brain-canonical-memory", "decision", "The Brain is the canonical institutional memory", "Architecture, intent, decisions, dependencies, validation, and reproducibility must be captured as searchable governed objects.", ["ADR-BRAIN-001"], ["brain", "governance", "memory"]),
        _object("decision:mission-control-command", "decision", "Mission Control is the operational command surface", "Mission Control exposes builds, approvals, blockers, health, and Brain governance without bypassing approval boundaries.", ["ADR-MC-001"], ["mission control", "operations"]),
        _object("decision:atlas-earth-systems", "decision", "Earth Systems and Thematic Cartography are core Atlas capabilities", "The Atlas explains environmental context and generates repeatable maps rather than serving only as a point viewer.", ["ADR-ATLAS-001"], ["atlas", "earth science", "thematic maps"]),
        _object("decision:knowledge-explorer", "decision", "Glossary is a Knowledge Explorer", "Scientific terms are gateways to figures, photographs, literature, taxa, ecology, cultivation, and learning resources.", ["ADR-KE-001"], ["glossary", "knowledge explorer"]),
        _object("decision:research-station-reproducible", "decision", "Research Station preserves evidence and reproducibility", "Research workflows retain provenance, distinguish evidence from interpretation, and produce repeatable outputs.", ["ADR-RS-001"], ["research station", "reproducibility"]),
        _object("decision:conservatory-living-record", "decision", "Conservatory treats each plant as a living scientific record", "QR-linked dossiers preserve identity, provenance, culture, environment, images, and lifecycle history.", ["ADR-CON-001"], ["conservatory", "collections", "QR"]),
        _object("decision:matrix-explainable-identification", "decision", "Matrix identification must remain explainable", "Character comparisons expose supporting evidence, missing data, ambiguity, and alternative identifications.", ["ADR-MATRIX-001"], ["matrix", "identification", "explainability"]),
        _object("decision:vision-candidate-observations", "decision", "AI.Vision produces governed candidate observations", "Visual models may propose annotations and character evidence but cannot silently publish scientific conclusions.", ["ADR-VISION-001"], ["AI.Vision", "images", "governance"]),
        _object("decision:publishing-evidence-backed", "decision", "Publishing outputs must be evidence-backed", "Reports, articles, grants, and educational products retain citations, provenance, review status, and reproducibility context.", ["ADR-PUB-001"], ["publishing", "evidence", "citations"]),
    ]
    for record in records:
        registry.register_object(record)

    relationships = [
        ("rel:brain-controls-mission", "architecture:brain", "contains", "architecture:mission-control", "Brain records Mission Control architecture."),
        ("rel:atlas-depends-brain", "architecture:atlas", "depends_on", "architecture:brain", "Atlas architecture and reproducibility are captured by the Brain."),
        ("rel:explorer-depends-brain", "architecture:knowledge-explorer", "depends_on", "architecture:brain", "Knowledge Explorer concepts and decisions are discoverable through the Brain."),
        ("rel:brain-decision", "decision:brain-canonical-memory", "documents", "architecture:brain", "The decision defines the Brain as canonical institutional memory."),
        ("rel:mission-control-decision", "decision:mission-control-command", "documents", "architecture:mission-control", "The decision defines Mission Control's governed command role."),
        ("rel:atlas-decision", "decision:atlas-earth-systems", "documents", "architecture:atlas", "The decision defines the Atlas scope."),
        ("rel:explorer-decision", "decision:knowledge-explorer", "documents", "architecture:knowledge-explorer", "The decision defines the integrated glossary scope."),
        ("rel:station-decision", "decision:research-station-reproducible", "documents", "architecture:research-station", "The decision defines evidence-preserving research workflows."),
        ("rel:conservatory-decision", "decision:conservatory-living-record", "documents", "architecture:conservatory", "The decision defines living collection records."),
        ("rel:matrix-decision", "decision:matrix-explainable-identification", "documents", "architecture:matrix", "The decision defines explainable matrix identification."),
        ("rel:vision-decision", "decision:vision-candidate-observations", "documents", "architecture:ai-vision", "The decision defines governed visual proposals."),
        ("rel:publishing-decision", "decision:publishing-evidence-backed", "documents", "architecture:publishing", "The decision defines evidence-backed publishing."),
        ("rel:brain-intent", "architecture:brain", "aligned_to", "intent:enable-governed-autonomy", "Canonical memory is required for governed autonomous operation."),
        ("rel:mission-control-intent", "architecture:mission-control", "aligned_to", "intent:enable-governed-autonomy", "Mission Control coordinates autonomous work and approval boundaries."),
        ("rel:atlas-intent", "architecture:atlas", "aligned_to", "intent:preserve-biodiversity", "Atlas conservation intelligence advances biodiversity preservation."),
        ("rel:station-intent", "architecture:research-station", "aligned_to", "intent:accelerate-discovery", "Research Station workflows accelerate discovery."),
        ("rel:explorer-intent", "architecture:knowledge-explorer", "aligned_to", "intent:educate-public", "Knowledge Explorer makes connected orchid knowledge understandable and discoverable."),
        ("rel:conservatory-intent", "architecture:conservatory", "aligned_to", "intent:support-living-collections", "Conservatory improves stewardship of living collections."),
        ("rel:matrix-intent", "architecture:matrix", "aligned_to", "intent:accelerate-discovery", "Explainable comparisons support identification and research."),
        ("rel:vision-intent", "architecture:ai-vision", "aligned_to", "intent:accelerate-discovery", "Governed visual observations accelerate evidence extraction."),
        ("rel:publishing-intent", "architecture:publishing", "aligned_to", "intent:educate-public", "Publishing converts governed evidence into accessible outputs."),
    ]
    for relation_id, subject_id, relation_type, object_id, rationale in relationships:
        registry.register_relationship(BrainRelationship(
            relationship_id=relation_id,
            subject_id=subject_id,
            relationship_type=relation_type,
            object_id=object_id,
            rationale=rationale,
            source_uri="brain://fixtures/relationships",
        ))
    return registry
