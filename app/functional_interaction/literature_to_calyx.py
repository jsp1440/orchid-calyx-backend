"""FIL-001B offline chain: Literature -> Taxonomy -> Evidence -> TraitBank -> Calyx.

Every step delegates to the canonical implementation that already owns it:

* Literature: ``app.literature_extraction`` pipeline (metadata, sections,
  entities, claims, normalization, review queue), run in-process with no output
  writer, over content-addressed fixture documents.
* Taxonomy: ``runtime.knowledge_graph.canonical_taxonomy`` (World Plants).
  Names are matched exactly against the backbone; nothing is fuzzy, nothing is
  created, and an ambiguous or unknown name is recorded, never guessed.
* Evidence: ``app.candidate_knowledge.extractor.extract_candidates`` turns each
  anchored claim sentence into structured facts; hedged language and
  interpretation-section claims carry explicit uncertainty.
* TraitBank: records in the ``harvesters.traitbank`` normalized shape, checked
  by ``harvesters.execution._validate_traitbank_record``, plus
  ``app.evidence_aggregation.models.CandidateInput`` aggregation inputs.
* Calyx: an ``oc-verification-handoff-v1`` packet per candidate value, admitted
  through ``app.parallel_platform.reasoning_contract_bridge`` into
  ``brain_candidate_handoff.handoff_brain_candidate`` -- the existing
  Brain-to-Calyx path. Candidates land review-required and unpublished.

Contradictory categorical findings become separate candidates that name each
other; differing measurements at an unstated assertion level are recorded as
variation, not conflict. Withheld claims and evidence gaps travel to Calyx with
their provenance. The candidate repository is injected: in-memory by default,
the existing PostgreSQL snapshot repository when a caller supplies one.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.executor import canonical_checksum
from app.candidate_knowledge.extractor import extract_candidates
from app.candidate_knowledge.models import EvidenceInput, SourceAnchor
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.evidence_aggregation.models import CandidateInput
from app.literature_extraction.context import PipelineContext
from app.literature_extraction.extractors.claims import ClaimExtractor
from app.literature_extraction.extractors.entities import EntityExtractor
from app.literature_extraction.extractors.metadata import MetadataExtractor
from app.literature_extraction.extractors.sections import SectionExtractor
from app.literature_extraction.ingest import build_empty_paper, ingest_text
from app.literature_extraction.normalization import normalize_and_reconcile
from app.literature_extraction.pipeline import PipelineRunner
from app.literature_extraction.review import (
    build_review_queue,
    refresh_publication_decisions,
)
from harvesters.execution import _validate_traitbank_record
from runtime.brain_capability_registry import canonical_brain_registry
from runtime.knowledge_graph.canonical_taxonomy import (
    build_canonical_registry,
    canonical_name_of,
)

from . import value_semantics
from .contracts import (
    AutonomyClass,
    CapabilityDescriptor,
    HealthSpec,
    OperatorClass,
    PortSpec,
    ProvenanceRequirement,
    TaxonResolutionPolicy,
)
from .dry_run import DryRunReport, Handler, HandlerResult, execute_dry_run
from .governance import evaluate_plan
from .planner import SourceArtifact, WorkflowPlan, plan_workflow
from .registry import FunctionalRegistry

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "functional_interaction"
    / "fil_001b"
)
SOURCE_OBJECT_TYPE = "fil_001b_literature_claim"
_PROTOTYPE_EVIDENCE = (
    "FIL-001B offline prototype; not wired to any route, worker or schedule",
)
_BINOMIAL = re.compile(r"^[A-Z][a-z]+ [a-z][a-z-]+$")
_HEDGE = re.compile(
    r"\b(?:may|might|possibly|probably|likely|suggests?|appears?)\b", re.IGNORECASE
)


_DEPENDENCIES_MODULE = "app.candidate_knowledge.dependencies"
#: Present only in the lazy form of that module (issue #1826 / draft PR #1827).
_LAZY_DEPENDENCIES_MARKER = "def resolve_components("
_DATABASE_ENV = ("DATABASE_URL", "TEST_DATABASE_URL")


def import_time_database_contact_risk() -> tuple[str, ...]:
    """Database variables FIL's first import of the bridge would connect with.

    ``app.parallel_platform.brain_candidate_handoff`` imports
    ``app.candidate_knowledge.dependencies``. In its current eager form, that
    module builds a repository from ``DATABASE_URL`` / ``TEST_DATABASE_URL``
    *at import time*: it connects and, if the schema is absent, creates it.
    The risk is empty when the module is already imported (FIL would cause no
    new contact), when no database variable is set, or when the installed
    module is the lazy form. The module source is read, never executed, to
    decide.
    """
    if _DEPENDENCIES_MODULE in sys.modules:
        return ()
    configured = tuple(name for name in _DATABASE_ENV if os.getenv(name))
    if not configured:
        return ()
    spec = importlib.util.find_spec(_DEPENDENCIES_MODULE)
    origin = Path(spec.origin) if spec is not None and spec.origin else None
    if origin is not None and _LAZY_DEPENDENCIES_MARKER in origin.read_text():
        return ()
    return configured


def _calyx_bridge(*, allow_import_time_database_contact: bool = False):
    """Import the existing Brain-to-Calyx handoff only when the Calyx step runs.

    Describing, planning and governing FIL plans never import it. Running the
    Calyx step refuses to trigger the eager module's import-time connection
    unless the caller explicitly allows it: an offline run must not reach
    whatever database the environment happens to name. The refusal surfaces
    as a BLOCKED receipt, not a silent skip.
    """
    risk = import_time_database_contact_risk()
    if risk and not allow_import_time_database_contact:
        raise RuntimeError(f"IMPORT_TIME_DATABASE_CONTACT_REFUSED:{','.join(risk)}")
    from app.parallel_platform.brain_candidate_handoff import (
        DOMAIN_KINDS,
        handoff_brain_candidate,
    )
    from app.parallel_platform.reasoning_contract_bridge import (
        verification_packet_to_handoff_request,
    )

    kind_domain = {kind.value: domain for domain, kind in DOMAIN_KINDS.items()}
    return verification_packet_to_handoff_request, handoff_brain_candidate, kind_domain


SOURCE = SourceArtifact(
    semantic_type="oc:LiteratureDocumentBatch",
    evidence_states=("UNKNOWN",),
    conditions=("source_content_addressed",),
)
#: The fixture backbone is invented and built with the World Plants spine
#: builder; it is NOT a World Plants release. Links, conditions and subject ids
#: therefore name this fixture authority, never ``world_plants``, so no fixture
#: output can be mistaken for canonical taxonomy provenance. A real run must
#: resolve against a pinned World Plants release under the contract default
#: authority (FIL-001C).
FIXTURE_TAXON_AUTHORITY = "fil_fixture_backbone"
TAXON_PROVIDER = TaxonResolutionPolicy(
    role="provides", authority=FIXTURE_TAXON_AUTHORITY
)
TAXON_ADMISSION = TaxonResolutionPolicy(
    role="requires",
    authority=FIXTURE_TAXON_AUTHORITY,
    admitted_statuses=("accepted", "synonym"),
)
_TAXON_CONDITIONS = TAXON_ADMISSION.conditions


def _health(*reasons: str) -> HealthSpec:
    return HealthSpec(
        status="IMPLEMENTED_NOT_INTEGRATED",
        evidence=_PROTOTYPE_EVIDENCE,
        failure_reasons=reasons,
    )


def chain_descriptors() -> tuple[CapabilityDescriptor, ...]:
    return (
        CapabilityDescriptor(
            capability_id="fil.literature.paper-transducer",
            version="1.0.0",
            operator_class=OperatorClass.TRANSDUCER,
            registry_capability="literature-evidence-lookup",
            summary="Run the canonical literature pipeline and emit span-anchored claims.",
            implementation="app.literature_extraction.pipeline.PipelineRunner",
            inputs=(PortSpec("documents", "oc:LiteratureDocumentBatch", ("UNKNOWN",)),),
            outputs=(
                PortSpec(
                    "claims",
                    "oc:PaperClaimBatch",
                    ("UNKNOWN",),
                    "app.literature_extraction.models.Claim",
                ),
            ),
            preconditions=("source_content_addressed",),
            effects=("claims_anchored",),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            provenance=ProvenanceRequirement(requires_source_anchor=True),
            emits=("evidence.assertion.created",),
            health=_health("PIPELINE_INCOMPLETE"),
        ),
        CapabilityDescriptor(
            capability_id="fil.taxonomy.literature-name-adaptor",
            version="1.0.0",
            operator_class=OperatorClass.ADAPTOR,
            registry_capability="taxonomy-resolution",
            summary="Resolve source-declared and backbone names in each claim, exactly, against World Plants.",
            implementation="runtime.knowledge_graph.canonical_taxonomy.CanonicalRegistry.resolve",
            inputs=(PortSpec("claims", "oc:ExtractedClaimBatch", ("UNKNOWN",)),),
            outputs=(
                PortSpec("linked_claims", "oc:TaxonLinkedClaimBatch", ("UNKNOWN",)),
            ),
            preconditions=("claims_anchored",),
            effects=(
                "taxon_resolution_recorded",
                f"taxon_authority_{FIXTURE_TAXON_AUTHORITY}",
            ),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            taxon_resolution=TAXON_PROVIDER,
            emits=("taxonomy.name.conflict_detected", "taxonomy.name.resolved"),
            health=_health("TAXON_UNRESOLVED", "TAXON_AMBIGUOUS"),
        ),
        CapabilityDescriptor(
            capability_id="fil.evidence.literature-claim-validator",
            version="1.0.0",
            operator_class=OperatorClass.VALIDATOR,
            registry_capability="schema-validation",
            summary="Structure each resolved claim and assign an evidence state with reasons and uncertainty.",
            implementation="app.candidate_knowledge.extractor.extract_candidates",
            inputs=(
                PortSpec("linked_claims", "oc:TaxonLinkedClaimBatch", ("UNKNOWN",)),
            ),
            outputs=(
                PortSpec(
                    "validated_claims",
                    "oc:ValidatedClaimBatch",
                    ("PROVISIONAL", "REJECTED", "UNKNOWN"),
                ),
            ),
            preconditions=("claims_anchored", "taxon_resolution_recorded"),
            effects=("evidence_state_assigned", "uncertainty_recorded"),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            emits=("evidence.assertion.withheld",),
            health=_health("TAXON_UNRESOLVED", "TAXON_AMBIGUOUS", "NO_STRUCTURED_FACT"),
        ),
        CapabilityDescriptor(
            capability_id="fil.traitbank.literature-record-buffer",
            version="1.0.0",
            operator_class=OperatorClass.BUFFER,
            registry_capability="provenance-assembly",
            summary="Hold provisional facts as taxon-resolved TraitBank records and aggregation inputs, review-required.",
            implementation="harvesters.execution._validate_traitbank_record",
            inputs=(
                PortSpec(
                    "validated_claims", "oc:ValidatedClaimBatch", ("PROVISIONAL",)
                ),
            ),
            outputs=(
                PortSpec(
                    "records",
                    "oc:TraitBankRecordBatch",
                    ("PROVISIONAL",),
                    "harvesters.traitbank.TraitBankHarvester._normalize",
                ),
            ),
            preconditions=("evidence_state_assigned", *_TAXON_CONDITIONS),
            effects=("candidate_only", "human_review_required"),
            permissions=("candidate_generation",),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            taxon_resolution=TAXON_ADMISSION,
            emits=("artifact.created",),
            health=_health("TRAITBANK_RECORD_INVALID"),
        ),
        CapabilityDescriptor(
            capability_id="fil.calyx.verification-handoff",
            version="1.0.0",
            operator_class=OperatorClass.TRANSPORTER,
            registry_capability="contradiction-detection",
            summary="Group records, mark contradictions and variation, and admit review-required candidates to Calyx.",
            implementation="app.parallel_platform.reasoning_contract_bridge.verification_packet_to_handoff_request",
            brain_capability_id="literature_candidate_handoff",
            inputs=(
                PortSpec("records", "oc:TraitBankCandidateBatch", ("PROVISIONAL",)),
            ),
            outputs=(
                PortSpec(
                    "handoffs",
                    "oc:CalyxCandidateHandoffBatch",
                    ("CONTRADICTORY", "PROVISIONAL"),
                    "app.parallel_platform.brain_candidate_handoff.BrainCandidateHandoffRequest",
                ),
            ),
            preconditions=(
                "candidate_only",
                "human_review_required",
                *_TAXON_CONDITIONS,
            ),
            effects=(
                "calyx_review_required",
                "contradictions_marked",
                "evidence_gaps_marked",
            ),
            permissions=("candidate_generation",),
            autonomy_class=AutonomyClass.SAFE_AUTONOMOUS,
            taxon_resolution=TAXON_ADMISSION,
            emits=("artifact.created", "evidence.assertion.conflicted"),
            health=_health("PACKET_GOVERNANCE_INVALID", "RESOLVED_EVIDENCE_REQUIRED"),
        ),
    )


def chain_registry() -> FunctionalRegistry:
    return FunctionalRegistry(
        chain_descriptors(), brain_registry=canonical_brain_registry()
    )


def load_manifest(directory: Path = FIXTURE_DIR) -> dict[str, Any]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["_directory"] = str(directory)
    return manifest


def source_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    directory = Path(manifest["_directory"])
    return {
        "fixture_id": manifest["fixture_id"],
        "documents": [
            {**paper, "path": str(directory / paper["file"])}
            for paper in manifest["papers"]
        ],
    }


def _run_pipeline(path: Path) -> dict[str, Any]:
    document = ingest_text(path)
    # output_dir is required by the context but nothing here writes to it:
    # write_output_bundle is deliberately not called.
    context = PipelineContext(source_path=path, output_dir=path.parent)
    paper = build_empty_paper(
        document, pipeline_version=context.config.pipeline_version
    )
    runner = PipelineRunner(
        [MetadataExtractor(), SectionExtractor(), EntityExtractor(), ClaimExtractor()]
    )
    result = asyncio.run(runner.run(context, paper))
    result = refresh_publication_decisions(
        build_review_queue(normalize_and_reconcile(result))
    )
    return result.model_dump(mode="json")


def _doi(paper: Mapping[str, Any]) -> str | None:
    for identifier in paper["metadata"].get("identifiers") or []:
        if identifier.get("scheme") == "doi":
            return f"doi:{identifier['value']}"
    return None


def _links(items: list[dict[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    return tuple(item["taxon_link"] for item in items if "taxon_link" in item)


def _provenance(items: list[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted({item["provenance"] for item in items if item.get("provenance")})
    )


def _carry(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fixture_id": payload["fixture_id"],
        "papers": list(payload.get("papers", [])),
        "gaps": list(payload.get("gaps", [])),
    }


def _components() -> tuple[MemoryCandidateRepository, CandidateExtractionService]:
    repository = MemoryCandidateRepository()
    return repository, CandidateExtractionService(repository)


def build_handlers(
    manifest: Mapping[str, Any],
    *,
    candidate_components: Callable[
        [], tuple[MemoryCandidateRepository, CandidateExtractionService]
    ]
    | None = None,
    allow_import_time_database_contact: bool = False,
) -> dict[str, Handler]:
    taxonomy = manifest["taxonomy"]
    if taxonomy.get("authority") != FIXTURE_TAXON_AUTHORITY:
        # Refuse rather than label any backbone with an authority it may not have.
        raise ValueError(f"TAXONOMY_AUTHORITY_MISMATCH:{taxonomy.get('authority')}")
    backbone = build_canonical_registry(taxonomy["load_rows"], taxonomy["synonym_rows"])
    release = taxonomy["release_label"]
    backbone_names = sorted(backbone.name_index, key=lambda name: (-len(name), name))
    components_factory = candidate_components or _components

    def transduce(payload: Mapping[str, Any]) -> HandlerResult:
        claims: list[dict[str, Any]] = []
        papers: list[dict[str, Any]] = []
        for document in payload["documents"]:
            paper = _run_pipeline(Path(document["path"]))
            status = paper["analysis_manifest"]["status"]
            if status != "completed":
                raise RuntimeError(f"PIPELINE_INCOMPLETE:{document['file']}:{status}")
            content_hash = paper["source"]["content_hash"]
            # Same fallback form as app/traitbank/adapters.py (#1811): doi:<doi>, else paper:<id>.
            source_id = _doi(paper) or f"paper:{paper['paper_id']}"
            papers.append(
                {
                    "paper_id": paper["paper_id"],
                    "source_id": source_id,
                    "title": paper["metadata"].get("title"),
                    "content_hash": content_hash,
                    "rights_status": paper["source"].get("rights_status"),
                    "declared_names": sorted(
                        k
                        for k in paper["metadata"].get("keywords") or []
                        if _BINOMIAL.match(k)
                    ),
                    "pipeline_version": paper["analysis_manifest"]["pipeline_version"],
                }
            )
            spans = {item["evidence_id"]: item["span"] for item in paper["evidence"]}
            for claim in paper["claims"]:
                span = spans[claim["evidence_ids"][0]]
                claims.append(
                    {
                        "claim_id": f"{source_id}#{claim['claim_id']}",
                        "source_id": source_id,
                        "source_object_id": document["source_object_id"],
                        "revision_id": document["revision_id"],
                        "extraction_run_id": document["extraction_run_id"],
                        "statement": claim["statement"],
                        "claim_type": claim["claim_type"],
                        "section_id": span["section_id"],
                        "char_start": span["char_start"],
                        "char_end": span["char_end"],
                        "content_hash": content_hash,
                        "declared_names": papers[-1]["declared_names"],
                        "provenance": f"{source_id}|sha256:{content_hash}#chars={span['char_start']}-{span['char_end']}",
                        "extraction": {
                            "method": claim["provenance"]["method"],
                            "confidence": claim["provenance"]["confidence"],
                        },
                    }
                )
        return HandlerResult(
            output={
                "fixture_id": payload["fixture_id"],
                "papers": papers,
                "claims": claims,
                "gaps": [],
            },
            established=("claims_anchored",),
            evidence_states=("UNKNOWN",),
            events=("evidence.assertion.created",) if claims else (),
            provenance=_provenance(claims),
            notes={"papers": len(papers), "claims": len(claims)},
        )

    def resolve(payload: Mapping[str, Any]) -> HandlerResult:
        linked = []
        for claim in payload["claims"]:
            statement = claim["statement"]
            names = sorted(
                {
                    n
                    for n in claim["declared_names"]
                    if re.search(rf"\b{re.escape(n)}\b", statement)
                }
                | {
                    n
                    for n in backbone_names
                    if re.search(rf"\b{re.escape(n)}\b", statement)
                }
            )
            taxa = {}
            unknown = []
            for name in names:
                taxon = backbone.resolve(name)
                if taxon is None:
                    unknown.append(name)
                elif (
                    taxon.canonical_id not in taxa
                    or canonical_name_of(name) == taxon.canonical_name
                ):
                    # The accepted spelling wins over a synonym of the same
                    # taxon, independent of name order.
                    taxa[taxon.canonical_id] = (taxon, name)
            link: dict[str, Any] = {
                "submitted_names": names,
                "authority": FIXTURE_TAXON_AUTHORITY,
                "release": release,
                "method": "exact_canonical_name",
                "automatic_fuzzy_matching": False,
                "canonical_id": None,
                "canonical_name": None,
            }
            if len(taxa) == 1 and not unknown:
                taxon, name = next(iter(taxa.values()))
                synonym = canonical_name_of(name) != taxon.canonical_name
                link.update(
                    status="synonym" if synonym else "accepted",
                    canonical_id=taxon.canonical_id,
                    canonical_name=taxon.canonical_name,
                    reason=None,
                )
            elif len(taxa) > 1:
                # Several resolved taxa: each name is exact, but the claim's
                # subject cannot be attributed to one taxon. Not a name conflict.
                link.update(status="ambiguous", reason="MULTIPLE_SUBJECT_TAXA")
            elif taxa and unknown:
                # One backbone taxon plus a declared name outside the backbone
                # (e.g. a pollinator): the subject is undetermined, not guessed.
                link.update(status="ambiguous", reason="SUBJECT_TAXON_UNDETERMINED")
            elif len(unknown) > 1:
                link.update(status="unresolved", reason="TAXON_UNRESOLVED")
            else:
                link.update(
                    status="unresolved",
                    reason="TAXON_UNRESOLVED" if names else "NO_TAXON_NAME_IN_CLAIM",
                )
            linked.append({**claim, "taxon_link": link})
        # Exact matching against one backbone cannot produce a name conflict;
        # multi-subject attribution is recorded per claim, not as an event.
        conflicts = False
        resolved = any(
            item["taxon_link"]["status"] in {"accepted", "synonym"} for item in linked
        )
        return HandlerResult(
            output={**_carry(payload), "claims": linked},
            established=(
                "taxon_resolution_recorded",
                f"taxon_authority_{FIXTURE_TAXON_AUTHORITY}",
            ),
            evidence_states=("UNKNOWN",),
            events=tuple(
                event
                for event, present in (
                    ("taxonomy.name.resolved", resolved),
                    ("taxonomy.name.conflict_detected", conflicts),
                )
                if present
            ),
            provenance=_provenance(linked),
            taxon_links=_links(linked),
            notes={
                s: sum(1 for i in linked if i["taxon_link"]["status"] == s)
                for s in ("accepted", "synonym", "ambiguous", "unresolved")
            },
        )

    def validate(payload: Mapping[str, Any]) -> HandlerResult:
        items: list[dict[str, Any]] = []
        for claim in payload["claims"]:
            link = claim["taxon_link"]
            if link["status"] not in {"accepted", "synonym"}:
                items.append(
                    {**claim, "evidence_state": "UNKNOWN", "reasons": [link["reason"]]}
                )
                continue
            evidence = EvidenceInput(
                source_object_type=SOURCE_OBJECT_TYPE,
                source_object_id=claim["source_object_id"],
                revision_id=claim["revision_id"],
                extraction_run_id=claim["extraction_run_id"],
                text=claim["statement"],
                source_anchors=(
                    SourceAnchor(
                        claim["char_start"] + 1,
                        char_start=claim["char_start"],
                        char_end=claim["char_end"],
                    ),
                ),
                metadata={"subject": link["canonical_name"]},
            )
            try:
                facts = extract_candidates(evidence)
            except ValueError as exc:
                items.append(
                    {**claim, "evidence_state": "REJECTED", "reasons": [str(exc)]}
                )
                continue
            if not facts:
                items.append(
                    {
                        **claim,
                        "evidence_state": "UNKNOWN",
                        "reasons": ["NO_STRUCTURED_FACT"],
                    }
                )
                continue
            uncertainty = []
            if _HEDGE.search(claim["statement"]):
                uncertainty.append("HEDGED_SOURCE_LANGUAGE")
            if claim["claim_type"] != "result":
                uncertainty.append("INTERPRETATION_NOT_OBSERVATION")
            for index, fact in enumerate(facts):
                items.append(
                    {
                        **claim,
                        "fact_id": f"{claim['claim_id']}/{index}",
                        "kind": fact.kind.value,
                        "predicate": fact.predicate,
                        "object_value": fact.object_value,
                        "numeric_value": fact.numeric_value,
                        "unit": fact.unit,
                        "confidence": fact.confidence,
                        "assertion_kind": "observation"
                        if claim["claim_type"] == "result"
                        else "interpretation",
                        "uncertainty": uncertainty,
                        "evidence_state": "PROVISIONAL",
                        "reasons": ["MACHINE_EXTRACTED_REQUIRES_HUMAN_REVIEW"],
                    }
                )
        withheld = [item for item in items if item["evidence_state"] != "PROVISIONAL"]
        return HandlerResult(
            output={**_carry(payload), "claims": items},
            established=("evidence_state_assigned", "uncertainty_recorded"),
            evidence_states=tuple(sorted({item["evidence_state"] for item in items})),
            events=("evidence.assertion.withheld",) if withheld else (),
            provenance=_provenance(items),
            notes={
                "provisional": len(items) - len(withheld),
                "withheld": len(withheld),
            },
        )

    def buffer(payload: Mapping[str, Any]) -> HandlerResult:
        records: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        gaps = list(payload.get("gaps", []))
        titles = {
            paper["source_id"]: paper["title"] for paper in payload.get("papers", [])
        }
        for item in payload["claims"]:
            if item["evidence_state"] != "PROVISIONAL":
                gaps.append(
                    {
                        "kind": "CLAIM_WITHHELD",
                        "claim_id": item["claim_id"],
                        "evidence_state": item["evidence_state"],
                        "reasons": item["reasons"],
                        "statement": item["statement"],
                        "provenance": item["provenance"],
                    }
                )
                continue
            link = item["taxon_link"]
            value = (
                item["object_value"]
                if item["object_value"] is not None
                else item["numeric_value"]
            )
            record = {
                "source_key": "FIL_001B_LITERATURE",
                "source_path": item["provenance"],
                "scientific_name": link["canonical_name"],
                "trait_raw": item["predicate"],
                "value_raw": value,
                "units_raw": item["unit"] or "",
                "reference_raw": item["source_id"],
                "raw": {
                    "record_id": item["fact_id"],
                    "resource_id": "fil-001b-fixture",
                    "citation": f"{titles.get(item['source_id'])} ({item['source_id']})",
                    "license": "fixture: invented text, no third-party content",
                    "fixture_status": "synthetic_contract_fixture",
                    "canonical_taxon_id": link["canonical_id"],
                    "taxon_link": link,
                    "assertion_level": "unstated",
                    "assertion_kind": item["assertion_kind"],
                    "uncertainty": item["uncertainty"],
                    "evidence_state": "PROVISIONAL",
                    "verbatim": item["statement"],
                    "kind": item["kind"],
                    "confidence": item["confidence"],
                    "source_object_id": item["source_object_id"],
                    "revision_id": item["revision_id"],
                    "extraction_run_id": item["extraction_run_id"],
                },
                "provenance": item["provenance"],
                "taxon_link": link,
            }
            valid, error = _validate_traitbank_record(record)
            if not valid:
                raise ValueError(f"TRAITBANK_RECORD_INVALID:{error}")
            records.append(record)
            candidate = CandidateInput(
                candidate_id=len(candidates) + 1,
                candidate_version=1,
                candidate_type=item["kind"],
                normalized_subject=link["canonical_name"],
                predicate=item["predicate"],
                object_value=item["object_value"],
                numeric_value=item["numeric_value"],
                unit=item["unit"],
                source_revision_id=item["revision_id"],
                source_document_id=item["source_id"],
                source_anchor_ids=(item["char_start"] + 1,),
                evidence_type="LITERATURE",
                source_class="FIL_001B_FIXTURE",
                directness="DIRECT"
                if item["assertion_kind"] == "observation"
                else "INDIRECT",
                document_hash=item["content_hash"],
                taxon_links=(
                    {
                        "candidate_taxon_id": link["canonical_id"],
                        "source_name": ";".join(link["submitted_names"]),
                        "match": link["status"],
                    },
                ),
                confidence=item["confidence"],
                metadata={
                    "fact_id": item["fact_id"],
                    "provenance": item["provenance"],
                    "uncertainty": item["uncertainty"],
                },
            )
            candidates.append(json.loads(json.dumps(asdict(candidate))))
        return HandlerResult(
            output={
                **_carry(payload),
                "gaps": gaps,
                "traitbank_records": records,
                "aggregation_candidates": candidates,
                "review_required": True,
                "published": False,
            },
            established=("candidate_only", "human_review_required"),
            evidence_states=("PROVISIONAL",) if records else (),
            events=("artifact.created",) if records else (),
            provenance=tuple(
                sorted(
                    {r["provenance"] for r in records} | {g["provenance"] for g in gaps}
                )
            ),
            taxon_links=_links(records),
            notes={"records": len(records), "gaps": len(gaps)},
        )

    def handoff(payload: Mapping[str, Any]) -> HandlerResult:
        to_request, admit_candidate, kind_domain = _calyx_bridge(
            allow_import_time_database_contact=allow_import_time_database_contact
        )
        repository, service = components_factory()
        atomic = getattr(repository, "atomic", None)
        groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for record in payload["traitbank_records"]:
            groups.setdefault(
                (record["raw"]["canonical_taxon_id"], record["trait_raw"]), []
            ).append(record)
        gap_lines = [
            f"{g['kind']}:{g.get('claim_id') or g.get('source_document_id')}:{','.join(g.get('reasons', []))}"
            for g in payload.get("gaps", [])
        ]
        handoffs: list[dict[str, Any]] = []
        packets: list[dict[str, Any]] = []
        states: set[str] = set()
        variation: list[dict[str, Any]] = []
        for (taxon_id, predicate), members in sorted(groups.items()):
            # Values are compared after normalization (case, separators, length
            # units); only mutually exclusive categorical values contradict.
            by_value: dict[str, list[dict[str, Any]]] = {}
            keys: dict[str, value_semantics.ValueKey] = {}
            for record in members:
                key = _value_key(record)
                keys[value_semantics.display(key)] = key
                by_value.setdefault(value_semantics.display(key), []).append(record)
            comparison = value_semantics.classify(predicate, keys.values())
            contradictory = comparison == value_semantics.CONTRADICTION
            differs = comparison not in {
                value_semantics.AGREEMENT,
                value_semantics.CONTRADICTION,
            }
            if differs:
                variation.append(
                    {
                        "taxon_id": taxon_id,
                        "predicate": predicate,
                        "values": sorted(by_value),
                        "assessment": comparison,
                        "sources": sorted({r["reference_raw"] for r in members}),
                    }
                )
            ids = _candidate_ids(taxon_id, predicate, keys)
            for value, records in sorted(by_value.items()):
                state = "CONTRADICTORY" if contradictory else "PROVISIONAL"
                states.add(state)
                packet = _packet(
                    candidate_id=ids[value],
                    records=records,
                    value=value,
                    contradictions=sorted(
                        other for v, other in ids.items() if v != value
                    )
                    if contradictory
                    else [],
                    variation=comparison == value_semantics.VARIATION_AT_UNSTATED_LEVEL,
                    gaps=gap_lines,
                )
                first = records[0]["raw"]
                request = to_request(
                    packet,
                    domain=kind_domain[first["kind"]],
                    source_object_type=SOURCE_OBJECT_TYPE,
                    source_object_id=first["source_object_id"],
                    revision_id=first["revision_id"],
                    extraction_run_id=first["extraction_run_id"],
                )

                def admit(request=request) -> dict[str, Any]:
                    return admit_candidate(request, (repository, service))

                result = atomic(admit) if atomic is not None else admit()
                packets.append(packet)
                handoffs.append(
                    {
                        "candidate_id": ids[value],
                        "evidence_state": state,
                        "subject": records[0]["scientific_name"],
                        "taxon_id": taxon_id,
                        "predicate": predicate,
                        "value": value,
                        "sources": sorted({r["reference_raw"] for r in records}),
                        "contradicts": packet["contradictions"],
                        "uncertainty": sorted(
                            {u for r in records for u in r["raw"]["uncertainty"]}
                        ),
                        "packet_digest": canonical_checksum(packet),
                        "calyx_candidate_ids": result["candidate_ids"],
                        "calyx_state": result["state"],
                        "review_required": result["review_required"],
                        "published": result["published"],
                        "graph_mutation": result["graph_mutation"],
                        "taxon_link": records[0]["taxon_link"],
                    }
                )
        candidate_ids = [h["candidate_id"] for h in handoffs]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("CANDIDATE_ID_COLLISION")
        return HandlerResult(
            output={
                "fixture_id": payload["fixture_id"],
                "handoffs": handoffs,
                "packets": packets,
                "variation": variation,
                "evidence_gaps": list(payload.get("gaps", [])),
                "human_review_required": True,
                "publication_authority": False,
            },
            established=(
                "calyx_review_required",
                "contradictions_marked",
                "evidence_gaps_marked",
            ),
            evidence_states=tuple(sorted(states)),
            events=tuple(
                sorted(
                    ({"artifact.created"} if handoffs else set())
                    | (
                        {"evidence.assertion.conflicted"}
                        if "CONTRADICTORY" in states
                        else set()
                    )
                )
            ),
            provenance=tuple(
                sorted(
                    {
                        p
                        for packet in packets
                        for e in packet["resolved_evidence"]
                        for p in e["provenance"][:1]
                    }
                    | {g["provenance"] for g in payload.get("gaps", [])}
                )
            ),
            taxon_links=tuple(h["taxon_link"] for h in handoffs),
            notes={
                "handoffs": len(handoffs),
                "contradictory": sum(
                    1 for h in handoffs if h["evidence_state"] == "CONTRADICTORY"
                ),
            },
        )

    return {
        "fil.literature.paper-transducer": transduce,
        "fil.taxonomy.literature-name-adaptor": resolve,
        "fil.evidence.literature-claim-validator": validate,
        "fil.traitbank.literature-record-buffer": buffer,
        "fil.calyx.verification-handoff": handoff,
    }


def _value_key(record: Mapping[str, Any]) -> value_semantics.ValueKey:
    value = record["value_raw"]
    numeric = isinstance(value, int | float) and not isinstance(value, bool)
    return value_semantics.value_key(
        object_value=None if numeric else str(value),
        numeric_value=value if numeric else None,
        unit=record["units_raw"] or None,
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _candidate_ids(
    taxon_id: int, predicate: str, keys: Mapping[str, value_semantics.ValueKey]
) -> dict[str, str]:
    """Readable, collision-free candidate ids for one (taxon, predicate) group.

    Distinct normalized values whose slugs coincide get a deterministic suffix
    derived from the comparison key, so no two candidates share an id.
    """
    slugs: dict[str, list[str]] = {}
    for display in keys:
        slugs.setdefault(_slug(display), []).append(display)
    ids: dict[str, str] = {}
    for slug, displays in slugs.items():
        for display in displays:
            suffix = (
                f"-{canonical_checksum(list(keys[display]))[:8]}"
                if len(displays) > 1
                else ""
            )
            ids[display] = f"fil001b:{taxon_id}:{predicate}:{slug}{suffix}"
    return ids


def _packet(
    *,
    candidate_id: str,
    records: list[dict[str, Any]],
    value: str,
    contradictions: list[str],
    variation: bool,
    gaps: list[str],
) -> dict[str, Any]:
    """An ``oc-verification-handoff-v1`` packet, the shape the existing bridge admits."""
    first = records[0]
    uncertainty = sorted({u for r in records for u in r["raw"]["uncertainty"]})
    pathways = ["taxonomist_review"]
    if contradictions:
        pathways.append("resolve_conflicting_sources")
    if uncertainty:
        pathways.append("expert_review_of_uncertain_claim")
    if variation:
        pathways.append("state_assertion_level_for_measurements")
    independent_sources = {r["reference_raw"] for r in records}
    candidate = {
        "candidate_id": candidate_id,
        "subject_id": f"taxon:{FIXTURE_TAXON_AUTHORITY}:{first['raw']['canonical_taxon_id']}",
        "predicate": first["trait_raw"],
        "object_id": f"value:{value}",
        "evidence_ids": sorted(r["raw"]["record_id"] for r in records),
        "confidence": min(r["raw"]["confidence"] for r in records),
        "review_state": "review_required" if contradictions else "candidate",
        "publication_authority": False,
    }
    return {
        "contract_version": "oc-verification-handoff-v1",
        "producer": "fil-001b-offline-fixture-chain",
        "verification_state": "ready_for_review",
        "reasoning": {
            "contract_version": "oc-parallel-v1",
            "candidate_knowledge": candidate,
            "contradictions": contradictions,
            "validation_pathways": pathways,
            "human_review_required": True,
            "automatic_scientific_publication_allowed": False,
            "private_chain_of_thought_stored": False,
        },
        "resolved_evidence": [
            {
                "evidence_id": r["raw"]["record_id"],
                "source_id": r["reference_raw"],
                "statement": r["raw"]["verbatim"],
                "provenance": [
                    r["provenance"],
                    f"taxon_link:{r['taxon_link']['status']}",
                    *(f"uncertainty:{u}" for u in r["raw"]["uncertainty"]),
                ],
                "confidence": r["raw"]["confidence"],
            }
            for r in sorted(records, key=lambda r: r["raw"]["record_id"])
        ],
        "missing_evidence": []
        if len(independent_sources) > 1
        else ["independent_corroboration"],
        "contradictions": contradictions,
        "knowledge_gaps": (["assertion_level_unstated"] if variation else []) + gaps,
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
        "canonical_knowledge_mutation_allowed": False,
    }


def plan_chain(registry: FunctionalRegistry | None = None) -> WorkflowPlan:
    return plan_workflow(
        registry or chain_registry(),
        source=SOURCE,
        goal_type="oc:CalyxCandidateHandoffBatch",
    )


def run_chain(
    manifest: Mapping[str, Any] | None = None,
    *,
    candidate_components: Callable[
        [], tuple[MemoryCandidateRepository, CandidateExtractionService]
    ]
    | None = None,
    allow_import_time_database_contact: bool = False,
) -> DryRunReport:
    """Plan, govern and run the chain over the fixture. Offline and deterministic.

    See :func:`import_time_database_contact_risk` for the one pre-existing
    import that can connect, and why it is refused unless explicitly allowed.
    """
    manifest = manifest if manifest is not None else load_manifest()
    plan = plan_chain()
    decision = evaluate_plan(plan)
    handlers = build_handlers(
        manifest,
        candidate_components=candidate_components,
        allow_import_time_database_contact=allow_import_time_database_contact,
    )
    return execute_dry_run(plan, decision, handlers, source_payload(manifest))
