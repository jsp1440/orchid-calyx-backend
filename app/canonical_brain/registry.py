from __future__ import annotations

import hashlib
import json

from .models import BrainObject, BrainRelationship, BrainSnapshot, SearchHit

_SEARCH_TYPE_PRIORITY = {
    "architecture": 0,
    "intent": 1,
    "decision": 2,
}


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
        for record in self._objects.values():
            fields = {
                "title": record.title.casefold(),
                "summary": record.summary.casefold(),
                "aliases": " ".join(record.aliases).casefold(),
                "tags": " ".join(record.tags).casefold(),
                "type": record.object_type.casefold(),
            }
            matched_fields: set[str] = set()
            terms_matched: set[str] = set()
            score = 0
            for term in terms:
                best_score = 0
                best_field: str | None = None
                for name, value in fields.items():
                    if term in value:
                        field_score = 4 if name == "title" else 3 if name == "aliases" else 1
                        if field_score > best_score:
                            best_score = field_score
                            best_field = name
                if best_field is not None:
                    score += best_score
                    matched_fields.add(best_field)
                    terms_matched.add(term)
            score += len(terms_matched) * 3
            matched = sorted(matched_fields)
            if matched:
                hits.append(
                    SearchHit(
                        object_id=record.object_id,
                        title=record.title,
                        object_type=record.object_type,
                        lifecycle=record.lifecycle,
                        score=score,
                        matched_fields=matched,
                    )
                )
        return sorted(
            hits,
            key=lambda item: (
                -item.score,
                _SEARCH_TYPE_PRIORITY.get(item.object_type, 10),
                item.title.casefold(),
                item.object_id,
            ),
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
            record
            for record in self.related(object_id, "aligned_to")
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
