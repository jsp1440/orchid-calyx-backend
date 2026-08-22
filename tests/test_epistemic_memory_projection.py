from __future__ import annotations

from uuid import uuid4

from app.reasoning_ledger.epistemic_memory import (
    project_epistemic_corpus,
    project_epistemic_memory,
)
from app.reasoning_ledger.models import (
    LedgerEntry,
    LedgerEntryKind,
    LedgerProvenance,
    LedgerStatus,
    ReasoningLedger,
    UncertaintyMarker,
)

OWNER = "owner:test"
PROJECT_ID = str(uuid4())


def _entry(
    kind: LedgerEntryKind,
    text: str,
    sequence: int,
    *,
    references: tuple = (),
    provenance: LedgerProvenance | None = None,
    confidence: float | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        kind=kind,
        text=text,
        sequence=sequence,
        author=OWNER,
        tenant_id=OWNER,
        project_id=PROJECT_ID,
        references_entry_ids=references,
        provenance=provenance,
        uncertainty=(
            UncertaintyMarker(confidence=confidence, rationale="bounded inference")
            if confidence is not None
            else None
        ),
    )


def _ledger(
    entries: tuple[LedgerEntry, ...], *, status: LedgerStatus = LedgerStatus.DRAFT
) -> ReasoningLedger:
    return ReasoningLedger(
        tenant_id=OWNER,
        project_id=PROJECT_ID,
        title="Epistemic memory fixture",
        description="Tests machine reasoning as durable non-authoritative memory.",
        status=status,
        entries=entries,
        created_by=OWNER,
    )


def _node_by_entry_id(projection: dict, entry: LedgerEntry) -> dict:
    return next(
        node
        for node in projection["nodes"]
        if node.get("entry_id") == str(entry.entry_id)
    )


def test_hypothesis_and_conclusion_are_recallable_but_never_source_evidence():
    evidence = _entry(
        LedgerEntryKind.SUPPORT,
        "Published observations report a repeatable association.",
        0,
        provenance=LedgerProvenance(
            source_kind="literature",
            source_id="paper:fixture-1",
            literature_record_id="paper:fixture-1",
        ),
    )
    hypothesis = _entry(
        LedgerEntryKind.HYPOTHESIS,
        "The association may reflect a shared ecological mechanism.",
        1,
        references=(evidence.entry_id,),
        confidence=0.71,
    )
    conclusion = _entry(
        LedgerEntryKind.CONCLUSION,
        "The mechanism is a plausible interpretation requiring independent testing.",
        2,
        references=(hypothesis.entry_id, evidence.entry_id),
        confidence=0.66,
    )

    projection = project_epistemic_memory(_ledger((evidence, hypothesis, conclusion)))

    for entry in (hypothesis, conclusion):
        node = _node_by_entry_id(projection, entry)
        assert node["machine_scientific_memory"] is True
        assert node["recallable"] is True
        assert node["canonical_knowledge"] is False
        assert node["source_evidence"] is False
        assert node["can_be_cited_as_source_evidence"] is False
        assert node["can_trigger_publication"] is False
        assert node["requires_controlled_publication_gate"] is True
        assert node["requires_independent_evidence_for_new_claim"] is True
        assert node["grounding_state"] == "transitive"

    assert projection["publication_boundary"] == {
        "automatic_promotion": False,
        "machine_memory_is_source_evidence": False,
        "controlled_graph_publication_required": True,
        "independent_evidence_required_for_new_scientific_claims": True,
    }


def test_support_counterevidence_and_conflict_relations_survive_projection():
    hypothesis = _entry(LedgerEntryKind.HYPOTHESIS, "Candidate explanation.", 0)
    support = _entry(
        LedgerEntryKind.SUPPORT,
        "Evidence supporting the candidate explanation.",
        1,
        references=(hypothesis.entry_id,),
    )
    counter = _entry(
        LedgerEntryKind.COUNTEREVIDENCE,
        "Evidence inconsistent with the candidate explanation.",
        2,
        references=(hypothesis.entry_id,),
    )
    conflict = _entry(
        LedgerEntryKind.CONFLICT,
        "The supporting and counter evidence remain unresolved.",
        3,
        references=(hypothesis.entry_id,),
    )

    projection = project_epistemic_memory(
        _ledger((hypothesis, support, counter, conflict))
    )
    predicates = {
        (edge["source"], edge["predicate"], edge["target"])
        for edge in projection["edges"]
    }
    hypothesis_node = _node_by_entry_id(projection, hypothesis)["node_id"]

    assert (
        _node_by_entry_id(projection, support)["node_id"],
        "supports",
        hypothesis_node,
    ) in predicates
    assert (
        _node_by_entry_id(projection, counter)["node_id"],
        "counters",
        hypothesis_node,
    ) in predicates
    assert (
        _node_by_entry_id(projection, conflict)["node_id"],
        "conflicts_with",
        hypothesis_node,
    ) in predicates


def test_memory_fingerprint_and_node_identities_are_deterministic_for_same_revision():
    hypothesis = _entry(LedgerEntryKind.HYPOTHESIS, "Stable hypothesis.", 0)
    ledger = _ledger((hypothesis,))

    first = project_epistemic_memory(ledger)
    second = project_epistemic_memory(ledger)

    assert first["memory_fingerprint"] == second["memory_fingerprint"]
    assert first["nodes"] == second["nodes"]
    assert first["edges"] == second["edges"]


def test_approved_ledger_does_not_promote_machine_inference_to_canonical_truth():
    hypothesis = _entry(LedgerEntryKind.HYPOTHESIS, "Reviewed candidate explanation.", 0)
    projection = project_epistemic_memory(
        _ledger((hypothesis,), status=LedgerStatus.APPROVED)
    )
    node = _node_by_entry_id(projection, hypothesis)

    assert projection["nodes"][0]["status"] == "approved"
    assert node["authority"] == "non_authoritative"
    assert node["canonical_knowledge"] is False
    assert node["source_evidence"] is False
    assert node["can_trigger_publication"] is False


def test_ungrounded_machine_memory_is_explicitly_marked_and_cannot_bootstrap_evidence():
    hypothesis = _entry(
        LedgerEntryKind.HYPOTHESIS,
        "A model-generated idea with no source lineage yet.",
        0,
        confidence=0.9,
    )
    projection = project_epistemic_memory(_ledger((hypothesis,)))
    node = _node_by_entry_id(projection, hypothesis)

    assert node["grounding_state"] == "ungrounded"
    assert node["confidence"] == 0.9
    assert node["can_be_cited_as_source_evidence"] is False
    assert node["requires_independent_evidence_for_new_claim"] is True


def test_grounding_resolution_is_cycle_safe():
    first_id = uuid4()
    second_id = uuid4()
    first = LedgerEntry(
        entry_id=first_id,
        kind=LedgerEntryKind.HYPOTHESIS,
        text="First cyclic hypothesis.",
        sequence=0,
        author=OWNER,
        tenant_id=OWNER,
        project_id=PROJECT_ID,
        references_entry_ids=(second_id,),
    )
    second = LedgerEntry(
        entry_id=second_id,
        kind=LedgerEntryKind.HYPOTHESIS,
        text="Second cyclic hypothesis.",
        sequence=1,
        author=OWNER,
        tenant_id=OWNER,
        project_id=PROJECT_ID,
        references_entry_ids=(first_id,),
    )

    projection = project_epistemic_memory(_ledger((first, second)))

    assert _node_by_entry_id(projection, first)["grounding_state"] == "ungrounded"
    assert _node_by_entry_id(projection, second)["grounding_state"] == "ungrounded"


def test_project_corpus_combines_recallable_memories_without_promoting_them():
    first = _ledger(
        (
            _entry(
                LedgerEntryKind.HYPOTHESIS,
                "Earlier Calyx hypothesis.",
                0,
                confidence=0.55,
            ),
        )
    )
    second = _ledger(
        (
            _entry(
                LedgerEntryKind.CONCLUSION,
                "Later Calyx interpretation.",
                0,
                confidence=0.64,
            ),
        )
    )

    corpus = project_epistemic_corpus((second, first))

    assert corpus["ledger_count"] == 2
    assert corpus["memory_count"] == 2
    assert corpus["authority"] == "non_authoritative_epistemic_memory"
    assert all(
        memory["can_be_cited_as_source_evidence"] is False
        for memory in corpus["memories"]
    )
    assert all(memory["project_id"] == PROJECT_ID for memory in corpus["memories"])
    assert corpus["corpus_fingerprint"] == project_epistemic_corpus(
        (first, second)
    )["corpus_fingerprint"]
