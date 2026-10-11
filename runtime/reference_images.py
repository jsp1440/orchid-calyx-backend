"""Taxonomically verified reference-image records (IMAGE-INTEL-001).

A reference image carries two independent identity claims that must never be
collapsed:

* the *accepted taxon* the image is currently filed under, resolved against a
  named taxonomic authority and source version; and
* the *identification* of the photographed specimen or observation, which is
  only as good as whoever made it.

Source identifications (GBIF, iNaturalist, iDigBio, herbaria) enter as
``unverified_source_identification`` - or ``community_consensus`` for
iNaturalist research-grade records - and are never treated as ground truth.
Only an explicit expert verification event can make an image eligible as a
training label or verified reference.

This module performs no database or network I/O and never mutates canonical
taxonomy. Taxonomic revisions are applied as new record versions that keep
the original identification and the verification history intact.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from runtime.image_staging import _is_allowed_license

SCHEMA_VERSION = "oc-reference-image/v1"

VERIFICATION_STATUSES = (
    "unverified_source_identification",
    "community_consensus",
    "expert_verified",
    "expert_rejected",
    "disputed",
    "needs_reverification",
)
# Statuses whose specimen identification an expert has actually confirmed.
EXPERT_CONFIRMED = frozenset({"expert_verified"})

ORGANS = (
    "whole_flower",
    "sepal",
    "petal",
    "labellum",
    "column",
    "inflorescence",
    "leaf",
    "pseudobulb",
    "stem",
    "root",
    "fruit",
    "seed",
    "whole_plant",
    "habitat",
    "herbarium_sheet",
    "unknown",
)
FLORAL_ORGANS = frozenset(
    {"whole_flower", "sepal", "petal", "labellum", "column", "inflorescence"}
)
DIAGNOSTIC_FLORAL_ORGANS = frozenset({"whole_flower", "labellum", "column"})
VEGETATIVE_ORGANS = frozenset({"leaf", "pseudobulb", "stem", "root", "whole_plant"})

VIEWPOINTS = (
    "frontal",
    "lateral",
    "dorsal",
    "ventral",
    "oblique",
    "longitudinal_section",
    "dissection",
    "habit",
    "unknown",
)
DIAGNOSTIC_FLORAL_VIEWPOINTS = frozenset(
    {"frontal", "lateral", "longitudinal_section", "dissection"}
)

RECORD_KINDS = (
    "human_observation",
    "preserved_specimen",
    "living_specimen",
    "illustration",
    "unknown",
)
QUALITY_GRADES = ("high", "usable", "poor", "unassessed")


@dataclass(frozen=True)
class TaxonConcept:
    """An accepted taxon as resolved by a named authority at a named version."""

    accepted_taxon_id: str
    accepted_name: str
    authority: str
    source_version: str


@dataclass(frozen=True)
class VerificationEvent:
    """One expert (or community) decision about a specimen identification."""

    decision: str  # confirm | reject | revise | dispute
    verifier: str
    verified_on: str | None = None
    revised_taxon_id: str | None = None
    revised_name: str | None = None
    basis: str | None = None
    expert: bool = True


@dataclass(frozen=True)
class ReferenceImageRecord:
    image_id: str
    source: str
    source_record_id: str
    # Identification as supplied by the source, preserved verbatim forever.
    verbatim_name: str | None
    original_identification: str | None
    # Accepted taxonomy (concept placement, not specimen verification).
    accepted_taxon_id: str | None
    accepted_name: str | None
    taxonomic_authority: str | None
    taxonomy_version: str | None
    # Specimen / observation identity.
    record_kind: str = "unknown"
    specimen_id: str | None = None
    occurrence_id: str | None = None
    # Identification verification (independent of accepted taxonomy).
    verification_status: str = "unverified_source_identification"
    verifier: str | None = None
    verified_on: str | None = None
    verification_history: tuple[VerificationEvent, ...] = ()
    # Media and rights.
    image_url: str | None = None
    storage_ref: str | None = None
    license: str | None = None
    rights_holder: str | None = None
    attribution: str | None = None
    # Photographic content.
    organ: str = "unknown"
    viewpoint: str = "unknown"
    quality: str = "unassessed"
    has_scale: bool = False
    scale_basis: str | None = None
    # Confidence of the *identification* (0-1) and free-text uncertainty.
    identification_confidence: float | None = None
    uncertainty_notes: tuple[str, ...] = ()
    # Deduplication.
    content_sha256: str | None = None
    perceptual_hash: str | None = None
    duplicate_group_id: str | None = None
    related_image_ids: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    # -- derived properties -------------------------------------------------

    @property
    def accessible(self) -> bool:
        return bool(self.image_url or self.storage_ref)

    @property
    def license_allowed(self) -> bool:
        return _is_allowed_license(self.license)

    @property
    def expert_confirmed(self) -> bool:
        return self.verification_status in EXPERT_CONFIRMED

    @property
    def specimen_group_key(self) -> str:
        """Key used to keep every image of one organism in one data split."""
        if self.specimen_id:
            return f"specimen:{self.specimen_id}"
        if self.occurrence_id:
            return f"occurrence:{self.occurrence_id}"
        if self.duplicate_group_id:
            return f"dup:{self.duplicate_group_id}"
        return f"image:{self.image_id}"

    def training_label_eligibility(self) -> tuple[bool, tuple[str, ...]]:
        """Whether this image may serve as a training label, and why not."""
        reasons: list[str] = []
        if not self.expert_confirmed:
            reasons.append("identification_not_expert_verified")
        if not self.accepted_taxon_id:
            reasons.append("accepted_taxon_id_missing")
        if not self.taxonomy_version:
            reasons.append("taxonomy_version_missing")
        if not self.accessible:
            reasons.append("image_not_accessible")
        if not self.license_allowed:
            reasons.append("license_not_allowed")
        if self.quality == "poor":
            reasons.append("image_quality_poor")
        return (not reasons, tuple(reasons))

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.image_id:
            issues.append("image_id_required")
        if not self.source or not self.source_record_id:
            issues.append("source_identity_required")
        if self.verification_status not in VERIFICATION_STATUSES:
            issues.append("unknown_verification_status")
        if self.organ not in ORGANS:
            issues.append("unknown_organ")
        if self.viewpoint not in VIEWPOINTS:
            issues.append("unknown_viewpoint")
        if self.record_kind not in RECORD_KINDS:
            issues.append("unknown_record_kind")
        if self.quality not in QUALITY_GRADES:
            issues.append("unknown_quality_grade")
        if self.accepted_taxon_id and not (
            self.taxonomic_authority and self.taxonomy_version
        ):
            issues.append("accepted_taxon_without_authority_version")
        if self.expert_confirmed and not self.verifier:
            issues.append("expert_verification_without_verifier")
        if self.has_scale and not self.scale_basis:
            issues.append("scale_claimed_without_basis")
        if (
            self.identification_confidence is not None
            and not 0 <= self.identification_confidence <= 1
        ):
            issues.append("identification_confidence_out_of_range")
        if not self.accessible:
            issues.append("no_image_url_or_storage_ref")
        if not self.license:
            issues.append("license_missing")
        return issues

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provenance"] = dict(self.provenance)
        payload["accessible"] = self.accessible
        payload["license_allowed"] = self.license_allowed
        eligible, reasons = self.training_label_eligibility()
        payload["training_label_eligible"] = eligible
        payload["training_label_ineligibility_reasons"] = list(reasons)
        payload["specimen_group_key"] = self.specimen_group_key
        return payload


# -- source normalisation ----------------------------------------------------


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _stable_image_id(source: str, source_record_id: str, url: str | None) -> str:
    digest = hashlib.sha256(
        f"{source}|{source_record_id}|{url or ''}".encode()
    ).hexdigest()
    return f"img_{digest[:20]}"


def record_from_source_row(
    row: Mapping[str, Any],
    *,
    source: str,
    taxon_lookup: Mapping[str, TaxonConcept] | None = None,
) -> ReferenceImageRecord:
    """Normalise a GBIF / iNaturalist / iDigBio / herbarium media row.

    The accepted taxon is attached only through an exact lookup of the
    source's own taxon key or verbatim name; nothing is fuzzy-matched. The
    specimen identification is always left unverified - an iNaturalist
    research-grade flag becomes ``community_consensus``, never
    ``expert_verified``.
    """
    source = source.strip().lower()
    source_record_id = str(
        _first(row, "source_record_id", "gbifID", "gbif_id", "id", "uuid", "photo_id")
        or ""
    )
    url = _first(
        row,
        "image_url",
        "identifier",
        "url",
        "accessURI",
        "ac:accessURI",
        "medium_url",
        "original_url",
    )
    verbatim = _first(
        row,
        "verbatim_name",
        "verbatimScientificName",
        "scientificName",
        "scientific_name",
        "taxon_name",
    )
    taxon_key = _first(row, "taxon_id", "taxonKey", "taxon_key", "accepted_taxon_id")
    concept: TaxonConcept | None = None
    if taxon_lookup:
        concept = taxon_lookup.get(str(taxon_key)) if taxon_key is not None else None
        if concept is None and verbatim:
            concept = taxon_lookup.get(str(verbatim).strip())
    basis = str(
        _first(row, "basisOfRecord", "basis_of_record", "record_kind") or ""
    ).upper()
    record_kind = {
        "PRESERVED_SPECIMEN": "preserved_specimen",
        "LIVING_SPECIMEN": "living_specimen",
        "HUMAN_OBSERVATION": "human_observation",
        "MACHINE_OBSERVATION": "human_observation",
    }.get(
        basis,
        "preserved_specimen"
        if source in {"idigbio", "herbarium"}
        else "human_observation"
        if source == "inaturalist"
        else "unknown",
    )
    grade = str(_first(row, "quality_grade", "qualityGrade") or "").lower()
    status = (
        "community_consensus"
        if source == "inaturalist" and grade == "research"
        else "unverified_source_identification"
    )
    organ = str(
        _first(row, "organ")
        or ("herbarium_sheet" if record_kind == "preserved_specimen" else "unknown")
    )
    return ReferenceImageRecord(
        image_id=str(
            _first(row, "image_id") or _stable_image_id(source, source_record_id, url)
        ),
        source=source,
        source_record_id=source_record_id,
        verbatim_name=str(verbatim) if verbatim else None,
        original_identification=str(
            _first(
                row,
                "identifiedBy_name",
                "original_identification",
                "verbatim_name",
                "scientificName",
                "scientific_name",
            )
            or ""
        )
        or None,
        accepted_taxon_id=concept.accepted_taxon_id if concept else None,
        accepted_name=concept.accepted_name if concept else None,
        taxonomic_authority=concept.authority if concept else None,
        taxonomy_version=concept.source_version if concept else None,
        record_kind=record_kind,
        specimen_id=_first(row, "catalogNumber", "catalog_number", "specimen_id"),
        occurrence_id=_first(row, "occurrenceID", "occurrence_id", "observation_id"),
        verification_status=status,
        image_url=str(url) if url else None,
        storage_ref=_first(row, "storage_ref", "storage_path"),
        license=_first(row, "license", "dcterms:license", "rights"),
        rights_holder=_first(row, "rightsHolder", "rights_holder"),
        attribution=_first(row, "attribution", "creator", "dc:creator"),
        organ=organ if organ in ORGANS else "unknown",
        content_sha256=_first(row, "content_sha256", "sha256"),
        perceptual_hash=_first(row, "perceptual_hash", "phash"),
        provenance={
            "source": source,
            "source_record_id": source_record_id,
            "taxon_resolution": "exact_lookup" if concept else "unresolved",
            "quality_grade": grade or None,
        },
    )


# -- expert verification and taxonomic revision ------------------------------


def apply_verification(
    record: ReferenceImageRecord, event: VerificationEvent
) -> ReferenceImageRecord:
    """Return a new record version reflecting one verification decision.

    A non-expert event can at most establish ``community_consensus``. A
    ``revise`` decision re-files the image under the expert's taxon but keeps
    the verbatim name and original identification untouched.
    """
    if event.decision not in {"confirm", "reject", "revise", "dispute"}:
        raise ValueError("unknown_verification_decision")
    if not event.verifier:
        raise ValueError("verifier_required")
    history = (*record.verification_history, event)
    if event.decision == "dispute":
        return replace(
            record, verification_status="disputed", verification_history=history
        )
    if not event.expert:
        status = "community_consensus" if event.decision == "confirm" else "disputed"
        return replace(record, verification_status=status, verification_history=history)
    if event.decision == "reject":
        return replace(
            record,
            verification_status="expert_rejected",
            verifier=event.verifier,
            verified_on=event.verified_on,
            verification_history=history,
        )
    changes: dict[str, Any] = {
        "verification_status": "expert_verified",
        "verifier": event.verifier,
        "verified_on": event.verified_on,
        "verification_history": history,
    }
    if event.decision == "revise":
        if not event.revised_taxon_id:
            raise ValueError("revised_taxon_id_required")
        changes["accepted_taxon_id"] = event.revised_taxon_id
        changes["accepted_name"] = event.revised_name or record.accepted_name
    return replace(record, **changes)


@dataclass(frozen=True)
class TaxonomicRevision:
    """A published change in taxon concepts between two taxonomy versions."""

    from_taxon_id: str
    to_taxon_ids: tuple[str, ...]
    to_names: tuple[str, ...]
    new_version: str
    kind: str  # synonymy | split | rename


def apply_taxonomic_revision(
    records: Iterable[ReferenceImageRecord],
    revision: TaxonomicRevision,
) -> list[ReferenceImageRecord]:
    """Re-file images after a taxonomic revision without losing history.

    Synonymy and renames move the accepted placement and keep the specimen
    verification (the specimen is the same organism). A split cannot be
    resolved without examining the specimen, so the accepted placement is
    cleared and expert-verified records drop to ``needs_reverification``.
    """
    if revision.kind not in {"synonymy", "split", "rename"}:
        raise ValueError("unknown_revision_kind")
    out: list[ReferenceImageRecord] = []
    for record in records:
        if record.accepted_taxon_id != revision.from_taxon_id:
            out.append(record)
            continue
        provenance = {
            **dict(record.provenance),
            "taxonomic_revisions": [
                *list(record.provenance.get("taxonomic_revisions", [])),
                {
                    "from_taxon_id": revision.from_taxon_id,
                    "from_version": record.taxonomy_version,
                    "to_taxon_ids": list(revision.to_taxon_ids),
                    "new_version": revision.new_version,
                    "kind": revision.kind,
                },
            ],
        }
        if revision.kind == "split" and len(revision.to_taxon_ids) != 1:
            out.append(
                replace(
                    record,
                    accepted_taxon_id=None,
                    accepted_name=None,
                    taxonomy_version=revision.new_version,
                    verification_status="needs_reverification"
                    if record.verification_status in EXPERT_CONFIRMED
                    else record.verification_status,
                    provenance=provenance,
                )
            )
            continue
        out.append(
            replace(
                record,
                accepted_taxon_id=revision.to_taxon_ids[0],
                accepted_name=revision.to_names[0]
                if revision.to_names
                else record.accepted_name,
                taxonomy_version=revision.new_version,
                provenance=provenance,
            )
        )
    return out


# -- duplicate detection -----------------------------------------------------


_SIZE_SEGMENT = re.compile(
    r"/(square|small|medium|large|original|thumb|thumbnail)(\.[a-z]+)?$", re.IGNORECASE
)


def normalize_image_url(url: str | None) -> str | None:
    """Collapse scheme, host case, query strings and size variants of a URL."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    path = _SIZE_SEGMENT.sub("", parts.path)
    return urlunsplit(("", parts.netloc.lower(), path.rstrip("/"), "", ""))


def _hamming_hex(left: str, right: str) -> int | None:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return None


def group_duplicates(
    records: Iterable[ReferenceImageRecord],
    *,
    phash_max_distance: int = 6,
) -> list[ReferenceImageRecord]:
    """Assign ``duplicate_group_id`` by exact hash, URL, source id or pHash.

    Groups are transitive (union-find). The group id is derived from the
    smallest member image id so it is stable across runs.
    """
    items = list(records)
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    index: dict[tuple[str, str], int] = {}
    for i, rec in enumerate(items):
        keys = []
        if rec.content_sha256:
            keys.append(("sha", rec.content_sha256.lower()))
        norm = normalize_image_url(rec.image_url)
        if norm:
            keys.append(("url", norm))
        keys.append(
            (
                "src",
                f"{rec.source}|{rec.source_record_id}|{norm or rec.storage_ref or ''}",
            )
        )
        for key in keys:
            if key in index:
                union(index[key], i)
            else:
                index[key] = i
    hashed = [(i, r.perceptual_hash) for i, r in enumerate(items) if r.perceptual_hash]
    for a in range(len(hashed)):
        for b in range(a + 1, len(hashed)):
            distance = _hamming_hex(hashed[a][1], hashed[b][1])
            if distance is not None and distance <= phash_max_distance:
                union(hashed[a][0], hashed[b][0])

    members: dict[int, list[int]] = {}
    for i in range(len(items)):
        members.setdefault(find(i), []).append(i)
    out = list(items)
    for group in members.values():
        ids = sorted(items[i].image_id for i in group)
        group_id = (
            "dupgrp_" + hashlib.sha256(ids[0].encode()).hexdigest()[:16]
            if len(group) > 1
            else None
        )
        for i in group:
            related = tuple(x for x in ids if x != items[i].image_id)
            out[i] = replace(
                items[i], duplicate_group_id=group_id, related_image_ids=related
            )
    return out
