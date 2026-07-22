from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from . import my_conservatory as factory
from .models import (
    ArtifactReference,
    AuditEvent,
    ImplementationSpecificationSet,
    SpecificationLifecycle,
    SpecificationReview,
    fingerprint,
    utcnow,
)
from .repository import MemoryImplementationPlanningRepository


class ImplementationPlanningError(ValueError):
    pass


@dataclass(frozen=True)
class SourcePlanningBundle:
    product_request: Any
    context: Any
    evidence: Any
    reasoning: tuple[Any, ...]
    conflicts: tuple[Any, ...]
    plan: Any


class ImplementationSpecificationService:
    VERSION = "091-my-conservatory-1"

    def __init__(self, repository=None) -> None:
        self.repository = repository or MemoryImplementationPlanningRepository()

    def generate_my_conservatory(self, source: SourcePlanningBundle, actor: str):
        if source.plan.lifecycle_state.value != "REVIEW_REQUIRED":
            raise ImplementationPlanningError("SOURCE_PLAN_MUST_REMAIN_REVIEW_REQUIRED")
        if len(source.conflicts) != 5 or any(
            item.review_status != "DECISION_REQUIRED" for item in source.conflicts
        ):
            raise ImplementationPlanningError(
                "FIVE_DECISION_REQUIRED_CONFLICTS_MUST_BE_PRESERVED"
            )
        pages = factory.page_specs(source.plan.interface_plan_id)
        components = factory.component_specs()
        navigation = factory.navigation_spec()
        states = factory.state_specs()
        apis = factory.api_contracts(source.plan.interface_plan_id)
        data = factory.data_specs()
        cross = factory.cross_cutting(pages, components)
        impacts = factory.conflict_impacts(source.conflicts)
        sequence = factory.phases()
        readiness = factory.readiness_records(
            pages, components, apis, data, sequence, source.plan.interface_plan_id
        )
        references = (
            self._ref("ProductRequest", source.product_request, "request_id"),
            self._ref("ProjectContextSnapshot", source.context, "snapshot_id"),
            self._ref("DesignEvidencePackage", source.evidence, "evidence_package_id"),
            *(
                self._ref("DesignReasoningRecord", item, "reasoning_record_id")
                for item in source.reasoning
            ),
            *(
                self._ref("MaterialConflictRecord", item, "conflict_id")
                for item in source.conflicts
            ),
            self._ref("InterfacePlan", source.plan, "interface_plan_id"),
        )
        content = {
            "generator": self.VERSION,
            "source": tuple(x.integrity_hash for x in references),
            "pages": pages,
            "components": components,
            "navigation": navigation,
            "states": states,
            "apis": apis,
            "data": data,
            "cross": cross,
            "impacts": impacts,
            "sequence": sequence,
        }
        digest = fingerprint(content)
        history = self.repository.history(
            "my-conservatory-implementation-specification"
        )
        if history and history[-1].integrity_hash == digest:
            return history[-1]
        artifact = ImplementationSpecificationSet(
            f"impl-{digest[:24]}",
            "my-conservatory-implementation-specification",
            len(history) + 1,
            history[-1].specification_id if history else None,
            references,
            source.plan.lifecycle_state.value,
            tuple(source.plan.evidence_package_ids),
            tuple(source.plan.reasoning_record_ids),
            tuple(source.plan.conflict_record_ids),
            (
                {
                    "generator": self.VERSION,
                    "source_plan": source.plan.interface_plan_id,
                    "source_hash": source.plan.integrity_hash,
                },
            ),
            tuple(source.plan.corpus_gaps),
            tuple(source.plan.unresolved_questions),
            tuple(source.evidence.rights_restrictions),
            tuple(role.value for role in source.plan.required_review_roles),
            pages,
            components,
            navigation,
            states,
            apis,
            data,
            cross,
            impacts,
            sequence,
            readiness,
            SpecificationLifecycle.REVIEW_REQUIRED,
            utcnow(),
            digest,
        )
        result = self.repository.append(artifact)
        self._audit(result, actor, "GENERATE")
        return result

    def new_version(self, specification_id: str, changes: dict[str, Any], actor: str):
        previous = self.get(specification_id)
        if set(changes) - {"unresolved_questions", "review_requirements"}:
            raise ImplementationPlanningError("UNSUPPORTED_SPECIFICATION_CHANGE")
        digest = fingerprint({"previous": previous.integrity_hash, "changes": changes})
        history = self.repository.history(previous.logical_key)
        successor = replace(
            previous,
            specification_id=f"impl-{digest[:24]}",
            version=len(history) + 1,
            supersedes_specification_id=previous.specification_id,
            unresolved_questions=tuple(
                changes.get("unresolved_questions", previous.unresolved_questions)
            ),
            review_requirements=tuple(
                changes.get("review_requirements", previous.review_requirements)
            ),
            lifecycle_state=SpecificationLifecycle.REVIEW_REQUIRED,
            created_at=utcnow(),
            integrity_hash=digest,
        )
        result = self.repository.append(successor)
        self._audit(result, actor, "NEW_VERSION")
        return result

    def review(
        self,
        specification_id: str,
        payload: dict[str, Any],
        reviewer: str,
        roles: set[str],
    ):
        artifact = self.get(specification_id)
        role = payload.get("reviewer_role")
        if role not in roles:
            raise ImplementationPlanningError("UNAUTHORIZED_REVIEWER")
        if payload.get("decision") == "APPROVE" and role != "PRODUCT_OWNER":
            raise ImplementationPlanningError("OWNER_REQUIRED_FOR_FINAL_APPROVAL")
        digest = fingerprint(
            {"artifact": artifact.integrity_hash, "reviewer": reviewer, **payload}
        )
        review = SpecificationReview(
            f"review-{digest[:24]}",
            specification_id,
            artifact.integrity_hash,
            reviewer,
            role,
            payload["decision"],
            payload["rationale"],
            tuple(payload.get("corrections", ())),
            utcnow(),
            digest,
        )
        return self.repository.append_review(review)

    def get(self, specification_id: str):
        value = self.repository.get(specification_id)
        if value is None:
            raise ImplementationPlanningError("SPECIFICATION_NOT_FOUND")
        return value

    def health(self):
        return {
            "ready": True,
            "version": self.VERSION,
            "specifications_only": True,
            "frontend_generation": False,
            "implementation_authorization": False,
            "knowledge_graph_publication": False,
        }

    def _audit(self, artifact, actor, action):
        digest = fingerprint(
            {"specification": artifact.integrity_hash, "actor": actor, "action": action}
        )
        self.repository.append_audit(
            AuditEvent(
                f"audit-{digest[:24]}",
                artifact.specification_id,
                actor,
                action,
                tuple(x.artifact_id for x in artifact.source_artifacts),
                "BUILD-091 controlled specification operation",
                utcnow(),
                digest,
            )
        )

    @staticmethod
    def _ref(kind, artifact, identity_field):
        return ArtifactReference(
            kind,
            getattr(artifact, identity_field),
            getattr(artifact, "version", 1),
            artifact.integrity_hash,
        )
