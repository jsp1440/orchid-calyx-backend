from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from typing import Iterable

from app.semantic_index.provider import DeterministicLocalProvider, EmbeddingProvider

from .knowledge import (
    DesignRelationship,
    EducationalClassification,
    RelationshipType,
    SemanticDesignDomain,
    SemanticUnit,
    SemanticUnitType,
    SourceLocation,
)
from .models import DesignDocument


DOMAIN_TERMS = {
    SemanticDesignDomain.UX: ("user experience", "usability", "ux"),
    SemanticDesignDomain.UI: ("user interface", "interface", "ui"),
    SemanticDesignDomain.INTERACTION_DESIGN: ("interaction", "affordance", "feedback"),
    SemanticDesignDomain.DASHBOARD_DESIGN: ("dashboard", "status display", "kpi"),
    SemanticDesignDomain.INFORMATION_ARCHITECTURE: (
        "information architecture",
        "navigation",
        "taxonomy",
    ),
    SemanticDesignDomain.ACCESSIBILITY: (
        "accessibility",
        "wcag",
        "screen reader",
        "keyboard",
    ),
    SemanticDesignDomain.MOTION_DESIGN: (
        "motion design",
        "reduced motion",
        "transition",
    ),
    SemanticDesignDomain.ANIMATION: ("animation", "animated"),
    SemanticDesignDomain.TYPOGRAPHY: ("typography", "type scale", "font"),
    SemanticDesignDomain.COLOR_SYSTEMS: ("color system", "colour system", "contrast"),
    SemanticDesignDomain.BRANDING: ("branding", "brand identity"),
    SemanticDesignDomain.DESIGN_SYSTEMS: ("design system", "design token"),
    SemanticDesignDomain.COMPONENT_LIBRARIES: (
        "component library",
        "component example",
    ),
    SemanticDesignDomain.EDUCATIONAL_PSYCHOLOGY: (
        "educational psychology",
        "cognitive",
    ),
    SemanticDesignDomain.LEARNING_SCIENCES: (
        "learning science",
        "learning theory",
        "mayer",
    ),
    SemanticDesignDomain.SCIENTIFIC_VISUALIZATION: (
        "scientific visualization",
        "data visualization",
    ),
    SemanticDesignDomain.KNOWLEDGE_GRAPH_VISUALIZATION: (
        "knowledge graph visualization",
        "node-link",
    ),
    SemanticDesignDomain.SCIENTIFIC_COMMUNICATION: (
        "scientific communication",
        "communicate uncertainty",
    ),
}
EDUCATION_TERMS = {
    EducationalClassification.BLOOM: ("bloom", "taxonomy of learning"),
    EducationalClassification.MAYER_MULTIMEDIA_LEARNING: (
        "mayer",
        "multimedia learning",
    ),
    EducationalClassification.COGNITIVE_LOAD_THEORY: ("cognitive load",),
    EducationalClassification.UNIVERSAL_DESIGN_FOR_LEARNING: (
        "universal design for learning",
        "udl",
    ),
    EducationalClassification.ACTIVE_LEARNING: ("active learning",),
    EducationalClassification.INQUIRY_LEARNING: ("inquiry learning", "inquiry-based"),
}
KNOWLEDGE_TERMS = {
    "DESIGN_PRINCIPLE": ("principle",),
    "PATTERN": ("pattern",),
    "ANTI_PATTERN": ("anti-pattern", "avoid", "do not"),
    "GUIDELINE": ("guideline", "should", "recommend"),
    "BEST_PRACTICE": ("best practice",),
    "STANDARD": ("standard", "conformance"),
    "ACCESSIBILITY_REQUIREMENT": ("wcag", "accessibility requirement", "must"),
    "VISUALIZATION_TECHNIQUE": ("visualization", "visual encoding"),
    "INTERACTION_PATTERN": ("interaction pattern", "affordance"),
    "EDUCATIONAL_THEORY": ("learning theory", "cognitive load", "mayer", "bloom"),
}


def _contains(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


class SemanticDecomposer:
    VERSION = "089b-decomposition-1"

    def decompose(self, document: DesignDocument) -> tuple[SemanticUnit, ...]:
        lines = document.content.splitlines()
        units: list[SemanticUnit] = []
        parent: str | None = None
        in_code = False
        buffer: list[tuple[int, str]] = []
        current_parent = object()

        def emit(
            kind: SemanticUnitType,
            values: list[tuple[int, str]],
            parent_id: str | None | object = current_parent,
        ):
            if not values:
                return
            text = "\n".join(value for _, value in values).strip()
            if not text:
                return
            ordinal = len(units) + 1
            identity = f"{document.document_id}:{document.version}:{ordinal}:{text}"
            unit_id = hashlib.sha256(identity.encode()).hexdigest()
            units.append(
                SemanticUnit(
                    unit_id=unit_id,
                    document_id=document.document_id,
                    document_version=document.version,
                    ordinal=ordinal,
                    unit_type=kind,
                    text=text,
                    parent_unit_id=parent if parent_id is current_parent else parent_id,
                    source_location=SourceLocation(
                        format=document.document_type,
                        start=values[0][0],
                        end=values[-1][0],
                        locator={
                            "line_start": values[0][0],
                            "line_end": values[-1][0],
                            "anchor_ids": list(document.provenance.anchor_ids),
                        },
                        content_hash=hashlib.sha256(text.encode()).hexdigest(),
                    ),
                )
            )

        for number, raw in enumerate(lines, 1):
            line = raw.strip()
            if line.startswith("```"):
                if in_code:
                    emit(SemanticUnitType.CODE_EXAMPLE, buffer)
                    buffer = []
                in_code = not in_code
                continue
            if in_code:
                buffer.append((number, raw))
                continue
            if not line:
                emit(SemanticUnitType.PARAGRAPH, buffer)
                buffer = []
                continue
            if line.startswith("#"):
                emit(SemanticUnitType.PARAGRAPH, buffer)
                buffer = []
                emit(SemanticUnitType.HEADING, [(number, line.lstrip("# "))], None)
                parent = units[-1].unit_id
                continue
            kind = self._line_type(line)
            if kind is not SemanticUnitType.PARAGRAPH:
                emit(SemanticUnitType.PARAGRAPH, buffer)
                buffer = []
                emit(kind, [(number, line)])
            else:
                buffer.append((number, line))
        emit(
            SemanticUnitType.CODE_EXAMPLE if in_code else SemanticUnitType.PARAGRAPH,
            buffer,
        )
        return tuple(units)

    @staticmethod
    def _line_type(line: str) -> SemanticUnitType:
        lowered = line.casefold()
        if re.match(r"^[-*+]\s+", line):
            return SemanticUnitType.BULLET_LIST
        if re.match(r"^\d+[.)]\s+", line):
            return SemanticUnitType.NUMBERED_PROCEDURE
        if line.startswith(">"):
            return SemanticUnitType.QUOTED_GUIDANCE
        if "|" in line:
            return SemanticUnitType.TABLE
        if re.match(r"^(figure|table)\s+\d+[:.]", lowered):
            return SemanticUnitType.CAPTION
        if lowered.startswith(("warning:", "caution:")):
            return SemanticUnitType.WARNING
        if "anti-pattern" in lowered:
            return SemanticUnitType.ANTI_PATTERN
        if "best practice" in lowered:
            return SemanticUnitType.BEST_PRACTICE
        if any(word in lowered for word in ("recommend", "should", "must")):
            return SemanticUnitType.RECOMMENDATION
        return SemanticUnitType.PARAGRAPH


class MemoryDesignKnowledgeRepository:
    def __init__(self) -> None:
        self.units: list[SemanticUnit] = []
        self.relationships: list[DesignRelationship] = []
        self.audit_events: list[dict] = []

    def append_units(self, units: Iterable[SemanticUnit]) -> None:
        existing = {item.unit_id for item in self.units}
        for unit in units:
            if unit.unit_id not in existing:
                self.units.append(unit)
                existing.add(unit.unit_id)
                self.audit_events.append(
                    {"event": "SEMANTIC_UNIT_APPENDED", "unit_id": unit.unit_id}
                )

    def append_relationships(self, values: Iterable[DesignRelationship]) -> None:
        existing = {item.relationship_id for item in self.relationships}
        for value in values:
            if value.relationship_id not in existing:
                self.relationships.append(value)
                existing.add(value.relationship_id)
                self.audit_events.append(
                    {
                        "event": "DESIGN_RELATIONSHIP_APPENDED",
                        "relationship_id": value.relationship_id,
                    }
                )


class DesignReasoningService:
    CLASSIFIER_VERSION = "089b-rules-1"
    RELATIONSHIP_VERSION = "089b-relationships-1"

    def __init__(
        self, repository=None, provider: EmbeddingProvider | None = None
    ) -> None:
        self.repository = repository or MemoryDesignKnowledgeRepository()
        self.provider = provider or DeterministicLocalProvider(dimension=32)
        self.decomposer = SemanticDecomposer()

    def index_document(self, document: DesignDocument) -> tuple[SemanticUnit, ...]:
        raw_units = self.decomposer.decompose(document)
        vectors = self.provider.embed_batch([unit.text for unit in raw_units])
        units = tuple(
            self._enrich(unit, vector)
            for unit, vector in zip(raw_units, vectors, strict=True)
        )
        self.repository.append_units(units)
        self.repository.append_relationships(self._relationships(units))
        return units

    def _enrich(self, unit: SemanticUnit, vector: list[float]) -> SemanticUnit:
        text = unit.text.casefold()
        domains = tuple(
            sorted(
                (
                    key
                    for key, terms in DOMAIN_TERMS.items()
                    if any(_contains(text, term) for term in terms)
                ),
                key=str,
            )
        )
        education = tuple(
            sorted(
                (
                    key
                    for key, terms in EDUCATION_TERMS.items()
                    if any(_contains(text, term) for term in terms)
                ),
                key=str,
            )
        )
        types = tuple(
            sorted(
                key
                for key, terms in KNOWLEDGE_TERMS.items()
                if any(_contains(text, term) for term in terms)
            )
        )
        evidence = tuple(
            sorted(
                {
                    term
                    for terms in (
                        *DOMAIN_TERMS.values(),
                        *EDUCATION_TERMS.values(),
                        *KNOWLEDGE_TERMS.values(),
                    )
                    for term in terms
                    if _contains(text, term)
                }
            )
        )
        confidence = (
            round(min(0.99, 0.55 + 0.04 * len(evidence)), 3) if evidence else 0.35
        )
        return SemanticUnit(
            **{
                **unit.__dict__,
                "domains": domains,
                "educational_classifications": education,
                "knowledge_types": types,
                "classification_confidence": confidence,
                "classification_evidence": evidence,
                "embedding": tuple(vector),
                "embedding_metadata": dict(self.provider.metadata),
            }
        )

    def _relationships(
        self, units: tuple[SemanticUnit, ...]
    ) -> tuple[DesignRelationship, ...]:
        output = []
        for index, source in enumerate(units):
            for target in units[index + 1 :]:
                shared = set(source.domains).intersection(target.domains) | set(
                    source.knowledge_types
                ).intersection(target.knowledge_types)
                explicit = self._explicit_relationship(source.text, target.text)
                if not shared and explicit is None:
                    continue
                relation = explicit or RelationshipType.RELATED_TO
                identity = f"{source.unit_id}:{target.unit_id}:{relation.value}:{self.RELATIONSHIP_VERSION}"
                output.append(
                    DesignRelationship(
                        relationship_id=hashlib.sha256(identity.encode()).hexdigest(),
                        source_unit_id=source.unit_id,
                        target_unit_id=target.unit_id,
                        relationship_type=relation,
                        confidence=0.9 if explicit else 0.72,
                        rationale="explicit relationship cue"
                        if explicit
                        else "shared classified concepts",
                        provenance={
                            "source": asdict(source.source_location),
                            "target": asdict(target.source_location),
                        },
                    )
                )
        return tuple(output)

    @staticmethod
    def _explicit_relationship(left: str, right: str) -> RelationshipType | None:
        text = f"{left} {right}".casefold()
        cues = {
            "contradict": RelationshipType.CONTRADICTS,
            "requires": RelationshipType.REQUIRES,
            "supports": RelationshipType.SUPPORTS,
            "extends": RelationshipType.EXTENDS,
            "specializes": RelationshipType.SPECIALIZES,
            "improves": RelationshipType.IMPROVES,
            "used by": RelationshipType.USED_BY,
            "references": RelationshipType.REFERENCES,
        }
        return next((kind for cue, kind in cues.items() if cue in text), None)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        domains: tuple[SemanticDesignDomain, ...] = (),
        classifications: tuple[str, ...] = (),
        citation: str | None = None,
    ) -> dict:
        normalized = " ".join(query.split()).casefold()
        if not normalized or not 1 <= limit <= 100:
            raise ValueError("INVALID_DESIGN_REASONING_QUERY")
        query_vector = self.provider.embed_batch([normalized])[0]
        terms = set(re.findall(r"[a-z0-9]+", normalized))
        relationships_by_unit: dict[str, list[DesignRelationship]] = {}
        for relationship in self.repository.relationships:
            relationships_by_unit.setdefault(relationship.source_unit_id, []).append(relationship)
            relationships_by_unit.setdefault(relationship.target_unit_id, []).append(relationship)
        ranked = []
        for unit in self.repository.units:
            if domains and not set(domains).intersection(unit.domains):
                continue
            if classifications and not set(classifications).intersection(
                unit.knowledge_types
            ):
                continue
            if (
                citation
                and citation.casefold()
                not in str(unit.source_location.locator).casefold()
            ):
                continue
            words = set(re.findall(r"[a-z0-9]+", unit.text.casefold()))
            lexical = len(terms.intersection(words)) / max(1, len(terms))
            semantic = max(
                0.0,
                sum(a * b for a, b in zip(query_vector, unit.embedding, strict=True)),
            )
            score = round(
                0.45 * lexical
                + 0.35 * semantic
                + 0.20 * unit.classification_confidence,
                6,
            )
            if score <= 0:
                continue
            related = relationships_by_unit.get(unit.unit_id, [])
            ranked.append((score, unit, related, lexical, semantic))
        ranked.sort(
            key=lambda item: (
                -item[0],
                item[1].document_id,
                item[1].ordinal,
                item[1].unit_id,
            )
        )
        return {
            "query": query,
            "total": len(ranked),
            "results": [
                {
                    "unit_id": unit.unit_id,
                    "document_id": unit.document_id,
                    "text": unit.text,
                    "confidence": score,
                    "classification": {
                        "domains": [x.value for x in unit.domains],
                        "educational": [
                            x.value for x in unit.educational_classifications
                        ],
                        "knowledge_types": list(unit.knowledge_types),
                    },
                    "supporting_citations": [asdict(unit.source_location)],
                    "provenance": asdict(unit.source_location),
                    "related_concepts": [
                        {
                            "relationship": rel.relationship_type.value,
                            "unit_id": rel.target_unit_id
                            if rel.source_unit_id == unit.unit_id
                            else rel.source_unit_id,
                            "provenance": rel.provenance,
                        }
                        for rel in related
                    ],
                    "explanation": {
                        "lexical": round(lexical, 6),
                        "semantic": round(semantic, 6),
                        "classification": unit.classification_confidence,
                        "formula": "0.45 lexical + 0.35 semantic + 0.20 classification",
                    },
                }
                for score, unit, related, lexical, semantic in ranked[:limit]
            ],
        }
