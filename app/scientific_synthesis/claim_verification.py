from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import BibliographicRecord, ClaimKind, EvidenceMatrixRow, SynthesisClaim
from .service import PRIMARY_EXPERIMENTAL_CLASSES, VERIFIED_STATES, fingerprint

CHECK_CALYX_VERSION = "CALYX-VERIFY-001"


def _check(
    check_id: str,
    label: str,
    status: str,
    summary: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "label": label,
        "status": status,
        "summary": summary,
        "details": details,
    }


def _source_payload(source: BibliographicRecord | None) -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "source_id": source.source_id,
        "title": source.title,
        "authors": list(source.authors),
        "year": source.year,
        "journal": source.journal,
        "doi": source.doi,
        "verification_state": source.verification_state.value,
        "verification_provider": source.verification_provider,
        "verification_identifier": source.verification_identifier,
    }


def _evidence_payload(
    row: EvidenceMatrixRow,
    source: BibliographicRecord | None,
) -> dict[str, Any]:
    metadata = dict(row.metadata)
    excerpt = (
        metadata.get("authorized_excerpt")
        or metadata.get("source_excerpt")
        or metadata.get("excerpt")
    )
    return {
        "evidence_id": row.evidence_id,
        "evidence_class": row.evidence_class.value,
        "taxon": row.taxon,
        "intervention": row.intervention,
        "comparator": row.comparator,
        "outcome": row.outcome,
        "method": row.method,
        "result": row.result,
        "sample_size": row.sample_size,
        "uncertainty": row.uncertainty,
        "limitations": list(row.limitations),
        "source": _source_payload(source),
        "anchors": [
            {
                "anchor_id": anchor.anchor_id,
                "source_id": anchor.source_id,
                "source_revision_id": anchor.source_revision_id,
                "locator": dict(anchor.locator),
                "content_hash": anchor.content_hash,
                "excerpt_hash": anchor.excerpt_hash,
            }
            for anchor in row.anchors
        ],
        "display_excerpt": excerpt,
        "analysis_recipe": metadata.get("analysis_recipe"),
        "occurrence_ids": metadata.get("occurrence_ids"),
        "metadata": metadata,
    }


def _anchors_complete(row: EvidenceMatrixRow) -> bool:
    if not row.anchors:
        return False
    for anchor in row.anchors:
        if (
            not anchor.anchor_id.strip()
            or not anchor.source_revision_id.strip()
            or not anchor.content_hash.strip()
            or not anchor.excerpt_hash.strip()
            or not anchor.locator
        ):
            return False
    return True


def _verified_source(source: BibliographicRecord | None) -> bool:
    return bool(
        source
        and source.verification_state in VERIFIED_STATES
        and (source.verification_provider or "").strip()
        and (source.verification_identifier or "").strip()
    )


def _verdict(
    *,
    claim: SynthesisClaim,
    support: list[EvidenceMatrixRow],
    conflicts: list[EvidenceMatrixRow],
    source_index: dict[str, BibliographicRecord],
    validation_errors: list[dict[str, Any]],
) -> str:
    claim_errors = [
        error
        for error in validation_errors
        if (error.get("context") or {}).get("claim_id") == claim.claim_id
    ]
    if claim_errors:
        return "claim_exceeds_evidence"
    if not support:
        return "insufficient_evidence"
    if conflicts:
        return "contested"
    if claim.kind is ClaimKind.INFERENCE:
        return "inference_supported_but_untested"

    all_sources_verified = all(
        _verified_source(source_index.get(row.source_id)) for row in support
    )
    all_anchors_complete = all(_anchors_complete(row) for row in support)
    if not all_sources_verified or not all_anchors_complete:
        return "provisional_synthesis"

    if claim.kind is ClaimKind.DIRECT and any(
        row.evidence_class in PRIMARY_EXPERIMENTAL_CLASSES for row in support
    ):
        return "verified_direct_evidence"
    if claim.kind is ClaimKind.SYNTHESIS:
        return "well_supported_synthesis"
    return "provisional_synthesis"


def verify_claim(
    *,
    claim_id: str,
    bibliography: tuple[BibliographicRecord, ...],
    evidence_rows: tuple[EvidenceMatrixRow, ...],
    claims: tuple[SynthesisClaim, ...],
    validation_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build a human-auditable verification dossier for one Calyx claim.

    This is deliberately not a second LLM judge. It is a deterministic audit over
    the evidence, source identities, immutable anchors, conflicts, and explicit
    inference rationale already carried by the synthesis system. The returned
    ``scientific_argument`` is an externally reviewable argument map, never private
    model chain-of-thought.
    """

    claim_index = {claim.claim_id: claim for claim in claims}
    evidence_index = {row.evidence_id: row for row in evidence_rows}
    source_index = {source.source_id: source for source in bibliography}
    claim = claim_index.get(claim_id)
    if claim is None:
        raise ValueError("CALYX_VERIFY_CLAIM_NOT_FOUND")

    support = [
        evidence_index[evidence_id]
        for evidence_id in claim.supporting_evidence_ids
        if evidence_id in evidence_index
    ]
    conflicts = [
        evidence_index[evidence_id]
        for evidence_id in claim.conflicting_evidence_ids
        if evidence_id in evidence_index
    ]
    missing_support = [
        evidence_id
        for evidence_id in claim.supporting_evidence_ids
        if evidence_id not in evidence_index
    ]
    missing_conflicts = [
        evidence_id
        for evidence_id in claim.conflicting_evidence_ids
        if evidence_id not in evidence_index
    ]

    relevant_rows = support + conflicts
    relevant_sources = [source_index.get(row.source_id) for row in relevant_rows]
    source_identity_ok = bool(relevant_sources) and all(
        source is not None for source in relevant_sources
    )
    authoritative_source_ok = bool(relevant_sources) and all(
        _verified_source(source) for source in relevant_sources
    )
    anchors_ok = bool(relevant_rows) and all(_anchors_complete(row) for row in relevant_rows)
    inference_ok = claim.kind is not ClaimKind.INFERENCE or bool(
        (claim.inference_rationale or "").strip()
    )
    support_ok = bool(support) and not missing_support
    conflict_accounted = not missing_conflicts

    checks = [
        _check(
            "claim_grounding",
            "Claim grounding",
            "pass" if support_ok else "fail",
            (
                "Every supporting evidence identifier resolves to an evidence row."
                if support_ok
                else "One or more supporting evidence records are missing."
            ),
            supporting_evidence_ids=list(claim.supporting_evidence_ids),
            missing_evidence_ids=missing_support,
        ),
        _check(
            "source_identity",
            "Source identity",
            "pass" if source_identity_ok else "fail",
            (
                "Every evidence row resolves to a bibliographic source."
                if source_identity_ok
                else "At least one evidence row has no matching bibliographic source."
            ),
        ),
        _check(
            "bibliographic_verification",
            "Bibliographic verification",
            "pass" if authoritative_source_ok else "needs_review",
            (
                "All sources are verified by an authority or publisher with a verification identifier."
                if authoritative_source_ok
                else "At least one source is not yet authority/publisher verified."
            ),
        ),
        _check(
            "evidence_anchor_integrity",
            "Exact evidence anchors",
            "pass" if anchors_ok else "fail",
            (
                "Every evidence record carries an immutable revision, locator, content hash, and excerpt hash."
                if anchors_ok
                else "At least one evidence record cannot yet be dereferenced to an exact immutable source location."
            ),
        ),
        _check(
            "counterevidence_accounting",
            "Counterevidence accounting",
            "pass" if conflict_accounted else "fail",
            (
                "All declared conflicting evidence is retained and inspectable."
                if conflict_accounted
                else "Declared conflicting evidence is missing from the evidence bundle."
            ),
            conflicting_evidence_ids=list(claim.conflicting_evidence_ids),
            missing_evidence_ids=missing_conflicts,
        ),
        _check(
            "inference_rationale",
            "Inference rationale",
            "pass" if inference_ok else "fail",
            (
                "The claim is either not an inference or carries an explicit reviewable rationale."
                if inference_ok
                else "This inference has no explicit reviewable rationale."
            ),
            rationale=claim.inference_rationale,
        ),
    ]

    rerunnable_rows = [
        row
        for row in relevant_rows
        if dict(row.metadata).get("analysis_recipe")
        or dict(row.metadata).get("occurrence_ids")
    ]
    quantitative_status = (
        "pass"
        if relevant_rows and len(rerunnable_rows) == len(relevant_rows)
        else "needs_review"
    )
    checks.append(
        _check(
            "quantitative_reproducibility",
            "Quantitative reproducibility",
            quantitative_status,
            (
                "Every relevant evidence row includes an analysis recipe or the record identifiers needed to recompute it."
                if quantitative_status == "pass"
                else "Some evidence can be inspected but does not yet include a machine-rerunnable analysis recipe or complete record-id set."
            ),
            rerunnable_evidence_ids=[row.evidence_id for row in rerunnable_rows],
        )
    )

    validation_errors = list(validation_manifest.get("errors") or [])
    verdict = _verdict(
        claim=claim,
        support=support,
        conflicts=conflicts,
        source_index=source_index,
        validation_errors=validation_errors,
    )

    argument_steps: list[dict[str, Any]] = [
        {
            "step": "evidence",
            "statement": "Inspect the source-bound evidence supporting the claim.",
            "evidence_ids": [row.evidence_id for row in support],
        }
    ]
    if conflicts:
        argument_steps.append(
            {
                "step": "counterevidence",
                "statement": "Retain and evaluate evidence that bears against the claim.",
                "evidence_ids": [row.evidence_id for row in conflicts],
            }
        )
    if claim.kind is ClaimKind.INFERENCE:
        argument_steps.append(
            {
                "step": "inference",
                "statement": claim.inference_rationale,
                "evidence_ids": [row.evidence_id for row in support],
            }
        )
    argument_steps.append(
        {
            "step": "claim",
            "statement": claim.text,
            "claim_kind": claim.kind.value,
        }
    )

    evidence_bundle = {
        "supporting": [
            _evidence_payload(row, source_index.get(row.source_id)) for row in support
        ],
        "conflicting": [
            _evidence_payload(row, source_index.get(row.source_id)) for row in conflicts
        ],
    }

    reproducibility_payload = {
        "claim": asdict(claim),
        "evidence": [asdict(row) for row in relevant_rows],
        "sources": [
            asdict(source_index[row.source_id])
            for row in relevant_rows
            if row.source_id in source_index
        ],
        "validator_fingerprint": validation_manifest.get("fingerprint"),
        "verification_version": CHECK_CALYX_VERSION,
    }

    failed_checks = [check for check in checks if check["status"] == "fail"]
    review_checks = [check for check in checks if check["status"] == "needs_review"]

    return {
        "operation": "CHECK_CALYX",
        "verification_version": CHECK_CALYX_VERSION,
        "claim": {
            "claim_id": claim.claim_id,
            "text": claim.text,
            "kind": claim.kind.value,
        },
        "verdict": verdict,
        "verification_status": "failed" if failed_checks else ("review_required" if review_checks else "verified"),
        "checks": checks,
        "scientific_argument": {
            "argument_type": "externally_auditable_scientific_argument",
            "private_chain_of_thought_included": False,
            "steps": argument_steps,
            "inference_rationale": claim.inference_rationale,
        },
        "evidence_bundle": evidence_bundle,
        "reproducibility": {
            "deterministic": True,
            "verification_fingerprint": fingerprint(reproducibility_payload),
            "validator_fingerprint": validation_manifest.get("fingerprint"),
            "rerunnable_evidence_ids": [row.evidence_id for row in rerunnable_rows],
            "source_revision_ids": sorted(
                {
                    anchor.source_revision_id
                    for row in relevant_rows
                    for anchor in row.anchors
                    if anchor.source_revision_id
                }
            ),
        },
        "human_review": {
            "required_for_publication": True,
            "failed_check_ids": [check["check_id"] for check in failed_checks],
            "review_check_ids": [check["check_id"] for check in review_checks],
        },
        "publication_boundary": {
            "read_only": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    }
