import hashlib
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from typing import Any

from .interfaces import OntologyRepository
from .models import ReadinessResult, ResolutionMethod
from .normalizers import normalize_canonical_key, normalize_ontology_text
from .validators import ensure_no_hierarchy_cycle, require_provenance, validate_evidence_hash, validate_resolution_state


class DeterministicResolutionEngine:
    def __init__(self, fuzzy_threshold: float = 0.88) -> None:
        if not 0.75 <= fuzzy_threshold <= 1:
            raise ValueError("INVALID_FUZZY_THRESHOLD")
        self.fuzzy_threshold = fuzzy_threshold

    def suggestions(self, original: str, terms: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        normalized = normalize_ontology_text(original, scientific_name=True)
        ranked: list[dict[str, Any]] = []
        for term in terms:
            key = str(term["canonical_key"])
            label = str(term["preferred_label"])
            synonym = term.get("synonym")
            normalized_label = normalize_ontology_text(label, scientific_name=True)
            normalized_synonym = normalize_ontology_text(str(synonym), scientific_name=True) if synonym else None
            if original == key or original == label:
                method, score = ResolutionMethod.EXACT, 1.0
            elif normalized in {normalize_canonical_key(key), normalized_label}:
                method, score = ResolutionMethod.NORMALIZED, 0.98
            elif synonym and (original == synonym or normalized == normalized_synonym):
                method, score = ResolutionMethod.SYNONYM, 0.96
            else:
                score = max(SequenceMatcher(None, normalized, normalized_label).ratio(), SequenceMatcher(None, normalized, normalized_synonym or "").ratio())
                if score < self.fuzzy_threshold:
                    continue
                method = ResolutionMethod.FUZZY
            ranked.append({
                "ontology_term_id": int(term["id"]), "resolution_method": method.value,
                "confidence": round(score, 6), "status": "PROPOSED", "normalized_input": normalized,
                "matched_label": label, "ontology_namespace": term["namespace"], "ontology_version": term["version"],
                "explanation": {"original_input": original, "normalized_input": normalized, "matched_on": method.value, "score": round(score, 6)},
                "provenance": {"resolver": "deterministic-local-v1", "registry_id": term["registry_id"], "term_id": term["id"]},
            })
        precedence = {"EXACT": 0, "NORMALIZED": 1, "SYNONYM": 2, "FUZZY": 3}
        return sorted(ranked, key=lambda item: (precedence[item["resolution_method"]], -item["confidence"], item["ontology_term_id"]))


class OntologyRegistryService:
    def __init__(self, repository: OntologyRepository) -> None:
        self.repository = repository

    def create_registry(self, data: Mapping[str, Any]) -> dict[str, Any]:
        require_provenance(data.get("provenance", {}))
        return self.repository.create_registry(data, str(data["created_by"]))

    def update_draft_registry(self, registry_id: int, changes: Mapping[str, Any], actor: str, reason: str) -> dict[str, Any]:
        result = self.repository.update_registry(registry_id, changes, actor, reason)
        if result is None:
            raise LookupError("REGISTRY_NOT_FOUND")
        return result

    def activate_registry(self, registry_id: int, actor: str, reason: str) -> dict[str, Any]:
        result = self.repository.set_registry_status(registry_id, "ACTIVE", actor, reason)
        if result is None:
            raise LookupError("REGISTRY_NOT_FOUND")
        return result

    def deprecate_registry(self, registry_id: int, actor: str, reason: str) -> dict[str, Any]:
        result = self.repository.set_registry_status(registry_id, "DEPRECATED", actor, reason)
        if result is None:
            raise LookupError("REGISTRY_NOT_FOUND")
        return result

    def list_registries(self) -> list[dict[str, Any]]:
        return self.repository.list_registries()

    def get_registry(self, registry_id: int) -> dict[str, Any]:
        result = self.repository.get_registry(registry_id)
        if result is None:
            raise LookupError("REGISTRY_NOT_FOUND")
        return result


class OntologyTermService:
    def __init__(self, repository: OntologyRepository) -> None:
        self.repository = repository

    def create_term(self, data: Mapping[str, Any]) -> dict[str, Any]:
        parent = data.get("parent_term_id")
        if parent:
            parent_term = self.repository.get_term(int(parent))
            registry = self.repository.get_registry(int(data["registry_id"]))
            if parent_term is None or registry is None or parent_term["registry_id"] != registry["id"]:
                raise ValueError("INVALID_ONTOLOGY_PARENT")
        return self.repository.create_term({**data, "canonical_key": normalize_canonical_key(str(data["canonical_key"])), "normalized_label": normalize_ontology_text(str(data["preferred_label"]), scientific_name=data["term_type"] == "TAXON")}, str(data["actor"]))

    def update_draft_term(self, term_id: int, changes: Mapping[str, Any], actor: str, reason: str) -> dict[str, Any]:
        if changes.get("parent_term_id"):
            ensure_no_hierarchy_cycle(term_id, int(changes["parent_term_id"]), self.repository.hierarchy_ancestors(int(changes["parent_term_id"])))
        result = self.repository.update_term(term_id, changes, actor, reason)
        if result is None:
            raise LookupError("TERM_NOT_FOUND")
        return result

    def deprecate_term(self, term_id: int, replacement_term_id: int, actor: str, reason: str) -> dict[str, Any]:
        if term_id == replacement_term_id:
            raise ValueError("ONTOLOGY_SELF_REPLACEMENT")
        return self.update_draft_term(term_id, {"status": "DEPRECATED", "replacement_term_id": replacement_term_id}, actor, reason)

    def add_synonym(self, term_id: int, data: Mapping[str, Any]) -> dict[str, Any]:
        require_provenance(data.get("provenance", {}))
        if self.repository.get_term(term_id) is None:
            raise LookupError("TERM_NOT_FOUND")
        normalized = normalize_ontology_text(str(data["synonym"]), scientific_name=data["synonym_type"] == "SCIENTIFIC_NAME")
        return self.repository.add_synonym(term_id, {**data, "normalized_synonym": normalized}, str(data["actor"]))

    def search_terms(self, query: str, registry_id: int | None = None) -> list[dict[str, Any]]:
        normalized = normalize_ontology_text(query)
        return [item for item in self.repository.search_terms(normalized, registry_id) if normalized in normalize_ontology_text(str(item["canonical_key"])) or normalized in normalize_ontology_text(str(item["preferred_label"])) or (item.get("synonym") and normalized in normalize_ontology_text(str(item["synonym"])))]

    def get_term(self, term_id: int) -> dict[str, Any]:
        result = self.repository.get_term(term_id)
        if result is None:
            raise LookupError("TERM_NOT_FOUND")
        return result


class CandidateResolutionService:
    def __init__(self, repository: OntologyRepository) -> None:
        self.repository = repository

    def resolve_one(self, candidate_id: int, actor: str, fuzzy_threshold: float = 0.88) -> list[dict[str, Any]]:
        candidate = self.repository.get_entity_candidate(candidate_id)
        if candidate is None:
            raise LookupError("ENTITY_CANDIDATE_NOT_FOUND")
        terms = self.repository.search_terms("")
        suggestions = DeterministicResolutionEngine(fuzzy_threshold).suggestions(candidate["name"], terms)
        if not suggestions:
            suggestions = [{"ontology_term_id": None, "resolution_method": "UNRESOLVED", "confidence": 0.0, "status": "NEEDS_REVIEW", "normalized_input": normalize_ontology_text(candidate["name"], scientific_name=True), "matched_label": None, "ontology_namespace": None, "ontology_version": None, "explanation": {"reason": "NO_CONTROLLED_TERM_MATCH"}, "provenance": {"resolver": "deterministic-local-v1", "candidate_id": candidate_id}}]
        return [self.repository.create_resolution(candidate_id, suggestion, actor) for suggestion in suggestions]

    def resolve_session(self, session_id: int, actor: str, fuzzy_threshold: float = 0.88) -> dict[str, Any]:
        candidates = self.repository.get_session_entity_candidates(session_id)
        return {"session_id": session_id, "resolutions": {item["id"]: self.resolve_one(item["id"], actor, fuzzy_threshold) for item in candidates}, "canonical_graph_mutated": False}

    def list_proposed_matches(self, candidate_id: int) -> list[dict[str, Any]]:
        return self.repository.list_resolutions(candidate_id)

    def decide(self, resolution_id: int, status: str, actor: str, reason: str) -> dict[str, Any]:
        result = self.repository.decide_resolution(resolution_id, status, actor, reason)
        if result is None:
            raise LookupError("RESOLUTION_NOT_FOUND")
        validate_resolution_state(result["resolution_method"], result["status"], result.get("ontology_term_id"))
        return result

    def manual_assign(self, candidate_id: int, term_id: int, actor: str, reason: str) -> dict[str, Any]:
        term = self.repository.get_term(term_id)
        candidate = self.repository.get_entity_candidate(candidate_id)
        if term is None or candidate is None:
            raise LookupError("TERM_OR_CANDIDATE_NOT_FOUND")
        suggestion = {"ontology_term_id": term_id, "resolution_method": "MANUAL", "confidence": 1.0, "status": "PROPOSED", "normalized_input": normalize_ontology_text(candidate["name"], scientific_name=True), "matched_label": term["preferred_label"], "ontology_namespace": term["namespace"], "ontology_version": term["version"], "explanation": {"reason": reason}, "provenance": {"manual_actor": actor, "term_id": term_id}}
        return self.repository.create_resolution(candidate_id, suggestion, actor)


class EvidenceRegistryService:
    validator_version = "ontology-evidence-v1"

    def __init__(self, repository: OntologyRepository) -> None:
        self.repository = repository

    @staticmethod
    def evidence_hash(source: Mapping[str, Any]) -> str:
        value = f"{source['source_sha256']}:{source['start_offset']}:{source['end_offset']}:{source['exact_text']}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def register(self, evidence_object_id: int, actor: str) -> dict[str, Any]:
        source = self.repository.evidence_source(evidence_object_id)
        if source is None:
            raise LookupError("EVIDENCE_OBJECT_NOT_FOUND")
        require_provenance(source.get("provenance", {}))
        data = {"evidence_hash": self.evidence_hash(source), "source_document_id": source["document_id"], "source_sha256": source["source_sha256"], "validation_status": "PENDING", "validation_details": {}, "validator_version": self.validator_version}
        return self.repository.create_evidence_entry(evidence_object_id, data, actor)

    def validate(self, evidence_object_id: int, actor: str) -> dict[str, Any]:
        source = self.repository.evidence_source(evidence_object_id)
        entry = self.repository.get_evidence_entry(evidence_object_id)
        if source is None or entry is None:
            raise LookupError("EVIDENCE_REGISTRY_ENTRY_NOT_FOUND")
        failures: list[str] = []
        if entry["evidence_hash"] != self.evidence_hash(source): failures.append("EVIDENCE_HASH_MISMATCH")
        if entry["source_sha256"] != source["source_sha256"]: failures.append("SOURCE_HASH_MISMATCH")
        if source.get("document_sha256") and source["document_sha256"] != source["source_sha256"]: failures.append("DOCUMENT_SOURCE_HASH_MISMATCH")
        if not source.get("provenance"): failures.append("PROVENANCE_INCOMPLETE")
        status = "INVALID" if failures else "VALID"
        result = self.repository.validate_evidence_entry(evidence_object_id, status, {"failures": failures, "validator_version": self.validator_version}, actor)
        if result is None: raise LookupError("EVIDENCE_REGISTRY_ENTRY_NOT_FOUND")
        return result

    def get(self, evidence_object_id: int) -> dict[str, Any]:
        result = self.repository.get_evidence_entry(evidence_object_id)
        if result is None: raise LookupError("EVIDENCE_REGISTRY_ENTRY_NOT_FOUND")
        return result

    def revalidate(self, evidence_object_id: int, actor: str) -> dict[str, Any]:
        return self.validate(evidence_object_id, actor)


class PublicationReadinessService:
    evaluation_version = "publication-readiness-v1"

    def __init__(self, repository: OntologyRepository) -> None:
        self.repository = repository

    def evaluate_candidate(self, candidate_id: int, actor: str) -> dict[str, Any]:
        context = self.repository.readiness_context(candidate_id)
        if context is None: raise LookupError("CANDIDATE_NOT_FOUND")
        blockers: list[str] = []
        if context["candidate_review_status"] != "ACCEPTED": blockers.append("CANDIDATE_NOT_ACCEPTED")
        if context["session_stage"] != "READY_FOR_REVIEW": blockers.append("SESSION_NOT_READY_FOR_REVIEW")
        if not context.get("candidate_provenance"): blockers.append("PROVENANCE_INCOMPLETE")
        if context["kind"] == "ENTITY":
            if not context.get("resolution_id"): blockers.append("ONTOLOGY_UNRESOLVED")
            elif context.get("resolution_status") != "ACCEPTED": blockers.append("ONTOLOGY_MATCH_NOT_ACCEPTED")
            elif context.get("registry_status") != "ACTIVE": blockers.append("ONTOLOGY_VERSION_INACTIVE")
        else:
            if not context.get("evidence_id"): blockers.append("EVIDENCE_MISSING")
            elif context.get("evidence_validation_status") != "VALID": blockers.append("EVIDENCE_INVALID")
            if not context.get("subject_ready"): blockers.append("SUBJECT_NOT_READY")
            if not context.get("object_ready"): blockers.append("OBJECT_NOT_READY")
        evidence_complete = context["kind"] == "ENTITY" or bool(context.get("evidence_id") and context.get("evidence_validation_status") == "VALID")
        ontology_resolved = context["kind"] == "RELATIONSHIP" or bool(context.get("resolution_status") == "ACCEPTED" and context.get("registry_status") == "ACTIVE")
        result = ReadinessResult(candidate_id, evidence_complete, ontology_resolved, context["candidate_review_status"] == "ACCEPTED", bool(context.get("candidate_provenance")), not blockers, tuple(dict.fromkeys(blockers)))
        return self.repository.save_readiness(candidate_id, {**result.__dict__, "blockers": list(result.blockers), "evaluation_version": self.evaluation_version}, actor)

    def evaluate_session(self, session_id: int, actor: str) -> dict[str, Any]:
        results = [self.evaluate_candidate(candidate_id, actor) for candidate_id in self.repository.session_candidate_ids(session_id)]
        return {"session_id": session_id, "results": results, "ready_for_publication": bool(results) and all(item["ready_for_publication"] for item in results), "canonical_graph_mutated": False}

    def get(self, candidate_id: int) -> dict[str, Any]:
        result = self.repository.get_readiness(candidate_id)
        if result is None: raise LookupError("READINESS_NOT_FOUND")
        return result
