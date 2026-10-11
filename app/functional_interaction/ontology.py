"""FIL-001 semantic type ontology.

Every port carries one ``oc:`` semantic type. The ontology is a single-parent
hierarchy: a producer of a subtype satisfies a consumer of its supertype, never
the reverse. Types name artifacts that already exist in the codebase; the
``schema_ref`` on each entry is the existing contract the artifact conforms to.

Adding a type is a deliberate act, like adding a capability: an unknown type is
refused rather than matched by spelling.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError


@dataclass(frozen=True)
class SemanticType:
    name: str
    parent: str | None
    schema_ref: str | None
    description: str


_TYPES = (
    SemanticType("oc:Artifact", None, None, "Root of every FIL artifact type."),
    SemanticType(
        "oc:LiteraturePassageBatch",
        "oc:Artifact",
        "app.candidate_knowledge.models.EvidenceInput",
        "Source-anchored literature passages awaiting extraction.",
    ),
    SemanticType(
        "oc:ClaimBatch",
        "oc:Artifact",
        "app.candidate_knowledge.models.CandidateFact",
        "Structured claims; carries no taxonomic or evidential verdict by itself.",
    ),
    SemanticType(
        "oc:ExtractedClaimBatch",
        "oc:ClaimBatch",
        "app.candidate_knowledge.models.CandidateFact",
        "Claims extracted from passages, each bound to its source anchor.",
    ),
    SemanticType(
        "oc:TaxonLinkedClaimBatch",
        "oc:ExtractedClaimBatch",
        "runtime.knowledge_graph.canonical_taxonomy.CanonicalTaxon",
        "Extracted claims with a canonical-backbone resolution attempt recorded.",
    ),
    SemanticType(
        "oc:ValidatedClaimBatch",
        "oc:TaxonLinkedClaimBatch",
        None,
        "Taxon-linked claims each carrying an explicit evidence state and reasons.",
    ),
    SemanticType(
        "oc:TraitBankCandidateBatch",
        "oc:Artifact",
        "app.evidence_aggregation.models.CandidateInput",
        "Review-required trait candidates in the evidence-aggregation input contract.",
    ),
    SemanticType(
        "oc:ReasoningDraft",
        "oc:Artifact",
        "app.reasoning_ledger.models.LedgerEntry",
        "Unpublished reasoning-ledger entries: support, conflict and gaps.",
    ),
    SemanticType(
        "oc:LiteratureDocumentBatch",
        "oc:Artifact",
        "app.literature_extraction.ingest.ingest_text",
        "Content-addressed literature documents awaiting the extraction pipeline.",
    ),
    SemanticType(
        "oc:PaperClaimBatch",
        "oc:ExtractedClaimBatch",
        "app.literature_extraction.models.Claim",
        "Claims from the canonical literature pipeline, each with its exact span.",
    ),
    SemanticType(
        "oc:TraitBankRecordBatch",
        "oc:TraitBankCandidateBatch",
        "harvesters.traitbank.TraitBankHarvester._normalize",
        "Taxon-resolved records in the TraitBank harvester shape plus aggregation inputs.",
    ),
    SemanticType(
        "oc:CalyxCandidateHandoffBatch",
        "oc:Artifact",
        "app.parallel_platform.brain_candidate_handoff.BrainCandidateHandoffRequest",
        "Review-required candidates admitted through the Brain-to-Calyx handoff.",
    ),
    SemanticType(
        "oc:PlainLanguageExplanation",
        "oc:Artifact",
        None,
        "Generated prose explaining a reasoning draft (provider-requiring).",
    ),
    SemanticType(
        "oc:PublishedKnowledge",
        "oc:Artifact",
        "app.reasoning_publication.models.PublicationArtifact",
        "Knowledge published to the governed graph (owner-gated, never automatic).",
    ),
)

SEMANTIC_TYPES: dict[str, SemanticType] = {item.name: item for item in _TYPES}

for _item in _TYPES:
    if (
        _item.parent is not None and _item.parent not in SEMANTIC_TYPES
    ):  # pragma: no cover - static data
        raise ContractError(f"UNKNOWN_PARENT_TYPE:{_item.parent}")


def require_type(name: str) -> SemanticType:
    try:
        return SEMANTIC_TYPES[name]
    except KeyError as exc:
        raise ContractError(f"UNKNOWN_SEMANTIC_TYPE:{name}") from exc


def lineage(name: str) -> tuple[str, ...]:
    """The type and every ancestor, most specific first."""
    chain: list[str] = []
    current: str | None = name
    while current is not None:
        if current in chain:  # pragma: no cover - static data has no cycles
            raise ContractError(f"SEMANTIC_TYPE_CYCLE:{name}")
        chain.append(current)
        current = require_type(current).parent
    return tuple(chain)


def is_subtype(candidate: str, required: str) -> bool:
    """True when an artifact of ``candidate`` type satisfies a ``required`` port."""
    require_type(required)
    return required in lineage(candidate)
