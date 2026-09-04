"""Bounded end-to-end GloBI interaction pipeline proof.

OC-COMPLETE-009 — Scientific Adapter Laboratory.

Demonstrates that an orchid interaction record can pass every stage of
the OC interaction pipeline:

  SOURCE → NORMALIZATION → TAXON_RECONCILIATION → EVIDENCE_PROVENANCE →
  REVIEW_CONTRACT → KG_CANDIDATE_CONTRACT

... without scientific auto-promotion at any stage.

This module is proof/test scaffolding, not a production data platform.
It calls the same functions used by the live interaction pipeline so the
proof is not hypothetical — it exercises real code on bounded fixtures.

Hard invariants (every pipeline result MUST satisfy all of these):
  - automatic_publication is False
  - knowledge_graph_mutation is False
  - verification_state is UNVERIFIED (or absent, which is also not promoted)
  - review_required is True
  - scientific_review_required is True (on the metadata level)
"""

from __future__ import annotations

from typing import Any

from app.calyx_conversation.interaction_discovery_ingest import (
    document_from_globi_interaction,
)

PROOF_SCHEMA_VERSION = "oc-globi-pipeline-proof/v1"

# Governs what fields the TAXON_RECONCILIATION stage emits.
# In production this stage is fed by GloBI's embedded GBIF taxon IDs;
# here we make the parsing explicit so the proof is readable.
_GBIF_PREFIX = "GBIF:"
_ITIS_PREFIX = "ITIS:"


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


def _stage_source(raw_record: dict[str, Any]) -> dict[str, Any]:
    """STAGE 1: SOURCE — accept a raw GloBI TSV row as-is.

    The record may use GloBI's stable export camelCase field names
    (sourceTaxonName, interactionTypeName, ...) or the live API's
    snake_case names. Both are valid GloBI record shapes.
    """
    return {
        "stage": "SOURCE",
        "description": "Raw record from GloBI stable dataset export or live API",
        "raw_field_count": len(raw_record),
        "raw_record": dict(raw_record),
        "source": "Global Biotic Interactions",
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def _stage_normalization(raw_record: dict[str, Any]) -> dict[str, Any]:
    """STAGE 2: NORMALIZATION — resolve field aliases, drop blanks.

    GloBI publishes two record shapes:
      - versioned stable export: camelCase (sourceTaxonName, interactionTypeName, ...)
      - live API: snake_case (source_taxon_name, interaction_type, ...)

    This stage produces a single normalized view regardless of input shape.
    Empty-string values are dropped (matching read_globi_dataset_rows behavior).
    """

    def _pick(*keys: str) -> str | None:
        for key in keys:
            value = raw_record.get(key)
            if value not in (None, ""):
                return str(value).strip() or None
        return None

    source_name = _pick("sourceTaxonName", "source_taxon_name", "source_name")
    source_id = _pick("sourceTaxonId", "source_taxon_external_id", "source_taxon_id")
    target_name = _pick("targetTaxonName", "target_taxon_name", "target_name")
    target_id = _pick("targetTaxonId", "target_taxon_external_id", "target_taxon_id")
    interaction_type = _pick(
        "interactionTypeName", "interaction_type", "interactionType", "interaction_type_name"
    )
    study_id = _pick("studyExternalId", "study_external_id", "referenceDoi", "referenceUrl")
    study_citation = _pick("referenceCitation", "studyCitation", "study_citation")
    source_citation = _pick("sourceCitation", "studySourceCitation", "study_source_citation")

    normalizable = source_name is not None and target_name is not None and interaction_type is not None
    return {
        "stage": "NORMALIZATION",
        "description": "Field aliases resolved; both camelCase and snake_case input shapes accepted",
        "normalizable": normalizable,
        "reason": None if normalizable else "Missing one or more required fields: source_name, target_name, interaction_type",
        "source_taxon_name": source_name,
        "source_taxon_id": source_id,
        "target_taxon_name": target_name,
        "target_taxon_id": target_id,
        "interaction_type": interaction_type,
        "study_external_id": study_id,
        "study_citation": study_citation,
        "source_citation": source_citation,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def _stage_taxon_reconciliation(normalization: dict[str, Any]) -> dict[str, Any]:
    """STAGE 3: TAXON_RECONCILIATION — parse embedded backbone IDs.

    OC's taxon reconciliation for GloBI-sourced records uses the backbone
    IDs that GloBI already embeds in its records (GBIF:NNN, ITIS:NNN).
    These were matched by GloBI's own nomer pipeline against the GBIF
    backbone and ITIS at indexing time; OC trusts the embedded IDs as the
    taxon-reconciliation output for candidate discovery purposes.

    In production a further reconciliation step (e.g. calling GBIF species
    API to confirm current accepted name) is performed before scientific review.
    That step is NOT performed here because this is bounded to static fixtures.

    Reconciliation outputs:
      MATCHED    — a backbone prefix (GBIF: or ITIS:) is present
      UNMATCHED  — no recognized backbone prefix; name-only match required
      UNKNOWN    — taxon ID absent; cannot determine reconciliation status
    """

    def _reconcile(taxon_name: str | None, taxon_id: str | None) -> dict[str, Any]:
        if taxon_id is None:
            if taxon_name is None:
                return {"reconciliation_status": "UNKNOWN", "backbone": None, "id_value": None}
            return {"reconciliation_status": "UNMATCHED", "backbone": "none", "id_value": None, "name_only": taxon_name}
        for prefix, backbone in ((_GBIF_PREFIX, "GBIF"), (_ITIS_PREFIX, "ITIS")):
            if taxon_id.startswith(prefix):
                return {
                    "reconciliation_status": "MATCHED",
                    "backbone": backbone,
                    "id_value": taxon_id[len(prefix):],
                    "full_id": taxon_id,
                }
        return {"reconciliation_status": "UNMATCHED", "backbone": "UNKNOWN_PREFIX", "id_value": taxon_id}

    source_rec = _reconcile(normalization.get("source_taxon_name"), normalization.get("source_taxon_id"))
    target_rec = _reconcile(normalization.get("target_taxon_name"), normalization.get("target_taxon_id"))

    both_reconciled = (
        source_rec["reconciliation_status"] == "MATCHED"
        and target_rec["reconciliation_status"] == "MATCHED"
    )
    either_reconciled = (
        source_rec["reconciliation_status"] == "MATCHED"
        or target_rec["reconciliation_status"] == "MATCHED"
    )

    return {
        "stage": "TAXON_RECONCILIATION",
        "description": (
            "Taxon IDs parsed against known backbone prefixes (GBIF, ITIS). "
            "MATCHED = backbone ID present. UNMATCHED = name-only. UNKNOWN = absent."
        ),
        "source_taxon": {
            "name": normalization.get("source_taxon_name"),
            **source_rec,
        },
        "target_taxon": {
            "name": normalization.get("target_taxon_name"),
            **target_rec,
        },
        "both_reconciled": both_reconciled,
        "either_reconciled": either_reconciled,
        "reconciliation_backbone_source": "GloBI nomer (embedded in record at export time)",
        "further_reconciliation_required_before_scientific_review": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def _stage_evidence_provenance(normalization: dict[str, Any], *, dataset_version: str) -> dict[str, Any]:
    """STAGE 4: EVIDENCE_PROVENANCE — surface study citation and dataset lineage.

    Provenance is surfaced as a contract: every candidate carries its study
    citation, source dataset, and dataset_version so a reviewer can verify
    the original source without relying on OC's derived representation.
    """
    has_study_citation = bool(normalization.get("study_citation"))
    has_study_id = bool(normalization.get("study_external_id"))
    has_source_citation = bool(normalization.get("source_citation"))

    return {
        "stage": "EVIDENCE_PROVENANCE",
        "description": "Study citation, dataset source, and versioned snapshot traceability",
        "study_citation": normalization.get("study_citation"),
        "study_external_id": normalization.get("study_external_id"),
        "source_citation": normalization.get("source_citation"),
        "dataset_version": dataset_version,
        "provider": "Global Biotic Interactions",
        "provider_url": "https://www.globalbioticinteractions.org",
        "provenance_contract": "globi-canonical-dataset-review-bound-v1",
        "has_study_citation": has_study_citation,
        "has_study_id": has_study_id,
        "has_source_citation": has_source_citation,
        "traceable_to_reproducible_source": has_study_citation or has_study_id,
        "evidence_type": "ECOLOGICAL_INTERACTION_CANDIDATE",
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def _stage_review_contract(document: Any) -> dict[str, Any]:
    """STAGE 5: REVIEW_CONTRACT — verify all review/publication guards are set.

    The review contract enforces that the document produced by
    document_from_globi_interaction carries all required non-promotion flags.
    Any deviation is a defect; the proof records it explicitly.
    """
    if document is None:
        return {
            "stage": "REVIEW_CONTRACT",
            "document_produced": False,
            "reason": "document_from_globi_interaction returned None (missing required fields)",
            "guards_satisfied": False,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        }

    meta = getattr(document, "metadata", {}) or {}
    guards = {
        "verification_state_is_unverified": document.verification_state == "UNVERIFIED",
        "automatic_publication_false": meta.get("automatic_publication") is False,
        "knowledge_graph_mutation_false": meta.get("knowledge_graph_mutation") is False,
        "scientific_review_required_true": meta.get("scientific_review_required") is True,
        "evidence_type_is_candidate": meta.get("evidence_type") == "ECOLOGICAL_INTERACTION_CANDIDATE",
        "display_policy_metadata_only": document.display_policy == "METADATA_ONLY",
    }
    all_satisfied = all(guards.values())

    return {
        "stage": "REVIEW_CONTRACT",
        "document_produced": True,
        "document_class": document.document_class,
        "source_object_type": document.source_object_type,
        "verification_state": document.verification_state,
        "display_policy": document.display_policy,
        "guards": guards,
        "guards_satisfied": all_satisfied,
        "defects": [k for k, v in guards.items() if not v],
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def _stage_kg_candidate_contract(document: Any) -> dict[str, Any]:
    """STAGE 6: KG_CANDIDATE_CONTRACT — confirm the document satisfies the KG candidate contract.

    A KG candidate is a document that:
    - Is in UNVERIFIED state (not yet reviewed or accepted)
    - Is review_state CLEAR (not blocked, not flagged)
    - Has internal_indexing_permission True (cleared for indexing)
    - Is NOT automatically promoted — promotion requires a separate review decision

    This stage does NOT promote the record; it merely confirms the candidate
    satisfies the contract that would let a reviewer see and act on it.
    """
    if document is None:
        return {
            "stage": "KG_CANDIDATE_CONTRACT",
            "candidate_eligible_for_review": False,
            "reason": "No document produced",
            "promoted_to_kg": False,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        }

    meta = getattr(document, "metadata", {}) or {}
    candidate_checks = {
        "verification_state_unverified": document.verification_state == "UNVERIFIED",
        "review_state_clear": document.review_state == "CLEAR",
        "internal_indexing_permission": document.internal_indexing_permission is True,
        "no_auto_publication": meta.get("automatic_publication") is False,
        "no_kg_mutation": meta.get("knowledge_graph_mutation") is False,
    }
    eligible = all(candidate_checks.values())

    return {
        "stage": "KG_CANDIDATE_CONTRACT",
        "description": (
            "Candidate is eligible to be shown to a reviewer. "
            "Review and explicit owner decision are required to promote to a KG edge."
        ),
        "candidate_eligible_for_review": eligible,
        "candidate_checks": candidate_checks,
        "defects": [k for k, v in candidate_checks.items() if not v],
        "promoted_to_kg": False,
        "promotion_requires": "Separate scientific review and owner authorization",
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


# ---------------------------------------------------------------------------
# Full proof runner
# ---------------------------------------------------------------------------


def run_globi_pipeline_proof(
    raw_record: dict[str, Any],
    *,
    dataset_version: str,
    query_role: str = "canonical_dataset",
) -> dict[str, Any]:
    """Run a single GloBI record through all six pipeline stages and return proof.

    This is the acceptance-criterion deliverable for OC-COMPLETE-009:
    one bounded GloBI-derived proof showing orchid interaction records can pass
    source → normalization → canonical taxon reconciliation →
    evidence/provenance → review/KG-candidate contract
    without scientific auto-promotion.

    Args:
        raw_record: A single row from a GloBI stable dataset export or live API.
        dataset_version: The snapshot identifier for this record's dataset.
        query_role: The GloBI query role ("canonical_dataset" for stable exports).

    Returns:
        A proof dict with all six stage results and a top-level PASS/FAIL verdict.
    """
    # Run all stages in order.
    stage_source = _stage_source(raw_record)
    stage_norm = _stage_normalization(raw_record)

    if not stage_norm["normalizable"]:
        # Record cannot proceed past normalization.
        return {
            "schema_version": PROOF_SCHEMA_VERSION,
            "dataset_version": dataset_version,
            "verdict": "FAIL_NOT_NORMALIZABLE",
            "reason": stage_norm["reason"],
            "stages": {
                "source": stage_source,
                "normalization": stage_norm,
            },
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        }

    stage_taxon = _stage_taxon_reconciliation(stage_norm)
    stage_provenance = _stage_evidence_provenance(stage_norm, dataset_version=dataset_version)

    document = document_from_globi_interaction(
        raw_record,
        query_role=query_role,
        provider_stability="VERSIONED_STABLE_DATASET",
        dataset_version=dataset_version,
    )

    stage_review = _stage_review_contract(document)
    stage_kg = _stage_kg_candidate_contract(document)

    all_guards_satisfied = stage_review["guards_satisfied"] and stage_kg["candidate_eligible_for_review"]
    verdict = "PASS" if all_guards_satisfied and stage_taxon["either_reconciled"] else "PASS_WITH_NOTES"
    if not stage_review["guards_satisfied"]:
        verdict = "FAIL_REVIEW_CONTRACT"

    notes = []
    if not stage_taxon["both_reconciled"]:
        notes.append(
            "One or both taxon IDs not matched to a recognized backbone; "
            "name-only match in place — further reconciliation required before scientific review."
        )
    if not stage_provenance["traceable_to_reproducible_source"]:
        notes.append("No study citation or DOI present; provenance traceability is reduced.")

    return {
        "schema_version": PROOF_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "verdict": verdict,
        "notes": notes,
        "stages": {
            "source": stage_source,
            "normalization": stage_norm,
            "taxon_reconciliation": stage_taxon,
            "evidence_provenance": stage_provenance,
            "review_contract": stage_review,
            "kg_candidate_contract": stage_kg,
        },
        "summary": {
            "normalizable": stage_norm["normalizable"],
            "either_taxon_reconciled": stage_taxon["either_reconciled"],
            "both_taxa_reconciled": stage_taxon["both_reconciled"],
            "traceable_to_source": stage_provenance["traceable_to_reproducible_source"],
            "review_guards_satisfied": stage_review["guards_satisfied"],
            "eligible_for_review": stage_kg["candidate_eligible_for_review"],
            "promoted_to_kg": False,
        },
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }
