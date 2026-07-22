from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from .models import (
    AuditEvent,
    ContextItem,
    CoverageOutcome,
    DesignEvidencePackage,
    DesignReasoningRecord,
    EvidenceResult,
    InterfacePlan,
    LifecycleState,
    MaterialConflictRecord,
    ProductRequest,
    Requirement,
    ReviewDecision,
    ReviewRecord,
    ReviewRole,
    fingerprint,
    utcnow,
)
from .repository import MemoryDesignPlanningRepository


ALLOWED_TRANSITIONS = {
    LifecycleState.REQUEST_DRAFT: {LifecycleState.REQUEST_VALIDATED},
    LifecycleState.REQUEST_VALIDATED: {LifecycleState.CONTEXT_RESOLVED},
    LifecycleState.CONTEXT_RESOLVED: {LifecycleState.EVIDENCE_RETRIEVED},
    LifecycleState.EVIDENCE_RETRIEVED: {LifecycleState.REASONING_IN_PROGRESS},
    LifecycleState.REASONING_IN_PROGRESS: {LifecycleState.PLAN_DRAFTED},
    LifecycleState.PLAN_DRAFTED: {LifecycleState.REVIEW_REQUIRED},
    LifecycleState.REVIEW_REQUIRED: {
        LifecycleState.APPROVED,
        LifecycleState.REVISION_REQUIRED,
        LifecycleState.REJECTED,
        LifecycleState.DEFERRED,
        LifecycleState.ESCALATED,
    },
    LifecycleState.REVISION_REQUIRED: {LifecycleState.PLAN_DRAFTED},
    LifecycleState.APPROVED: {LifecycleState.SUPERSEDED},
}
FUTURE_STATES = {
    LifecycleState.IMPLEMENTATION_AUTHORIZED,
    LifecycleState.IMPLEMENTED,
    LifecycleState.VALIDATED,
}
RIGHTS = "USER_SUPPLIED_INTERNAL_RESEARCH_ONLY"
LICENSE = "NOT_SUPPLIED"


class PlanningError(ValueError):
    pass


class Build089EvidenceAdapter:
    """Read-only, bounded adapter over the existing BUILD-089 reasoning service."""

    VERSION = "090b-build-089-adapter-1"

    def __init__(self, reasoning_service: Any) -> None:
        self.service = reasoning_service

    def retrieve(
        self, query: str, domains: tuple[str, ...], classifications: tuple[str, ...]
    ) -> dict[str, Any]:
        from app.design_intelligence.knowledge import SemanticDesignDomain

        parsed = tuple(SemanticDesignDomain(value) for value in domains)
        return self.service.search(
            query, domains=parsed, classifications=classifications, limit=20
        )


class DesignPlanningService:
    POLICY_VERSION = "090b-policy-1"

    def __init__(self, repository=None, evidence_adapter=None) -> None:
        self.repository = repository or MemoryDesignPlanningRepository()
        self.evidence_adapter = evidence_adapter

    def create_product_request(
        self, payload: dict[str, Any], actor: str
    ) -> ProductRequest:
        logical_key = self._required(payload, "logical_key")
        requirements = tuple(
            self._requirement(item) for item in payload.get("requirements", ())
        )
        required = ("product_name", "business_objective", "intended_users")
        if any(not payload.get(key) for key in required) or not actor:
            raise PlanningError("INVALID_PRODUCT_REQUEST")
        if any(
            r.status is r.status.CONFIRMED and not r.provenance for r in requirements
        ):
            raise PlanningError("CONFIRMED_REQUIREMENT_MISSING_PROVENANCE")
        previous = self.repository.history("product_request", logical_key)
        version = len(previous) + 1
        content = {
            key: value
            for key, value in payload.items()
            if key not in {"request_id", "version", "lifecycle_state", "integrity_hash"}
        }
        digest = fingerprint(content)
        if previous and previous[-1].integrity_hash == digest:
            return previous[-1]
        request = ProductRequest(
            request_id=f"pr-{digest[:24]}",
            logical_key=logical_key,
            version=version,
            supersedes_request_id=previous[-1].request_id if previous else None,
            product_name=payload["product_name"],
            product_family=payload.get("product_family", ""),
            requesting_actor=actor,
            business_objective=payload["business_objective"],
            scientific_objective=payload.get("scientific_objective", ""),
            educational_objective=payload.get("educational_objective", ""),
            intended_users=tuple(payload["intended_users"]),
            user_roles=tuple(payload.get("user_roles", ())),
            primary_tasks=tuple(payload.get("primary_tasks", ())),
            secondary_tasks=tuple(payload.get("secondary_tasks", ())),
            required_data=tuple(payload.get("required_data", ())),
            required_workflows=tuple(payload.get("required_workflows", ())),
            platform_targets=tuple(payload.get("platform_targets", ())),
            device_targets=tuple(payload.get("device_targets", ())),
            accessibility_requirements=tuple(
                payload.get("accessibility_requirements", ())
            ),
            privacy_requirements=tuple(payload.get("privacy_requirements", ())),
            security_requirements=tuple(payload.get("security_requirements", ())),
            rights_and_licensing_constraints=tuple(
                payload.get("rights_and_licensing_constraints", ())
            ),
            integration_dependencies=tuple(payload.get("integration_dependencies", ())),
            performance_expectations=tuple(payload.get("performance_expectations", ())),
            branding_constraints=tuple(payload.get("branding_constraints", ())),
            known_design_decisions=tuple(payload.get("known_design_decisions", ())),
            unresolved_questions=tuple(payload.get("unresolved_questions", ())),
            excluded_scope=tuple(payload.get("excluded_scope", ())),
            priority=payload.get("priority", "NORMAL"),
            requested_delivery_phase=payload.get(
                "requested_delivery_phase", "PLANNING"
            ),
            requirements=requirements,
            lifecycle_state=LifecycleState.REQUEST_DRAFT,
            created_at=utcnow(),
            integrity_hash=digest,
        )
        result = self.repository.append("product_request", request, logical_key, digest)
        self._audit(
            "ProductRequest", result.request_id, result.version, actor, "CREATE", digest
        )
        return result

    def create_context(self, request_id: str, payload: dict[str, Any], actor: str):
        request = self._get("product_request", request_id)
        items = tuple(ContextItem(**item) for item in payload.get("items", ()))
        if not items or any(
            not item.provenance or not item.rights_classification for item in items
        ):
            raise PlanningError("MISSING_CONTEXT_PROVENANCE_OR_RIGHTS")
        if any(item.hard_constraint and item.status != "ACTIVE" for item in items):
            raise PlanningError("MISSING_HARD_CONSTRAINT")
        deadline = payload["freshness_deadline"]
        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)
        if deadline <= utcnow():
            raise PlanningError("STALE_CONTEXT")
        logical = payload.get("logical_key", request.logical_key)
        prior = self.repository.history("context", logical)
        base = {"request": request.integrity_hash, "items": items, "deadline": deadline}
        digest = fingerprint(base)
        from .models import ProjectContextSnapshot

        artifact = ProjectContextSnapshot(
            snapshot_id=f"ctx-{digest[:24]}",
            logical_key=logical,
            version=len(prior) + 1,
            product_request_id=request.request_id,
            product_request_version=request.version,
            items=items,
            inaccessible_sources=tuple(payload.get("inaccessible_sources", ())),
            freshness_deadline=deadline,
            created_at=utcnow(),
            integrity_hash=digest,
        )
        result = self.repository.append("context", artifact, logical, digest)
        self._audit(
            "ProjectContextSnapshot",
            result.snapshot_id,
            result.version,
            actor,
            "CREATE",
            digest,
        )
        return result

    def build_evidence(
        self, request_id: str, context_id: str, payload: dict[str, Any], actor: str
    ):
        request = self._get("product_request", request_id)
        context = self._get("context", context_id)
        queries = tuple(self._normalize(q) for q in payload.get("queries", ()))
        if not queries:
            raise PlanningError("NO_RETRIEVAL_QUERY")
        domains = tuple(payload.get("domains", ()))
        results: list[EvidenceResult] = []
        coverage: dict[str, CoverageOutcome] = {}
        retrieval_failed = False
        for query in queries:
            try:
                response = self.evidence_adapter.retrieve(
                    query, domains, tuple(payload.get("knowledge_types", ()))
                )
            except Exception as exc:
                retrieval_failed = True
                if domains:
                    coverage.update(
                        {d: CoverageOutcome.RETRIEVAL_UNAVAILABLE for d in domains}
                    )
                if payload.get("fail_on_unavailable", True):
                    raise PlanningError("RETRIEVAL_UNAVAILABLE") from exc
                continue
            for item in response.get("results", ()):
                provenance = item.get("provenance") or {}
                if not provenance:
                    raise PlanningError("MISSING_EVIDENCE_PROVENANCE")
                excerpt = item.get("text", "")[:240] or None
                results.append(
                    EvidenceResult(
                        semantic_unit_id=item["unit_id"],
                        document_id=item["document_id"],
                        source_location=provenance,
                        citation=str(item.get("supporting_citations", "")),
                        score=float(item["confidence"]),
                        explanation=item.get("explanation", {}),
                        provenance=provenance,
                        rights_status=RIGHTS,
                        bounded_excerpt=excerpt,
                    )
                )
            for domain in domains:
                matched = sum(
                    domain in r.get("classification", {}).get("domains", ())
                    for r in response.get("results", ())
                )
                coverage[domain] = (
                    CoverageOutcome.COVERED
                    if matched >= 2
                    else (
                        CoverageOutcome.PARTIALLY_COVERED
                        if matched
                        else CoverageOutcome.NOT_PRESENT_IN_SOURCE_CORPUS
                    )
                )
        if retrieval_failed and not results:
            known_gaps = ()
        else:
            known_gaps = tuple(
                k for k, v in coverage.items() if v is not CoverageOutcome.COVERED
            )
        ranked = tuple(
            sorted(
                results,
                key=lambda item: (-item.score, item.document_id, item.semantic_unit_id),
            )
        )
        content = {
            "request": request.integrity_hash,
            "context": context.integrity_hash,
            "queries": queries,
            "domains": domains,
            "results": tuple(r.semantic_unit_id for r in ranked),
            "coverage": coverage,
            "corpus": payload.get("corpus_version", "BUILD-089C"),
        }
        digest = fingerprint(content)
        logical = payload.get("logical_key", f"{request.logical_key}:evidence")
        prior = self.repository.history("evidence", logical)
        artifact = DesignEvidencePackage(
            evidence_package_id=f"ev-{digest[:24]}",
            logical_key=logical,
            version=len(prior) + 1,
            supersedes_package_id=prior[-1].evidence_package_id if prior else None,
            product_request_id=request.request_id,
            product_request_version=request.version,
            project_context_snapshot_id=context.snapshot_id,
            affected_requirement_ids=tuple(payload.get("requirement_ids", ())),
            retrieval_queries=tuple(payload["queries"]),
            normalized_queries=queries,
            corpus_version=payload.get("corpus_version", "BUILD-089C"),
            retrieval_provider_version=self.evidence_adapter.VERSION,
            embedding_provider_version="089b-deterministic-local",
            filters={
                "domains": domains,
                "knowledge_types": tuple(payload.get("knowledge_types", ())),
            },
            ranked_results=ranked,
            supporting_guidance=tuple(r.semantic_unit_id for r in ranked),
            conflicting_guidance=tuple(payload.get("conflicting_guidance", ())),
            related_concepts=tuple(payload.get("related_concepts", ())),
            coverage=coverage,
            known_corpus_gaps=known_gaps,
            confidence_factors={
                "retrieval": round(
                    sum(r.score for r in ranked) / max(1, len(ranked)), 6
                )
            },
            rights_restrictions=(RIGHTS, LICENSE, "PUBLIC_REDISTRIBUTION_PROHIBITED"),
            created_at=utcnow(),
            integrity_hash=digest,
        )
        result = self.repository.append("evidence", artifact, logical, digest)
        self._audit(
            "DesignEvidencePackage",
            result.evidence_package_id,
            result.version,
            actor,
            "CREATE",
            digest,
        )
        return result

    def create_reasoning(self, payload: dict[str, Any], actor: str):
        evidence = tuple(
            self._get("evidence", item) for item in payload["evidence_package_ids"]
        )
        rationale = self._required(payload, "concise_decision_rationale")
        forbidden = ("chain of thought", "hidden prompt", "system prompt")
        if len(rationale) > 2000 or any(
            term in rationale.casefold() for term in forbidden
        ):
            raise PlanningError("UNSAFE_OR_UNBOUNDED_REASONING")
        logical = self._required(payload, "logical_key")
        prior = self.repository.history("reasoning", logical)
        digest = fingerprint(
            {**payload, "evidence": tuple(x.integrity_hash for x in evidence)}
        )
        artifact = DesignReasoningRecord(
            reasoning_record_id=f"rr-{digest[:24]}",
            logical_key=logical,
            version=len(prior) + 1,
            supersedes_record_id=prior[-1].reasoning_record_id if prior else None,
            product_request_id=payload["product_request_id"],
            context_snapshot_id=payload["context_snapshot_id"],
            evidence_package_ids=tuple(payload["evidence_package_ids"]),
            affected_product_area=payload["affected_product_area"],
            affected_user_roles=tuple(payload.get("affected_user_roles", ())),
            affected_requirements=tuple(payload.get("affected_requirements", ())),
            recommendation=payload["recommendation"],
            considered_alternatives=tuple(payload.get("considered_alternatives", ())),
            selected_approach=payload["selected_approach"],
            rejected_alternatives=tuple(payload.get("rejected_alternatives", ())),
            concise_decision_rationale=rationale,
            supporting_evidence_references=tuple(
                payload.get("supporting_evidence_references", ())
            ),
            conflicting_evidence_references=tuple(
                payload.get("conflicting_evidence_references", ())
            ),
            assumptions=tuple(payload.get("assumptions", ())),
            unresolved_questions=tuple(payload.get("unresolved_questions", ())),
            risks=tuple(payload.get("risks", ())),
            effects={k: tuple(v) for k, v in payload.get("effects", {}).items()},
            implementation_implications=tuple(
                payload.get("implementation_implications", ())
            ),
            confidence_factors=dict(payload.get("confidence_factors", {})),
            corpus_gaps=tuple(g for e in evidence for g in e.known_corpus_gaps),
            reviewer_status="PENDING",
            lifecycle_state=LifecycleState.REASONING_IN_PROGRESS,
            created_at=utcnow(),
            integrity_hash=digest,
        )
        result = self.repository.append("reasoning", artifact, logical, digest)
        self._audit(
            "DesignReasoningRecord",
            result.reasoning_record_id,
            result.version,
            actor,
            "CREATE",
            digest,
        )
        return result

    def create_conflict(self, payload: dict[str, Any], actor: str):
        from .models import ConflictType

        logical = self._required(payload, "logical_key")
        digest = fingerprint(payload)
        prior = self.repository.history("conflict", logical)
        artifact = MaterialConflictRecord(
            conflict_id=f"cf-{digest[:24]}",
            logical_key=logical,
            version=len(prior) + 1,
            product_request_id=payload["product_request_id"],
            context_snapshot_id=payload["context_snapshot_id"],
            evidence_package_ids=tuple(payload.get("evidence_package_ids", ())),
            conflict_type=ConflictType(payload["conflict_type"]),
            conflicting_references=tuple(payload["conflicting_references"]),
            authority_levels=tuple(payload["authority_levels"]),
            severity=payload["severity"],
            affected_users=tuple(payload.get("affected_users", ())),
            affected_workflows=tuple(payload.get("affected_workflows", ())),
            hard_constraint=bool(payload.get("hard_constraint")),
            alternatives=tuple(payload.get("alternatives", ())),
            recommended_resolution=payload["recommended_resolution"],
            evidence=tuple(payload.get("evidence", ())),
            required_decision_owner_role=ReviewRole(
                payload["required_decision_owner_role"]
            ),
            review_status="DECISION_REQUIRED",
            disposition=None,
            rationale=payload["rationale"],
            supersession_reference=prior[-1].conflict_id if prior else None,
            created_at=utcnow(),
            integrity_hash=digest,
        )
        result = self.repository.append("conflict", artifact, logical, digest)
        self._audit(
            "MaterialConflictRecord",
            result.conflict_id,
            result.version,
            actor,
            "CREATE",
            digest,
        )
        return result

    def create_plan(self, payload: dict[str, Any], actor: str):
        for item in payload["evidence_package_ids"]:
            self._get("evidence", item)
        for item in payload["reasoning_record_ids"]:
            self._get("reasoning", item)
        for item in payload.get("conflict_record_ids", ()):
            self._get("conflict", item)
        sections = payload.get("sections", {})
        required_sections = {
            "product_scope",
            "user_journeys",
            "information_architecture",
            "states",
            "accessibility",
            "responsive_behavior",
            "rights_and_attribution",
        }
        if missing := required_sections - sections.keys():
            raise PlanningError(
                f"INCOMPLETE_INTERFACE_PLAN:{','.join(sorted(missing))}"
            )
        if not payload.get("acceptance_criteria"):
            raise PlanningError("MISSING_ACCEPTANCE_CRITERIA")
        logical = self._required(payload, "logical_key")
        prior = self.repository.history("plan", logical)
        digest = fingerprint(payload)
        artifact = InterfacePlan(
            interface_plan_id=f"ip-{digest[:24]}",
            logical_key=logical,
            version=len(prior) + 1,
            supersedes_plan_id=prior[-1].interface_plan_id if prior else None,
            product_request_id=payload["product_request_id"],
            context_snapshot_id=payload["context_snapshot_id"],
            evidence_package_ids=tuple(payload["evidence_package_ids"]),
            reasoning_record_ids=tuple(payload["reasoning_record_ids"]),
            conflict_record_ids=tuple(payload.get("conflict_record_ids", ())),
            sections=sections,
            acceptance_criteria=tuple(payload["acceptance_criteria"]),
            unresolved_questions=tuple(payload.get("unresolved_questions", ())),
            corpus_gaps=tuple(payload.get("corpus_gaps", ())),
            required_review_roles=tuple(
                ReviewRole(x)
                for x in payload.get(
                    "required_review_roles", (ReviewRole.PRODUCT_OWNER,)
                )
            ),
            lifecycle_state=LifecycleState.PLAN_DRAFTED,
            created_at=utcnow(),
            integrity_hash=digest,
        )
        result = self.repository.append("plan", artifact, logical, digest)
        self._audit(
            "InterfacePlan",
            result.interface_plan_id,
            result.version,
            actor,
            "CREATE",
            digest,
        )
        return result

    def transition_plan(self, plan_id: str, target: LifecycleState, actor: str):
        plan = self._get("plan", plan_id)
        if target in FUTURE_STATES or target not in ALLOWED_TRANSITIONS.get(
            plan.lifecycle_state, set()
        ):
            raise PlanningError("INVALID_OR_FUTURE_LIFECYCLE_TRANSITION")
        if target is LifecycleState.APPROVED:
            reviews = self.repository.reviews(plan_id)
            approved = {
                r.reviewer_role
                for r in reviews
                if r.artifact_hash == plan.integrity_hash
                and r.decision is ReviewDecision.APPROVE
            }
            if not set(plan.required_review_roles) <= approved:
                raise PlanningError("MISSING_SAME_HASH_REQUIRED_APPROVALS")
            if any(
                self._get("conflict", c).hard_constraint
                for c in plan.conflict_record_ids
            ):
                raise PlanningError("UNRESOLVED_BLOCKING_CONFLICT")
        digest = fingerprint(
            {
                "predecessor": plan.integrity_hash,
                "target": target,
                "policy": self.POLICY_VERSION,
            }
        )
        updated = replace(
            plan,
            interface_plan_id=f"ip-{digest[:24]}",
            version=plan.version + 1,
            supersedes_plan_id=plan.interface_plan_id,
            lifecycle_state=target,
            created_at=utcnow(),
            integrity_hash=digest,
        )
        updated = self.repository.append("plan", updated, plan.logical_key, digest)
        self._audit(
            "InterfacePlan",
            updated.interface_plan_id,
            updated.version,
            actor,
            f"TRANSITION:{target.value}",
            digest,
        )
        return updated

    def review(
        self, plan_id: str, payload: dict[str, Any], reviewer: str, roles: set[str]
    ):
        plan = self._get("plan", plan_id)
        role = ReviewRole(payload["reviewer_role"])
        if role.value not in roles or (
            role is ReviewRole.PRODUCT_OWNER and "PRODUCT_OWNER" not in roles
        ):
            raise PlanningError("UNAUTHORIZED_REVIEWER")
        decision = ReviewDecision(payload["decision"])
        corrections = tuple(payload.get("structured_corrections", ()))
        if decision is ReviewDecision.APPROVE_WITH_CORRECTIONS and not corrections:
            raise PlanningError("CORRECTIONS_REQUIRED")
        content = {
            "plan": plan.integrity_hash,
            "reviewer": reviewer,
            "role": role,
            "decision": decision,
            "corrections": corrections,
        }
        digest = fingerprint(content)
        review = ReviewRecord(
            review_id=f"rv-{digest[:24]}",
            artifact_type="InterfacePlan",
            artifact_id=plan_id,
            artifact_version=plan.version,
            artifact_hash=plan.integrity_hash,
            reviewer_identity=reviewer,
            reviewer_role=role,
            decision=decision,
            structured_corrections=corrections,
            rationale=self._required(payload, "rationale"),
            before_state=plan.lifecycle_state.value,
            after_state="REVISION_REQUIRED"
            if corrections
            else plan.lifecycle_state.value,
            audit_context={
                "correlation_id": payload.get("correlation_id", str(uuid4()))
            },
            created_at=utcnow(),
            integrity_hash=digest,
        )
        result = self.repository.append_review(review)
        self._audit(
            "ReviewRecord", result.review_id, 1, reviewer, decision.value, digest
        )
        return result

    def health(self) -> dict[str, Any]:
        return {
            "ready": self.evidence_adapter is not None,
            "policy_version": self.POLICY_VERSION,
            "rights": RIGHTS,
            "license": LICENSE,
            "implementation_authorization": False,
        }

    def _get(self, kind: str, identity: str):
        value = self.repository.get(kind, identity)
        if value is None:
            raise PlanningError(f"{kind.upper()}_NOT_FOUND")
        return value

    def _audit(
        self,
        kind: str,
        identity: str,
        version: int,
        actor: str,
        action: str,
        basis: str,
    ):
        now = utcnow()
        content = {
            "kind": kind,
            "id": identity,
            "version": version,
            "actor": actor,
            "action": action,
            "basis": basis,
        }
        digest = fingerprint(content)
        self.repository.append_audit(
            AuditEvent(
                f"au-{digest[:24]}",
                kind,
                identity,
                version,
                actor,
                action,
                "BUILD-090B controlled operation",
                {},
                basis[:32],
                now,
                digest,
            )
        )

    @staticmethod
    def _required(payload: dict[str, Any], key: str):
        value = payload.get(key)
        if value is None or value == "":
            raise PlanningError(f"MISSING_{key.upper()}")
        return value

    @staticmethod
    def _normalize(query: str) -> str:
        value = " ".join(query.split()).casefold()
        if not value or len(value) > 500:
            raise PlanningError("INVALID_RETRIEVAL_QUERY")
        return value

    @staticmethod
    def _requirement(item: dict[str, Any]) -> Requirement:
        from .models import ProvenanceRef, RequirementStatus

        return Requirement(
            requirement_id=item["requirement_id"],
            category=item["category"],
            statement=item["statement"],
            status=RequirementStatus(item["status"]),
            source=item["source"],
            rationale=item.get("rationale", ""),
            priority=item.get("priority", "NORMAL"),
            hard_constraint=bool(item.get("hard_constraint")),
            provenance=tuple(ProvenanceRef(**p) for p in item.get("provenance", ())),
        )
