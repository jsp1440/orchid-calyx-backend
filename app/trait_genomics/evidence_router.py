from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoutedPublication:
    route: str
    confidence: float
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


class ScientificEvidenceRouter:
    """Route retrieved orchid papers without promoting them to live TIG evidence.

    Routing is intentionally descriptive. It helps Calyx retain scientifically useful
    papers in the correct evidence channel while preserving the stricter molecular
    association gate. A route is never equivalent to human acceptance or causality.
    """

    PHYLOGENETIC_TERMS = (
        "phylogeny",
        "phylogenetic",
        "molecular phylogeny",
        "matk",
        "rbcl",
        "its1",
        "its2",
        "internal transcribed spacer",
        "plastid",
        "chloroplast",
        "barcode",
        "barcoding",
    )
    MORPHOLOGY_TERMS = (
        "morphology",
        "micromorphology",
        "labellum",
        "floral morphology",
        "flower morphology",
        "petal",
        "sepal",
        "spur length",
        "floral trait",
    )
    POLLINATION_TERMS = (
        "pollinator",
        "pollination",
        "pollinator-mediated",
        "pollinator mediated",
        "pollination syndrome",
        "floral visitor",
        "bee",
        "moth",
        "hawkmoth",
    )
    GENOMIC_RESOURCE_TERMS = (
        "genome",
        "genomic",
        "transcriptome",
        "transcriptomic",
        "rna-seq",
        "rna seq",
        "whole genome",
        "genome assembly",
        "reference genome",
        "proteome",
    )
    ASSOCIATION_TERMS = (
        "associated with",
        "association with",
        "correlated with",
        "linked to",
        "linked with",
        "differential expression",
        "differentially expressed",
        "upregulated",
        "downregulated",
        "regulates",
        "regulated",
        "qtl",
        "locus",
        "selection on",
    )
    MOLECULAR_TERMS = (
        "gene",
        "genes",
        "protein",
        "expression",
        "transcript",
        "sequence",
        "sequencing",
        "dna",
        "rna",
        "locus",
        "marker",
    )

    @staticmethod
    def _text(article: dict[str, Any]) -> str:
        values = (
            article.get("title"),
            article.get("abstractText"),
            article.get("authorString"),
            article.get("journalTitle"),
        )
        return " ".join(str(value or "") for value in values).casefold()

    @staticmethod
    def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
        return [term for term in terms if term.casefold() in text]

    def route(
        self,
        article: dict[str, Any],
        *,
        has_gene_annotations: bool,
        molecular_candidate_count: int,
        full_text_available: bool = False,
    ) -> RoutedPublication:
        text = self._text(article)
        phylogenetic = self._matches(text, self.PHYLOGENETIC_TERMS)
        morphology = self._matches(text, self.MORPHOLOGY_TERMS)
        pollination = self._matches(text, self.POLLINATION_TERMS)
        genomic = self._matches(text, self.GENOMIC_RESOURCE_TERMS)
        association = self._matches(text, self.ASSOCIATION_TERMS)
        molecular = self._matches(text, self.MOLECULAR_TERMS)

        if molecular_candidate_count > 0:
            return RoutedPublication(
                route="molecular_association_candidate",
                confidence=0.95,
                reasons=(
                    "strict_same_sentence_molecular_trait_relation_gate_passed",
                    "human_review_still_required",
                ),
            )

        if pollination and association and (has_gene_annotations or molecular or genomic):
            return RoutedPublication(
                route="pollinator_selection_context",
                confidence=0.8,
                reasons=tuple(["pollination_terms", "selection_or_association_terms"] + pollination[:2] + association[:2]),
            )

        if genomic:
            reasons = ["genomic_resource_terms"] + genomic[:3]
            if has_gene_annotations:
                reasons.append("europe_pmc_gene_annotations_present")
            return RoutedPublication(
                route="genomic_resource",
                confidence=0.8 if has_gene_annotations else 0.7,
                reasons=tuple(reasons),
            )

        if phylogenetic:
            reasons = ["phylogenetic_or_sequence_context"] + phylogenetic[:3]
            if full_text_available:
                reasons.append("open_access_full_text_available")
            return RoutedPublication(
                route="phylogenetic_sequence_context",
                confidence=0.85,
                reasons=tuple(reasons),
            )

        if morphology:
            reasons = ["morphology_or_trait_terms"] + morphology[:3]
            if has_gene_annotations:
                reasons.append("gene_annotations_present_but_no_strict_association")
            return RoutedPublication(
                route="trait_morphology_evidence",
                confidence=0.8,
                reasons=tuple(reasons),
            )

        if pollination:
            return RoutedPublication(
                route="pollination_ecology_evidence",
                confidence=0.75,
                reasons=tuple(["pollination_terms"] + pollination[:3]),
            )

        if has_gene_annotations or molecular:
            reasons = ["molecular_context_without_qualifying_trait_association"]
            if has_gene_annotations:
                reasons.append("europe_pmc_gene_annotations_present")
            reasons.extend(molecular[:3])
            return RoutedPublication(
                route="molecular_context",
                confidence=0.65,
                reasons=tuple(reasons),
            )

        return RoutedPublication(
            route="general_orchid_literature",
            confidence=0.5,
            reasons=("no_specialized_route_gate_passed",),
        )
