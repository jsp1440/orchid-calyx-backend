from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from .models import (
    ArticleDraft,
    ArticleSentence,
    BibliographicRecord,
    ClaimKind,
    EvidenceClass,
    EvidenceMatrixRow,
    SynthesisClaim,
)
from .service import PRIMARY_EXPERIMENTAL_CLASSES, ScientificSynthesisService


@dataclass(frozen=True, slots=True)
class EvidenceClassificationDecision:
    evidence_id: str
    evidence_class: EvidenceClass
    reviewer_id: str
    rationale: str


@dataclass(frozen=True, slots=True)
class FigureBrief:
    figure_id: str
    title: str
    purpose: str
    visual_claims: tuple[str, ...]
    supporting_claim_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    uncertainty_notes: tuple[str, ...]
    generation_instruction: str


class ReviewedEvidenceClassificationService:
    def apply(
        self,
        rows: tuple[EvidenceMatrixRow, ...],
        decisions: tuple[EvidenceClassificationDecision, ...],
    ) -> tuple[EvidenceMatrixRow, ...]:
        indexed = {row.evidence_id: row for row in rows}
        if len(indexed) != len(rows):
            raise ValueError("DUPLICATE_EVIDENCE_ID")
        seen: set[str] = set()
        for decision in decisions:
            if decision.evidence_id in seen:
                raise ValueError("DUPLICATE_CLASSIFICATION_DECISION")
            seen.add(decision.evidence_id)
            row = indexed.get(decision.evidence_id)
            if row is None:
                raise ValueError("CLASSIFICATION_EVIDENCE_NOT_FOUND")
            if not decision.reviewer_id.strip() or not decision.rationale.strip():
                raise ValueError("CLASSIFICATION_REVIEW_PROVENANCE_REQUIRED")
            indexed[decision.evidence_id] = replace(
                row,
                evidence_class=decision.evidence_class,
                metadata={
                    **row.metadata,
                    "reviewed_evidence_classification": {
                        "reviewer_id": decision.reviewer_id,
                        "rationale": decision.rationale,
                        "evidence_class": decision.evidence_class.value,
                    },
                },
            )
        return tuple(indexed[row.evidence_id] for row in rows)


class CrossStudySynthesisService:
    _recognized_polarities = {"positive", "negative", "mixed", "uncertain"}

    def synthesize(self, rows: tuple[EvidenceMatrixRow, ...]) -> tuple[SynthesisClaim, ...]:
        if not rows:
            raise ValueError("EVIDENCE_ROWS_REQUIRED")
        groups: dict[tuple[str, str], list[EvidenceMatrixRow]] = {}
        for row in rows:
            key = (row.taxon or "unspecified taxon", row.outcome or "reported outcome")
            groups.setdefault(key, []).append(row)

        claims: list[SynthesisClaim] = []
        for (taxon, outcome), members in sorted(groups.items()):
            if len(members) == 1:
                row = members[0]
                kind = (
                    ClaimKind.DIRECT
                    if row.evidence_class in PRIMARY_EXPERIMENTAL_CLASSES
                    else ClaimKind.SYNTHESIS
                )
                claims.append(
                    SynthesisClaim(
                        claim_id=f"claim:{row.evidence_id}",
                        text=row.result or f"The source reported {outcome} for {taxon}.",
                        kind=kind,
                        supporting_evidence_ids=(row.evidence_id,),
                    )
                )
                continue

            support_ids = tuple(sorted(row.evidence_id for row in members))
            polarities = {
                row.evidence_id: str(row.metadata.get("polarity") or "").casefold()
                for row in members
            }
            recognized = set(polarities.values()) <= self._recognized_polarities
            all_positive = recognized and set(polarities.values()) == {"positive"}
            all_negative = recognized and set(polarities.values()) == {"negative"}
            directionally_consistent = all_positive or all_negative

            if directionally_consistent:
                text = (
                    f"Across {len(members)} source-bound evidence records concerning "
                    f"{outcome} in {taxon}, the extracted results are directionally consistent."
                )
                conflicting_ids: tuple[str, ...] = ()
            else:
                text = (
                    f"Across {len(members)} source-bound evidence records concerning "
                    f"{outcome} in {taxon}, the reported results are mixed or uncertain."
                )
                conflicting_ids = tuple(
                    sorted(
                        evidence_id
                        for evidence_id, polarity in polarities.items()
                        if polarity != "positive" or not recognized
                    )
                )
                if not conflicting_ids:
                    conflicting_ids = support_ids

            digest = hashlib.sha256(
                repr((taxon, outcome, support_ids)).encode()
            ).hexdigest()[:20]
            claims.append(
                SynthesisClaim(
                    claim_id=f"synthesis:{digest}",
                    text=text,
                    kind=ClaimKind.SYNTHESIS,
                    supporting_evidence_ids=support_ids,
                    conflicting_evidence_ids=conflicting_ids,
                )
            )
        return tuple(claims)


class GroundedScientificAuthoringService:
    def author(
        self,
        *,
        question: str,
        title: str,
        audience: str,
        format: str,
        bibliography: tuple[BibliographicRecord, ...],
        claims: tuple[SynthesisClaim, ...],
        evidence_rows: tuple[EvidenceMatrixRow, ...],
    ) -> tuple[ArticleDraft, str]:
        if not all(value.strip() for value in (question, title, audience, format)):
            raise ValueError("AUTHORING_CONTEXT_REQUIRED")
        if not claims:
            raise ValueError("SYNTHESIS_CLAIMS_REQUIRED")
        evidence = {row.evidence_id: row for row in evidence_rows}
        source_ids: set[str] = set()
        for claim in claims:
            for evidence_id in claim.supporting_evidence_ids:
                row = evidence.get(evidence_id)
                if row is None:
                    raise ValueError("AUTHORING_CLAIM_EVIDENCE_NOT_FOUND")
                source_ids.add(row.source_id)
        source_map = {record.source_id: record for record in bibliography}
        if source_ids - set(source_map):
            raise ValueError("AUTHORING_BIBLIOGRAPHY_INCOMPLETE")

        sentences: list[ArticleSentence] = [
            ArticleSentence(
                sentence_id="intro-1",
                text=f"This evidence-grounded review examines the question: {question.strip()}",
                scientific=False,
            )
        ]
        for index, claim in enumerate(claims, start=1):
            sentences.append(
                ArticleSentence(
                    sentence_id=f"scientific-{index}",
                    text=claim.text,
                    scientific=True,
                    claim_ids=(claim.claim_id,),
                )
            )
        sentences.append(
            ArticleSentence(
                sentence_id="closing-1",
                text=(
                    "The conclusions above are constrained to the verified, source-bound evidence "
                    "available to Calyx and should be revised when new evidence is added."
                ),
                scientific=False,
            )
        )
        article = ArticleDraft(
            article_id=f"article:{hashlib.sha256((question + title).encode()).hexdigest()[:20]}",
            title=title.strip(),
            sentences=tuple(sentences),
            audience=audience.strip(),
            format=format.strip(),
            bibliography_source_ids=tuple(sorted(source_ids)),
        )
        paragraphs = [f"# {article.title}", ""]
        paragraphs.extend(sentence.text for sentence in article.sentences)
        paragraphs.extend(["", "## References"])
        for source_id in article.bibliography_source_ids:
            record = source_map[source_id]
            authors = ", ".join(record.authors)
            year = str(record.year) if record.year is not None else "n.d."
            journal = f" {record.journal}." if record.journal else ""
            doi = f" DOI: {record.doi}." if record.doi else ""
            paragraphs.append(f"- {authors} ({year}). {record.title}.{journal}{doi}")
        return article, "\n\n".join(paragraphs) + "\n"


class ScientificArticleAuditService:
    _number = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:%|\b)")

    def __init__(self) -> None:
        self.validator = ScientificSynthesisService()

    def audit(
        self,
        *,
        bibliography: tuple[BibliographicRecord, ...],
        evidence_rows: tuple[EvidenceMatrixRow, ...],
        claims: tuple[SynthesisClaim, ...],
        article: ArticleDraft,
    ) -> dict[str, Any]:
        manifest = self.validator.validate(
            bibliography=bibliography,
            evidence_rows=evidence_rows,
            claims=claims,
            article=article,
        )
        evidence = {row.evidence_id: row for row in evidence_rows}
        claim_index = {claim.claim_id: claim for claim in claims}
        quantitative_errors: list[dict[str, Any]] = []
        for sentence in article.sentences:
            if not sentence.scientific:
                continue
            numbers = {
                match.group(0).rstrip("%")
                for match in self._number.finditer(sentence.text)
            }
            if not numbers:
                continue
            support_text: list[str] = []
            structurally_grounded: set[str] = set()
            for claim_id in sentence.claim_ids:
                claim = claim_index.get(claim_id)
                if claim is None:
                    continue
                structurally_grounded.add(str(len(claim.supporting_evidence_ids)))
                for evidence_id in claim.supporting_evidence_ids:
                    row = evidence.get(evidence_id)
                    if row is not None:
                        support_text.extend(
                            value
                            for value in (row.result, row.sample_size, row.uncertainty)
                            if value
                        )
            corpus = " ".join(support_text)
            unsupported = sorted(
                number
                for number in numbers
                if number not in corpus and number not in structurally_grounded
            )
            if unsupported:
                quantitative_errors.append(
                    {
                        "code": "QUANTITATIVE_SENTENCE_VALUE_UNSUPPORTED",
                        "context": {
                            "sentence_id": sentence.sentence_id,
                            "values": unsupported,
                        },
                    }
                )
        manifest["quantitative_errors"] = quantitative_errors
        manifest["publication_ready"] = bool(manifest["publication_ready"]) and not (
            quantitative_errors
        )
        manifest["state"] = (
            "ARTICLE_AUDIT_PASSED"
            if manifest["publication_ready"]
            else "ARTICLE_AUDIT_BLOCKED"
        )
        return manifest


class FigureEvidenceBriefService:
    def build(
        self,
        *,
        claims: tuple[SynthesisClaim, ...],
        evidence_rows: tuple[EvidenceMatrixRow, ...],
    ) -> tuple[FigureBrief, ...]:
        evidence = {row.evidence_id: row for row in evidence_rows}
        briefs: list[FigureBrief] = []
        for index, claim in enumerate(claims, start=1):
            rows = [
                evidence[value]
                for value in claim.supporting_evidence_ids
                if value in evidence
            ]
            if len(rows) != len(claim.supporting_evidence_ids):
                raise ValueError("FIGURE_CLAIM_EVIDENCE_NOT_FOUND")
            briefs.append(
                FigureBrief(
                    figure_id=f"figure-{index}",
                    title=f"Evidence view {index}",
                    purpose=(
                        "Visualize a source-grounded scientific claim without adding "
                        "unsupported biology."
                    ),
                    visual_claims=(claim.text,),
                    supporting_claim_ids=(claim.claim_id,),
                    source_ids=tuple(sorted({row.source_id for row in rows})),
                    uncertainty_notes=tuple(
                        sorted({row.uncertainty for row in rows if row.uncertainty})
                    ),
                    generation_instruction=(
                        "Illustrate only the stated visual claim and explicitly supplied evidence. "
                        "Do not invent anatomy, measurements, causal mechanisms, taxa, or effect sizes."
                    ),
                )
            )
        return tuple(briefs)


class ResearchToArticleMissionService:
    def __init__(self) -> None:
        self.classifier = ReviewedEvidenceClassificationService()
        self.synthesizer = CrossStudySynthesisService()
        self.author = GroundedScientificAuthoringService()
        self.auditor = ScientificArticleAuditService()
        self.figure_briefs = FigureEvidenceBriefService()

    def run(
        self,
        *,
        question: str,
        title: str,
        audience: str,
        format: str,
        bibliography: tuple[BibliographicRecord, ...],
        evidence_rows: tuple[EvidenceMatrixRow, ...],
        classification_decisions: tuple[EvidenceClassificationDecision, ...] = (),
    ) -> dict[str, Any]:
        classified = self.classifier.apply(evidence_rows, classification_decisions)
        claims = self.synthesizer.synthesize(classified)
        article, markdown = self.author.author(
            question=question,
            title=title,
            audience=audience,
            format=format,
            bibliography=bibliography,
            claims=claims,
            evidence_rows=classified,
        )
        audit = self.auditor.audit(
            bibliography=bibliography,
            evidence_rows=classified,
            claims=claims,
            article=article,
        )
        figures = self.figure_briefs.build(claims=claims, evidence_rows=classified)
        return {
            "state": (
                "RESEARCH_TO_ARTICLE_COMPLETE"
                if audit["publication_ready"]
                else "RESEARCH_TO_ARTICLE_BLOCKED"
            ),
            "question": question,
            "classified_evidence_rows": [asdict(row) for row in classified],
            "claims": [asdict(claim) for claim in claims],
            "article": asdict(article),
            "article_markdown": markdown,
            "audit": audit,
            "figure_briefs": [asdict(brief) for brief in figures],
            "human_review_required": True,
            "published": False,
        }
