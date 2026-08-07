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
        _object("architecture:brain", "architecture", "Canonical Brain", "Institutional memory for architecture, decisions, intent, dependencies, validation, and reproducibility.", ["Project Brain", "Calyx Brain"], ["brain", "governance", "search"]),
        _object("architecture:mission-control", "architecture", "Mission Control", "Operational command surface for engineers, builds, approvals, blockers, and system health.", ["Control Plane"], ["operations", "orchestration"]),
        _object("architecture:knowledge-explorer", "architecture", "Knowledge Explorer", "Integrated glossary, scientific figures, photographs, learning paths, and evidence-linked concept exploration.", ["Illustrated Glossary", "Lexicon Engine"], ["glossary", "FigureLabs", "education"]),
        _object("architecture:atlas", "architecture", "Planetary Intelligence Atlas", "Earth systems, biodiversity, conservation, temporal intelligence, and deterministic thematic cartography.", ["Atlas", "Earth Systems Atlas"], ["maps", "earth science", "cartography"]),
        _object("architecture:research-station", "architecture", "Research Station", "Reproducible scientific workspaces and evidence-preserving analysis workflows.", ["Orchid Research Station"], ["research", "evidence"]),
        _object("architecture:conservatory", "architecture", "Conservatory", "Living-collection intelligence, QR records, cultivation history, and specimen dossiers.", ["Oasis", "Collection Manager"], ["collection", "QR"]),
        _object("architecture:matrix", "architecture", "Matrix Identification", "Explainable character-based comparison and identification with missing-data accounting.", ["Matrix"], ["identification", "characters"]),
        _object("architecture:ai-vision", "architecture", "AI.Vision", "Governed visual observations, annotations, and image-to-character proposals.", ["Vision Lab"], ["images", "annotation"]),
        _object("architecture:publishing", "architecture", "Scientific Publishing Platform", "Evidence-backed reports, articles, grants, presentations, and educational outputs.", ["Publishing Engine"], ["reports", "publication"]),
        _object("decision:atlas-earth-systems", "decision", "Earth Systems and Thematic Cartography are core Atlas capabilities", "The Atlas explains environmental context and generates repeatable maps rather than serving only as a point viewer.", ["ADR-ATLAS-001"], ["atlas", "earth science", "thematic maps"]),
        _object("decision:knowledge-explorer", "decision", "Glossary is a Knowledge Explorer", "Scientific terms are gateways to figures, photographs, literature, taxa, ecology, cultivation, and learning resources.", ["Glossary decision"], ["glossary", "knowledge explorer"]),
    ]
    for record in records:
        registry.register_object(record)

    relationships = [
        ("rel:brain-controls-mission", "architecture:brain", "contains", "architecture:mission-control", "Brain records Mission Control architecture."),
        ("rel:atlas-depends-brain", "architecture:atlas", "depends_on", "architecture:brain", "Atlas architecture and reproducibility are captured by the Brain."),
        ("rel:explorer-depends-brain", "architecture:knowledge-explorer", "depends_on", "architecture:brain", "Knowledge Explorer concepts and decisions are discoverable through the Brain."),
        ("rel:atlas-decision", "decision:atlas-earth-systems", "documents", "architecture:atlas", "The decision defines the Atlas scope."),
        ("rel:explorer-decision", "decision:knowledge-explorer", "documents", "architecture:knowledge-explorer", "The decision defines the integrated glossary scope."),
        ("rel:atlas-intent", "architecture:atlas", "aligned_to", "intent:preserve-biodiversity", "Atlas conservation intelligence advances biodiversity preservation."),
        ("rel:station-intent", "architecture:research-station", "aligned_to", "intent:accelerate-discovery", "Research Station workflows accelerate discovery."),
        ("rel:explorer-intent", "architecture:knowledge-explorer", "aligned_to", "intent:accelerate-discovery", "Knowledge Explorer makes connected evidence discoverable."),
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
