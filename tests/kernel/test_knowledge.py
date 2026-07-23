from dataclasses import FrozenInstanceError

import pytest

from app.kernel import (
    KnowledgeObject,
    KnowledgeObjectType,
    KnowledgeStatus,
    OCIDFactory,
    OCIDKind,
    ScientificObjectValidationError,
)


def test_knowledge_object_defaults_to_knowledge_ocid() -> None:
    knowledge = KnowledgeObject(title="Dendrobium ecological profile")

    assert knowledge.ocid.kind is OCIDKind.KNOWLEDGE_OBJECT
    assert knowledge.knowledge_type is KnowledgeObjectType.GENERIC
    assert knowledge.status is KnowledgeStatus.DRAFT


def test_knowledge_object_is_immutable() -> None:
    knowledge = KnowledgeObject(title="Immutable synthesis")

    with pytest.raises(FrozenInstanceError):
        knowledge.title = "Changed"  # type: ignore[misc]


def test_knowledge_object_requires_title() -> None:
    with pytest.raises(ScientificObjectValidationError, match="title must not be empty"):
        KnowledgeObject(title="   ")


def test_knowledge_object_rejects_duplicate_support_ocids() -> None:
    assertion = OCIDFactory.new(OCIDKind.ASSERTION)

    with pytest.raises(ScientificObjectValidationError, match="assertion_ocids must be unique"):
        KnowledgeObject(
            title="Duplicate support",
            assertion_ocids=(assertion, assertion),
        )


def test_knowledge_object_enforces_typed_support_ocids() -> None:
    with pytest.raises(ScientificObjectValidationError, match="only ASSERTION"):
        KnowledgeObject(
            title="Invalid support",
            assertion_ocids=(OCIDFactory.new(OCIDKind.EVIDENCE),),
        )


def test_accepted_knowledge_requires_support_and_reviewer() -> None:
    with pytest.raises(ScientificObjectValidationError, match="supporting scientific objects"):
        KnowledgeObject(title="Unsupported", status=KnowledgeStatus.ACCEPTED)

    with pytest.raises(ScientificObjectValidationError, match="reviewed_by"):
        KnowledgeObject(
            title="Unreviewed",
            status=KnowledgeStatus.ACCEPTED,
            assertion_ocids=(OCIDFactory.new(OCIDKind.ASSERTION),),
        )


def test_accepted_knowledge_tracks_support_count() -> None:
    knowledge = KnowledgeObject(
        title="Reviewed synthesis",
        status=KnowledgeStatus.ACCEPTED,
        reviewed_by="Dr. Reviewer",
        assertion_ocids=(OCIDFactory.new(OCIDKind.ASSERTION),),
        relationship_ocids=(OCIDFactory.new(OCIDKind.RELATIONSHIP),),
        evidence_ocids=(OCIDFactory.new(OCIDKind.EVIDENCE),),
        publication_ocids=(OCIDFactory.new(OCIDKind.PUBLICATION),),
    )

    assert knowledge.is_supported
    assert knowledge.support_count == 4


def test_superseded_knowledge_requires_valid_prior_knowledge_ocid() -> None:
    with pytest.raises(ScientificObjectValidationError, match="supersedes_knowledge_ocid"):
        KnowledgeObject(
            title="Superseded synthesis",
            status=KnowledgeStatus.SUPERSEDED,
            evidence_ocids=(OCIDFactory.new(OCIDKind.EVIDENCE),),
        )

    with pytest.raises(ScientificObjectValidationError, match="KNOWLEDGE_OBJECT"):
        KnowledgeObject(
            title="Invalid predecessor",
            supersedes_knowledge_ocid=OCIDFactory.new(OCIDKind.PUBLICATION),
        )
