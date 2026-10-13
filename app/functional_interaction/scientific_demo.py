"""FIL-001 fixture demonstration: Literature -> Taxonomy -> Evidence Validation
-> TraitBank Candidate -> Scientific Reasoning.

Every handler delegates to code that already exists in this repository:

* literature claims: ``app.candidate_knowledge.extractor.extract_candidates``
* taxonomy: ``runtime.knowledge_graph.canonical_taxonomy`` (World Plants backbone)
* validation: ``app.candidate_knowledge.models.CandidateFact`` invariants
* TraitBank candidates: ``app.evidence_aggregation.models.CandidateInput``
* reasoning: ``app.reasoning_ledger.models.LedgerEntry``

It runs only over the synthetic fixture it is given. It does not read a
database, call a provider, append to a ledger, write a candidate store or
publish anything; its outputs are review-required drafts.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from app.candidate_knowledge.extractor import extract_candidates
from app.candidate_knowledge.models import (
    CandidateFact,
    CandidateKind,
    EvidenceInput,
    SourceAnchor,
)
from app.evidence_aggregation.models import CandidateInput
from app.reasoning_ledger.models import (
    ConflictState,
    LedgerEntry,
    LedgerEntryKind,
    LedgerProvenance,
    UncertaintyMarker,
)
from runtime.brain_capability_registry import canonical_brain_registry
from runtime.knowledge_graph.canonical_taxonomy import (
    build_canonical_registry,
    canonical_name_of,
)

from . import value_semantics
from .compatibility import check_edge
from .contracts import (
    FIXTURE_TAXON_AUTHORITY,
    AutonomyClass,
    BudgetRequirement,
    CapabilityDescriptor,
    HealthSpec,
    OperatorClass,
    PortSpec,
    ProvenanceRequirement,
)
from .dry_run import EXECUTOR_KEY, DryRunReport, Handler, HandlerResult, execute_dry_run
from .governance import evaluate_plan
from .planner import SourceArtifact, plan_workflow
from .registry import FunctionalRegistry

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "functional_interaction"
    / "fil_001_scientific_demo.json"
)
_ENTRY_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://orchid-continuum/fil-001/reasoning-draft"
)
_PROTOTYPE_EVIDENCE = (
    "FIL-001 fixture prototype; not wired to any route, worker or schedule",
)

SOURCE = SourceArtifact(
    semantic_type="oc:LiteraturePassageBatch",
    evidence_states=("UNKNOWN",),
    conditions=("source_anchored",),
)


def _status(status: str, *reasons: str) -> HealthSpec:
    return HealthSpec(
        status=status, evidence=_PROTOTYPE_EVIDENCE, failure_reasons=reasons
    )


def demo_descriptors() -> tuple[CapabilityDescriptor, ...]:
    """The five chain functions plus one provider-requiring explainer."""

    return (
        CapabilityDescriptor(
            capability_id="fil.literature.claim-transducer",
            version="1.0.0",
            operator_class=OperatorClass.TRANSDUCER,
            registry_capability="literature-evidence-lookup",
            summary="Transduce source-anchored passages into structured candidate claims.",
            implementation="app.candidate_knowledge.extractor.extract_candidates",
            inputs=(
                PortSpec(
                    "passages",
                    "oc:LiteraturePassageBatch",
                    ("UNKNOWN",),
                    "app.candidate_knowledge.models.EvidenceInput",
                ),
            ),
            outputs=(
                PortSpec(
                    "claims",
                    "oc:ExtractedClaimBatch",
                    ("UNKNOWN",),
                    "app.candidate_knowledge.models.CandidateFact",
                ),
            ),
            preconditions=("source_anchored",),
            effects=("claims_anchored",),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            provenance=ProvenanceRequirement(requires_source_anchor=True),
            emits=("evidence.assertion.created",),
            health=_status(
                "IMPLEMENTED_NOT_INTEGRATED",
                "EXACT_SOURCE_ANCHORS_REQUIRED",
                "EMPTY_EVIDENCE",
            ),
        ),
        CapabilityDescriptor(
            capability_id="fil.taxonomy.backbone-adaptor",
            version="1.0.0",
            operator_class=OperatorClass.ADAPTOR,
            registry_capability="taxonomy-resolution",
            summary="Map claim subjects to the canonical World Plants backbone; never fuzzy, never dropped.",
            implementation="runtime.knowledge_graph.canonical_taxonomy.CanonicalRegistry.resolve",
            inputs=(PortSpec("claims", "oc:ExtractedClaimBatch", ("UNKNOWN",)),),
            outputs=(
                PortSpec("linked_claims", "oc:TaxonLinkedClaimBatch", ("UNKNOWN",)),
            ),
            preconditions=("claims_anchored",),
            effects=("taxon_resolution_recorded",),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            emits=("taxonomy.name.resolved",),
            health=_status("IMPLEMENTED_NOT_INTEGRATED", "TAXON_UNRESOLVED"),
        ),
        CapabilityDescriptor(
            capability_id="fil.evidence.candidate-validator",
            version="1.0.0",
            operator_class=OperatorClass.VALIDATOR,
            registry_capability="schema-validation",
            summary="Assign each linked claim an explicit evidence state with reasons; never VERIFIED.",
            implementation="app.candidate_knowledge.models.CandidateFact",
            inputs=(
                PortSpec("linked_claims", "oc:TaxonLinkedClaimBatch", ("UNKNOWN",)),
            ),
            outputs=(
                PortSpec(
                    "validated_claims",
                    "oc:ValidatedClaimBatch",
                    ("PROVISIONAL", "UNKNOWN", "REJECTED"),
                ),
            ),
            preconditions=("claims_anchored", "taxon_resolution_recorded"),
            effects=("evidence_state_assigned",),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            emits=("evidence.assertion.withheld",),
            health=_status(
                "IMPLEMENTED_NOT_INTEGRATED",
                "TAXON_UNRESOLVED",
                "CANDIDATE_VALUE_REQUIRED",
            ),
        ),
        CapabilityDescriptor(
            capability_id="fil.traitbank.candidate-buffer",
            version="1.0.0",
            operator_class=OperatorClass.BUFFER,
            registry_capability="provenance-assembly",
            summary="Hold provisional claims as review-required TraitBank candidates in the aggregation input contract.",
            implementation="app.evidence_aggregation.models.CandidateInput",
            inputs=(
                PortSpec(
                    "validated_claims", "oc:ValidatedClaimBatch", ("PROVISIONAL",)
                ),
            ),
            outputs=(
                PortSpec(
                    "candidates",
                    "oc:TraitBankCandidateBatch",
                    ("PROVISIONAL",),
                    "app.evidence_aggregation.models.CandidateInput",
                ),
            ),
            preconditions=("evidence_state_assigned",),
            effects=("candidate_only", "human_review_required"),
            permissions=("candidate_generation",),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            emits=("artifact.created",),
            health=_status(
                "IMPLEMENTED_NOT_INTEGRATED", "EXACT_SOURCE_ANCHORS_REQUIRED"
            ),
        ),
        CapabilityDescriptor(
            capability_id="fil.reasoning.ledger-integrator",
            version="1.0.0",
            operator_class=OperatorClass.INTEGRATOR,
            registry_capability="contradiction-detection",
            summary="Integrate candidates into unpublished reasoning-ledger drafts marking support, conflict and gaps.",
            implementation="app.reasoning_ledger.models.LedgerEntry",
            brain_capability_id="reasoning_ledger",
            inputs=(
                PortSpec("candidates", "oc:TraitBankCandidateBatch", ("PROVISIONAL",)),
            ),
            outputs=(
                PortSpec(
                    "reasoning",
                    "oc:ReasoningDraft",
                    ("CONTRADICTORY", "PROVISIONAL"),
                    "app.reasoning_ledger.models.LedgerEntry",
                ),
            ),
            preconditions=("candidate_only", "human_review_required"),
            effects=("contradictions_marked", "evidence_gaps_marked"),
            permissions=("candidate_generation",),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            emits=("evidence.assertion.conflicted",),
            health=_status("IMPLEMENTED_NOT_INTEGRATED"),
        ),
        CapabilityDescriptor(
            capability_id="fil.reasoning.prose-explainer",
            version="0.1.0",
            operator_class=OperatorClass.AMPLIFIER,
            registry_capability="natural-language-explanation",
            summary="Render a reasoning draft as plain-language prose (needs a language model).",
            inputs=(
                PortSpec(
                    "reasoning", "oc:ReasoningDraft", ("CONTRADICTORY", "PROVISIONAL")
                ),
            ),
            outputs=(
                PortSpec(
                    "explanation", "oc:PlainLanguageExplanation", ("PROVISIONAL",)
                ),
            ),
            preconditions=("human_review_required",),
            autonomy_class=AutonomyClass.HUMAN_APPROVAL,
            budget=BudgetRequirement(provider_calls_max=1, cost_units_max=5),
            emits=("ai.provider.used",),
            health=_status("DOCUMENTED_ONLY", "NO_API_PROVIDER_WORK_PARKED"),
        ),
    )


def demo_registry() -> FunctionalRegistry:
    return FunctionalRegistry(
        demo_descriptors(), brain_registry=canonical_brain_registry()
    )


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _passthrough(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"gaps": list(payload.get("gaps", [])), "fixture_id": payload["fixture_id"]}


def _provenance(items: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted({item["provenance"] for item in items}))


def build_handlers(fixture: Mapping[str, Any]) -> dict[str, Handler]:
    """Dry-run handlers bound to the fixture's taxonomy backbone and clock."""

    taxonomy = fixture["taxonomy"]
    backbone = build_canonical_registry(taxonomy["load_rows"], taxonomy["synonym_rows"])
    release = taxonomy["release_label"]
    as_of = datetime.fromisoformat(fixture["as_of"])

    def transduce(payload: Mapping[str, Any]) -> HandlerResult:
        claims: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        for passage in payload["passages"]:
            evidence = EvidenceInput(
                source_object_type="fil_fixture_passage",
                source_object_id=passage["source_object_id"],
                revision_id=passage["revision_id"],
                extraction_run_id=passage["extraction_run_id"],
                text=passage["text"],
                source_anchors=(
                    SourceAnchor(
                        passage["anchor_id"],
                        char_start=0,
                        char_end=len(passage["text"]),
                    ),
                ),
                metadata={"subject": passage["subject"]},
            )
            facts = extract_candidates(evidence)
            if not facts:
                gaps.append(
                    {
                        "kind": "PASSAGE_WITHOUT_EXTRACTABLE_CLAIM",
                        "source_document_id": passage["source_document_id"],
                        "provenance": f"fixture://{passage['source_document_id']}#anchor-{passage['anchor_id']}",
                    }
                )
            for index, fact in enumerate(facts):
                claims.append(
                    {
                        "claim_id": f"{passage['source_document_id']}:{passage['anchor_id']}:{index}",
                        "source_document_id": passage["source_document_id"],
                        "source_revision_id": passage["revision_id"],
                        "anchor_id": passage["anchor_id"],
                        "provenance": f"fixture://{passage['source_document_id']}#anchor-{passage['anchor_id']}",
                        "subject": fact.subject,
                        "kind": fact.kind.value,
                        "predicate": fact.predicate,
                        "object_value": fact.object_value,
                        "numeric_value": fact.numeric_value,
                        "unit": fact.unit,
                        "confidence": fact.confidence,
                        "method": fact.method,
                        "evidence_state": "UNKNOWN",
                    }
                )
        return HandlerResult(
            output={
                "fixture_id": payload["fixture_id"],
                "claims": claims,
                "gaps": gaps,
            },
            established=("claims_anchored",),
            evidence_states=("UNKNOWN",),
            events=("evidence.assertion.created",) if claims else (),
            provenance=_provenance(claims + gaps),
            notes={"claims": len(claims), "passages": len(payload["passages"])},
        )

    def resolve(payload: Mapping[str, Any]) -> HandlerResult:
        linked = []
        for claim in payload["claims"]:
            taxon = backbone.resolve(claim["subject"])
            submitted = canonical_name_of(claim["subject"])
            if taxon is None:
                link = {
                    "status": "unresolved",
                    "canonical_id": None,
                    "canonical_name": None,
                }
            else:
                link = {
                    "status": "accepted"
                    if taxon.canonical_name == submitted
                    else "synonym",
                    "canonical_id": taxon.canonical_id,
                    "canonical_name": taxon.canonical_name,
                }
            link.update(
                submitted_name=claim["subject"],
                authority=FIXTURE_TAXON_AUTHORITY,
                release=release,
                method="exact_canonical_name",
                automatic_fuzzy_matching=False,
            )
            linked.append({**claim, "taxon_link": link})
        return HandlerResult(
            output={**_passthrough(payload), "claims": linked},
            established=("taxon_resolution_recorded",),
            evidence_states=("UNKNOWN",),
            events=("taxonomy.name.resolved",) if linked else (),
            provenance=_provenance(linked + list(payload.get("gaps", []))),
            notes={
                "unresolved": sum(
                    1 for item in linked if item["taxon_link"]["status"] == "unresolved"
                )
            },
        )

    def validate(payload: Mapping[str, Any]) -> HandlerResult:
        validated = []
        for claim in payload["claims"]:
            reasons: list[str] = []
            try:
                CandidateFact(
                    kind=CandidateKind(claim["kind"]),
                    subject=claim["subject"],
                    predicate=claim["predicate"],
                    object_value=claim["object_value"],
                    numeric_value=claim["numeric_value"],
                    unit=claim["unit"],
                    confidence=claim["confidence"],
                    method=claim["method"],
                )
            except ValueError as exc:
                state, reasons = "REJECTED", [str(exc)]
            else:
                if not claim.get("anchor_id"):
                    state, reasons = "REJECTED", ["EXACT_SOURCE_ANCHOR_REQUIRED"]
                elif claim["taxon_link"]["status"] == "unresolved":
                    state, reasons = "UNKNOWN", ["TAXON_UNRESOLVED"]
                else:
                    state, reasons = (
                        "PROVISIONAL",
                        ["MACHINE_EXTRACTED_REQUIRES_HUMAN_REVIEW"],
                    )
            validated.append(
                {**claim, "evidence_state": state, "validation_reasons": reasons}
            )
        withheld = [
            item for item in validated if item["evidence_state"] != "PROVISIONAL"
        ]
        return HandlerResult(
            output={**_passthrough(payload), "claims": validated},
            established=("evidence_state_assigned",),
            evidence_states=tuple(
                sorted({item["evidence_state"] for item in validated})
            ),
            events=("evidence.assertion.withheld",) if withheld else (),
            provenance=_provenance(validated + list(payload.get("gaps", []))),
            notes={
                "states": {
                    s: sum(1 for i in validated if i["evidence_state"] == s)
                    for s in sorted({i["evidence_state"] for i in validated})
                }
            },
        )

    def buffer(payload: Mapping[str, Any]) -> HandlerResult:
        candidates: list[dict[str, Any]] = []
        traitbank_rows: list[dict[str, Any]] = []
        withheld: list[dict[str, Any]] = []
        for claim in payload["claims"]:
            if claim["evidence_state"] != "PROVISIONAL":
                withheld.append(
                    {
                        "claim_id": claim["claim_id"],
                        "evidence_state": claim["evidence_state"],
                        "reasons": claim["validation_reasons"],
                        "provenance": claim["provenance"],
                    }
                )
                continue
            link = claim["taxon_link"]
            candidate = CandidateInput(
                candidate_id=len(candidates) + 1,
                candidate_version=1,
                candidate_type=claim["kind"],
                normalized_subject=link["canonical_name"],
                predicate=claim["predicate"],
                object_value=claim["object_value"],
                numeric_value=claim["numeric_value"],
                unit=claim["unit"],
                source_revision_id=claim["source_revision_id"],
                source_document_id=claim["source_document_id"],
                source_anchor_ids=(claim["anchor_id"],),
                evidence_type="LITERATURE",
                source_class="FIL_001_FIXTURE",
                directness="DIRECT",
                taxon_links=(
                    {
                        "candidate_taxon_id": link["canonical_id"],
                        "source_name": link["submitted_name"],
                        "match": link["status"],
                        "authority": link["authority"],
                    },
                ),
                confidence=claim["confidence"],
                metadata={
                    "claim_id": claim["claim_id"],
                    "provenance": claim["provenance"],
                    "fixture": True,
                },
            )
            candidates.append(json.loads(json.dumps(asdict(candidate))))
            traitbank_rows.append(
                {
                    "source_key": claim["claim_id"],
                    "scientific_name": link["canonical_name"],
                    "taxonomy_id": link["canonical_id"],
                    "trait_raw": claim["predicate"],
                    "value_raw": claim["object_value"]
                    if claim["object_value"] is not None
                    else claim["numeric_value"],
                    "units_raw": claim["unit"],
                    "reference_raw": claim["provenance"],
                    "review_state": "REQUIRED",
                }
            )
        gaps = list(payload.get("gaps", [])) + [
            {
                "kind": "CLAIM_WITHHELD",
                "claim_id": item["claim_id"],
                "reasons": item["reasons"],
                "provenance": item["provenance"],
            }
            for item in withheld
        ]
        return HandlerResult(
            output={
                "fixture_id": payload["fixture_id"],
                "gaps": gaps,
                "candidates": candidates,
                "traitbank_rows": traitbank_rows,
                "withheld": withheld,
                "review_required": True,
                "published": False,
            },
            established=("candidate_only", "human_review_required"),
            evidence_states=("PROVISIONAL",) if candidates else (),
            events=("artifact.created",) if candidates else (),
            provenance=tuple(
                sorted(
                    {row["reference_raw"] for row in traitbank_rows}
                    | {w["provenance"] for w in withheld}
                )
            ),
            notes={"candidates": len(candidates), "withheld": len(withheld)},
        )

    def integrate(payload: Mapping[str, Any]) -> HandlerResult:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for candidate in payload["candidates"]:
            groups.setdefault(
                (candidate["normalized_subject"], candidate["predicate"]), []
            ).append(candidate)
        entries = []
        states: set[str] = set()
        for sequence, (key, members) in enumerate(sorted(groups.items())):
            # Compare normalized values (case, separators, length units) so only
            # mutually exclusive categorical claims become conflicts.
            keys = [
                value_semantics.value_key(
                    object_value=m["object_value"],
                    numeric_value=m["numeric_value"],
                    unit=m["unit"],
                )
                for m in members
            ]
            values = sorted({value_semantics.display(k) for k in keys})
            comparison = value_semantics.classify(key[1], keys)
            documents = sorted({m["source_document_id"] for m in members})
            # Each member's exact evidence span stays traceable from the draft.
            anchors = sorted(
                (
                    {
                        "candidate_id": m["candidate_id"],
                        "source_document_id": m["source_document_id"],
                        "source_anchor_ids": list(m["source_anchor_ids"]),
                        "provenance": m["metadata"]["provenance"],
                    }
                    for m in members
                ),
                key=lambda a: a["candidate_id"],
            )
            contradictory = comparison == value_semantics.CONTRADICTION
            states.add("CONTRADICTORY" if contradictory else "PROVISIONAL")
            first = min(members, key=lambda m: m["candidate_id"])
            entry = LedgerEntry(
                entry_id=uuid.uuid5(
                    _ENTRY_NAMESPACE, f"{payload['fixture_id']}:{key[0]}:{key[1]}"
                ),
                kind=LedgerEntryKind.CONFLICT
                if contradictory
                else LedgerEntryKind.SUPPORT,
                sequence=sequence,
                text=(
                    f"{key[0]} {key[1]}: sources disagree ({', '.join(values)})"
                    if contradictory
                    else f"{key[0]} {key[1]}: {', '.join(values)} ({comparison.lower()})"
                    if len(values) > 1
                    else f"{key[0]} {key[1]}: {values[0]} (single machine-extracted source)"
                ),
                author=EXECUTOR_KEY,
                tenant_id="fil-001-fixture",
                project_id="fil-001-dry-run",
                provenance=LedgerProvenance(
                    source_kind="literature",
                    source_id=first["source_document_id"],
                    retrieved_at=as_of,
                    collector=EXECUTOR_KEY,
                    extra={
                        "source_document_ids": documents,
                        "evidence_anchors": anchors,
                    },
                ),
                uncertainty=UncertaintyMarker(
                    confidence=min(m["confidence"] for m in members),
                    rationale="Machine-extracted fixture claims; no human review has occurred.",
                    unresolved_assumptions=(
                        "extraction rule correctness",
                        "source reliability unassessed",
                    ),
                ),
                conflict_state=ConflictState.UNRESOLVED,
                tags=("fil-001", "dry-run", "review-required"),
                attributes={
                    "values": values,
                    "candidate_ids": sorted(m["candidate_id"] for m in members),
                },
                created_at=as_of,
            )
            entries.append(
                {
                    "entry_id": str(entry.entry_id),
                    "kind": entry.kind.value,
                    "text": entry.text,
                    "fingerprint": entry.fingerprint,
                    "evidence_state": "CONTRADICTORY"
                    if contradictory
                    else "PROVISIONAL",
                    "subject": key[0],
                    "predicate": key[1],
                    "values": values,
                    "value_comparison": comparison,
                    "source_document_ids": documents,
                    "evidence_anchors": anchors,
                    "confidence": entry.uncertainty.confidence
                    if entry.uncertainty
                    else None,
                    "conflict_state": entry.conflict_state.value,
                }
            )
        return HandlerResult(
            output={
                "fixture_id": payload["fixture_id"],
                "entries": entries,
                "evidence_gaps": list(payload.get("gaps", [])),
                "human_review_required": True,
                "publication_authority": False,
                "ledger_appended": False,
            },
            established=("contradictions_marked", "evidence_gaps_marked"),
            evidence_states=tuple(sorted(states)),
            events=("evidence.assertion.conflicted",)
            if "CONTRADICTORY" in states
            else (),
            provenance=tuple(
                sorted(
                    {
                        f"fixture://{d}"
                        for e in entries
                        for d in e["source_document_ids"]
                    }
                    | {gap["provenance"] for gap in payload.get("gaps", [])}
                )
            ),
            notes={"entries": len(entries), "gaps": len(payload.get("gaps", []))},
        )

    return {
        "fil.literature.claim-transducer": transduce,
        "fil.taxonomy.backbone-adaptor": resolve,
        "fil.evidence.candidate-validator": validate,
        "fil.traitbank.candidate-buffer": buffer,
        "fil.reasoning.ledger-integrator": integrate,
    }


def source_payload(fixture: Mapping[str, Any]) -> dict[str, Any]:
    return {"fixture_id": fixture["fixture_id"], "passages": list(fixture["passages"])}


def run_dry_run(
    fixture: Mapping[str, Any], *, registry: FunctionalRegistry | None = None
) -> DryRunReport:
    registry = registry or demo_registry()
    plan = plan_workflow(registry, source=SOURCE, goal_type="oc:ReasoningDraft")
    decision = evaluate_plan(plan)
    return execute_dry_run(
        plan, decision, build_handlers(fixture), source_payload(fixture)
    )


def run_demonstration(fixture: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The full FIL-001 demonstration as one deterministic, JSON-serializable record."""

    fixture = fixture if fixture is not None else load_fixture()
    registry = demo_registry()
    by_id = {d.capability_id: d for d in registry.descriptors()}

    chain = [
        "fil.literature.claim-transducer",
        "fil.taxonomy.backbone-adaptor",
        "fil.evidence.candidate-validator",
        "fil.traitbank.candidate-buffer",
        "fil.reasoning.ledger-integrator",
    ]
    conditions: tuple[str, ...] = SOURCE.conditions
    chain_edges = []
    for producer_id, consumer_id in pairwise(chain):
        producer, consumer = by_id[producer_id], by_id[consumer_id]
        edge = check_edge(
            producer,
            producer.outputs[0].name,
            consumer,
            consumer.inputs[0].name,
            upstream_conditions=conditions,
        )
        conditions = edge.carried_conditions
        chain_edges.append(edge.to_dict())
    counter_examples = [
        check_edge(
            by_id["fil.reasoning.ledger-integrator"],
            "reasoning",
            by_id["fil.evidence.candidate-validator"],
            "linked_claims",
        ).to_dict(),
        check_edge(
            by_id["fil.literature.claim-transducer"],
            "claims",
            by_id["fil.traitbank.candidate-buffer"],
            "validated_claims",
        ).to_dict(),
    ]

    plan = plan_workflow(registry, source=SOURCE, goal_type="oc:ReasoningDraft")
    decision = evaluate_plan(plan)
    report = execute_dry_run(
        plan, decision, build_handlers(fixture), source_payload(fixture)
    )
    parked_plan = plan_workflow(
        registry, source=SOURCE, goal_type="oc:PlainLanguageExplanation"
    )

    return {
        "schema": "oc.fil.scientific-demonstration.v1",
        "fixture_id": fixture["fixture_id"],
        "fixture_notice": fixture["fixture_notice"],
        "discovery": {
            "registry": registry.view(),
            "consumers_of_validated_claims": [
                d.capability_id
                for d in registry.discover(consumes="oc:ValidatedClaimBatch")
            ],
            "producers_of_reasoning_drafts": [
                d.capability_id for d in registry.discover(produces="oc:ReasoningDraft")
            ],
        },
        "compatibility": {
            "chain_edges": chain_edges,
            "counter_examples": counter_examples,
        },
        "plan": plan.to_dict(),
        "governance": decision.to_dict(),
        "dry_run": report.to_dict(),
        "downstream": report.final_output,
        "provider_goal": {
            "plan": parked_plan.to_dict(),
            "governance": evaluate_plan(parked_plan).to_dict(),
        },
    }
