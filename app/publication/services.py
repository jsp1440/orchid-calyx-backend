from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.knowledge_graph.vocabulary import EDGE_TYPE_DOMAIN, NODE_TYPE_DOMAIN

from .repositories import digest_manifest


ENTITY_NODE_TYPES = {
    "TAXON": "taxon",
    "TRAIT": "trait",
    "HABITAT": "habitat",
    "POLLINATOR": "pollinator",
    "MYCORRHIZA": "fungus",
    "GEOGRAPHY": "place",
    "LITERATURE": "publication",
    "MEDIA": "image",
}
TAXON_ATTACHMENT_KEYS = {"world_plants_id", "world_plants_taxon_id", "canonical_taxon_id"}


@dataclass(frozen=True)
class PublicationPlan:
    source_scope: dict[str, Any]
    manifest: dict[str, Any]
    manifest_digest: str
    items: list[dict[str, Any]]
    blockers: list[dict[str, Any]]


class PublicationService:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan = self._plan(payload)
        existing = self.repository.existing_publication("DRY_RUN", plan.manifest_digest)
        if existing and existing["status"] in {"DRY_RUN_COMPLETE", "BLOCKED"}:
            items = self.repository.read_run_items(existing["id"])
            return self._response(existing, items, self._blockers_from_items(items))
        result = self.repository.record_dry_run(self._run_payload(payload, plan), plan.items)
        return self._response(result["run"], result["items"], plan.blockers)

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload.get("approval_reference"):
            raise ValueError("HUMAN_APPROVAL_REQUIRED")
        if not payload.get("publication_authority"):
            raise ValueError("PUBLICATION_AUTHORITY_REQUIRED")
        plan = self._plan(payload)
        if plan.blockers:
            raise ValueError("PUBLICATION_BLOCKED")
        existing = self.repository.existing_publication("PUBLISH", plan.manifest_digest)
        if existing and existing["status"] == "PUBLISHED":
            items = self.repository.read_run_items(existing["id"])
            return self._response(existing, items, [])
        result = self.repository.publish(self._run_payload(payload, plan), plan.items)
        return self._response(result["run"], result["items"], [])

    def rollback(self, run_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.rollback_run(run_id, payload["actor"], payload["reason"], payload["strategy"])

    def _plan(self, payload: dict[str, Any]) -> PublicationPlan:
        scope = {k: v for k, v in payload["scope"].items() if v is not None}
        candidate_ids = self.repository.candidate_ids_for_scope(scope)
        if not candidate_ids:
            raise LookupError("NO_PUBLICATION_CANDIDATES")

        candidates = [self.repository.load_candidate(candidate_id) for candidate_id in candidate_ids]
        missing = [candidate_ids[index] for index, item in enumerate(candidates) if item is None]
        if missing:
            raise LookupError(f"PUBLICATION_CANDIDATE_NOT_FOUND:{missing[0]}")

        entity_node_ids: dict[int, int | None] = {}
        planned_entity_keys: dict[int, str] = {}
        items: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []

        for candidate in candidates:
            if candidate["kind"] == "ENTITY":
                item = self._entity_item(candidate, payload)
                planned_entity_keys[int(candidate["id"])] = item["canonical_key"]
                existing = self.repository.get_node_by_key(item["canonical_key"])
                if existing and existing.get("node_type") != item["node_type"]:
                    item["blockers"].append("CANONICAL_NODE_TYPE_CONFLICT")
                    item["conflict_keys"].append(item["canonical_key"])
                elif existing:
                    item["action"] = "LINK_EXISTING_NODE"
                    entity_node_ids[int(candidate["id"])] = int(existing["kg_node_id"])
                else:
                    entity_node_ids[int(candidate["id"])] = None
                self._finalize_item_state(item)
                items.append(item)
                if item["blockers"]:
                    blockers.append({"candidate_id": item["candidate_id"], "blockers": item["blockers"]})

        for candidate in candidates:
            if candidate["kind"] == "RELATIONSHIP":
                item = self._relationship_item(candidate, payload, entity_node_ids, planned_entity_keys)
                self._finalize_item_state(item)
                items.append(item)
                if item["blockers"]:
                    blockers.append({"candidate_id": item["candidate_id"], "blockers": item["blockers"]})

        manifest_items = [
            {
                "candidate_id": item["candidate_id"],
                "item_type": item["item_type"],
                "canonical_key": item["canonical_key"],
                "blockers": item["blockers"],
            }
            for item in items
        ]
        manifest = {
            "build": "BUILD-078",
            "source_scope": scope,
            "candidate_ids": candidate_ids,
            "items": manifest_items,
            "approval_reference": payload.get("approval_reference"),
            "publication_authority": payload.get("publication_authority"),
        }
        digest = digest_manifest(manifest)
        for item in items:
            item["manifest_digest"] = digest
        return PublicationPlan(scope, manifest, digest, items, blockers)

    def _entity_item(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        blockers = self._common_blockers(candidate)
        ontology_type = candidate.get("ontology_type")
        term_type = candidate.get("term_type")
        node_type = ENTITY_NODE_TYPES.get(term_type) or ENTITY_NODE_TYPES.get(ontology_type) or "glossary_term"
        external_ids = candidate.get("external_ids") or {}
        if node_type not in NODE_TYPE_DOMAIN:
            blockers.append("UNSUPPORTED_NODE_TYPE")
        if candidate.get("resolution_status") != "ACCEPTED" or not candidate.get("ontology_term_id"):
            blockers.append("ONTOLOGY_RESOLUTION_NOT_ACCEPTED")
        if candidate.get("registry_status") != "ACTIVE" or candidate.get("term_status") != "ACTIVE":
            blockers.append("ONTOLOGY_TERM_NOT_ACTIVE")
        if (ontology_type == "TAXONOMY" or term_type == "TAXON") and not any(external_ids.get(key) for key in TAXON_ATTACHMENT_KEYS):
            blockers.append("CANONICAL_TAXON_ATTACHMENT_MISSING")
        canonical_key = f"ontology:{candidate.get('namespace')}:{candidate.get('version')}:{candidate.get('term_canonical_key')}"
        return {
            "candidate_id": int(candidate["id"]),
            "item_type": "ENTITY",
            "state": "READY",
            "action": "INSERT_NODE",
            "canonical_key": canonical_key,
            "node_type": node_type,
            "display_label": candidate.get("preferred_label") or candidate.get("name"),
            "evidence_class": "accepted_ontology_resolution",
            "confidence_score": candidate.get("resolution_confidence") or candidate.get("confidence"),
            "confidence_label": "human_accepted",
            "payload": {
                "candidate": self._candidate_identity(candidate),
                "ontology": {
                    "term_id": candidate.get("ontology_term_id"),
                    "namespace": candidate.get("namespace"),
                    "version": candidate.get("version"),
                    "canonical_key": candidate.get("term_canonical_key"),
                    "external_ids": external_ids,
                    "metadata": candidate.get("term_metadata") or {},
                },
            },
            "blockers": blockers,
            "conflict_keys": [],
            "provenance": self._provenance(candidate, payload),
            "audit_action": "DRY_RUN_ENTITY" if blockers else "PLAN_ENTITY",
        }

    def _relationship_item(
        self,
        candidate: dict[str, Any],
        payload: dict[str, Any],
        entity_node_ids: dict[int, int | None],
        planned_entity_keys: dict[int, str],
    ) -> dict[str, Any]:
        blockers = self._common_blockers(candidate)
        edge_type = str(candidate.get("predicate") or "").strip().lower().replace(" ", "_")
        if edge_type not in EDGE_TYPE_DOMAIN:
            blockers.append("UNSUPPORTED_EDGE_TYPE")
        if candidate.get("evidence_validation_status") != "VALID":
            blockers.append("EVIDENCE_NOT_VALID")
        subject_id = int(candidate["subject_candidate_id"]) if candidate.get("subject_candidate_id") else None
        object_id = int(candidate["object_candidate_id"]) if candidate.get("object_candidate_id") else None
        from_node_id = entity_node_ids.get(subject_id) if subject_id is not None else None
        to_node_id = entity_node_ids.get(object_id) if object_id is not None else None
        if subject_id not in planned_entity_keys and from_node_id is None:
            blockers.append("SUBJECT_NOT_IN_PUBLICATION_SCOPE")
        if object_id not in planned_entity_keys and to_node_id is None:
            blockers.append("OBJECT_NOT_IN_PUBLICATION_SCOPE")
        canonical_key = f"relationship:{subject_id}:{edge_type}:{object_id}:evidence:{candidate.get('evidence_id')}"
        return {
            "candidate_id": int(candidate["id"]),
            "item_type": "RELATIONSHIP",
            "state": "READY",
            "action": "INSERT_EDGE",
            "canonical_key": canonical_key,
            "edge_type": edge_type,
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "from_canonical_key": planned_entity_keys.get(subject_id),
            "to_canonical_key": planned_entity_keys.get(object_id),
            "evidence_class": "validated_evidence",
            "confidence_score": candidate.get("confidence"),
            "confidence_label": "human_accepted",
            "payload": {
                "candidate": self._candidate_identity(candidate),
                "relationship": {
                    "subject_candidate_id": subject_id,
                    "predicate": edge_type,
                    "object_candidate_id": object_id,
                    "evidence_id": candidate.get("evidence_id"),
                    "evidence_hash": candidate.get("evidence_hash"),
                },
            },
            "blockers": blockers,
            "conflict_keys": [],
            "provenance": self._provenance(candidate, payload),
            "audit_action": "DRY_RUN_RELATIONSHIP" if blockers else "PLAN_RELATIONSHIP",
        }

    def _common_blockers(self, candidate: dict[str, Any]) -> list[str]:
        blockers: list[str] = []
        if candidate.get("review_status") != "ACCEPTED":
            blockers.append("CANDIDATE_NOT_ACCEPTED")
        if candidate.get("session_stage") != "READY_FOR_REVIEW":
            blockers.append("SESSION_NOT_READY_FOR_REVIEW")
        if not candidate.get("ready_for_publication"):
            blockers.append("READINESS_NOT_ACCEPTED")
        for blocker in candidate.get("readiness_blockers") or []:
            if blocker not in blockers:
                blockers.append(str(blocker))
        return blockers

    @staticmethod
    def _finalize_item_state(item: dict[str, Any]) -> None:
        if item["blockers"]:
            item["state"] = "BLOCKED"
            item["action"] = "BLOCKED"

    @staticmethod
    def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate["id"],
            "session_id": candidate["session_id"],
            "kind": candidate["kind"],
            "review_status": candidate["review_status"],
        }

    @staticmethod
    def _provenance(candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "build": "BUILD-078",
            "source": "controlled-publication-gate",
            "actor": payload["actor"],
            "approval_reference": payload.get("approval_reference"),
            "publication_authority": payload.get("publication_authority"),
            "candidate": PublicationService._candidate_identity(candidate),
            "session_provenance": candidate.get("session_provenance") or {},
            "resolution_id": candidate.get("resolution_id"),
            "evidence_id": candidate.get("evidence_id"),
        }

    @staticmethod
    def _run_payload(payload: dict[str, Any], plan: PublicationPlan) -> dict[str, Any]:
        return {
            "actor": payload["actor"],
            "reason": payload["reason"],
            "approval_reference": payload.get("approval_reference"),
            "publication_authority": payload.get("publication_authority"),
            "dry_run_run_id": payload.get("dry_run_run_id"),
            "source_scope": plan.source_scope,
            "manifest": plan.manifest,
            "manifest_digest": plan.manifest_digest,
        }

    @staticmethod
    def _blockers_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"candidate_id": item["candidate_id"], "blockers": item["blockers"]} for item in items if item.get("blockers")]

    @staticmethod
    def _response(run: dict[str, Any], items: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "run_id": int(run["id"]),
            "mode": run["mode"],
            "status": run["status"],
            "manifest_digest": run["manifest_digest"],
            "canonical_graph_mutated": bool(run["canonical_graph_mutated"]),
            "counts": {
                "items": int(run.get("item_count") or len(items)),
                "ready": int(run.get("ready_count") or sum(1 for item in items if item.get("state") in {"READY", "DRY_RUN_COMPLETE", "PUBLISHED"})),
                "blocked": int(run.get("blocked_count") or len(blockers)),
                "inserted_nodes": int(run.get("inserted_node_count") or 0),
                "linked_nodes": int(run.get("linked_node_count") or 0),
                "inserted_edges": int(run.get("inserted_edge_count") or 0),
                "linked_edges": int(run.get("linked_edge_count") or 0),
            },
            "blockers": blockers,
            "items": [dict(item) for item in items],
        }
