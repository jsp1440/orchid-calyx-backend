from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.reasoning_ledger.models import (
    ConflictState,
    LedgerEntry,
    LedgerEntryKind,
    LedgerProvenance,
    LedgerValidationError,
    ReasoningLedger,
    ReviewDecision,
    ReviewOutcome,
    UncertaintyMarker,
)
from app.reasoning_publication.gateway import (
    ExistingKnowledgeGraphPublicationGate,
    PublicationGateError,
)
from app.reasoning_publication.service import ReasoningLedgerPublicationService

ATTRIBUTES = {
    "graph_operation_type": "CREATE_EDGE",
    "subject_canonical_node_id": 11,
    "subject_canonical_key": "Masdevallia veitchiana",
    "object_canonical_node_id": 12,
    "object_canonical_key": "Euglossine bee",
    "predicate": "pollinated_by",
    "supporting_evidence_references": ["edge:7"],
    "counterevidence_references": [],
    "literature_evidence_ids": ["evidence:1"],
    "source_document_hashes": ["a" * 64],
    "inference_family": "pollinator",
    "inference_rule_id": "ocb010.pollinator",
    "inference_rule_version": "1.0.0",
    "originating_candidate_ids": ["candidate:1"],
    "originating_inference_hash": "b" * 64,
    "provenance_chain": [{"source": "literature"}],
    "canonical_assertion_id": 41,
    "canonical_assertion_version": 2,
    "publication_policy_id": "scientific-human-review",
    "publication_policy_version": 1,
}


def approved_ledger(attributes=None, *, confidence=0.9, conflict_state=None, tags=()):
    entry = LedgerEntry(
        kind=LedgerEntryKind.CONCLUSION,
        text="The reviewed conclusion.",
        author="owner",
        tenant_id="owner",
        project_id=str(uuid4()),
        provenance=LedgerProvenance(
            source_kind="knowledge_graph_inference",
            source_id="b" * 64,
            content_hash="b" * 64,
            retrieved_at=datetime.now(timezone.utc),
        ),
        uncertainty=UncertaintyMarker(confidence=confidence, rationale="reviewable"),
        attributes=ATTRIBUTES if attributes is None else attributes,
        tags=tags,
    )
    entries = (entry,)
    if conflict_state:
        entries += (
            LedgerEntry(
                kind=LedgerEntryKind.CONFLICT,
                text="Conflict",
                author="owner",
                tenant_id="owner",
                project_id=entry.project_id,
                conflict_state=conflict_state,
            ),
        )
    ledger = ReasoningLedger(
        tenant_id="owner",
        project_id=entry.project_id,
        title="Publication",
        created_by="owner",
        entries=entries,
    )
    return ledger.with_review(
        ReviewDecision(
            reviewer="reviewer",
            outcome=ReviewOutcome.APPROVED,
            rationale="Human approval",
        )
    )


class FakeLedgers:
    def __init__(self, ledger):
        self.ledger = ledger
        self.literature = SimpleNamespace(validate=lambda provenance: None)

    def current(self, ledger_id, owner):
        if owner != self.ledger.tenant_id:
            raise LedgerValidationError("CROSS_TENANT")
        return self.ledger


class FakeArtifacts:
    def __init__(self):
        self.rows = {}
        self.attempts = []

    def save_prepared(self, snapshot):
        if snapshot["artifact_hash"] in self.rows:
            return self.rows[snapshot["artifact_hash"]]
        row = SimpleNamespace(
            snapshot=snapshot,
            status="prepared",
            canonical_publication_id=None,
            canonical_graph_result=None,
            failure_reason=None,
        )
        self.rows[snapshot["artifact_hash"]] = row
        return row

    def record_attempt(self, row, outcome, actor, details):
        self.attempts.append((outcome, actor, details))


class FakeGate:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def publish(self, artifact):
        self.calls += 1
        if self.fail:
            raise PublicationGateError("GATE_REJECTED")
        return {
            "publication_id": 99,
            "graph": {"outcome": "PUBLISHED", "graph_version_id": 8},
        }


def service(ledger, *, fail=False):
    value = ReasoningLedgerPublicationService.__new__(ReasoningLedgerPublicationService)
    value.ledgers = FakeLedgers(ledger)
    value.db = SimpleNamespace(commit=lambda: None)
    value.artifacts = FakeArtifacts()
    value.gate = FakeGate(fail)
    return value


def submit(value, ledger):
    return value.publish(
        str(ledger.ledger_id),
        owner="owner",
        expected_version=ledger.version,
        expected_review_content_hash=ledger.review_content_hash,
    )


def test_approved_exact_revision_uses_canonical_gate_and_is_idempotent():
    ledger = approved_ledger()
    value = service(ledger)
    first, created = submit(value, ledger)
    second, duplicate_created = submit(value, ledger)
    assert created is True
    assert duplicate_created is False
    assert first["publication_status"] == "published"
    assert second["artifact_hash"] == first["artifact_hash"]
    assert value.gate.calls == 1


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda ledger: (ledger.version - 1, ledger.review_content_hash),
            "STALE_LEDGER_VERSION",
        ),
        (lambda ledger: (ledger.version, "0" * 64), "STALE_REVIEW_CONTENT_HASH"),
    ],
)
def test_exact_version_and_hash_are_required(mutation, code):
    ledger = approved_ledger()
    version, digest = mutation(ledger)
    with pytest.raises(LedgerValidationError, match=code):
        service(ledger).publish(
            str(ledger.ledger_id),
            owner="owner",
            expected_version=version,
            expected_review_content_hash=digest,
        )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"graph_operation_type": "DELETE_EDGE"}, "UNSUPPORTED_GRAPH_OPERATION"),
        ({"subject_canonical_node_id": None}, "AMBIGUOUS_SUBJECT_IDENTITY"),
        ({"object_canonical_node_id": None}, "AMBIGUOUS_OBJECT_IDENTITY"),
        ({"supporting_evidence_references": []}, "PUBLICATION_EVIDENCE_INCOMPLETE"),
        ({"literature_evidence_ids": []}, "PUBLICATION_EVIDENCE_INCOMPLETE"),
        ({"source_document_hashes": []}, "PUBLICATION_EVIDENCE_INCOMPLETE"),
        ({"canonical_assertion_id": 0}, "CANONICAL_PUBLICATION_BINDING_REQUIRED"),
        ({"hidden_reasoning": "secret"}, "PRIVATE_REASONING_PROHIBITED"),
    ],
)
def test_fail_closed_eligibility(changes, code):
    attrs = {**ATTRIBUTES, **changes}
    ledger = approved_ledger(attrs)
    with pytest.raises(LedgerValidationError, match=code):
        submit(service(ledger), ledger)


@pytest.mark.parametrize("state", [ConflictState.UNRESOLVED, ConflictState.DEFERRED])
def test_unresolved_or_deferred_conflict_blocks(state):
    ledger = approved_ledger(conflict_state=state)
    with pytest.raises(LedgerValidationError, match="UNRESOLVED_CONFLICTS"):
        submit(service(ledger), ledger)


def test_low_confidence_blocks_publication():
    ledger = approved_ledger(confidence=0.2)
    with pytest.raises(LedgerValidationError, match="LOW_CONFIDENCE"):
        submit(service(ledger), ledger)


def test_unapproved_ledger_is_rejected():
    approved = approved_ledger()
    unapproved = ReasoningLedger(
        tenant_id=approved.tenant_id,
        project_id=approved.project_id,
        title=approved.title,
        created_by=approved.created_by,
        entries=approved.entries,
    )
    with pytest.raises(LedgerValidationError, match="MISSING_HUMAN_APPROVAL"):
        submit(service(unapproved), unapproved)


def test_later_ledger_mutation_invalidates_old_approval():
    ledger = approved_ledger()
    changed = ledger.append(
        LedgerEntry(
            kind=LedgerEntryKind.SUPPORT,
            text="Later evidence",
            author="owner",
            tenant_id="owner",
            project_id=ledger.project_id,
        )
    )
    with pytest.raises(LedgerValidationError, match="MISSING_HUMAN_APPROVAL"):
        submit(service(changed), changed)


def test_outreach_is_rejected():
    ledger = approved_ledger(tags=("outreach",))
    with pytest.raises(LedgerValidationError, match="OUTREACH_PUBLICATION_PROHIBITED"):
        submit(service(ledger), ledger)


def test_gate_rejection_is_retained_as_auditable_artifact():
    ledger = approved_ledger()
    value = service(ledger, fail=True)
    artifact, created = submit(value, ledger)
    assert created is True
    assert artifact["publication_status"] == "rejected"
    assert artifact["failure_reason"] == "GATE_REJECTED"
    assert value.artifacts.attempts[0][0] == "REJECTED"


def test_cross_tenant_is_rejected_before_artifact_creation():
    ledger = approved_ledger()
    value = service(ledger)
    with pytest.raises(LedgerValidationError, match="CROSS_TENANT"):
        value.publish(
            str(ledger.ledger_id),
            owner="other",
            expected_version=ledger.version,
            expected_review_content_hash=ledger.review_content_hash,
        )
    assert not value.artifacts.rows


def test_canonical_gate_rejects_assertion_that_does_not_match_ledger_operation():
    gate = ExistingKnowledgeGraphPublicationGate.__new__(
        ExistingKnowledgeGraphPublicationGate
    )
    gate.registry = SimpleNamespace(
        submit=lambda request: {
            "trusted_snapshot": {
                "assertion": {
                    "normalized_statement": {
                        "subject": "Different orchid",
                        "predicate": "pollinated_by",
                        "object": "Euglossine bee",
                    }
                }
            }
        }
    )
    gate.graph = SimpleNamespace()
    artifact = {
        **ATTRIBUTES,
        "canonical_literal_value": None,
        "artifact_hash": "a" * 64,
        "submitting_actor": "owner",
        "publication_artifact_id": str(uuid4()),
        "policy_id": "scientific-human-review",
        "policy_version": 1,
    }
    with pytest.raises(PublicationGateError, match="LEDGER_ASSERTION_BINDING_MISMATCH"):
        gate.publish(artifact)
