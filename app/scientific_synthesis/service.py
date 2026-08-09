from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .models import (
    ArticleDraft,
    BibliographicRecord,
    ClaimKind,
    EvidenceClass,
    EvidenceMatrixRow,
    SynthesisClaim,
    VerificationState,
)

PRIMARY_EXPERIMENTAL_CLASSES = {
    EvidenceClass.DIRECT_TRACER,
    EvidenceClass.CONTROLLED_EXPERIMENT,
}
VERIFIED_STATES = {
    VerificationState.VERIFIED_AUTHORITY,
    VerificationState.VERIFIED_PUBLISHER,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ScientificSynthesisService:
    """Deterministic grounding and publication-readiness checks for scientific prose.

    This service intentionally does not generate prose. It defines the contract that
    discovery, extraction, interpretation, and later authoring systems must satisfy.
    """

    def validate(
        self,
        *,
        bibliography: tuple[BibliographicRecord, ...],
        evidence_rows: tuple[EvidenceMatrixRow, ...],
        claims: tuple[SynthesisClaim, ...],
        article: ArticleDraft,
    ) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        sources = self._unique_index(bibliography, "source_id", errors, "DUPLICATE_SOURCE_ID")
        evidence = self._unique_index(evidence_rows, "evidence_id", errors, "DUPLICATE_EVIDENCE_ID")
        claim_index = self._unique_index(claims, "claim_id", errors, "DUPLICATE_CLAIM_ID")

        for source in bibliography:
            if not source.source_id.strip() or not source.title.strip():
                errors.append(self._error("BIBLIOGRAPHIC_IDENTITY_REQUIRED", source_id=source.source_id))
            if source.verification_state in VERIFIED_STATES and (
                not (source.verification_provider or "").strip()
                or not (source.verification_identifier or "").strip()
            ):
                errors.append(
                    self._error(
                        "VERIFIED_SOURCE_PROVENANCE_REQUIRED",
                        source_id=source.source_id,
                        verification_state=source.verification_state.value,
                    )
                )

        for row in evidence_rows:
            source = sources.get(row.source_id)
            if source is None:
                errors.append(self._error("EVIDENCE_SOURCE_NOT_FOUND", evidence_id=row.evidence_id, source_id=row.source_id))
                continue
            if not row.anchors:
                errors.append(self._error("EVIDENCE_ANCHOR_REQUIRED", evidence_id=row.evidence_id))
            for anchor in row.anchors:
                if anchor.source_id != row.source_id:
                    errors.append(self._error("ANCHOR_SOURCE_MISMATCH", evidence_id=row.evidence_id, anchor_id=anchor.anchor_id))
                if not anchor.anchor_id.strip() or not anchor.source_revision_id.strip():
                    errors.append(
                        self._error(
                            "ANCHOR_IDENTITY_REQUIRED",
                            evidence_id=row.evidence_id,
                            anchor_id=anchor.anchor_id,
                        )
                    )
                if not anchor.locator or not any(
                    value is not None and (not isinstance(value, str) or value.strip())
                    for value in anchor.locator.values()
                ):
                    errors.append(
                        self._error(
                            "ANCHOR_LOCATOR_REQUIRED",
                            evidence_id=row.evidence_id,
                            anchor_id=anchor.anchor_id,
                        )
                    )
                if not anchor.content_hash.strip() or not anchor.excerpt_hash.strip():
                    errors.append(self._error("ANCHOR_HASH_REQUIRED", evidence_id=row.evidence_id, anchor_id=anchor.anchor_id))
            if row.evidence_class in PRIMARY_EXPERIMENTAL_CLASSES and source.verification_state is VerificationState.UNVERIFIED:
                errors.append(self._error("PRIMARY_EVIDENCE_SOURCE_UNVERIFIED", evidence_id=row.evidence_id, source_id=row.source_id))

        for claim in claims:
            support = [evidence.get(value) for value in claim.supporting_evidence_ids]
            conflicts = [evidence.get(value) for value in claim.conflicting_evidence_ids]
            if not claim.supporting_evidence_ids:
                errors.append(self._error("CLAIM_SUPPORT_REQUIRED", claim_id=claim.claim_id))
            for evidence_id, row in zip(claim.supporting_evidence_ids, support, strict=False):
                if row is None:
                    errors.append(self._error("CLAIM_EVIDENCE_NOT_FOUND", claim_id=claim.claim_id, evidence_id=evidence_id))
            for evidence_id, row in zip(claim.conflicting_evidence_ids, conflicts, strict=False):
                if row is None:
                    errors.append(self._error("CLAIM_CONFLICT_EVIDENCE_NOT_FOUND", claim_id=claim.claim_id, evidence_id=evidence_id))
            if claim.kind is ClaimKind.INFERENCE and not (claim.inference_rationale or "").strip():
                errors.append(self._error("INFERENCE_RATIONALE_REQUIRED", claim_id=claim.claim_id))
            if claim.kind is ClaimKind.DIRECT:
                valid_support = [row for row in support if row is not None]
                if valid_support and not any(row.evidence_class in PRIMARY_EXPERIMENTAL_CLASSES for row in valid_support):
                    errors.append(self._error("DIRECT_CLAIM_REQUIRES_PRIMARY_EXPERIMENTAL_EVIDENCE", claim_id=claim.claim_id))
            commercial_only = [row for row in support if row is not None]
            if commercial_only and all(row.evidence_class in {EvidenceClass.COMMERCIAL_CLAIM, EvidenceClass.EXPERT_PRACTICE} for row in commercial_only):
                warnings.append(self._error("CLAIM_SUPPORTED_ONLY_BY_PRACTICE_OR_COMMERCIAL_EVIDENCE", claim_id=claim.claim_id))

        article_sources = set(article.bibliography_source_ids)
        for source_id in article_sources:
            source = sources.get(source_id)
            if source is None:
                errors.append(self._error("ARTICLE_BIBLIOGRAPHY_SOURCE_NOT_FOUND", source_id=source_id))
            elif source.verification_state is VerificationState.UNVERIFIED:
                errors.append(self._error("ARTICLE_BIBLIOGRAPHY_SOURCE_UNVERIFIED", source_id=source_id))
            elif not (source.verification_provider or "").strip() or not (
                source.verification_identifier or ""
            ).strip():
                errors.append(self._error("ARTICLE_BIBLIOGRAPHY_VERIFICATION_PROVENANCE_MISSING", source_id=source_id))

        referenced_claim_ids: set[str] = set()
        for sentence in article.sentences:
            if sentence.scientific and not sentence.claim_ids:
                errors.append(self._error("SCIENTIFIC_SENTENCE_UNGROUNDED", sentence_id=sentence.sentence_id))
            for claim_id in sentence.claim_ids:
                referenced_claim_ids.add(claim_id)
                claim = claim_index.get(claim_id)
                if claim is None:
                    errors.append(self._error("ARTICLE_CLAIM_NOT_FOUND", sentence_id=sentence.sentence_id, claim_id=claim_id))
                    continue
                supporting_sources = {
                    evidence[evidence_id].source_id
                    for evidence_id in claim.supporting_evidence_ids
                    if evidence_id in evidence
                }
                missing_from_bibliography = sorted(supporting_sources - article_sources)
                if missing_from_bibliography:
                    errors.append(
                        self._error(
                            "CLAIM_SOURCE_MISSING_FROM_ARTICLE_BIBLIOGRAPHY",
                            sentence_id=sentence.sentence_id,
                            claim_id=claim_id,
                            source_ids=missing_from_bibliography,
                        )
                    )

        unused_claims = sorted(set(claim_index) - referenced_claim_ids)
        if unused_claims:
            warnings.append(self._error("UNUSED_SYNTHESIS_CLAIMS", claim_ids=unused_claims))

        verified_source_count = sum(
            source.verification_state in VERIFIED_STATES
            and bool((source.verification_provider or "").strip())
            and bool((source.verification_identifier or "").strip())
            for source in bibliography
        )
        primary_evidence_count = sum(row.evidence_class in PRIMARY_EXPERIMENTAL_CLASSES for row in evidence_rows)
        manifest = {
            "article_id": article.article_id,
            "article_title": article.title,
            "audience": article.audience,
            "format": article.format,
            "source_count": len(bibliography),
            "verified_source_count": verified_source_count,
            "evidence_row_count": len(evidence_rows),
            "primary_experimental_evidence_count": primary_evidence_count,
            "claim_count": len(claims),
            "scientific_sentence_count": sum(sentence.scientific for sentence in article.sentences),
            "errors": errors,
            "warnings": warnings,
        }
        manifest["fingerprint"] = fingerprint(
            {
                "bibliography": [asdict(value) for value in bibliography],
                "evidence_rows": [asdict(value) for value in evidence_rows],
                "claims": [asdict(value) for value in claims],
                "article": asdict(article),
                "validator_version": "CALYX-SYN-001.1",
            }
        )
        manifest["publication_ready"] = not errors
        manifest["state"] = "SYNTHESIS_VALIDATED" if not errors else "SYNTHESIS_BLOCKED"
        return manifest

    @staticmethod
    def _unique_index(values, key: str, errors: list[dict[str, Any]], code: str):
        result = {}
        for value in values:
            identifier = getattr(value, key)
            if identifier in result:
                errors.append(ScientificSynthesisService._error(code, **{key: identifier}))
            else:
                result[identifier] = value
        return result

    @staticmethod
    def _error(code: str, **context: Any) -> dict[str, Any]:
        return {"code": code, "context": context}
