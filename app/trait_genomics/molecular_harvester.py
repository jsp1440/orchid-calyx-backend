from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .molecular_evidence import MolecularEvidenceCandidate, MolecularEvidenceRepository

EUROPE_PMC_SEARCH_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_ANNOTATIONS_BASE = (
    "https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds"
)

MOLECULAR_QUERY = (
    '(gene OR genes OR transcriptome OR transcriptomic OR expression OR locus OR loci '
    'OR QTL OR selection OR "differential expression")'
)

TRAIT_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("flower_color", ("flower color", "floral color", "flower colour", "floral colour", "pigmentation", "anthocyanin")),
    ("floral_scent", ("floral scent", "flower scent", "fragrance", "volatile", "volatile compound", "scent chemistry")),
    ("spur_length", ("spur length", "nectar spur", "floral spur", "long spur", "short spur")),
    ("flowering_time", ("flowering time", "anthesis", "flowering phenology", "floral induction")),
    ("floral_morphology", ("labellum", "lip shape", "petal shape", "sepal shape", "floral morphology", "flower morphology")),
    ("pollination_trait", ("pollination syndrome", "pollinator attraction", "pollinator preference", "pollinator-mediated", "pollinator mediated")),
)

RELATION_TERMS = (
    "associated with",
    "association with",
    "correlated with",
    "linked to",
    "linked with",
    "involved in",
    "controls",
    "control of",
    "regulates",
    "regulated",
    "upregulated",
    "downregulated",
    "differential expression",
    "differentially expressed",
    "expression of",
    "selected",
    "selection on",
    "selection at",
    "qtl",
    "locus",
)

EXPRESSION_TERMS = (
    "expression",
    "transcript",
    "transcriptome",
    "upregulated",
    "downregulated",
    "differentially expressed",
)
SELECTION_TERMS = ("selection", "selected", "qtl", "locus", "loci")

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


class MolecularHarvestTarget(BaseModel):
    canonical_taxon_id: str = Field(min_length=1)
    scientific_name: str = Field(min_length=3)


class EuropePMCHarvestRequest(BaseModel):
    targets: list[MolecularHarvestTarget] = Field(min_length=1, max_length=100)
    page_size: int = Field(default=25, ge=1, le=100)
    persist: bool = True


class CandidateSink(Protocol):
    def upsert_candidate(self, candidate: MolecularEvidenceCandidate) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HarvestDiagnostics:
    targets: int
    publications: int
    annotated_publications: int
    annotation_mentions: int
    candidates: int
    persisted: int
    skipped_no_abstract: int
    skipped_no_gene_annotation: int
    skipped_no_trait_relation: int


class EuropePMCClient:
    """Small dependency-free client for Europe PMC search and annotation APIs."""

    def __init__(self, *, timeout: int = 30) -> None:
        self.timeout = timeout

    def _get_json(self, base_url: str, params: dict[str, Any]) -> Any:
        query = urllib.parse.urlencode(params, doseq=True)
        request = urllib.request.Request(
            f"{base_url}?{query}",
            headers={"Accept": "application/json", "User-Agent": "OrchidContinuum-Calyx/1.0"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def search(self, scientific_name: str, *, page_size: int) -> list[dict[str, Any]]:
        payload = self._get_json(
            EUROPE_PMC_SEARCH_BASE,
            {
                "query": f'"{scientific_name}" AND {MOLECULAR_QUERY}',
                "format": "json",
                "resultType": "core",
                "pageSize": page_size,
            },
        )
        return list((payload or {}).get("resultList", {}).get("result", []) or [])

    def annotations(self, article_id: str) -> list[dict[str, Any]]:
        payload = self._get_json(
            EUROPE_PMC_ANNOTATIONS_BASE,
            {
                "articleIds": article_id,
                "type": "Gene_Proteins",
                "provider": "Europe PMC",
                "format": "JSON",
            },
        )
        if not payload:
            return []
        article = payload[0] if isinstance(payload, list) else payload
        return list(article.get("annotations", []) or [])


class EuropePMCMolecularHarvester:
    """Generate review-only molecular candidates from explicit literature statements.

    The harvester deliberately requires all of the following before proposing a
    candidate: an exact configured taxon target, an abstract sentence containing
    a Europe PMC gene/protein annotation, a controlled orchid trait phrase, and a
    relation phrase. Mere co-occurrence at article level is never enough.
    """

    def __init__(
        self,
        *,
        client: EuropePMCClient | Any | None = None,
        repository: CandidateSink | None = None,
    ) -> None:
        self.client = client or EuropePMCClient()
        self.repository = repository or MolecularEvidenceRepository()

    @staticmethod
    def _article_id(article: dict[str, Any]) -> str | None:
        pmcid = str(article.get("pmcid") or "").strip()
        if pmcid:
            return f"PMC:{pmcid}"
        pmid = str(article.get("pmid") or article.get("id") or "").strip()
        source = str(article.get("source") or "MED").strip().upper()
        if pmid:
            return f"{source}:{pmid}"
        return None

    @staticmethod
    def _source_identity(article: dict[str, Any]) -> tuple[str, str | None, str | None, str | None]:
        pmid = str(article.get("pmid") or "").strip() or None
        pmcid = str(article.get("pmcid") or "").strip() or None
        doi = str(article.get("doi") or "").strip() or None
        if pmid:
            return f"pmid:{pmid}", doi, pmid, pmcid
        if pmcid:
            return f"pmcid:{pmcid}", doi, None, pmcid
        if doi:
            return f"doi:{doi}", doi, None, None
        ext = str(article.get("id") or article.get("extId") or "unknown").strip()
        return f"europepmc:{ext}", None, None, None

    @staticmethod
    def _annotation_name(annotation: dict[str, Any]) -> str | None:
        exact = str(annotation.get("exact") or "").strip()
        if exact:
            return exact
        for tag in annotation.get("tags", []) or []:
            name = str(tag.get("name") or "").strip()
            if name:
                return name
        return None

    @staticmethod
    def _annotation_uri(annotation: dict[str, Any]) -> str | None:
        for tag in annotation.get("tags", []) or []:
            uri = str(tag.get("uri") or "").strip()
            if uri:
                return uri
        return None

    @staticmethod
    def _feature_fields(name: str, uri: str | None) -> dict[str, str | None]:
        lower = (uri or "").lower()
        if "uniprot" in lower:
            return {"protein_id": uri, "gene_id": None, "marker_name": name}
        if any(token in lower for token in ("ncbigene", "ensembl", "/gene/", "geneid")):
            return {"protein_id": None, "gene_id": uri, "marker_name": name}
        return {"protein_id": None, "gene_id": None, "marker_name": name}

    @staticmethod
    def _sentences(abstract: str) -> list[str]:
        return [part.strip() for part in _SENTENCE_BOUNDARY.split(abstract) if part.strip()]

    @staticmethod
    def _trait(sentence: str) -> tuple[str, str] | None:
        lower = sentence.lower()
        for predicate, terms in TRAIT_TERMS:
            for term in terms:
                if term in lower:
                    return predicate, term
        return None

    @staticmethod
    def _relation(sentence: str) -> str | None:
        lower = sentence.lower()
        return next((term for term in RELATION_TERMS if term in lower), None)

    @staticmethod
    def _kind(sentence: str) -> str:
        lower = sentence.lower()
        if any(term in lower for term in EXPRESSION_TERMS):
            return "expression_association"
        if any(term in lower for term in SELECTION_TERMS):
            return "selection_association"
        return "genetic_association"

    @staticmethod
    def _sentence_for_gene(abstract: str, gene_name: str) -> str | None:
        needle = gene_name.casefold()
        for sentence in EuropePMCMolecularHarvester._sentences(abstract):
            if needle in sentence.casefold():
                return sentence
        return None

    def _candidate_from_annotation(
        self,
        *,
        target: MolecularHarvestTarget,
        article: dict[str, Any],
        annotation: dict[str, Any],
    ) -> MolecularEvidenceCandidate | None:
        abstract = str(article.get("abstractText") or "").strip()
        if not abstract:
            return None
        gene_name = self._annotation_name(annotation)
        if not gene_name:
            return None
        sentence = self._sentence_for_gene(abstract, gene_name)
        if not sentence:
            return None
        trait = self._trait(sentence)
        relation = self._relation(sentence)
        if trait is None or relation is None:
            return None

        trait_predicate, matched_trait_term = trait
        evidence_kind = self._kind(sentence)
        source_id, doi, pmid, pmcid = self._source_identity(article)
        annotation_uri = self._annotation_uri(annotation)
        features = self._feature_fields(gene_name, annotation_uri)
        publication_id = pmid or pmcid or str(article.get("id") or article.get("extId") or "") or None
        source_uri = None
        if pmcid:
            source_uri = f"https://europepmc.org/article/PMC/{pmcid}"
        elif pmid:
            source_uri = f"https://europepmc.org/article/MED/{pmid}"
        elif doi:
            source_uri = f"https://europepmc.org/article/DOI/{urllib.parse.quote(doi, safe='')}"

        confidence = 0.5
        if target.scientific_name.casefold() in abstract.casefold():
            confidence += 0.05
        if annotation_uri:
            confidence += 0.05
        if doi or pmid:
            confidence += 0.05
        confidence = min(confidence, 0.65)

        return MolecularEvidenceCandidate(
            canonical_taxon_id=target.canonical_taxon_id,
            scientific_name=target.scientific_name,
            evidence_kind=evidence_kind,
            trait_predicate=trait_predicate,
            association_type=relation.replace(" ", "_"),
            gene_id=features["gene_id"],
            protein_id=features["protein_id"],
            marker_name=features["marker_name"],
            evidence_text=sentence,
            method="EUROPE_PMC_ANNOTATION_SENTENCE_GATE",
            source_id=source_id,
            source_uri=source_uri,
            doi=doi,
            pmid=pmid,
            publication_id=publication_id,
            confidence_score=confidence,
            provenance={
                "provider": "Europe PMC",
                "search_query_taxon": target.scientific_name,
                "annotation_type": annotation.get("type") or "Gene_Proteins",
                "annotation_provider": annotation.get("provider") or "Europe PMC",
                "annotation_exact": gene_name,
                "annotation_uri": annotation_uri,
                "annotation_section": annotation.get("section"),
                "matched_trait_term": matched_trait_term,
                "matched_relation_term": relation,
                "candidate_policy": "machine_detected_requires_human_review",
                "causal_claim": False,
            },
        )

    def harvest(
        self,
        targets: Iterable[MolecularHarvestTarget],
        *,
        page_size: int = 25,
        persist: bool = True,
    ) -> dict[str, Any]:
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")

        target_list = list(targets)
        candidates: dict[str, MolecularEvidenceCandidate] = {}
        publications = 0
        annotated_publications = 0
        annotation_mentions = 0
        skipped_no_abstract = 0
        skipped_no_gene_annotation = 0
        skipped_no_trait_relation = 0

        for target in target_list:
            articles = self.client.search(target.scientific_name, page_size=page_size)
            publications += len(articles)
            for article in articles:
                abstract = str(article.get("abstractText") or "").strip()
                if not abstract:
                    skipped_no_abstract += 1
                    continue
                article_id = self._article_id(article)
                if not article_id:
                    skipped_no_gene_annotation += 1
                    continue
                annotations = self.client.annotations(article_id)
                if not annotations:
                    skipped_no_gene_annotation += 1
                    continue
                annotated_publications += 1
                annotation_mentions += len(annotations)
                produced = 0
                for annotation in annotations:
                    candidate = self._candidate_from_annotation(
                        target=target,
                        article=article,
                        annotation=annotation,
                    )
                    if candidate is None:
                        continue
                    candidates[candidate.stable_id()] = candidate
                    produced += 1
                if produced == 0:
                    skipped_no_trait_relation += 1

        persisted_rows: list[dict[str, Any]] = []
        if persist:
            for candidate_id in sorted(candidates):
                persisted_rows.append(self.repository.upsert_candidate(candidates[candidate_id]))

        diagnostics = HarvestDiagnostics(
            targets=len(target_list),
            publications=publications,
            annotated_publications=annotated_publications,
            annotation_mentions=annotation_mentions,
            candidates=len(candidates),
            persisted=len(persisted_rows),
            skipped_no_abstract=skipped_no_abstract,
            skipped_no_gene_annotation=skipped_no_gene_annotation,
            skipped_no_trait_relation=skipped_no_trait_relation,
        )
        return {
            "diagnostics": diagnostics.__dict__,
            "candidate_ids": sorted(candidates),
            "candidates": [
                {"association_id": candidate_id, **candidates[candidate_id].model_dump(mode="json")}
                for candidate_id in sorted(candidates)
            ],
            "persisted": persist,
            "live_tig_eligible": False,
            "review_required": True,
            "scientific_boundary": (
                "The harvester proposes candidates only when one abstract sentence contains a Europe PMC "
                "gene/protein annotation, a controlled orchid trait term, and an explicit relation term. "
                "All harvested records remain excluded from live TIG until human acceptance."
            ),
        }
