from __future__ import annotations

import hashlib
import json

from .models import BrainObject, BrainRelationship, BrainSnapshot, SearchHit


class CanonicalBrainRegistry:
    def __init__(self) -> None:
        self._objects: dict[str, BrainObject] = {}
        self._relationships: dict[str, BrainRelationship] = {}

    def register_object(self, record: BrainObject) -> BrainObject:
        existing = self._objects.get(record.object_id)
        if existing and existing != record:
            raise ValueError(f"conflicting Brain object identity: {record.object_id}")
        self._objects[record.object_id] = record
        return record

    def register_relationship(self, relation: BrainRelationship) -> BrainRelationship:
        if relation.subject_id not in self._objects or relation.object_id not in self._objects:
            raise ValueError("Brain relationships require registered endpoints")
        existing = self._relationships.get(relation.relationship_id)
        if existing and existing != relation:
            raise ValueError(f"conflicting Brain relationship identity: {relation.relationship_id}")
        self._relationships[relation.relationship_id] = relation
        return relation

    def get(self, object_id: str) -> BrainObject | None:
        return self._objects.get(object_id)

    def search(self, query: str) -> list[SearchHit]:
        terms = [term for term in query.casefold().split() if term]
        hits: list[SearchHit] = []
        weights = {
            "title": 4,
            "summary": 2,
            "aliases": 3,
            "tags": 2,
            "type": 1,
        }
        for record in self._objects.values():
            fields = {
                "title": record.title.casefold(),
                "summary": record.summary.casefold(),
                "aliases": " ".join(record.aliases).casefold(),
                "tags": " ".join(record.tags).casefold(),
                "type": record.object_type.casefold(),
            }
            matched_terms: set[str] = set()
            matched: list[str] = []
            score = 0
            for name, value in fields.items():
                field_hits = {term for term in terms if term in value}
                if not field_hits:
                    continue
                matched.append(name)
                matched_terms.update(field_hits)
                score += len(field_hits) * weights[name]
            if matched:
                score += len(matched_terms) * 10
                hits.append(SearchHit(
                    object_id=record.object_id,
                    title=record.title,
                    object_type=record.object_type,
                    lifecycle=record.lifecycle,
                    score=score,
                    matched_fields=sorted(matched),
                ))
        _type_rank = {"architecture": 0, "intent": 1, "build": 2, "decision": 3}
        return sorted(
            hits,
            key=lambda item: (-item.score, _type_rank.get(item.object_type, 9), item.title.casefold(), item.object_id),
        )

    def related(self, object_id: str, relationship_type: str | None = None) -> list[BrainObject]:
        related_ids: set[str] = set()
        for relation in self._relationships.values():
            if relationship_type and relation.relationship_type != relationship_type:
                continue
            if relation.subject_id == object_id:
                related_ids.add(relation.object_id)
            elif relation.object_id == object_id:
                related_ids.add(relation.subject_id)
        return [self._objects[item_id] for item_id in sorted(related_ids)]

    def aligned_intents(self, object_id: str) -> list[BrainObject]:
        return [
            record for record in self.related(object_id, "aligned_to")
            if record.object_type == "intent"
        ]

    def snapshot(self) -> BrainSnapshot:
        objects = sorted(self._objects.values(), key=lambda item: item.object_id)
        relationships = sorted(self._relationships.values(), key=lambda item: item.relationship_id)
        payload = {
            "objects": [item.model_dump(mode="json") for item in objects],
            "relationships": [item.model_dump(mode="json") for item in relationships],
        }
        checksum = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return BrainSnapshot(objects=objects, relationships=relationships, snapshot_checksum=checksum)
