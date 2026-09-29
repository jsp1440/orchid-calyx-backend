"""Bounded metadata scouting through the existing intelligence ledger.

Rule matches are discovery signals, never evidence of scientific validity or
measured benefit to OC. This module neither fetches content nor dispatches work.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .intelligence import knowledge_fingerprint

SCOUT_VERSION = "oc.technology-scout.v1"
TRIAGE_DIMENSIONS = (
    "orchid_relevance",
    "technology_relevance",
    "scientific_method_relevance",
    "novelty",
    "transferability",
    "evidence_quality",
    "implementation_feasibility",
    "expected_benefit",
    "computational_cost",
    "financial_cost",
    "risk",
    "duplication",
)

# Candidate architectural mappings, not claims that the method is absent or
# already integrated. Compare current repository evidence before designing work.
_METHODS = (
    (
        "retrieval",
        ("hybrid search", "graph rag", "graphrag", "retrieval", "rag"),
        ("calyx", "research_station", "literature"),
    ),
    (
        "knowledge_graph",
        ("knowledge graph", "provenance", "contradiction"),
        ("calyx", "knowledge_graph", "scientific_memory"),
    ),
    (
        "orchestration",
        ("multi agent", "topomas", "orchestration", "event stream", "scheduling"),
        ("calyx", "orchestration"),
    ),
    (
        "vision",
        ("multispectral", "segmentation", "disease classification", "computer vision"),
        ("vision_lab", "conservatory"),
    ),
    (
        "geospatial",
        ("spatiotemporal", "remote sensing", "ecological model", "imputation"),
        ("atlas", "research_station", "conservation"),
    ),
    (
        "sensors",
        ("edge ai", "iot", "lora", "sensor"),
        ("field_journal", "conservatory", "atlas"),
    ),
    (
        "scientific_method",
        (
            "formal verification",
            "experiment",
            "replication",
            "model drift",
            "analogical",
        ),
        ("calyx", "research_station"),
    ),
)


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


class ScoutMetadata(BaseModel):
    """Bibliographic leads only; no transcript, full text, or execution prompt."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    primary_url: str = Field(min_length=1, max_length=2_000)
    doi: str | None = Field(default=None, max_length=300)
    discovery_url: str | None = Field(default=None, max_length=2_000)
    source_kind: Literal["journalclub", "scholarly_index", "oc_harvester", "user"]
    keywords: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("doi")
    @classmethod
    def normalize_doi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = re.sub(
            r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.IGNORECASE
        )
        if not re.fullmatch(r"10\.\d{4,9}/[^\s]+", value, re.IGNORECASE):
            raise ValueError("INVALID_DOI")
        return value.casefold()

    @field_validator("primary_url", "discovery_url")
    @classmethod
    def public_reference_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(char.isspace() for char in value)
        ):
            raise ValueError("HTTPS_REFERENCE_WITHOUT_CREDENTIALS_REQUIRED")
        # URLs are retained as references only. They are never fetched here.
        return urlunsplit(
            ("https", parsed.netloc.lower(), parsed.path, parsed.query, "")
        )

    @field_validator("keywords")
    @classmethod
    def bounded_keywords(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("KEYWORD_MUST_HAVE_1_TO_100_CHARACTERS")
        return sorted({_normalized(value) for value in values})


class ScoutBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ScoutMetadata] = Field(min_length=1, max_length=50)


def screen_metadata(metadata: ScoutMetadata) -> dict[str, object]:
    """Assess metadata cheaply while leaving evidence-dependent dimensions open."""
    text = re.sub(
        r"[-_\u2010-\u2015]",
        " ",
        _normalized(" ".join([metadata.title, *metadata.keywords])),
    )
    matches = []
    modules: set[str] = set()
    for method, phrases, targets in _METHODS:
        found = [
            phrase
            for phrase in phrases
            if re.search(r"\b" + re.escape(phrase) + r"\b", text)
        ]
        if found:
            matches.append({"method": method, "matched_terms": found})
            modules.update(targets)
    orchid_signal = bool(re.search(r"\borchids?\b|\borchidaceae\b", text))
    if orchid_signal:
        modules.add("literature")

    triage = {
        name: {
            "state": "UNASSESSED",
            "score": None,
            "reason": "Requires primary-source evidence and current OC architectural comparison.",
        }
        for name in TRIAGE_DIMENSIONS
    }
    for name, signal in (
        ("orchid_relevance", orchid_signal),
        ("technology_relevance", bool(matches)),
        (
            "scientific_method_relevance",
            any(match["method"] == "scientific_method" for match in matches),
        ),
    ):
        triage[name] = {
            "state": "METADATA_SIGNAL" if signal else "NO_METADATA_SIGNAL",
            "score": None,
            "reason": (
                "Title/keyword rule matched; relevance still requires source verification."
                if signal
                else "No configured rule matched; this does not establish irrelevance."
            ),
        }

    return {
        "schema": SCOUT_VERSION,
        "assessment_basis": "METADATA_ONLY",
        "source": metadata.model_dump(mode="json"),
        "triage": triage,
        "matched_methods": matches,
        "affected_modules": sorted(modules),
        "disposition": "RESEARCH_CANDIDATE" if modules else "UNASSESSED",
        "next_action": "VERIFY_PRIMARY_SOURCE" if modules else "REVIEW_METADATA",
        "source_reported_findings": [],
        "transfer_hypotheses": [
            f"Evaluate whether the reported method can improve {module}; benefit is unmeasured."
            for module in sorted(modules)
        ],
        "canonical_graph_mutated": False,
        "engineering_dispatch_authorized": False,
        "provider_calls": 0,
    }


def scout_intelligence_item(metadata: ScoutMetadata) -> dict[str, object]:
    """Use existing ledger identity, lifecycle, and observation contracts."""
    assessment = screen_metadata(metadata)
    dois = [metadata.doi] if metadata.doi else []
    identity = knowledge_fingerprint("technology", metadata.primary_url, dois)
    return {
        "intelligence_id": _digest(assessment),
        "knowledge_fingerprint": identity,
        "lifecycle": "DISCOVERED",
        "knowledge_delta": "UNASSESSED",
        "domain": "technology",
        "title": metadata.title,
        "normalized_title": _normalized(metadata.title),
        "priority": "MEDIUM",
        "detail": "Metadata discovery lead. Primary-source verification and OC comparison remain pending.",
        "source_urls": sorted(
            {url for url in (metadata.primary_url, metadata.discovery_url) if url}
        ),
        "dois": dois,
        "verification_required": True,
        "canonical_destinations": assessment["affected_modules"],
        "follow_up_tasks": [assessment["next_action"]],
        "parser_version": SCOUT_VERSION,
        "technology_scout": assessment,
        "canonical_graph_mutated": False,
        "external_contacted": False,
    }


def ingest_scout_batch(batch: ScoutBatch) -> dict[str, object]:
    """Persist bounded leads through existing intake and observation tables.

    Each source is idempotent; retrying a partially processed batch safely
    converges. No speculative engineering tasks are materialized from metadata.
    """
    from .intelligence_repository import record_intelligence_items
    from .repository import create_source
    from .schemas import ExtractionResult

    receipts = []
    for metadata in batch.items:
        item = scout_intelligence_item(metadata)
        content = json.dumps(
            item["technology_scout"], sort_keys=True, ensure_ascii=False
        )
        source = create_source(
            source_type="api",
            title=metadata.title,
            content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            source_url=metadata.primary_url,
            imported_by=SCOUT_VERSION,
            extraction=ExtractionResult(
                entities=[], relationships=[], tasks=[], parser_version=SCOUT_VERSION
            ),
        )
        recorded = record_intelligence_items(source_id=source["id"], items=[item])
        receipts.append({**recorded[0], "assessment": item["technology_scout"]})
    return {
        "schema": SCOUT_VERSION,
        "items": receipts,
        "canonical_graph_mutated": False,
        "provider_calls": 0,
    }
