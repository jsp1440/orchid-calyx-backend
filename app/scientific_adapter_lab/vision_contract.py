"""Provider-free governed image/vision provenance contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Protocol


class ImageType(str, Enum):
    HERBARIUM = "herbarium"
    FIELD = "field"
    COLLECTION = "collection"
    ILLUSTRATION = "illustration"


class LicenseState(str, Enum):
    CC0 = "cc0"
    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    CC_BY_NC = "cc_by_nc"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class IdentificationStatus(str, Enum):
    CANDIDATE = "candidate"
    REVIEWED_ACCEPTED = "reviewed_accepted"
    REVIEWED_REJECTED = "reviewed_rejected"
    PENDING = "pending"


@dataclass(frozen=True)
class ImageRecord:
    image_id: str
    taxon_name: str | None
    image_type: ImageType
    license_state: LicenseState
    attribution: str
    source_authority: str
    evidence_state: str
    broken: bool = False
    curator_reviewed_binding: bool = False

    def to_public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["image_type"] = self.image_type.value
        payload["license_state"] = self.license_state.value
        return payload


@dataclass(frozen=True)
class ImageIdentificationCandidate:
    candidate_taxon: str
    confidence: float | None
    model_identifier: str
    status: IdentificationStatus = IdentificationStatus.PENDING
    automatic_publication: bool = False

    def __post_init__(self) -> None:
        if self.automatic_publication:
            raise ValueError("automatic identification publication is prohibited")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be within [0, 1]")


class ImageRepository(Protocol):
    def records_for_taxon(self, taxon_name: str) -> Iterable[ImageRecord]:
        ...


@dataclass(frozen=True)
class ImageMatrix:
    taxon_name: str
    state: str
    records: tuple[ImageRecord, ...]


def build_unavailable_image_matrix(taxon_name: str) -> ImageMatrix:
    return ImageMatrix(taxon_name=taxon_name, state="unknown", records=())


def _precedence(record: ImageRecord) -> int:
    return 1 if record.curator_reviewed_binding else 0


class ImageGateway:
    def __init__(self, repository: ImageRepository | None = None) -> None:
        self._repository = repository

    def read_taxon(self, taxon_name: str) -> ImageMatrix:
        if self._repository is None:
            return build_unavailable_image_matrix(taxon_name)
        records = tuple(self._repository.records_for_taxon(taxon_name))
        if not records:
            return build_unavailable_image_matrix(taxon_name)
        return ImageMatrix(
            taxon_name=taxon_name,
            state="available",
            records=tuple(sorted(records, key=_precedence, reverse=True)),
        )
