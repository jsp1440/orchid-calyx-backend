"""Provider-neutral assisted scientific figure gateway for BUILD-FIG-301.

This module generates deterministic figure briefs and validates operator-returned
SVG/PPTX/PNG exports. It never stores provider credentials, performs provider
network calls, publishes science, or mutates the production Knowledge Graph.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from typing import Any

from app.calyx_orchestrator.artifact_registry import (
    ArtifactRegistration,
    ImmutableArtifactRegistry,
)

SUPPORTED_FORMATS = {"svg", "pptx", "png"}
SUPPORTED_MEDIA_TYPES = {
    "svg": "image/svg+xml",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "png": "image/png",
}
MAX_ASSET_BYTES = 25 * 1024 * 1024
MAX_PPTX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_PPTX_MEMBERS = 5000
MAX_ESTIMATED_COST_USD = 25.0
SAFE_LICENSES = {"cc0", "cc-by-4.0", "cc-by-sa-4.0", "public-domain", "internal-reviewed"}
PRODUCER_ASSIGNMENT_ID = "build-fig-301-assisted-gateway"


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_stable_json(value).encode("utf-8"))


def _clean_text(value: str, *, field: str, maximum: int = 4000) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field.upper()}_REQUIRED")
    if len(normalized) > maximum:
        raise ValueError(f"{field.upper()}_TOO_LONG")
    return normalized


def _clean_uri(value: str) -> str:
    normalized = value.strip()
    if not normalized or ":" not in normalized:
        raise ValueError("SOURCE_URI_INVALID")
    return normalized


@dataclass(frozen=True, slots=True)
class FigureSource:
    source_uri: str
    citation: str
    license: str
    evidence_sha256: str

    def validate(self) -> None:
        _clean_uri(self.source_uri)
        _clean_text(self.citation, field="citation", maximum=2000)
        if self.license.casefold() not in SAFE_LICENSES:
            raise ValueError("SOURCE_LICENSE_NOT_ALLOWED")
        if not re.fullmatch(r"[0-9a-f]{64}", self.evidence_sha256):
            raise ValueError("SOURCE_EVIDENCE_SHA256_INVALID")


@dataclass(frozen=True, slots=True)
class FigureBrief:
    brief_id: str
    project_id: str
    title: str
    purpose: str
    required_labels: tuple[str, ...]
    source_records: tuple[FigureSource, ...]
    output_formats: tuple[str, ...]
    provider_hint: str | None
    estimated_cost_usd: float
    scientific_review_required: bool = True
    licensing_review_required: bool = True
    publication_authorized: bool = False

    @property
    def digest(self) -> str:
        return _sha256_json(asdict(self))

    def validate(self) -> None:
        _clean_text(self.brief_id, field="brief_id", maximum=200)
        _clean_text(self.project_id, field="project_id", maximum=200)
        _clean_text(self.title, field="title", maximum=300)
        _clean_text(self.purpose, field="purpose", maximum=4000)
        if not self.required_labels:
            raise ValueError("REQUIRED_LABELS_REQUIRED")
        cleaned_labels = tuple(
            _clean_text(label, field="required_label", maximum=300)
            for label in self.required_labels
        )
        if cleaned_labels != self.required_labels:
            raise ValueError("REQUIRED_LABELS_MUST_BE_CANONICAL")
        if len(set(label.casefold() for label in cleaned_labels)) != len(cleaned_labels):
            raise ValueError("DUPLICATE_REQUIRED_LABEL")
        if not self.source_records:
            raise ValueError("SOURCE_RECORDS_REQUIRED")
        for source in self.source_records:
            source.validate()
        if not self.output_formats:
            raise ValueError("OUTPUT_FORMAT_REQUIRED")
        if any(item != item.casefold().strip() for item in self.output_formats):
            raise ValueError("OUTPUT_FORMAT_MUST_BE_CANONICAL")
        formats = set(self.output_formats)
        if not formats.issubset(SUPPORTED_FORMATS):
            raise ValueError("OUTPUT_FORMAT_NOT_SUPPORTED")
        if len(formats) != len(self.output_formats):
            raise ValueError("DUPLICATE_OUTPUT_FORMAT")
        if self.estimated_cost_usd < 0 or self.estimated_cost_usd > MAX_ESTIMATED_COST_USD:
            raise ValueError("ESTIMATED_COST_EXCEEDS_BOUND")
        if self.publication_authorized:
            raise ValueError("PUBLICATION_AUTHORITY_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class ImportedFigureAsset:
    asset_id: str
    brief_digest: str
    media_type: str
    format: str
    checksum: str
    byte_length: int
    source_uri: str
    creator: str
    attribution: str
    license: str
    semantic_hotspots: tuple[dict[str, Any], ...]
    duplicate_of: str | None
    scientific_review_required: bool = True
    licensing_review_required: bool = True
    publication_authorized: bool = False
    production_graph_mutation_authorized: bool = False


class AssistedFigureGateway:
    """Deterministic local gateway for assisted export/import workflows."""

    def __init__(self, artifact_registry: ImmutableArtifactRegistry | None = None) -> None:
        self._briefs: dict[str, FigureBrief] = {}
        self._assets: dict[str, ImportedFigureAsset] = {}
        self._artifact_registry = artifact_registry or ImmutableArtifactRegistry()

    def register_brief(self, brief: FigureBrief) -> dict[str, Any]:
        brief.validate()
        existing = self._briefs.get(brief.brief_id)
        if existing is not None and existing != brief:
            raise ValueError("IMMUTABLE_FIGURE_BRIEF_CONFLICT")
        self._briefs[brief.brief_id] = brief
        return self.brief_package(brief.brief_id)

    def brief_package(self, brief_id: str) -> dict[str, Any]:
        try:
            brief = self._briefs[brief_id]
        except KeyError as exc:
            raise LookupError("FIGURE_BRIEF_NOT_FOUND") from exc
        return {
            "schema_version": "calyx-assisted-figure-v1",
            "brief": asdict(brief),
            "brief_digest": brief.digest,
            "instructions": {
                "mode": "assisted",
                "provider_network_call_authorized": False,
                "credential_storage_authorized": False,
                "operator_exports_asset_manually": True,
            },
            "publication_authorized": False,
            "production_graph_mutation_authorized": False,
        }

    def import_asset(
        self,
        *,
        brief_id: str,
        format: str,
        content: bytes,
        source_uri: str,
        creator: str,
        attribution: str,
        license: str,
        semantic_hotspots: list[dict[str, Any]] | None = None,
    ) -> ImportedFigureAsset:
        package = self.brief_package(brief_id)
        brief = self._briefs[brief_id]
        normalized_format = format.casefold().strip()
        if normalized_format not in SUPPORTED_FORMATS:
            raise ValueError("OUTPUT_FORMAT_NOT_SUPPORTED")
        if normalized_format not in brief.output_formats:
            raise ValueError("OUTPUT_FORMAT_NOT_REQUESTED")
        if not content or len(content) > MAX_ASSET_BYTES:
            raise ValueError("ASSET_SIZE_INVALID")
        self._validate_signature(normalized_format, content)
        normalized_license = license.casefold().strip()
        if normalized_license not in SAFE_LICENSES:
            raise ValueError("ASSET_LICENSE_NOT_ALLOWED")
        normalized_source_uri = _clean_uri(source_uri)
        normalized_creator = _clean_text(creator, field="creator", maximum=500)
        normalized_attribution = _clean_text(attribution, field="attribution", maximum=2000)
        hotspots = tuple(self._validate_hotspots(semantic_hotspots or []))
        checksum = _sha256_bytes(content)
        asset_id = f"figure:{package['brief_digest'][:16]}:{checksum[:20]}"

        existing = self._assets.get(asset_id)
        if existing is not None:
            replay = ImportedFigureAsset(
                asset_id=asset_id,
                brief_digest=str(package["brief_digest"]),
                media_type=SUPPORTED_MEDIA_TYPES[normalized_format],
                format=normalized_format,
                checksum=checksum,
                byte_length=len(content),
                source_uri=normalized_source_uri,
                creator=normalized_creator,
                attribution=normalized_attribution,
                license=normalized_license,
                semantic_hotspots=hotspots,
                duplicate_of=existing.duplicate_of,
            )
            if existing != replay:
                raise ValueError("IMMUTABLE_FIGURE_ASSET_CONFLICT")
            return existing

        evidence_uris = tuple(
            dict.fromkeys(
                [source.source_uri for source in brief.source_records]
                + [item["evidence_uri"] for item in hotspots]
            )
        )
        registration = self._artifact_registry.register(
            ArtifactRegistration(
                artifact_id=asset_id,
                content=content,
                media_type=SUPPORTED_MEDIA_TYPES[normalized_format],
                source_uri=normalized_source_uri,
                producer_assignment_id=PRODUCER_ASSIGNMENT_ID,
                license=normalized_license,
                evidence_uris=evidence_uris,
                metadata={
                    "brief_id": brief_id,
                    "brief_digest": package["brief_digest"],
                    "format": normalized_format,
                    "creator": normalized_creator,
                    "attribution": normalized_attribution,
                    "semantic_hotspots": list(hotspots),
                    "scientific_review_required": True,
                    "licensing_review_required": True,
                    "publication_authorized": False,
                },
            )
        )
        self._artifact_registry.require_evidence(asset_id)
        candidate = ImportedFigureAsset(
            asset_id=asset_id,
            brief_digest=str(package["brief_digest"]),
            media_type=registration.record.media_type,
            format=normalized_format,
            checksum=registration.record.checksum,
            byte_length=registration.record.byte_length,
            source_uri=registration.record.source_uri,
            creator=normalized_creator,
            attribution=normalized_attribution,
            license=normalized_license,
            semantic_hotspots=hotspots,
            duplicate_of=registration.duplicate_content_of,
        )
        self._assets[asset_id] = candidate
        return candidate

    def readiness(self, brief_id: str) -> dict[str, Any]:
        package = self.brief_package(brief_id)
        brief = self._briefs[brief_id]
        digest = str(package["brief_digest"])
        assets = sorted(
            (asset for asset in self._assets.values() if asset.brief_digest == digest),
            key=lambda item: item.asset_id,
        )
        required_formats = set(brief.output_formats)
        imported_formats = {item.format for item in assets}
        missing_formats = sorted(required_formats - imported_formats)
        blockers: list[str] = []
        if not assets:
            blockers.append("ASSISTED_EXPORT_NOT_IMPORTED")
        if missing_formats:
            blockers.append("REQUIRED_OUTPUT_FORMATS_MISSING")
        blockers.extend(["SCIENTIFIC_REVIEW_REQUIRED", "LICENSING_REVIEW_REQUIRED"])
        return {
            "brief_id": brief_id,
            "brief_digest": digest,
            "asset_count": len(assets),
            "asset_ids": [item.asset_id for item in assets],
            "imported_formats": sorted(imported_formats),
            "missing_formats": missing_formats,
            "required_review_classes": ["scientific", "licensing"],
            "blockers": blockers,
            "decision": "REVIEW_ONLY" if assets else "HOLD",
            "ready_for_scientific_review": bool(assets),
            "ready_for_publication": False,
            "provider_network_call_authorized": False,
            "credential_storage_authorized": False,
            "publication_authorized": False,
            "production_graph_mutation_authorized": False,
        }

    @staticmethod
    def _validate_signature(format: str, content: bytes) -> None:
        if format == "png":
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("PNG_SIGNATURE_INVALID")
            return
        if format == "pptx":
            AssistedFigureGateway._validate_pptx(content)
            return
        if format == "svg":
            prefix = content[:4096].lstrip().lower()
            lowered = content.lower()
            if b"<svg" not in prefix:
                raise ValueError("SVG_SIGNATURE_INVALID")
            forbidden = (
                b"<script",
                b"javascript:",
                b"onload=",
                b"onerror=",
                b"<!doctype",
                b"<!entity",
                b'href="http:',
                b'href="https:',
                b"href='http:",
                b"href='https:",
            )
            if any(token in lowered for token in forbidden):
                raise ValueError("SVG_ACTIVE_CONTENT_FORBIDDEN")

    @staticmethod
    def _validate_pptx(content: bytes) -> None:
        if not content.startswith(b"PK"):
            raise ValueError("PPTX_SIGNATURE_INVALID")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_PPTX_MEMBERS:
                    raise ValueError("PPTX_MEMBER_LIMIT_EXCEEDED")
                total_uncompressed = sum(max(0, info.file_size) for info in infos)
                if total_uncompressed > MAX_PPTX_UNCOMPRESSED_BYTES:
                    raise ValueError("PPTX_EXPANSION_LIMIT_EXCEEDED")
                names = {info.filename for info in infos}
                required = {"[Content_Types].xml", "ppt/presentation.xml"}
                if not required.issubset(names):
                    raise ValueError("PPTX_STRUCTURE_INVALID")
                if any(
                    name.startswith("/") or ".." in name.split("/")
                    for name in names
                ):
                    raise ValueError("PPTX_PATH_INVALID")
        except zipfile.BadZipFile as exc:
            raise ValueError("PPTX_SIGNATURE_INVALID") from exc

    @staticmethod
    def _validate_hotspots(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            concept_id = _clean_text(
                str(item.get("concept_id") or ""),
                field="concept_id",
                maximum=200,
            )
            label = _clean_text(
                str(item.get("label") or ""),
                field="hotspot_label",
                maximum=300,
            )
            evidence_uri = _clean_uri(str(item.get("evidence_uri") or ""))
            key = f"{concept_id}\0{label}\0{evidence_uri}"
            if key in seen:
                continue
            seen.add(key)
            output.append(
                {
                    "concept_id": concept_id,
                    "label": label,
                    "evidence_uri": evidence_uri,
                }
            )
        return sorted(
            output,
            key=lambda item: (
                item["concept_id"],
                item["label"],
                item["evidence_uri"],
            ),
        )


def orchid_root_velamen_brief() -> FigureBrief:
    source = FigureSource(
        source_uri="evidence://knowledge-explorer/velamen/1",
        citation="Knowledge Explorer reviewed evidence packet for orchid root velamen anatomy",
        license="internal-reviewed",
        evidence_sha256=_sha256_bytes(b"knowledge-explorer:velamen:reviewed-evidence-v1"),
    )
    return FigureBrief(
        brief_id="figure-brief:orchid-root-velamen-v1",
        project_id="knowledge-explorer:velamen",
        title="Orchid Root and Velamen Scientific Plate",
        purpose=(
            "Create an evidence-bound candidate plate illustrating major orchid root "
            "tissues without asserting unreviewed scientific claims."
        ),
        required_labels=(
            "root tip",
            "velamen",
            "exodermis",
            "passage cells",
            "cortex",
            "endodermis",
            "stele",
        ),
        source_records=(source,),
        output_formats=("svg", "pptx", "png"),
        provider_hint="FigureLabs-assisted",
        estimated_cost_usd=0.0,
    )
