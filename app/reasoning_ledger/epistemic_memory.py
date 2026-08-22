from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from .models import LedgerEntry, LedgerEntryKind, ReasoningLedger

SCHEMA_VERSION = "calyx-epistemic-memory/1"

# These entry classes are useful to recall as prior machine reasoning. Recall does
# not turn them into evidence: downstream consumers must still resolve independent
# source evidence before a new scientific assertion can cross publication gates.
RECALLABLE_KINDS = frozenset(
    {
        LedgerEntryKind.HYPOTHESIS,
        LedgerEntryKind.CONCLUSION,
        LedgerEntryKind.CONFLICT,
        LedgerEntryKind.REVIEW_DECISION,
        LedgerEntryKind.MEMORY_REF,
        LedgerEntryKind.ASSUMPTION,
    }
)

SCIENTIFIC_INFERENCE_KINDS = frozenset(
    {
        LedgerEntryKind.HYPOTHESIS,
        LedgerEntryKind.CONCLUSION,
        LedgerEntryKind.ASSUMPTION,
        LedgerEntryKind.CONFLICT,
    }
)

REFERENCE_RELATION_BY_KIND = {
    LedgerEntryKind.SUPPORT: "supports",
    LedgerEntryKind.COUNTEREVIDENCE: "counters",
    LedgerEntryKind.CONFLICT: "conflicts_with",
    LedgerEntryKind.MEMORY_REF: "references_memory",
    LedgerEntryKind.REVIEW_DECISION: "reviews",
    LedgerEntryKind.ASSUMPTION: "assumes",
    LedgerEntryKind.HYPOTHESIS: "derived_from",
    LedgerEntryKind.CONCLUSION: "derived_from",
    LedgerEntryKind.OPERATION: "derived_from",
    LedgerEntryKind.INTERMEDIATE_ARTIFACT: "derived_from",
    LedgerEntryKind.PLAN: "derived_from",
}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _entry_node_id(ledger: ReasoningLedger, entry: LedgerEntry) -> str:
    return f"reasoning:{ledger.ledger_id}:entry:{entry.entry_id}"


def _ledger_node_id(ledger: ReasoningLedger) -> str:
    return f"reasoning:{ledger.ledger_id}:revision:{ledger.version}"


def _edge_id(source: str, predicate: str, target: str) -> str:
    return f"reasoning-edge:{_canonical_hash([source, predicate, target])}"


def _provenance(entry: LedgerEntry) -> dict[str, Any] | None:
    provenance = entry.provenance
    if provenance is None:
        return None
    return {
        "source_kind": provenance.source_kind,
        "source_id": provenance.source_id,
        "literature_record_id": provenance.literature_record_id,
        "concept_id": provenance.concept_id,
        "rs_project_id": provenance.rs_project_id,
        "dataset_id": provenance.dataset_id,
        "method_id": provenance.method_id,
        "tool_id": provenance.tool_id,
        "execution_id": provenance.execution_id,
        "content_hash": provenance.content_hash,
        "retrieved_at": provenance.retrieved_at.isoformat(),
        "collector": provenance.collector,
        "extra": dict(provenance.extra),
    }


def _grounding_states(ledger: ReasoningLedger) -> dict[UUID, str]:
    entries = {entry.entry_id: entry for entry in ledger.entries}
    memo: dict[UUID, str] = {}

    def resolve(entry_id: UUID, stack: frozenset[UUID]) -> str:
        if entry_id in memo:
            return memo[entry_id]
        entry = entries.get(entry_id)
        if entry is None:
            return "ungrounded"
        if entry.provenance is not None:
            memo[entry_id] = "direct"
            return "direct"
        if entry_id in stack:
            return "ungrounded"
        next_stack = stack | {entry_id}
        for reference_id in entry.references_entry_ids:
            if resolve(reference_id, next_stack) in {"direct", "transitive"}:
                memo[entry_id] = "transitive"
                return "transitive"
        memo[entry_id] = "ungrounded"
        return "ungrounded"

    for entry_id in entries:
        resolve(entry_id, frozenset())
    return memo


def _node(
    ledger: ReasoningLedger,
    entry: LedgerEntry,
    grounding_state: str,
) -> dict[str, Any]:
    uncertainty = entry.uncertainty
    is_machine_scientific_memory = entry.kind in SCIENTIFIC_INFERENCE_KINDS
    recallable = entry.kind in RECALLABLE_KINDS
    unresolved_refs = [
        str(reference_id)
        for reference_id in entry.references_entry_ids
        if all(other.entry_id != reference_id for other in ledger.entries)
    ]
    return {
        "node_id": _entry_node_id(ledger, entry),
        "node_type": f"REASONING_{entry.kind.value.upper()}",
        "entry_id": str(entry.entry_id),
        "entry_kind": entry.kind.value,
        "text": entry.text,
        "ledger_id": str(ledger.ledger_id),
        "ledger_version": ledger.version,
        "project_id": ledger.project_id,
        "sequence": entry.sequence,
        "entry_version": entry.version,
        "content_hash": entry.fingerprint,
        "provenance": _provenance(entry),
        "grounding_state": grounding_state,
        "confidence": uncertainty.confidence if uncertainty else None,
        "uncertainty_rationale": uncertainty.rationale if uncertainty else None,
        "unresolved_assumptions": (
            list(uncertainty.unresolved_assumptions) if uncertainty else []
        ),
        "conflict_state": entry.conflict_state.value,
        "tags": list(entry.tags),
        "attributes": dict(entry.attributes),
        "unresolved_reference_ids": unresolved_refs,
        # Core anti-self-contamination boundary.
        "authority": "non_authoritative",
        "canonical_knowledge": False,
        "source_evidence": False,
        "can_be_cited_as_source_evidence": False,
        "can_trigger_publication": False,
        "requires_controlled_publication_gate": True,
        "requires_independent_evidence_for_new_claim": is_machine_scientific_memory,
        "machine_scientific_memory": is_machine_scientific_memory,
        "recallable": recallable,
        "reuse_role": "prior_reasoning_context" if recallable else "audit_context",
    }


def project_epistemic_memory(ledger: ReasoningLedger) -> dict[str, Any]:
    """Project one durable reasoning-ledger revision into an epistemic subgraph.

    The projection is deterministic and read-only. It deliberately does *not*
    publish to ``oc_graph``. Machine hypotheses and conclusions are institutional
    memory, not canonical scientific truth; controlled publication remains the only
    path to authoritative graph assertions.
    """

    grounding = _grounding_states(ledger)
    root_id = _ledger_node_id(ledger)
    entry_nodes = [
        _node(ledger, entry, grounding.get(entry.entry_id, "ungrounded"))
        for entry in ledger.entries
    ]
    entry_nodes.sort(key=lambda item: (item["sequence"], item["entry_id"]))

    nodes: list[dict[str, Any]] = [
        {
            "node_id": root_id,
            "node_type": "REASONING_LEDGER_REVISION",
            "ledger_id": str(ledger.ledger_id),
            "ledger_version": ledger.version,
            "project_id": ledger.project_id,
            "title": ledger.title,
            "status": ledger.status.value,
            "content_hash": ledger.ledger_fingerprint,
            "authority": "institutional_record",
            "canonical_knowledge": False,
            "source_evidence": False,
        }
    ] + entry_nodes

    entry_ids = {entry.entry_id for entry in ledger.entries}
    edges: list[dict[str, Any]] = []
    for entry in ledger.entries:
        entry_node_id = _entry_node_id(ledger, entry)
        edges.append(
            {
                "edge_id": _edge_id(root_id, "contains", entry_node_id),
                "source": root_id,
                "predicate": "contains",
                "target": entry_node_id,
                "authority": "structural",
            }
        )
        relation = REFERENCE_RELATION_BY_KIND.get(entry.kind, "references")
        for reference_id in entry.references_entry_ids:
            if reference_id not in entry_ids:
                continue
            target = f"reasoning:{ledger.ledger_id}:entry:{reference_id}"
            edges.append(
                {
                    "edge_id": _edge_id(entry_node_id, relation, target),
                    "source": entry_node_id,
                    "predicate": relation,
                    "target": target,
                    "authority": "non_authoritative_reasoning_relation",
                }
            )
    edges.sort(key=lambda item: item["edge_id"])

    recallable = [
        {
            "node_id": item["node_id"],
            "entry_id": item["entry_id"],
            "entry_kind": item["entry_kind"],
            "text": item["text"],
            "confidence": item["confidence"],
            "grounding_state": item["grounding_state"],
            "reuse_role": item["reuse_role"],
            "can_be_cited_as_source_evidence": False,
            "requires_independent_evidence_for_new_claim": item[
                "requires_independent_evidence_for_new_claim"
            ],
        }
        for item in entry_nodes
        if item["recallable"]
    ]

    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "ledger_id": str(ledger.ledger_id),
        "ledger_version": ledger.version,
        "nodes": nodes,
        "edges": edges,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "ledger_id": str(ledger.ledger_id),
        "ledger_version": ledger.version,
        "project_id": ledger.project_id,
        "memory_fingerprint": _canonical_hash(fingerprint_payload),
        "authority": "non_authoritative_epistemic_memory",
        "publication_boundary": {
            "automatic_promotion": False,
            "machine_memory_is_source_evidence": False,
            "controlled_graph_publication_required": True,
            "independent_evidence_required_for_new_scientific_claims": True,
        },
        "nodes": nodes,
        "edges": edges,
        "recallable_memories": recallable,
    }
