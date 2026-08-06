from __future__ import annotations

from collections.abc import Iterable, Mapping, Protocol
from dataclasses import dataclass, field
from hashlib import sha256
import re

from .contracts import (
    CharacterDefinition,
    CharacterObservation,
    EvidenceSpan,
    ImageAnalysisResult,
    LiteratureClaim,
    MatrixCandidate,
    MatrixProfile,
    ModelProvenance,
    PlantPartDetection,
    SourceIdentity,
)
from .engine import matrix_observations_from_vision, rank_matrix_candidates


@dataclass(frozen=True, slots=True)
class DocumentPage:
    page_number: int
    text: str
    extraction_method: str = "embedded_text"

    def validate(self) -> None:
        if self.page_number < 1 or not self.text.strip():
            raise ValueError("DOCUMENT_PAGE_INVALID")
        if self.extraction_method not in {"embedded_text", "ocr"}:
            raise ValueError("EXTRACTION_METHOD_INVALID")


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    source_id: str
    title: str
    pages: tuple[DocumentPage, ...]
    canonical_uri: str | None = None

    @property
    def content_hash(self) -> str:
        payload = "\n\f\n".join(page.text for page in self.pages)
        return sha256(payload.encode("utf-8")).hexdigest()

    def source_identity(self) -> SourceIdentity:
        for page in self.pages:
            page.validate()
        source = SourceIdentity(
            source_id=self.source_id,
            title=self.title,
            content_hash=self.content_hash,
            canonical_uri=self.canonical_uri,
        )
        source.validate()
        return source


class OCRAdapter(Protocol):
    provider_name: str

    def extract(self, *, image_id: str, image_bytes: bytes) -> str: ...


@dataclass(frozen=True, slots=True)
class DisabledOCRAdapter:
    provider_name: str = "disabled"

    def extract(self, *, image_id: str, image_bytes: bytes) -> str:
        del image_id, image_bytes
        raise RuntimeError("OCR_PROVIDER_NOT_CONFIGURED")


@dataclass(frozen=True, slots=True)
class TaxonResolution:
    submitted_name: str
    canonical_taxon_id: str | None
    accepted_name: str | None
    status: str
    matched_name: str | None = None


@dataclass(slots=True)
class TaxonomyResolver:
    accepted: Mapping[str, str]
    synonyms: Mapping[str, str] = field(default_factory=dict)

    def resolve(self, name: str) -> TaxonResolution:
        normalized = " ".join(name.strip().split()).casefold()
        accepted_index = {key.casefold(): (taxon_id, key) for key, taxon_id in self.accepted.items()}
        synonym_index = {key.casefold(): value for key, value in self.synonyms.items()}
        if normalized in accepted_index:
            taxon_id, accepted_name = accepted_index[normalized]
            return TaxonResolution(name, taxon_id, accepted_name, "accepted", accepted_name)
        accepted_name = synonym_index.get(normalized)
        if accepted_name and accepted_name.casefold() in accepted_index:
            taxon_id, canonical_name = accepted_index[accepted_name.casefold()]
            return TaxonResolution(name, taxon_id, canonical_name, "synonym", name)
        return TaxonResolution(name, None, None, "unresolved")


def literature_claim_from_phrase(
    *,
    document: DocumentRecord,
    page_number: int,
    phrase: str,
    predicate: str,
    object_value: str,
    taxon_name: str | None = None,
    resolver: TaxonomyResolver | None = None,
    confidence: float | None = None,
) -> LiteratureClaim:
    source = document.source_identity()
    page = next((item for item in document.pages if item.page_number == page_number), None)
    if page is None:
        raise ValueError("DOCUMENT_PAGE_NOT_FOUND")
    start = page.text.find(phrase)
    if start < 0:
        raise ValueError("EVIDENCE_PHRASE_NOT_FOUND")
    canonical_taxon_id = None
    if taxon_name and resolver:
        canonical_taxon_id = resolver.resolve(taxon_name).canonical_taxon_id
    claim = LiteratureClaim(
        claim_id=sha256(f"{source.content_hash}:{page_number}:{start}:{predicate}:{object_value}".encode()).hexdigest(),
        source=source,
        evidence_spans=(EvidenceSpan(start=start, end=start + len(phrase), text=phrase),),
        predicate=predicate,
        object_value=object_value,
        canonical_taxon_id=canonical_taxon_id,
        confidence=confidence,
    )
    claim.validate()
    return claim


def candidate_knowledge_payload(claim: LiteratureClaim) -> dict[str, object]:
    claim.validate()
    return {
        "candidate_type": "literature_claim",
        "external_identity": claim.claim_id,
        "canonical_taxon_id": claim.canonical_taxon_id,
        "predicate": claim.predicate,
        "object_value": claim.object_value,
        "confidence": claim.confidence,
        "contradictions": list(claim.contradictions),
        "source": {
            "source_id": claim.source.source_id,
            "title": claim.source.title,
            "content_hash": claim.source.content_hash,
            "canonical_uri": claim.source.canonical_uri,
        },
        "evidence_spans": [
            {"start": span.start, "end": span.end, "text": span.text}
            for span in claim.evidence_spans
        ],
        "publication_state": "human_review_required",
    }


@dataclass(frozen=True, slots=True)
class MatrixDataset:
    matrix_id: str
    version: str
    definitions: Mapping[str, CharacterDefinition]
    profiles: tuple[MatrixProfile, ...]
    geography: Mapping[str, frozenset[str]] = field(default_factory=dict)
    flowering_months: Mapping[str, frozenset[int]] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.matrix_id.strip() or not self.version.strip() or not self.profiles:
            raise ValueError("MATRIX_DATASET_INVALID")
        for definition in self.definitions.values():
            definition.validate()
        for profile in self.profiles:
            profile.validate()


@dataclass(slots=True)
class MatrixRegistry:
    datasets: dict[tuple[str, str], MatrixDataset] = field(default_factory=dict)

    def register(self, dataset: MatrixDataset) -> None:
        dataset.validate()
        key = (dataset.matrix_id, dataset.version)
        if key in self.datasets:
            raise ValueError("MATRIX_VERSION_ALREADY_EXISTS")
        self.datasets[key] = dataset

    def get(self, matrix_id: str, version: str) -> MatrixDataset:
        try:
            return self.datasets[(matrix_id, version)]
        except KeyError as exc:
            raise KeyError("MATRIX_VERSION_NOT_FOUND") from exc


def filter_profiles(
    dataset: MatrixDataset,
    *,
    region: str | None = None,
    flowering_month: int | None = None,
) -> tuple[MatrixProfile, ...]:
    dataset.validate()
    if flowering_month is not None and not 1 <= flowering_month <= 12:
        raise ValueError("FLOWERING_MONTH_INVALID")
    selected = []
    for profile in dataset.profiles:
        if region is not None:
            allowed_regions = dataset.geography.get(profile.taxon_id)
            if allowed_regions and region not in allowed_regions:
                continue
        if flowering_month is not None:
            months = dataset.flowering_months.get(profile.taxon_id)
            if months and flowering_month not in months:
                continue
        selected.append(profile)
    return tuple(selected)


class VisionProvider(Protocol):
    provider_name: str

    def analyze(self, *, image_id: str, content_hash: str) -> ImageAnalysisResult: ...


@dataclass(frozen=True, slots=True)
class FixtureVisionProvider:
    result: ImageAnalysisResult
    provider_name: str = "fixture"

    def analyze(self, *, image_id: str, content_hash: str) -> ImageAnalysisResult:
        if image_id != self.result.image_id or content_hash != self.result.content_hash:
            raise ValueError("VISION_FIXTURE_IDENTITY_MISMATCH")
        self.result.validate()
        return self.result


def extract_label_tokens(text: str) -> tuple[str, ...]:
    tokens = re.findall(r"[A-Za-z][A-Za-z.-]+|\d{2,}", text)
    return tuple(token for token in tokens if len(token) >= 2)


@dataclass(frozen=True, slots=True)
class IdentificationResult:
    candidates: tuple[MatrixCandidate, ...]
    abstained: bool
    abstention_reason: str | None
    label_tokens: tuple[str, ...]


def identify_from_image(
    *,
    provider: VisionProvider,
    image_id: str,
    content_hash: str,
    dataset: MatrixDataset,
    region: str | None = None,
    flowering_month: int | None = None,
    label_text: str = "",
    minimum_score: float = 0.65,
    minimum_margin: float = 0.10,
) -> IdentificationResult:
    analysis = provider.analyze(image_id=image_id, content_hash=content_hash)
    observations = matrix_observations_from_vision(analysis)
    profiles = filter_profiles(dataset, region=region, flowering_month=flowering_month)
    candidates = rank_matrix_candidates(
        definitions=dataset.definitions,
        observations=observations,
        profiles=profiles,
    )
    reason = None
    if not candidates:
        reason = "NO_CANDIDATES_AFTER_FILTERS"
    elif candidates[0].score < minimum_score:
        reason = "TOP_SCORE_BELOW_THRESHOLD"
    elif len(candidates) > 1 and candidates[0].score - candidates[1].score < minimum_margin:
        reason = "CANDIDATE_MARGIN_TOO_SMALL"
    return IdentificationResult(
        candidates=candidates,
        abstained=reason is not None,
        abstention_reason=reason,
        label_tokens=extract_label_tokens(label_text),
    )
