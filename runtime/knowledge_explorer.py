"""Governed candidate-only Knowledge Explorer for CALYX issue #444.

The explorer resolves reviewed fixture concepts and synonyms into compact/expanded
educational payloads. All scientific content remains candidate/review-required; this
module cannot publish science or mutate the production Knowledge Graph.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

KNOWLEDGE_EXPLORER_SCHEMA = "calyx-knowledge-explorer/v1"
LEVELS = ("plain", "learner", "advanced")
RELATIONSHIPS = {"part_of", "supports_function", "associated_with", "contrasts_with"}


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def explorer_root() -> Path:
    return Path(os.getenv("CALYX_KNOWLEDGE_EXPLORER_DIR", "/tmp/calyx/knowledge-explorer"))


@dataclass(frozen=True)
class EvidenceSpan:
    evidence_id: str
    source_uri: str
    source_title: str
    text: str
    locator: dict[str, Any]
    checksum_sha256: str


@dataclass(frozen=True)
class ConceptImage:
    image_id: str
    source_uri: str
    license: str
    attribution: str
    alt_text: str


@dataclass(frozen=True)
class Figure:
    figure_id: str
    title: str
    description: str
    image_id: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Relationship:
    relationship_id: str
    source_concept_id: str
    predicate: str
    target_concept_id: str
    evidence_ids: tuple[str, ...]


class KnowledgeExplorerService:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace or explorer_root()

    def _path(self, concept_id: str) -> Path:
        clean = _text(concept_id)
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("KNOWLEDGE_CONCEPT_ID_INVALID")
        return self.workspace / "concepts" / f"{clean}.json"

    def register_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        concept_id = _text(payload.get("concept_id"))
        preferred_term = _text(payload.get("preferred_term"))
        synonyms = sorted({_text(item) for item in payload.get("synonyms", []) if _text(item)}, key=str.casefold)
        definitions = {level: _text((payload.get("definitions") or {}).get(level)) for level in LEVELS}
        if not concept_id or not preferred_term or any(not definitions[level] for level in LEVELS):
            raise ValueError("KNOWLEDGE_CONCEPT_FIELDS_REQUIRED")

        evidence: list[dict[str, Any]] = []
        evidence_ids: set[str] = set()
        for item in payload.get("evidence_spans", []):
            source_uri = _text(item.get("source_uri"))
            source_title = _text(item.get("source_title"))
            text = str(item.get("text") or "").strip()
            locator = dict(item.get("locator") or {})
            if ":" not in source_uri or not source_title or not text or not locator:
                raise ValueError("KNOWLEDGE_EVIDENCE_FIELDS_REQUIRED")
            checksum = _sha(text)
            evidence_id = _text(item.get("evidence_id")) or f"evidence-{checksum[:20]}"
            if evidence_id in evidence_ids:
                raise ValueError("KNOWLEDGE_DUPLICATE_EVIDENCE_ID")
            evidence_ids.add(evidence_id)
            evidence.append(asdict(EvidenceSpan(evidence_id, source_uri, source_title, text, locator, checksum)))
        if not evidence:
            raise ValueError("KNOWLEDGE_EVIDENCE_REQUIRED")

        images: list[dict[str, Any]] = []
        image_ids: set[str] = set()
        for item in payload.get("images", []):
            image = ConceptImage(
                image_id=_text(item.get("image_id")),
                source_uri=_text(item.get("source_uri")),
                license=_text(item.get("license")),
                attribution=_text(item.get("attribution")),
                alt_text=_text(item.get("alt_text")),
            )
            if not all(asdict(image).values()) or ":" not in image.source_uri:
                raise ValueError("KNOWLEDGE_IMAGE_FIELDS_REQUIRED")
            if image.image_id in image_ids:
                raise ValueError("KNOWLEDGE_DUPLICATE_IMAGE_ID")
            image_ids.add(image.image_id)
            images.append(asdict(image))

        figures: list[dict[str, Any]] = []
        for item in payload.get("figures", []):
            figure = Figure(
                figure_id=_text(item.get("figure_id")),
                title=_text(item.get("title")),
                description=_text(item.get("description")),
                image_id=_text(item.get("image_id")) or None,
                evidence_ids=tuple(_text(v) for v in item.get("evidence_ids", []) if _text(v)),
            )
            if not figure.figure_id or not figure.title or not figure.description or not figure.evidence_ids:
                raise ValueError("KNOWLEDGE_FIGURE_FIELDS_REQUIRED")
            if not set(figure.evidence_ids) <= evidence_ids:
                raise ValueError("KNOWLEDGE_FIGURE_EVIDENCE_UNKNOWN")
            if figure.image_id and figure.image_id not in image_ids:
                raise ValueError("KNOWLEDGE_FIGURE_IMAGE_UNKNOWN")
            figures.append(asdict(figure))

        relationships: list[dict[str, Any]] = []
        for item in payload.get("relationships", []):
            predicate = _text(item.get("predicate")).casefold()
            target = _text(item.get("target_concept_id"))
            rel_evidence = tuple(_text(v) for v in item.get("evidence_ids", []) if _text(v))
            if predicate not in RELATIONSHIPS or not target or not rel_evidence or not set(rel_evidence) <= evidence_ids:
                raise ValueError("KNOWLEDGE_RELATIONSHIP_INVALID")
            material = _stable({"source": concept_id, "predicate": predicate, "target": target})
            relationship_id = _text(item.get("relationship_id")) or f"rel-{_sha(material)[:20]}"
            relationships.append(
                asdict(Relationship(relationship_id, concept_id, predicate, target, rel_evidence))
            )

        canonical = {
            "schema_version": KNOWLEDGE_EXPLORER_SCHEMA,
            "concept_id": concept_id,
            "preferred_term": preferred_term,
            "synonyms": synonyms,
            "definitions": definitions,
            "evidence_spans": evidence,
            "images": images,
            "figures": figures,
            "relationships": relationships,
            "candidate_only": True,
            "scientific_review_required": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        canonical["candidate_sha256"] = _sha(_stable(canonical))
        path = self._path(concept_id)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != canonical:
                raise ValueError("KNOWLEDGE_CONCEPT_IMMUTABLE_CONFLICT")
            return {"created": False, "concept": existing}
        _atomic(path, canonical)
        return {"created": True, "concept": canonical}

    def get(self, concept_id: str) -> dict[str, Any]:
        path = self._path(concept_id)
        if not path.exists():
            raise FileNotFoundError(f"knowledge concept not found: {concept_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_concepts(self) -> list[dict[str, Any]]:
        directory = self.workspace / "concepts"
        if not directory.exists():
            return []
        records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]
        return sorted(records, key=lambda item: item["preferred_term"].casefold())

    def resolve(self, term: str) -> dict[str, Any]:
        normalized = _text(term).casefold()
        if not normalized:
            raise ValueError("KNOWLEDGE_TERM_REQUIRED")
        matches = []
        for concept in self.list_concepts():
            names = {concept["preferred_term"].casefold(), *(item.casefold() for item in concept["synonyms"])}
            if normalized in names:
                matches.append(concept)
        if len(matches) == 1:
            concept = matches[0]
            return {
                "state": "matched",
                "concept_id": concept["concept_id"],
                "preferred_term": concept["preferred_term"],
                "matched_term": term,
                "candidate_only": True,
                "scientific_review_required": True,
            }
        if len(matches) > 1:
            return {
                "state": "ambiguous",
                "concept_ids": sorted(item["concept_id"] for item in matches),
                "matched_term": term,
                "candidate_only": True,
                "scientific_review_required": True,
            }
        return {
            "state": "unmatched",
            "concept_ids": [],
            "matched_term": term,
            "candidate_only": True,
            "scientific_review_required": True,
        }

    def popover(self, term: str, *, level: str = "plain") -> dict[str, Any]:
        if level not in LEVELS:
            raise ValueError("KNOWLEDGE_DEFINITION_LEVEL_INVALID")
        resolution = self.resolve(term)
        if resolution["state"] != "matched":
            return {**resolution, "popover": None}
        concept = self.get(resolution["concept_id"])
        return {
            **resolution,
            "popover": {
                "preferred_term": concept["preferred_term"],
                "definition": concept["definitions"][level],
                "definition_level": level,
                "synonyms": concept["synonyms"],
                "evidence_count": len(concept["evidence_spans"]),
                "relationship_count": len(concept["relationships"]),
            },
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    def expanded(self, concept_id: str) -> dict[str, Any]:
        concept = self.get(concept_id)
        connected = []
        for relationship in concept["relationships"]:
            try:
                target = self.get(relationship["target_concept_id"])
            except FileNotFoundError:
                target = None
            connected.append(
                {
                    **relationship,
                    "target_preferred_term": target["preferred_term"] if target else None,
                    "target_available": target is not None,
                }
            )
        return {
            "concept": concept,
            "connected_concepts": connected,
            "candidate_only": True,
            "scientific_review_required": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    def readiness(self) -> dict[str, Any]:
        concepts = self.list_concepts()
        return {
            "schema_version": KNOWLEDGE_EXPLORER_SCHEMA,
            "concepts": len(concepts),
            "evidence_spans": sum(len(item["evidence_spans"]) for item in concepts),
            "images": sum(len(item["images"]) for item in concepts),
            "figures": sum(len(item["figures"]) for item in concepts),
            "relationships": sum(len(item["relationships"]) for item in concepts),
            "candidate_only": True,
            "scientific_review_required": True,
            "scientific_publication_authorized": False,
            "production_deployment_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "decision": "KNOWLEDGE_EXPLORER_REVIEW_READY" if concepts else "NO_CONCEPTS",
        }
